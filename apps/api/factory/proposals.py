"""Connection proposals: a drafted integration that grants nothing until an administrator approves it.

A proposal never holds a credential and is never used to reach anything. Static checks run when it is
drafted. Only approval, by an administrator who confirms the exact hosts and supplies the secret, creates
a connection, and attaching it to an agent creates a fresh immutable version that must be re-evaluated.
"""

import re
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, validate
from jsonschema.exceptions import SchemaError, ValidationError
from sqlalchemy import select

from factory.db import now
from factory.http_transport import validate_url
from factory.models import AgentRecord, AgentVersion, BuildJob, Connection, ConnectionProposal
from factory.schemas import AgentSpec
from factory.security import SECRET_KEYS, encrypt, redact_tenant

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
MAX_OPERATIONS = 40
NAME = re.compile(r"^[a-z][a-z0-9_]{2,59}$")


class ProposalError(ValueError):
    """The draft is not acceptable. The message is safe to show to its author."""


def static_path(path):
    return (
        isinstance(path, str)
        and path.startswith("/")
        and not path.startswith("//")
        and ".." not in path
        and "?" not in path
        and "#" not in path
        and "{" not in path
    )


def _no_secrets(value, trail="config"):
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEYS.search(str(key)) and trail.split(".")[-1] not in ("properties", "required"):
                raise ProposalError("A proposal must not contain credentials; the administrator supplies them")
            _no_secrets(item, f"{trail}.{key}")
    elif isinstance(value, list):
        for item in value:
            _no_secrets(item, trail)


def check_rest_config(config, samples=()):
    """Static validation only. Nothing is contacted. Returns a summary of what was checked."""
    if not isinstance(config, dict):
        raise ProposalError("Connection configuration must be an object")
    unknown = set(config) - {"base_url", "allowed_hosts", "operations", "health_path", "resources"}
    if unknown:
        raise ProposalError(f"Unsupported configuration keys: {', '.join(sorted(unknown))}")
    _no_secrets({key: value for key, value in config.items() if key != "operations"})
    base_url = config.get("base_url")
    parsed = urlparse(base_url if isinstance(base_url, str) else "")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        raise ProposalError("base_url must be a credential-free https URL without a query")
    hosts = config.get("allowed_hosts")
    if hosts != [parsed.hostname]:
        raise ProposalError("allowed_hosts must list exactly the host of base_url")
    try:
        validate_url(base_url, hosts)
    except ValueError as error:
        raise ProposalError(str(error)) from None
    if "health_path" in config and not static_path(config["health_path"]):
        raise ProposalError("health_path must be static and relative")
    operations = config.get("operations")
    if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
        raise ProposalError(f"A proposal needs 1 to {MAX_OPERATIONS} operations")
    by_name, writes = {}, []
    for operation in operations:
        if not isinstance(operation, dict):
            raise ProposalError("Each operation must be an object")
        extra = set(operation) - {"name", "description", "path", "method", "input_schema", "output_schema"}
        if extra:
            raise ProposalError(f"Unsupported operation keys: {', '.join(sorted(extra))}")
        name = operation.get("name")
        if not isinstance(name, str) or not NAME.match(name) or name in by_name:
            raise ProposalError("Operation names are distinct lowercase identifiers of 3 to 60 characters")
        description = operation.get("description")
        if not isinstance(description, str) or not 1 <= len(description) <= 500:
            raise ProposalError(f"Operation {name} needs a description of at most 500 characters")
        if not static_path(operation.get("path")):
            raise ProposalError(f"Operation {name} must use a static relative path without parameters")
        method = str(operation.get("method", "GET")).upper()
        if method not in METHODS:
            raise ProposalError(f"Operation {name} uses an unsupported method")
        for key in ("input_schema", "output_schema"):
            schema = operation.get(key, {"type": "object"})
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError:
                raise ProposalError(f"Operation {name} has an invalid {key}") from None
        by_name[name] = operation
        if method != "GET":
            writes.append(name)
    checked = 0
    for sample in samples or ():
        operation = by_name.get(sample.get("operation") if isinstance(sample, dict) else None)
        if not operation:
            raise ProposalError("A sample refers to an operation that is not in the proposal")
        try:
            validate(sample.get("arguments", {}), operation.get("input_schema", {"type": "object"}))
            validate(sample.get("response", {}), operation.get("output_schema", {"type": "object"}))
        except ValidationError:
            raise ProposalError(
                f"The documented sample for {operation['name']} does not match its declared schemas"
            ) from None
        checked += 1
    return {
        "static": "passed",
        "host": parsed.hostname,
        "operations": len(operations),
        "write_operations": writes,
        "samples_checked": checked,
        "contacted": False,
    }


def _resolve(schema, components, hops=0):
    """Inline local component references. Only reference hops are counted, so a cyclic document cannot
    expand without limit while ordinary nesting is left intact."""
    if isinstance(schema, dict):
        reference = schema.get("$ref")
        if isinstance(reference, str):
            if hops >= 8 or not reference.startswith("#/components/schemas/"):
                return {"type": "object"}
            return _resolve(components.get(reference.rsplit("/", 1)[-1], {"type": "object"}), components, hops + 1)
        return {
            key: _resolve(value, components, hops)
            for key, value in schema.items()
            if key not in ("example", "examples", "xml", "externalDocs", "discriminator")
        }
    if isinstance(schema, list):
        return [_resolve(item, components, hops) for item in schema]
    return schema


def openapi_to_config(document, base_url=None):
    """Convert an OpenAPI 3 document into a REST connection draft. Deterministic; contacts nothing.

    Operations the connector cannot express (templated paths, non-JSON bodies) are skipped and reported.
    """
    if not isinstance(document, dict) or not str(document.get("openapi", "")).startswith("3"):
        raise ProposalError("An OpenAPI 3 JSON document is required")
    servers = document.get("servers") or []
    base_url = base_url or (servers[0].get("url") if servers and isinstance(servers[0], dict) else None)
    parsed = urlparse(base_url or "")
    if parsed.scheme != "https" or not parsed.hostname:
        raise ProposalError("The document needs an https server URL, or supply base_url")
    components = (document.get("components") or {}).get("schemas") or {}
    operations, skipped, used = [], [], set()
    for path, item in sorted((document.get("paths") or {}).items()):
        if not isinstance(item, dict):
            continue
        for method in METHODS:
            operation = item.get(method.lower())
            if not isinstance(operation, dict):
                continue
            label = f"{method} {path}"
            if not static_path(path):
                skipped.append({"operation": label, "reason": "path parameters are not supported"})
                continue
            name = re.sub(r"[^a-z0-9_]+", "_", str(operation.get("operationId") or f"{method}_{path}").lower())
            name = re.sub(r"_+", "_", name).strip("_")[:60]
            if not NAME.match(name) or name in used:
                skipped.append({"operation": label, "reason": "no usable unique operation name"})
                continue
            if method == "GET":
                properties, required = {}, []
                for parameter in [*item.get("parameters", []), *operation.get("parameters", [])]:
                    if isinstance(parameter, dict) and parameter.get("in") == "query" and parameter.get("name"):
                        properties[parameter["name"]] = _resolve(parameter.get("schema", {}), components)
                        if parameter.get("required"):
                            required.append(parameter["name"])
                input_schema = {"type": "object", "properties": properties, "additionalProperties": False}
                if required:
                    input_schema["required"] = required
            else:
                content = ((operation.get("requestBody") or {}).get("content") or {}).get("application/json")
                if (operation.get("requestBody") or {}).get("content") and not content:
                    skipped.append({"operation": label, "reason": "only JSON request bodies are supported"})
                    continue
                input_schema = _resolve((content or {}).get("schema", {"type": "object"}), components)
            responses = operation.get("responses") or {}
            success = responses.get("200") or responses.get("201") or {}
            output = ((success.get("content") or {}).get("application/json") or {}).get("schema", {"type": "object"})
            output_schema = _resolve(output, components)
            if output_schema.get("type") != "object":
                # The runtime's tool contract is an object; wrap anything else rather than guess.
                skipped.append({"operation": label, "reason": "response is not a JSON object"})
                continue
            if len(operations) >= MAX_OPERATIONS:
                skipped.append({"operation": label, "reason": f"limit of {MAX_OPERATIONS} operations reached"})
                continue
            used.add(name)
            operations.append(
                {
                    "name": name,
                    "description": str(operation.get("summary") or operation.get("description") or label)[:500],
                    "path": path,
                    "method": method,
                    "input_schema": input_schema,
                    "output_schema": output_schema,
                }
            )
    if not operations:
        raise ProposalError("No operation in the document can be expressed by the REST connector")
    config = {
        "base_url": f"https://{parsed.netloc}{parsed.path.rstrip('/')}",
        "allowed_hosts": [parsed.hostname],
        "operations": operations,
    }
    return config, skipped


def create_proposal(
    db, org_id, name, config, rationale="", samples=(), sources=(), agent_id=None, job_id=None, origin="manual"
):
    checks = check_rest_config(config, samples)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
        raise ProposalError("A proposal needs a name of at most 200 characters")
    proposal = ConnectionProposal(
        org_id=org_id,
        agent_id=agent_id,
        job_id=job_id,
        name=name.strip(),
        kind="rest",
        config=redact_tenant(db, org_id, config),
        rationale=redact_tenant(db, org_id, str(rationale)[:4000]),
        sources=[str(source)[:500] for source in list(sources)[:20]],
        checks=checks,
        origin=origin,
    )
    db.add(proposal)
    db.flush()
    return proposal


async def approve_proposal(db, actor, proposal, secret, allow_write, confirmed_hosts, attach=True):
    """Create the connection. Only here does a credential exist, encrypted, and only here is anything contacted."""
    from factory.builder import available_tools, persist_version
    from factory.connectors import discover_connection
    from factory.runtime import emit

    if proposal.status != "proposed":
        raise ProposalError("This proposal has already been reviewed")
    checks = check_rest_config(proposal.config)
    if sorted(confirmed_hosts or []) != sorted(proposal.config["allowed_hosts"]):
        raise PermissionError("Confirm the exact hosts this connection may reach")
    connection = Connection(
        org_id=proposal.org_id,
        name=proposal.name,
        kind=proposal.kind,
        config=proposal.config,
        encrypted_secret=encrypt(secret or ""),
        permissions={"read": True, "write": bool(allow_write)},
        status="setup_required",
    )
    db.add(connection)
    db.flush()
    await discover_connection(db, connection)
    proposal.status, proposal.connection_id = "approved", connection.id
    proposal.reviewed_by, proposal.reviewed_at = actor.user_id, now()
    proposal.checks = {**checks, "activated": True, "write_granted": bool(allow_write)}
    version = None
    if attach and proposal.agent_id:
        agent = db.get(AgentRecord, proposal.agent_id)
        if agent and agent.org_id == proposal.org_id:
            base = db.get(AgentVersion, agent.best_version_id) if agent.best_version_id else None
            base = base or db.scalar(
                select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.number.desc())
            )
            spec = AgentSpec.model_validate(base.spec)
            tools = available_tools(db, proposal.org_id, [connection.id])
            spec.connection_ids = [*spec.connection_ids, connection.id]
            spec.tools = [*spec.tools, *[tool.id for tool in tools]]
            version = persist_version(db, agent, spec, f"Administrator-approved connection: {proposal.name}")
            job = db.scalar(
                select(BuildJob)
                .where(BuildJob.agent_id == agent.id, BuildJob.org_id == proposal.org_id)
                .order_by(BuildJob.created_at.desc())
                .with_for_update()
            )
            terminal = {"READY_FOR_REVIEW", "DEPLOYED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"}
            if job and job.state not in terminal and job.iteration < job.budget["max_iterations"]:
                entry = {
                    "from_version_id": job.checkpoint.get("version_id"),
                    "version_id": version.id,
                    "reason": f"Connection approved: {proposal.name}",
                    "actor_id": actor.user_id,
                    "at": now().isoformat(),
                }
                # Same rule as a redirect: new capabilities need fresh evidence, never old scorecards.
                job.checkpoint = {
                    "version_id": version.id,
                    "stagnation": 0,
                    "redirections": [*job.checkpoint.get("redirections", []), entry],
                }
                job.state, job.error = "BUILDING", None
                job.lease_owner, job.lease_until = None, None
                emit(db, proposal.org_id, "build_redirected", entry, job_id=job.id)
    return connection, version
