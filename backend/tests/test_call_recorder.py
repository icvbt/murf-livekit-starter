from __future__ import annotations

import sqlite3
from pathlib import Path

from call_recorder import (
    initialize_database,
    record_call_finished,
    record_call_started,
)


def _metrics(db_path: Path) -> tuple[int, int]:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT
                SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END),
                SUM(CASE WHEN outcome = 'failed' THEN 1 ELSE 0 END)
            FROM call_outcomes
            """
        ).fetchone()
    return (row[0] or 0, row[1] or 0)


async def test_record_lifecycle_success(tmp_path: Path) -> None:
    db_path = tmp_path / "outcomes.sqlite3"
    initialize_database(db_path)

    started = await record_call_started(
        call_id="room_abc",
        channel="sip",
        language_preference="Hindi",
        db_path=db_path,
    )
    assert started["success"] is True

    finished = await record_call_finished(
        "room_abc",
        outcome="success",
        success_reason="Agent produced a spoken response and the call ended without error.",
        db_path=db_path,
    )
    assert finished["success"] is True

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT call_id, channel, outcome, success_reason, ended_at, started_at "
            "FROM call_outcomes WHERE call_id = ?",
            ("room_abc",),
        ).fetchone()

    assert row is not None
    assert row[0] == "room_abc"
    assert row[1] == "sip"
    assert row[2] == "success"
    assert row[3] == "Agent produced a spoken response and the call ended without error."
    assert row[4] is not None
    assert row[5] is not None
    assert row[5] <= row[4]

    assert _metrics(db_path) == (1, 0)


async def test_record_failed_path(tmp_path: Path) -> None:
    db_path = tmp_path / "outcomes.sqlite3"
    initialize_database(db_path)

    await record_call_started(call_id="room_xyz", channel="browser", db_path=db_path)
    await record_call_finished(
        "room_xyz",
        outcome="failed",
        failure_reason="close_reason=JOB_SHUTDOWN; no spoken response was produced",
        db_path=db_path,
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT channel, outcome, failure_reason FROM call_outcomes WHERE call_id = ?",
            ("room_xyz",),
        ).fetchone()

    assert row is not None
    assert row[0] == "browser"
    assert row[1] == "failed"
    assert row[2] == "close_reason=JOB_SHUTDOWN; no spoken response was produced"

    assert _metrics(db_path) == (0, 1)


async def test_finished_without_start_inserts_full_row(tmp_path: Path) -> None:
    db_path = tmp_path / "outcomes.sqlite3"
    initialize_database(db_path)

    await record_call_finished(
        "room_unanswered",
        outcome="failed",
        failure_reason="call not answered",
        db_path=db_path,
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT call_id, channel, started_at, ended_at, outcome "
            "FROM call_outcomes WHERE call_id = ?",
            ("room_unanswered",),
        ).fetchone()

    assert row is not None
    assert row[0] == "room_unanswered"
    assert row[1] == "unknown"
    assert row[2] == row[3]
    assert row[4] == "failed"

    assert _metrics(db_path) == (0, 1)


async def test_rejects_invalid_outcome(tmp_path: Path) -> None:
    db_path = tmp_path / "outcomes.sqlite3"
    initialize_database(db_path)

    await record_call_started(call_id="room_invalid", channel="sip", db_path=db_path)
    result = await record_call_finished(
        "room_invalid",
        outcome="in_progress",
        db_path=db_path,
    )

    assert result["success"] is False
    assert _metrics(db_path) == (0, 0)
