"""Builder-authored bundle contents: examples, tool notes and verifiers are executed by the runtime."""

import json

import pytest
from agents import Model, ModelResponse, Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from sqlalchemy import select

from factory.builder import persist_version
from factory.config import settings
from factory.db import uid
from factory.evaluation import evaluate_case
from factory.models import Approval, EvaluationCase, EvaluationRun, ToolDefinition
from factory.runtime import bundle_instructions, execute, reconstruct_agent, tool_name
from factory.schemas import AgentSpec, Example, Verifier
from factory.verifiers import verify


def message(payload):
    return ResponseOutputMessage(
        type="message",
        role="assistant",
        id=uid(),
        status="completed",
        content=[ResponseOutputText(type="output_text", text=json.dumps(payload), annotations=[])],
    )


class ScriptedModel(Model):
    """Local provider transport: reads one collection, then returns the next scripted final answer."""

    def __init__(self, tool_name, finals):
        self.tool_name, self.finals = tool_name, list(finals)
        self.instructions, self.user_inputs, self.final_calls = [], [], 0

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        self.instructions.append(system_instructions)
        items = input if isinstance(input, list) else [{"role": "user", "content": input}]
        pending_tool = not any(isinstance(i, dict) and i.get("type") == "function_call_output" for i in items)
        if pending_tool:
            self.user_inputs.append(
                next(i["content"] for i in items if isinstance(i, dict) and i.get("role") == "user")
            )
            output = [
                ResponseFunctionToolCall(
                    type="function_call",
                    name=self.tool_name,
                    arguments=json.dumps({"collection": "products"}),
                    call_id=uid(),
                    id=uid(),
                )
            ]
        else:
            self.final_calls += 1
            output = [message(self.finals.pop(0))]
        return ModelResponse(
            output=output, usage=Usage(requests=1, input_tokens=5, output_tokens=5, total_tokens=10), response_id=uid()
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


@pytest.fixture
def custom(db, seeded, monkeypatch):
    """A live custom agent over the fictional ERP's read tool, driven by a scripted provider."""
    _, _, agent, initial, suite, connection = seeded
    read = db.scalar(
        select(ToolDefinition).where(
            ToolDefinition.connection_id == connection.id, ToolDefinition.name == "read_records"
        )
    )
    spec = AgentSpec.model_validate(initial.spec)
    agent.template = spec.template = "custom"
    spec.tools = [read.id]
    spec.output_schema = {
        "type": "object",
        "required": ["count", "status"],
        "properties": {"count": {"type": "integer"}, "status": {"type": "string"}},
        "additionalProperties": False,
    }
    spec.verifiers = [
        Verifier(id="known_status", kind="one_of", path="status", values=["ok", "empty"]),
        Verifier(id="count_positive", kind="range", path="count", minimum=1),
    ]
    spec.examples = [
        Example(input={"text": "How many products?"}, output={"count": 100, "status": "ok"}, note="Count rows")
    ]
    spec.tool_notes = {read.id: "Collections are plural, for example products."}
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr(settings(), "execution_mode", "live")

    def install(finals):
        model = ScriptedModel(tool_name(read), finals)

        def bind(context, mode):
            built = reconstruct_agent(context, mode)
            built.model = model
            return built

        monkeypatch.setattr("factory.runtime.reconstruct_agent", bind)
        return model

    return agent, spec, suite, read, install


def test_verifier_vocabulary_is_closed_and_never_raises_on_malformed_output():
    total = Verifier(id="total", kind="sum_equals", path="lines", field="amount", total_path="total")
    assert verify([total], {"lines": [{"amount": 2}, {"amount": 3}], "total": 5}) == []
    assert verify([total], {"lines": [{"amount": 2}], "total": 5})[0]["id"] == "total"
    # Malformed shapes are failures, not exceptions.
    for broken in (
        {},
        {"lines": "x", "total": 1},
        {"lines": [{}], "total": 1},
        {"lines": [{"amount": True}], "total": 1},
    ):
        assert verify([total], broken)
    required = Verifier(id="needs_name", kind="required", path="customer.name")
    assert verify([required], {"customer": {"name": "Harbor"}}) == []
    assert verify([required], {"customer": {"name": ""}}) and verify([required], {})
    schema = Verifier(id="shape", kind="schema", path="$", schema={"type": "object", "required": ["id"]})
    assert verify([schema], {"id": 1}) == [] and verify([schema], {})
    bounded = Verifier(id="bounded", kind="range", path="n", minimum=0, maximum=10)
    assert verify([bounded], {"n": 5}) == []
    assert verify([bounded], {"n": 11}) and verify([bounded], {"n": "5"}) and verify([bounded], {"n": True})
    with pytest.raises(ValueError):
        Verifier(id="x", kind="eval", path="$")  # no expression or code kinds exist
    with pytest.raises(ValueError):
        Verifier(id="x", kind="sum_equals", path="lines")


def test_bundle_instructions_render_examples_and_only_notes_for_authorized_tools():
    spec = AgentSpec(
        name="n",
        purpose="p",
        template="custom",
        instructions="Base instructions.",
        tools=["tool-1"],
        tool_contracts={"tool-1": {"name": "read_records"}},
        examples=[Example(input={"text": "a"}, output={"ok": True}, note="why")],
        tool_notes={"tool-1": "Use plural names."},
    )
    text = bundle_instructions(spec)
    assert text.startswith("Base instructions.")
    assert '{"text": "a"}' in text and '{"ok": true}' in text and "why" in text
    assert "read_records__tool_1: Use plural names." in text
    spec.tool_notes = {"other": "ignored"}
    assert "ignored" not in bundle_instructions(spec)


@pytest.mark.asyncio
async def test_failed_verifier_gets_one_repair_with_feedback_and_then_passes(db, custom):
    agent, spec, _, _, install = custom
    version = persist_version(db, agent, spec)
    model = install([{"count": 100, "status": "DONE"}, {"count": 100, "status": "ok"}])
    run = await execute(db, version, {"text": "How many products?"})
    assert run.status == "completed", run.error
    assert run.output == {"count": 100, "status": "ok"}
    assert run.metrics["verifier_repairs"] == 1 and run.metrics["verification_failures"] == []
    assert run.metrics["verifiers_checked"] == 2
    # The repair pass is told exactly which verifier failed; the first pass is the plain input.
    assert json.loads(model.user_inputs[0]) == {"text": "How many products?"}
    feedback = json.loads(model.user_inputs[1])["verification_feedback"]
    assert [item["id"] for item in feedback] == ["known_status"]
    # Examples and tool notes reached the model.
    assert "Worked examples" in model.instructions[0] and "Collections are plural" in model.instructions[0]
    assert run.metrics["tokens"] == 40  # both passes are accounted


@pytest.mark.asyncio
async def test_repair_is_bounded_and_persistent_failure_needs_attention(db, custom):
    agent, spec, _, _, install = custom
    version = persist_version(db, agent, spec)
    model = install([{"count": 0, "status": "nope"}, {"count": 0, "status": "nope"}, {"count": 1, "status": "ok"}])
    run = await execute(db, version, {"text": "How many products?"})
    assert model.final_calls == 2, "exactly one repair attempt"
    assert run.status == "needs_attention"
    assert run.metrics["verification_failures"] == ["known_status", "count_positive"]
    # The deliverable's output contract is not rewritten by the verifier.
    assert run.output == {"count": 0, "status": "nope"}


@pytest.mark.asyncio
async def test_unverified_template_output_is_never_staged_for_approval(db, seeded):
    _, _, agent, initial, _, _ = seeded
    spec = AgentSpec.model_validate(initial.spec)
    spec.verifiers = [Verifier(id="small_orders_only", kind="range", path="total_cents", maximum=1)]
    version = persist_version(db, agent, spec)
    run = await execute(db, version, {"text": "Harbor Bistro: 2 kg Tomatoes"})
    assert run.output["total_cents"] > 1 and not run.output["flags"]
    assert run.status == "needs_attention"
    assert run.metrics["verification_failures"] == ["small_orders_only"]
    assert run.metrics["verifier_repairs"] == 0  # deterministic demo execution is never re-run
    assert db.scalar(select(Approval).where(Approval.run_id == run.id)) is None
    # The same input without the verifier is staged as before.
    plain = await execute(db, initial, {"text": "Harbor Bistro: 2 kg Tomatoes"})
    assert plain.status == "waiting_for_approval"


@pytest.mark.asyncio
async def test_evaluation_grades_verifier_failures(db, custom):
    agent, spec, suite, _, install = custom
    version = persist_version(db, agent, spec)
    install([{"count": 0, "status": "ok"}, {"count": 0, "status": "ok"}])
    case = EvaluationCase(
        org_id=agent.org_id,
        suite_id=suite.id,
        name="Counts products",
        split="development",
        input={"text": "How many products?"},
        assertions=[{"path": "count", "value": 0}],
    )
    evaluation = EvaluationRun(org_id=agent.org_id, version_id=version.id, suite_id=suite.id)
    db.add_all([case, evaluation])
    db.flush()
    result = await evaluate_case(db, evaluation, version, case)
    assert "verification" in result.failures and not result.passed
    assert [c["passed"] for c in result.checks if c["category"] == "structured_accuracy"] == [True], result.checks


@pytest.mark.parametrize("split", ["regression", "validation"])
def test_examples_cannot_be_drawn_from_or_copy_protected_cases(db, custom, split):
    agent, spec, suite, _, _ = custom
    protected = EvaluationCase(
        org_id=agent.org_id,
        suite_id=suite.id,
        name="Protected",
        split=split,
        input={"text": "secret scenario"},
        assertions=[],
    )
    development = EvaluationCase(
        org_id=agent.org_id,
        suite_id=suite.id,
        name="Dev",
        split="development",
        input={"text": "open scenario"},
        assertions=[],
    )
    db.add_all([protected, development])
    db.flush()
    answer = {"count": 1, "status": "ok"}
    spec.examples = [Example(input={"text": "anything"}, output=answer, source_case=protected.id)]
    with pytest.raises(PermissionError, match="development cases"):
        persist_version(db, agent, spec)
    spec.examples = [Example(input={"text": "secret scenario"}, output=answer)]
    with pytest.raises(PermissionError, match="regression or held-out"):
        persist_version(db, agent, spec)
    spec.examples = [Example(input={"text": "open scenario"}, output=answer, source_case=development.id)]
    assert persist_version(db, agent, spec).spec["examples"][0]["source_case"] == development.id
    spec.examples = [Example(input={"text": "x"}, output=answer, source_case=uid())]
    with pytest.raises(PermissionError):
        persist_version(db, agent, spec)


def test_bundle_contents_must_match_the_version_contract(db, custom):
    agent, spec, _, _, _ = custom
    spec.tool_notes = {uid(): "A tool this version does not have"}
    with pytest.raises(PermissionError, match="Tool notes"):
        persist_version(db, agent, spec)
    spec.tool_notes = {}
    spec.examples = [Example(input={"text": "x"}, output={"count": "many", "status": "ok"})]
    with pytest.raises(Exception, match="is not of type"):
        persist_version(db, agent, spec)
