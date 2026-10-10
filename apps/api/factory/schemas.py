from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def checked_schema(schema):
    """A malformed JSON Schema is a validation error here, never an unhandled SchemaError."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"Invalid JSON Schema: {error.message[:120]}") from None
    return schema


class BusinessRequirements(StrictModel):
    objective: str
    inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    required_systems: list[str] = Field(default_factory=list)
    workflow_steps: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    success_metrics: list[str] = Field(default_factory=list)
    side_effect_permissions: str = "explicit_human_approval"
    assumptions: list[str] = Field(default_factory=list)


class QualityPolicy(StrictModel):
    minimum_score: float = Field(default=0.95, ge=0, le=1)
    minimum_cases: int = Field(default=1, ge=1, le=10000)
    minimum_validation_cases: int = Field(default=1, ge=1, le=10000)
    maximum_mean_latency_ms: float = Field(default=60000, ge=0, le=3600000)
    maximum_evaluation_cost: float = Field(default=1000, ge=0, le=1000)
    objective: Literal["pass_rate", "cost", "latency"] = "pass_rate"
    minimum_improvement: float = Field(default=0, ge=0, le=1000)


class Example(StrictModel):
    """A worked input/output the runtime shows the model. Provenance is checked when a version is persisted."""

    input: dict
    output: dict
    note: str = Field(default="", max_length=500)
    source_case: str | None = None


class Verifier(StrictModel):
    """Closed vocabulary of deterministic output checks run before a result is returned."""

    # Stored versions serialise the field name, authored input uses the "schema" alias; accept both.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")
    kind: Literal["required", "one_of", "range", "sum_equals", "schema"]
    path: str = Field(default="$", max_length=200)
    values: list[Any] | None = Field(default=None, max_length=100)
    minimum: float | None = None
    maximum: float | None = None
    field: str | None = Field(default=None, max_length=100)
    total_path: str | None = Field(default=None, max_length=200)
    tolerance: float = Field(default=0, ge=0, le=1000000)
    expected_schema: dict | None = Field(default=None, alias="schema")
    message: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def complete(self):
        needs = {
            "one_of": self.values is not None and len(self.values) > 0,
            "range": self.minimum is not None or self.maximum is not None,
            "sum_equals": bool(self.field and self.total_path),
            "schema": self.expected_schema is not None,
            "required": True,
        }
        if not needs[self.kind]:
            raise ValueError(f"Verifier kind {self.kind} is missing required parameters")
        if self.expected_schema is not None:
            checked_schema(self.expected_schema)
        return self


class GeneratedTool(StrictModel):
    """Builder-written tool code. It runs only in the sandbox and reaches systems only through capabilities."""

    name: str = Field(min_length=3, max_length=40, pattern=r"^[a-z][a-z0-9_]+$")
    description: str = Field(min_length=1, max_length=500)
    input_schema: dict = Field(default_factory=lambda: {"type": "object"})
    output_schema: dict = Field(default_factory=lambda: {"type": "object"})
    code: str = Field(min_length=1, max_length=20000)
    # alias used in code -> a registered tool id of this version. The only way out of the sandbox.
    capabilities: dict[str, str] = Field(default_factory=dict)
    # sha256 of code, set when the version is persisted and re-checked before every run.
    code_hash: str = Field(default="", max_length=64)

    @field_validator("capabilities")
    @classmethod
    def bounded_capabilities(cls, capabilities):
        if len(capabilities) > 8 or any(not alias.isidentifier() for alias in capabilities):
            raise ValueError("A generated tool has at most 8 capabilities with identifier aliases")
        return capabilities

    @field_validator("input_schema", "output_schema")
    @classmethod
    def valid_schema(cls, schema):
        return checked_schema(schema)


class AgentSpec(StrictModel):
    schema_version: int = 1
    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=10000)
    template: Literal["orders", "quotes", "hiring", "custom"]
    instructions: str = Field(min_length=1, max_length=20000)
    model: str = "gpt-4.1-mini"
    tools: list[str] = Field(default_factory=list)
    connection_ids: list[str] = Field(default_factory=list)
    tool_contracts: dict = Field(default_factory=dict)
    connection_fingerprints: dict[str, str] = Field(default_factory=dict)
    input_schema: dict = Field(
        default_factory=lambda: {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    )
    output_schema: dict = Field(default_factory=lambda: {"type": "object"})
    workflow: list[dict] = Field(default_factory=list)
    rules: dict = Field(
        default_factory=lambda: {
            "resolve_aliases": False,
            "fuzzy_match": False,
            "aggregate_duplicates": True,
            "check_inventory": True,
            "margin": 0.25,
        }
    )
    guardrails: dict = Field(default_factory=lambda: {"require_approval": True, "deny_production_evaluation": True})
    max_turns: int = Field(default=12, ge=1, le=50)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    max_cost: float = Field(default=1, ge=0, le=100)
    requirements: BusinessRequirements | None = None
    quality_policy: QualityPolicy = Field(default_factory=QualityPolicy)
    design_metrics: dict = Field(default_factory=dict)
    # Builder-authored bundle contents. The runtime acts on every one of these.
    examples: list[Example] = Field(default_factory=list, max_length=8)
    verifiers: list[Verifier] = Field(default_factory=list, max_length=20)
    tool_notes: dict[str, str] = Field(default_factory=dict)
    generated_tools: list[GeneratedTool] = Field(default_factory=list, max_length=6)

    @field_validator("tool_notes")
    @classmethod
    def bounded_notes(cls, notes):
        if len(notes) > 40 or any(len(note) > 1000 for note in notes.values()):
            raise ValueError("Tool notes are limited to 40 entries of 1000 characters")
        return notes

    @field_validator("examples")
    @classmethod
    def bounded_examples(cls, examples):
        import json

        if any(len(json.dumps(example.model_dump())) > 6000 for example in examples):
            raise ValueError("Each example is limited to 6000 serialized characters")
        return examples


class SpecPatch(StrictModel):
    """The only fields a builder may change. Locked fields do not exist here, so they cannot be named."""

    hypothesis: str = Field(default="", max_length=1000)
    instructions: str | None = Field(default=None, min_length=1, max_length=20000)
    rules: dict | None = None
    output_schema: dict | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    examples: list[Example] | None = Field(default=None, max_length=8)
    verifiers: list[Verifier] | None = Field(default=None, max_length=20)
    tool_notes: dict[str, str] | None = None
    generated_tools: list[GeneratedTool] | None = Field(default=None, max_length=6)

    @field_validator("output_schema")
    @classmethod
    def object_schema(cls, schema):
        # An agent result is a JSON object. Anything else here is a malformed reply, not a schema.
        if schema is not None:
            if schema.get("type") != "object":
                raise ValueError("output_schema must be a JSON Schema of type object")
            checked_schema(schema)
        return schema


class Budget(StrictModel):
    max_iterations: int = Field(default=10, ge=1, le=100)
    max_cost: float = Field(default=5, ge=0, le=1000)
    max_seconds: int = Field(default=1800, ge=1, le=86400)
    target_score: float = Field(default=0.95, ge=0, le=1)
    stagnation_limit: int = Field(default=3, ge=1, le=20)
    # Proposals generated per round. One reproduces the original single-candidate loop.
    candidates_per_round: int = Field(default=1, ge=1, le=6)
    # Passing development cases added to a screen so a candidate cannot win by breaking them.
    screen_sample: int = Field(default=3, ge=0, le=20)
    # Investigator tool-use turns for the live optimizer. Zero keeps the one-shot behaviour.
    investigator_turns: int = Field(default=6, ge=0, le=20)


class RedirectBuild(StrictModel):
    expected_version_id: str
    reason: str = Field(min_length=10, max_length=4000)
    spec: AgentSpec


class Register(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=200)
    organization: str = Field(min_length=1, max_length=200)


class Login(StrictModel):
    email: str
    password: str
    org_id: str | None = None


class CreateProject(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class CreateAgent(StrictModel):
    project_id: str
    request: str = Field(min_length=10, max_length=10000)
    connection_ids: list[str] = Field(default_factory=list)
    template: Literal["orders", "quotes", "hiring", "custom"] | None = None


class CreateConnection(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["fixture", "rest", "postgres", "file", "webhook", "email", "mcp"]
    config: dict = Field(default_factory=dict)
    secret: str = Field(default="", max_length=20000)
    permissions: dict = Field(default_factory=lambda: {"read": True, "write": False})


class Invoke(StrictModel):
    input: dict
    idempotency_key: str = Field(min_length=1, max_length=200)


class Assertion(StrictModel):
    scope: Literal["output", "state", "metrics"] = "output"
    path: str = Field(default="$", max_length=500)
    op: Literal["equals", "contains", "gte", "lte", "json_schema", "contains_record"] = "equals"
    value: Any = None
    expected_schema: dict | None = Field(default=None, alias="schema")
    category: str = Field(default="structured_accuracy", min_length=1, max_length=100, pattern=r"^[a-z_]+$")


class ReplayResponse(StrictModel):
    tool_id: str
    arguments: dict
    response: dict


class DataMapping(StrictModel):
    source_id: str
    collection: str = Field(min_length=1, max_length=100)
    fields: dict[str, str] = Field(min_length=1, max_length=100)


class CaseEnvironment(StrictModel):
    state_overrides: dict[str, list[dict]] = Field(default_factory=dict)
    replay: list[ReplayResponse] = Field(default_factory=list, max_length=1000)
    live_connection_ids: list[str] = Field(default_factory=list, max_length=100)
    data_mappings: list[DataMapping] = Field(default_factory=list, max_length=20)


class QualitativeRubric(StrictModel):
    criteria: list[str] = Field(min_length=1, max_length=20)
    threshold: float = Field(default=0.8, ge=0, le=1)


class HumanReview(StrictModel):
    passed: bool
    evidence: str = Field(min_length=10, max_length=4000)


class CreateCase(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    split: Literal["development", "regression", "validation"]
    source: Literal["synthetic", "replay", "human", "live_read_only"] = "synthetic"
    input: dict
    assertions: list[dict]
    critical: bool = False
    trials: int = Field(default=1, ge=1, le=20)
    environment: CaseEnvironment = Field(default_factory=CaseEnvironment)
    rubric: QualitativeRubric | None = None

    @field_validator("assertions")
    @classmethod
    def valid_assertions(cls, assertions):
        from jsonschema import Draft202012Validator

        for item in assertions:
            assertion = Assertion.model_validate(item)
            if assertion.op == "contains_record" and not isinstance(assertion.value, dict):
                raise ValueError("Record assertions require expected field values")
            if assertion.op == "json_schema":
                if assertion.expected_schema is None:
                    raise ValueError("Schema assertions require a schema")
                Draft202012Validator.check_schema(assertion.expected_schema)
        return assertions


class TestDesign(StrictModel):
    rationale: str = Field(min_length=10, max_length=4000)
    cases: list[CreateCase] = Field(min_length=6, max_length=40)


class CreateTrigger(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["schedule", "webhook"]
    input: dict = Field(default_factory=dict)
    interval_seconds: int | None = Field(default=None, ge=10, le=86400 * 30)
    secret: str = Field(default="", max_length=10000)


class TriggerUpdate(StrictModel):
    enabled: bool


class Reconciliation(StrictModel):
    outcome: Literal["applied", "not_applied"]
    receipt: str = Field(min_length=10, max_length=2000)
