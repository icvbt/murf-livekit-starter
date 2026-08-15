from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "arthsakhi.sqlite3"

ALLOWED_LANGUAGE_PREFERENCES = {"Hindi", "English", "Hinglish"}
ALLOWED_FACT_KEYS = {
    "schemes_discussed",
    "preferred_explanation_style",
    "digital_safety_interest",
}
ALLOWED_SCHEMES = {"PMJDY", "PMSBY", "PMJJBY", "APY", "SSY"}
ALLOWED_EXPLANATION_STYLES = {"simple", "detailed"}
SAFE_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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
            CREATE TABLE IF NOT EXISTS caller_memory (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                language_preference TEXT,
                facts TEXT NOT NULL DEFAULT '{}',
                last_interaction TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
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


def validate_user_id(user_id: str) -> str:
    candidate = user_id.strip() if isinstance(user_id, str) else ""
    if not candidate or not SAFE_USER_ID_PATTERN.fullmatch(candidate):
        raise ValueError("Invalid safe user id")
    return candidate


def validate_name(name: str) -> str:
    candidate = name.strip() if isinstance(name, str) else ""
    if not candidate or len(candidate) > 80:
        raise ValueError("Invalid caller name")
    if any(character in candidate for character in ("\n", "\r", "\t")):
        raise ValueError("Invalid caller name")
    return candidate


def validate_language_preference(language_preference: str) -> str:
    candidate = language_preference.strip() if isinstance(language_preference, str) else ""
    if candidate not in ALLOWED_LANGUAGE_PREFERENCES:
        raise ValueError("Invalid language preference")
    return candidate


def _normalize_scheme(value: str) -> str:
    scheme = value.strip().upper()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError("Invalid scheme value")
    return scheme


def validate_facts(facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(facts, dict):
        raise ValueError("Facts must be a dictionary")

    unknown_keys = set(facts) - ALLOWED_FACT_KEYS
    if unknown_keys:
        raise ValueError("Unapproved fact key")

    validated: dict[str, Any] = {}

    if "schemes_discussed" in facts:
        schemes_value = facts["schemes_discussed"]
        if schemes_value in (None, [], ""):
            validated["schemes_discussed"] = []
        elif isinstance(schemes_value, list):
            schemes: list[str] = []
            for scheme in schemes_value:
                if not isinstance(scheme, str):
                    raise ValueError("Invalid scheme value")
                normalized_scheme = _normalize_scheme(scheme)
                if normalized_scheme not in schemes:
                    schemes.append(normalized_scheme)
            validated["schemes_discussed"] = schemes
        else:
            raise ValueError("Invalid schemes_discussed value")

    if "preferred_explanation_style" in facts:
        style_value = facts["preferred_explanation_style"]
        if style_value in (None, ""):
            validated["preferred_explanation_style"] = None
        elif isinstance(style_value, str):
            style = style_value.strip().lower()
            if style not in ALLOWED_EXPLANATION_STYLES:
                raise ValueError("Invalid explanation style")
            validated["preferred_explanation_style"] = style
        else:
            raise ValueError("Invalid explanation style")

    if "digital_safety_interest" in facts:
        interest_value = facts["digital_safety_interest"]
        if isinstance(interest_value, bool):
            validated["digital_safety_interest"] = interest_value
        elif interest_value in (0, 1):
            validated["digital_safety_interest"] = bool(interest_value)
        elif interest_value in (None, ""):
            validated["digital_safety_interest"] = None
        else:
            raise ValueError("Invalid digital safety interest value")

    return validated


def _load_facts(raw_facts: str | None) -> dict[str, Any]:
    if not raw_facts:
        return {}
    try:
        parsed = json.loads(raw_facts)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _merge_facts(existing: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in updates.items():
        if value in (None, [], ""):
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _lookup_sync(user_id: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    validated_user_id = validate_user_id(user_id)
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT user_id, name, language_preference, facts, last_interaction
            FROM caller_memory
            WHERE user_id = ?
            """,
            (validated_user_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "found": True,
        "user_id": row["user_id"],
        "name": row["name"],
        "language_preference": row["language_preference"],
        "facts": _load_facts(row["facts"]),
        "last_interaction": row["last_interaction"],
    }


def _save_sync(
    user_id: str,
    name: str,
    language_preference: str,
    facts: dict[str, Any],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        validated_user_id = validate_user_id(user_id)
        validated_name = validate_name(name)
        validated_language_preference = validate_language_preference(language_preference)
        validated_facts = validate_facts(facts)
        timestamp = _utc_now()

        with _connect(db_path) as connection:
            existing_row = connection.execute(
                "SELECT facts FROM caller_memory WHERE user_id = ?",
                (validated_user_id,),
            ).fetchone()
            existing_facts = _load_facts(existing_row["facts"]) if existing_row else {}
            merged_facts = _merge_facts(existing_facts, validated_facts)

            if existing_row is None:
                connection.execute(
                    """
                    INSERT INTO caller_memory (
                        user_id,
                        name,
                        language_preference,
                        facts,
                        last_interaction,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        validated_user_id,
                        validated_name,
                        validated_language_preference,
                        json.dumps(merged_facts, ensure_ascii=False, sort_keys=True),
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE caller_memory
                    SET name = ?,
                        language_preference = ?,
                        facts = ?,
                        last_interaction = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        validated_name,
                        validated_language_preference,
                        json.dumps(merged_facts, ensure_ascii=False, sort_keys=True),
                        timestamp,
                        timestamp,
                        validated_user_id,
                    ),
                )

            connection.commit()

        return {"success": True, "message": "Caller memory saved safely."}
    except (sqlite3.Error, ValueError):
        return {
            "success": False,
            "message": "Main is samay aapki information save nahi kar pa rahi hoon, lekin hum conversation continue kar sakte hain.",
        }


async def lookup_caller(user_id: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    try:
        return await asyncio.to_thread(_lookup_sync, user_id, db_path)
    except (ValueError, sqlite3.Error):
        return None


async def save_caller_memory(
    user_id: str,
    name: str,
    language_preference: str,
    facts: dict[str, Any],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(_save_sync, user_id, name, language_preference, facts, db_path)
