"""Behaviour that only a real model exposed: tool naming, tool choice, argument shape and provider options."""

import pytest
from sqlalchemy import select

from factory.builder import persist_version, structured_output
from factory.config import Settings, settings
from factory.models import ExecutionRun, ToolDefinition
from factory.runtime import ExecutionContext, reconstruct_agent, tool_name, tool_name_for
from factory.schemas import AgentSpec, Budget, SpecPatch
from factory.workflow import advance, new_job


def context_for(db, version):
    run = ExecutionRun(org_id=version.org_id, version_id=version.id, mode="live", input={})
    db.add(run)
    db.flush()
    return ExecutionContext(db, version, run, AgentSpec.model_validate(version.spec), {}, True)


def test_tool_names_are_readable_unique_and_valid():
    name = tool_name_for("d3fb0850-b21c-4a5e-9d3e-0a1b2c3d4e5f", "prepare_operation")
    assert name == "prepare_operation__d3fb0850_b21c_4a5e_9d3e_0a1b2c3d4e5f"
    long = tool_name_for("d3fb0850-b21c-4a5e-9d3e-0a1b2c3d4e5f", "a very long tool name! with spaces and punctuation")
    assert len(long) <= 64 and all(ch.isalnum() or ch == "_" for ch in long)
    assert tool_name_for("a-b", "x") != tool_name_for("a-c", "x")


def test_live_template_agent_is_offered_only_its_preparation_tool_with_a_useful_schema(db, seeded, monkeypatch):
    _, _, agent, initial, _, connection = seeded
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    prepare = db.scalar(
        select(ToolDefinition).where(
            ToolDefinition.connection_id == connection.id, ToolDefinition.name == "prepare_operation"
        )
    )
    built = reconstruct_agent(context_for(db, initial), "live")
    # A template agent stops on its first call, so a second tool could only be a wrong turn.
    assert [tool.name for tool in built.tools] == [tool_name(prepare)]
    assert built.model_settings.tool_choice == tool_name(prepare)
    # The model is shown what the input must contain, not just "an object".
    assert built.tools[0].params_json_schema["properties"]["input"] == initial.spec["input_schema"]

    spec = AgentSpec.model_validate(initial.spec)
    agent.template = spec.template = "custom"
    custom = reconstruct_agent(context_for(db, persist_version(db, agent, spec)), "live")
    assert len(custom.tools) == len(spec.tools) > 1, "a custom agent keeps every authorized tool"
    assert custom.model_settings.tool_choice is None


def test_prompt_mode_moves_the_schema_into_the_instructions(monkeypatch):
    instructions, output_type = structured_output(SpecPatch, "Base.")
    assert instructions == "Base." and output_type is not None
    monkeypatch.setattr(settings(), "openai_structured_output", "prompt")
    instructions, output_type = structured_output(SpecPatch, "Base.")
    assert output_type is None
    assert instructions.startswith("Base.") and '"hypothesis"' in instructions
    assert "do not wrap it in another object" in instructions


def test_provider_options_are_validated():
    assert Settings(openai_api="chat_completions", openai_structured_output="prompt").validate_provider() is None
    with pytest.raises(ValueError):
        Settings(openai_api="grpc").validate_provider()
    with pytest.raises(ValueError):
        Settings(openai_structured_output="hope").validate_provider()


@pytest.mark.asyncio
async def test_a_proposal_that_times_out_is_a_rejected_attempt_not_a_failed_build(db, seeded, monkeypatch):
    _, _, agent, initial, _, _ = seeded

    async def slow(spec, development_failures, **kwargs):
        raise TimeoutError

    monkeypatch.setattr("factory.workflow.optimize", slow)
    job = new_job(db, agent, Budget(stagnation_limit=5))
    job.state = "OPTIMIZING"
    job.checkpoint = {**job.checkpoint, "diagnosis": {"development_failures": [{"case": "x"}]}}
    db.commit()
    await advance(db, job)
    db.commit()
    assert job.state == "OPTIMIZING" and job.error is None
    assert job.checkpoint["attempts"][-1]["rejected_before_evaluation"] == "TimeoutError"
    assert job.checkpoint["version_id"] == initial.id


def test_patch_parsing_keeps_valid_fields_and_never_widens_what_a_patch_can_do():
    from agents import ModelBehaviorError

    from factory.builder import parse_patch

    # A weak model's reply: wrapped, with empty placeholders, one good change and junk elsewhere.
    reply = (
        '{"spec": {"hypothesis": "Aliases are not resolved", "instructions": "", "output_schema": {}, '
        '"rules": {"resolve_aliases": true}, "examples": [{"text": "not an example"}], '
        '"verifiers": [{"path": "x"}], "status": "passed"}}'
    )
    patch, dropped = parse_patch(reply)
    assert patch.rules == {"resolve_aliases": True} and patch.hypothesis == "Aliases are not resolved"
    assert patch.instructions is None and patch.output_schema is None, "empty placeholders change nothing"
    assert patch.examples is None and patch.verifiers is None
    assert dropped == ["examples", "status", "verifiers"]

    clean, none_dropped = parse_patch('{"hypothesis": "x", "rules": {"margin": 0.3}}')
    assert clean.rules == {"margin": 0.3} and none_dropped == []
    assert parse_patch('{"hypothesis": ""}')[0] == SpecPatch(), "an explicitly empty patch is still allowed"

    # Naming a field outside the patch is refused, wrapped or not. Nothing is salvaged from it.
    for locked in ('{"tools": ["x"], "rules": {"margin": 0.3}}', '{"spec": {"template": "custom", "rules": {"a": 1}}}'):
        with pytest.raises(ModelBehaviorError, match="outside the patch"):
            parse_patch(locked)
    # A reply with nothing usable is rejected rather than evaluated as a no-op.
    for useless in ('{"examples": [{"bad": 1}]}', '{"hypothesis": "h", "verifiers": [{}]}', "no json", "[1, 2]"):
        with pytest.raises(ModelBehaviorError):
            parse_patch(useless)
    # A junk object is not accepted as an output schema.
    patch, dropped = parse_patch('{"rules": {"margin": 0.3}, "output_schema": {"requires_approval": null}}')
    assert patch.output_schema is None and dropped == ["output_schema"]


def test_a_malformed_json_schema_in_a_patch_is_a_dropped_field_not_a_crash():
    from factory.builder import parse_patch
    from factory.schemas import GeneratedTool, Verifier

    # Seen from a real model: a schema whose "type" is not a valid JSON Schema type.
    bad = {"type": "object", "properties": {"a": {"type": "not-a-type"}}}
    patch, dropped = parse_patch({"rules": {"margin": 0.3}, "output_schema": bad})
    assert patch.output_schema is None and dropped == ["output_schema"]
    with pytest.raises(ValueError):
        Verifier(id="v", kind="schema", schema={"type": "nope"})
    with pytest.raises(ValueError):
        GeneratedTool(name="tool", description="d", code="x", input_schema={"type": "nope"})
    with pytest.raises(ValueError):
        SpecPatch(output_schema=bad)


def test_patch_parsing_reads_the_first_complete_object_and_prompt_mode_uses_the_field_guide(monkeypatch):
    from factory.builder import OPTIMIZER_INSTRUCTIONS, PATCH_GUIDE, parse_patch

    # Seen from a real model: a second object, or commentary, after a valid patch.
    patch, dropped = parse_patch('{"hypothesis": "h", "rules": {"margin": 0.3}}, \n{"instructions": "another object"}')
    assert patch.rules == {"margin": 0.3} and patch.instructions is None and dropped == []
    patch, _ = parse_patch('```json\n{"hypothesis": "h", "rules": {"margin": 0.3}}\n``` I changed the margin.')
    assert patch.rules == {"margin": 0.3}

    monkeypatch.setattr(settings(), "openai_structured_output", "prompt")
    instructions, output_type = structured_output(SpecPatch, OPTIMIZER_INSTRUCTIONS, guide=PATCH_GUIDE)
    assert output_type is None and instructions.endswith(PATCH_GUIDE)
    assert "$defs" not in instructions, "the field guide replaces the JSON Schema"
    # The guide may only describe fields the patch really has, and must not hint at the benchmark's answer.
    for field in ("hypothesis", "rules", "instructions", "tool_notes", "examples", "verifiers", "generated_tools"):
        assert f'"{field}"' in PATCH_GUIDE and field in SpecPatch.model_fields
    assert "resolve_aliases" not in PATCH_GUIDE and "fuzzy_match" not in PATCH_GUIDE


class PlainText:
    """Builds a local provider transport that answers with fixed text and records what it was sent."""

    def __init__(self, reply):
        from agents import Model, ModelResponse, Usage
        from openai.types.responses import ResponseOutputMessage, ResponseOutputText

        from factory.db import uid

        seen = self.seen = {}

        class Transport(Model):
            async def get_response(
                self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
            ):
                seen["instructions"], seen["schema"] = system_instructions, output_schema
                text = ResponseOutputText(type="output_text", text=reply, annotations=[])
                item = ResponseOutputMessage(
                    type="message", role="assistant", id=uid(), status="completed", content=[text]
                )
                return ModelResponse(output=[item], usage=Usage(requests=1, total_tokens=10), response_id=uid())

            async def stream_response(self, *args, **kwargs):
                raise NotImplementedError
                yield

        self.model = Transport()


@pytest.mark.asyncio
async def test_research_notes_may_be_plain_text_in_prompt_mode(monkeypatch):
    from agents import Agent

    from factory.research import OutboundScreen, research

    provider = PlainText("Amounts are integers in cents.\nSee the orders page.")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr(settings(), "openai_structured_output", "prompt")
    monkeypatch.setattr("factory.research.Agent", lambda **kwargs: Agent(**{**kwargs, "model": provider.model}))
    result = await research("What unit does the Acme API use for amounts?", OutboundScreen())
    assert result["notes"] == "Amounts are integers in cents.\nSee the orders page."
    assert provider.seen["schema"] is None and "plain text" in provider.seen["instructions"]
    monkeypatch.setattr("factory.research.Agent", lambda **kwargs: Agent(**{**kwargs, "model": PlainText("  ").model}))
    with pytest.raises(ValueError):
        await research("What unit does the Acme API use for amounts?", OutboundScreen())


@pytest.mark.asyncio
async def test_a_proposal_strategy_is_stated_in_the_instructions(monkeypatch):
    from agents import Agent

    from factory.builder import optimize

    spec = AgentSpec(name="n", purpose="p", template="custom", instructions="base", tools=["t1"], connection_ids=["c1"])
    provider = PlainText('{"hypothesis": "h", "rules": {"margin": 0.3}}')
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": provider.model}))
    candidate, _ = await optimize(spec, [{"case": "x"}], strategy="Add a verifier for the total.")
    assert candidate.rules["margin"] == 0.3
    assert "For this proposal: Add a verifier for the total." in provider.seen["instructions"]
    await optimize(spec, [{"case": "x"}])
    assert "For this proposal" not in provider.seen["instructions"]
