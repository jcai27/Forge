from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class Budget(StrictModel):
    max_iterations: int = Field(default=10, ge=1, le=100)
    max_cost: float = Field(default=5, ge=0, le=1000)
    max_seconds: int = Field(default=1800, ge=1, le=86400)
    target_score: float = Field(default=0.95, ge=0, le=1)
    stagnation_limit: int = Field(default=3, ge=1, le=20)


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
