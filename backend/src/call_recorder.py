from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "arthsakhi.sqlite3"
DATABASE_PATH = Path(os.getenv("CALL_DB_PATH", str(DEFAULT_DATABASE_PATH)))

VALID_OUTCOMES = {"started", "success", "failed"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _normalize_database_path(db_path: str | Path | None = None) -> Path:
    path = Path(db_path) if db_path is not None else DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def initialize_database(db_path: str | Path | None = None) -> Path:
    path = _normalize_database_path(db_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS call_outcomes (
                call_id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                outcome TEXT NOT NULL,
                success_reason TEXT,
                failure_reason TEXT,
                language_preference TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
    return path


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = initialize_database(db_path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _normalize_call_id(call_id: str) -> str:
    candidate = call_id.strip() if isinstance(call_id, str) else ""
    return candidate[:128]


def _normalize_channel(channel: str) -> str:
    candidate = channel.strip().lower() if isinstance(channel, str) else ""
    return candidate if candidate in {"browser", "sip"} else "unknown"


def _normalize_text(value: Any, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    return candidate[:max_length]


def _record_started_sync(
    call_id: str,
    channel: str,
    *,
    language_preference: str | None = None,
    started_at: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    safe_call_id = _normalize_call_id(call_id)
    if not safe_call_id:
        return {"success": False, "message": "Call id is required to record a call start."}

    timestamp = started_at or _utc_now()
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO call_outcomes (
                call_id,
                channel,
                started_at,
                ended_at,
                outcome,
                success_reason,
                failure_reason,
                language_preference,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                safe_call_id,
                _normalize_channel(channel),
                timestamp,
                None,
                "started",
                None,
                None,
                _normalize_text(language_preference, max_length=50),
                timestamp,
            ),
        )
        connection.commit()

    return {"success": True, "message": "Call start recorded."}


def _record_finished_sync(
    call_id: str,
    *,
    outcome: str,
    success_reason: str | None = None,
    failure_reason: str | None = None,
    ended_at: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    if outcome not in {"success", "failed"}:
        return {"success": False, "message": "Outcome must be 'success' or 'failed'."}

    safe_call_id = _normalize_call_id(call_id)
    if not safe_call_id:
        return {"success": False, "message": "Call id is required to record a call end."}

    timestamp = ended_at or _utc_now()
    with _connect(db_path) as connection:
        existing_row = connection.execute(
            "SELECT call_id FROM call_outcomes WHERE call_id = ?",
            (safe_call_id,),
        ).fetchone()

        if existing_row is None:
            connection.execute(
                """
                INSERT INTO call_outcomes (
                    call_id,
                    channel,
                    started_at,
                    ended_at,
                    outcome,
                    success_reason,
                    failure_reason,
                    language_preference,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    safe_call_id,
                    "unknown",
                    timestamp,
                    timestamp,
                    outcome,
                    _normalize_text(success_reason, max_length=500),
                    _normalize_text(failure_reason, max_length=500),
                    None,
                    timestamp,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE call_outcomes
                SET ended_at = ?, outcome = ?, success_reason = ?, failure_reason = ?
                WHERE call_id = ?
                """,
                (
                    timestamp,
                    outcome,
                    _normalize_text(success_reason, max_length=500),
                    _normalize_text(failure_reason, max_length=500),
                    safe_call_id,
                ),
            )
        connection.commit()

    return {"success": True, "message": "Call outcome recorded."}


async def record_call_started(
    call_id: str,
    channel: str,
    *,
    language_preference: str | None = None,
    started_at: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _record_started_sync,
            call_id,
            channel,
            language_preference=language_preference,
            started_at=started_at,
            db_path=db_path,
        )
    except (sqlite3.Error, ValueError):
        return {"success": False, "message": "Failed to record the call start."}


async def record_call_finished(
    call_id: str,
    *,
    outcome: str,
    success_reason: str | None = None,
    failure_reason: str | None = None,
    ended_at: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _record_finished_sync,
            call_id,
            outcome=outcome,
            success_reason=success_reason,
            failure_reason=failure_reason,
            ended_at=ended_at,
            db_path=db_path,
        )
    except (sqlite3.Error, ValueError):
        return {"success": False, "message": "Failed to record the call outcome."}
