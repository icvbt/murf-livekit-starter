from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "arthsakhi.sqlite3"

BLOCKED_PATTERNS = [
    r"\botp\b",
    r"\bupi\s*pin\b",
    r"\bpin\b",
    r"\bpassword\b",
    r"\bcvv\b",
    r"\baadhaar\b",
    r"\baadhar\b",
    r"\bpan\b",
    r"\baccount\s*(number|no)\b",
    r"\bcard\s*(number|no)\b",
    r"\btransaction\s*(id|number|no)\b",
]

ALLOWED_ISSUES = {
    "suspected_fraud",
    "unauthorized_transaction",
    "account_specific_issue",
    "application_decision",
    "disputed_charge",
    "professional_financial_advice",
}

ALLOWED_URGENCY = {"urgent", "high", "normal"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def contains_sensitive_data(text: str) -> bool:
    text = text.lower()
    return any(re.search(pattern, text) for pattern in BLOCKED_PATTERNS)


def init_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS escalation_requests (
                request_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                checked_information TEXT NOT NULL,
                urgency TEXT NOT NULL,
                language_preference TEXT,
                preferred_follow_up_method TEXT,
                consent_given INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def create_escalation(
    user_id: str,
    issue_type: str,
    summary: str,
    checked_information: list[str],
    urgency: str,
    language_preference: str,
    preferred_follow_up_method: str,
    consent_given: bool,
) -> dict:
    init_database()

    if not consent_given:
        return {
            "success": False,
            "error": "consent_required",
        }

    if issue_type not in ALLOWED_ISSUES:
        return {
            "success": False,
            "error": "invalid_issue_type",
        }

    if urgency not in ALLOWED_URGENCY:
        return {
            "success": False,
            "error": "invalid_urgency",
        }

    safe_summary = summary[:500]
    safe_checked = [str(item)[:200] for item in checked_information[:5]]

    if contains_sensitive_data(safe_summary):
        return {
            "success": False,
            "error": "sensitive_information_rejected",
        }

    if any(contains_sensitive_data(item) for item in safe_checked):
        return {
            "success": False,
            "error": "sensitive_information_rejected",
        }

    request_id = f"ASH-{datetime.now().year}-{secrets.token_hex(4).upper()}"
    now = utc_now()

    with sqlite3.connect(DB_PATH) as connection:
        existing = connection.execute(
            """
            SELECT request_id
            FROM escalation_requests
            WHERE user_id = ?
              AND issue_type = ?
              AND status = 'open'
            LIMIT 1
            """,
            (user_id, issue_type),
        ).fetchone()

        if existing:
            return {
                "success": True,
                "duplicate": True,
                "request_id": existing[0],
                "status": "open",
            }

        connection.execute(
            """
            INSERT INTO escalation_requests (
                request_id,
                user_id,
                issue_type,
                summary,
                checked_information,
                urgency,
                language_preference,
                preferred_follow_up_method,
                consent_given,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                user_id,
                issue_type,
                safe_summary,
                json.dumps(safe_checked, ensure_ascii=False),
                urgency,
                language_preference[:50],
                preferred_follow_up_method[:50],
                1,
                "open",
                now,
                now,
            ),
        )
        connection.commit()

    return {
        "success": True,
        "duplicate": False,
        "request_id": request_id,
        "status": "open",
    }


def list_open_escalations() -> list[dict]:
    init_database()

    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT request_id, issue_type, summary, checked_information,
                   urgency, language_preference, preferred_follow_up_method,
                   status, created_at
            FROM escalation_requests
            WHERE status = 'open'
            ORDER BY created_at DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]