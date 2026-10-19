"""Public contract tests for the read-only pipeline HITL query."""

from __future__ import annotations

import copy
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from raise_cli.mcp.workspace_config import CODEX_ENABLED_TOOLS
from raise_cli.pipeline import _caller_context
from raise_cli.pipeline._mcp_instance import mcp
from raise_cli.pipeline.mcp_tools_pipeline import pipeline_gate_status


def _run(
    *,
    phase_id: str = "review",
    gate_type: str | None = "hitl",
    awaiting_gate: dict[str, str] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if awaiting_gate is not None:
        metadata["awaiting_gate"] = awaiting_gate
    return {
        "run_id": "run-1",
        "pipeline_name": "story-pulso",
        "issue_id": "PUL-01-S1.1",
        "current_phase_index": 0,
        "phases": [
            {
                "id": phase_id,
                "status": "running",
                "gate_type": gate_type,
            }
        ],
        "metadata": metadata,
    }


async def _query(run: dict[str, Any] | None) -> tuple[dict[str, Any], AsyncMock]:
    store = AsyncMock()
    store.load.return_value = run
    with patch(
        "raise_cli.pipeline.mcp_tools_pipeline.get_run_store", return_value=store
    ):
        payload = json.loads(await pipeline_gate_status("run-1"))
    return payload, store


@pytest.mark.asyncio
async def test_pipeline_gate_status_reports_current_pending_hitl_gate() -> None:
    """A matching persisted HITL stamp is returned as pending."""
    stamp = {
        "phase": "review",
        "entered_at": "2026-10-18T15:00:00+00:00",
        "last_checked_at": "2026-10-18T15:01:00+00:00",
    }
    run = _run(awaiting_gate=stamp)
    before = copy.deepcopy(run)

    payload, store = await _query(run)

    assert payload == {
        "run_id": "run-1",
        "pipeline": "story-pulso",
        "issue": "PUL-01-S1.1",
        "current_phase": "review",
        "status": "gate_pending",
        "gate": {
            "type": "hitl",
            "phase": "review",
            "status": "pending",
            "entered_at": "2026-10-18T15:00:00+00:00",
            "last_checked_at": "2026-10-18T15:01:00+00:00",
        },
    }
    assert run == before
    store.save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gate_type", "stamp"),
    [
        ("hitl", None),
        (
            "hitl",
            {
                "phase": "implement",
                "entered_at": "2026-10-18T15:00:00+00:00",
                "last_checked_at": "2026-10-18T15:01:00+00:00",
            },
        ),
        (
            "auto",
            {
                "phase": "review",
                "entered_at": "2026-10-18T15:00:00+00:00",
                "last_checked_at": "2026-10-18T15:01:00+00:00",
            },
        ),
    ],
)
async def test_pipeline_gate_status_is_clear_without_a_current_hitl_stamp(
    gate_type: str, stamp: dict[str, str] | None
) -> None:
    """Missing, stale, and non-HITL stamps never block a consumer."""
    payload, store = await _query(_run(gate_type=gate_type, awaiting_gate=stamp))

    assert payload["status"] == "clear"
    assert payload["current_phase"] == "review"
    assert payload["gate"] is None
    store.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_gate_status_reports_a_missing_run() -> None:
    """Unknown run IDs use the existing structured error convention."""
    payload, store = await _query(None)

    assert payload == {"status": "error", "reason": "Run run-1 not found"}
    store.save.assert_not_awaited()


def test_pipeline_gate_status_is_public_and_run_addressed() -> None:
    """Generated Codex config exposes the tool without requiring caller CWD."""
    assert "pipeline_gate_status" in CODEX_ENABLED_TOOLS
    assert "pipeline_gate_status" in _caller_context.EXEMPT_TOOLS
    assert "pipeline_gate_status" not in _caller_context.CHECKOUT_SCOPED_TOOLS


@pytest.mark.asyncio
async def test_pipeline_gate_status_is_registered_in_tools_list() -> None:
    """The public MCP server advertises the query through ``tools/list``."""
    registered = {tool.name for tool in await mcp.list_tools()}

    assert "pipeline_gate_status" in registered
