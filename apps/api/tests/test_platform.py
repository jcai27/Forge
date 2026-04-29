from datetime import datetime, timedelta
from types import SimpleNamespace

from app.db.models import EventType
from app.services.platform import summarize_automated_score, summarize_provenance


def make_event(event_type: str, minutes: int, payload: dict | None = None):
    return SimpleNamespace(
        event_type=event_type,
        occurred_at=datetime(2026, 1, 1, 9, 0, 0) + timedelta(minutes=minutes),
        payload_json=payload or {},
    )


def test_provenance_flags_large_paste_and_iteration_gap():
    events = [
        make_event(EventType.ide_edit.value, 0),
        make_event(EventType.paste.value, 1, {"chars": 900}),
        make_event(EventType.terminal_command.value, 2, {"command": "pytest"}),
        make_event(EventType.checkpoint.value, 3, {"label": "checkpoint"}),
        make_event(EventType.terminal_command.value, 4, {"command": "git diff"}),
        make_event(EventType.ide_edit.value, 5),
        make_event(EventType.ide_edit.value, 6),
        make_event(EventType.ide_edit.value, 7),
        make_event(EventType.ide_edit.value, 8),
        make_event(EventType.ide_edit.value, 9),
    ]

    summary = summarize_provenance(events, events[0].occurred_at, events[-1].occurred_at)

    assert "large paste activity detected" in summary["integrity"]["flags"]
    assert "limited visible iteration before submission" in summary["integrity"]["flags"]
    assert summary["integrity"]["confidence_score"] < 100


def test_automated_score_prefers_latest_test_run():
    events = [
        make_event(EventType.test_run.value, 10, {"passed_tests": 2, "total_tests": 10, "build_success": False}),
        make_event(EventType.test_run.value, 20, {"passed_tests": 8, "total_tests": 10, "build_success": True, "lint_passed": True, "typecheck_passed": True, "security_passed": False}),
    ]

    score = summarize_automated_score(events)

    assert score["passed_tests"] == 8
    assert score["total_tests"] == 10
    assert score["build_success"] is True
    assert score["total_score"] > 60

