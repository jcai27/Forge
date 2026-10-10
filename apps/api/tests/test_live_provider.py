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
