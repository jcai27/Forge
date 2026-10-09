from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class CreateCase(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    split: Literal["development", "regression", "validation"]
    source: Literal["synthetic", "replay", "human", "live_read_only"] = "synthetic"
    input: dict
    assertions: list[dict]
    critical: bool = False
    trials: int = Field(default=1, ge=1, le=20)
