from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from livekit.agents import AgentSession, inference, llm

from agent import Assistant
from caller_memory import initialize_database, lookup_caller, save_caller_memory
from prompt import build_system_prompt


def _llm() -> llm.LLM:
    return inference.LLM(model="openai/gpt-4.1-mini")


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "arthsakhi.sqlite3"


def _fetch_row(db_path: Path, user_id: str):
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT * FROM caller_memory WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def test_database_initialization(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)

    initialize_database(db_path)

    assert db_path.exists()
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'caller_memory'"
        ).fetchone()

    assert row is not None


@pytest.mark.asyncio
async def test_new_caller_lookup_returns_none(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    initialize_database(db_path)

    result = await lookup_caller("caller_test_01", db_path=db_path)

    assert result is None


@pytest.mark.asyncio
async def test_save_caller_record_after_consent(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    initialize_database(db_path)

    result = await save_caller_memory(
        "caller_test_02",
        "Ramesh",
        "Hindi",
        {"schemes_discussed": ["PMJDY", "PMSBY"], "digital_safety_interest": True},
        db_path=db_path,
    )

    assert result == {"success": True, "message": "Caller memory saved safely."}


@pytest.mark.asyncio
async def test_returning_caller_lookup_returns_saved_data(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    initialize_database(db_path)

    await save_caller_memory(
        "caller_test_03",
        "Ramesh",
        "Hinglish",
        {"schemes_discussed": ["PMJDY"], "preferred_explanation_style": "simple"},
        db_path=db_path,
    )

    result = await lookup_caller("caller_test_03", db_path=db_path)

    assert result is not None
    assert result["found"] is True
    assert result["name"] == "Ramesh"
    assert result["language_preference"] == "Hinglish"
    assert result["facts"] == {
        "schemes_discussed": ["PMJDY"],
        "preferred_explanation_style": "simple",
    }


@pytest.mark.asyncio
async def test_name_and_language_are_stored_correctly(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    initialize_database(db_path)

    await save_caller_memory(
        "caller_test_04",
        "  Sita  ",
        "English",
        {"digital_safety_interest": False},
        db_path=db_path,
    )

    row = _fetch_row(db_path, "caller_test_04")

    assert row is not None
    assert row["name"] == "Sita"
    assert row["language_preference"] == "English"


@pytest.mark.asyncio
async def test_last_interaction_is_utc(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    initialize_database(db_path)

    await save_caller_memory(
        "caller_test_05",
        "Ramesh",
        "Hindi",
        {"digital_safety_interest": True},
        db_path=db_path,
    )

    row = _fetch_row(db_path, "caller_test_05")

    assert row is not None
    assert row["last_interaction"].endswith("Z")
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
        row["last_interaction"],
    )


@pytest.mark.asyncio
async def test_existing_facts_are_preserved_during_update(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    initialize_database(db_path)

    await save_caller_memory(
        "caller_test_06",
        "Ramesh",
        "Hindi",
        {"schemes_discussed": ["PMJDY", "PMSBY"], "digital_safety_interest": True},
        db_path=db_path,
    )
    await save_caller_memory(
        "caller_test_06",
        "Ramesh",
        "Hindi",
        {"preferred_explanation_style": "simple"},
        db_path=db_path,
    )

    result = await lookup_caller("caller_test_06", db_path=db_path)

    assert result is not None
    assert result["facts"] == {
        "schemes_discussed": ["PMJDY", "PMSBY"],
        "digital_safety_interest": True,
        "preferred_explanation_style": "simple",
    }


@pytest.mark.asyncio
async def test_no_consent_does_not_save(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    initialize_database(db_path)

    assistant = Assistant(user_id="caller_test_07", db_path=db_path)
    assistant.memory_consent_granted = False

    result = await assistant.save_caller_memory(
        None,
        "caller_test_07",
        "Ramesh",
        "Hindi",
        {"schemes_discussed": ["PMJDY"]},
    )

    assert result["success"] is False
    assert await lookup_caller("caller_test_07", db_path=db_path) is None


@pytest.mark.asyncio
async def test_ambiguous_consent_does_not_trigger_saving(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    initialize_database(db_path)

    assistant = Assistant(user_id="caller_test_08", db_path=db_path)
    assistant.memory_consent_granted = False

    result = await assistant.save_caller_memory(
        None,
        "caller_test_08",
        "Ramesh",
        "Hindi",
        {"schemes_discussed": ["PMJDY"]},
    )

    assert result["success"] is False
    assert await lookup_caller("caller_test_08", db_path=db_path) is None


@pytest.mark.parametrize("facts", [{"otp": "123456"}, {"pin": "1234"}, {"cvv": "111"}])
@pytest.mark.asyncio
async def test_sensitive_keys_are_rejected(tmp_path: Path, facts: dict[str, str]) -> None:
    db_path = _db_path(tmp_path)
    initialize_database(db_path)

    result = await save_caller_memory(
        "caller_test_09",
        "Ramesh",
        "Hindi",
        facts,
        db_path=db_path,
    )

    assert result["success"] is False
    assert await lookup_caller("caller_test_09", db_path=db_path) is None


@pytest.mark.parametrize(
    ("facts",),
    [
        ({"schemes_discussed": ["OTP"]},),
        ({"schemes_discussed": ["PIN"]},),
        ({"schemes_discussed": ["CVV"]},),
        ({"schemes_discussed": ["123456789012"]},),
        ({"schemes_discussed": ["Aadhaar"]},),
        ({"schemes_discussed": ["PAN"]},),
        ({"schemes_discussed": ["BANK-ACCOUNT"]},),
    ],
)
@pytest.mark.asyncio
async def test_sensitive_values_are_never_stored(tmp_path: Path, facts: dict[str, list[str]]) -> None:
    db_path = _db_path(tmp_path)
    initialize_database(db_path)

    result = await save_caller_memory(
        "caller_test_10",
        "Ramesh",
        "Hindi",
        facts,
        db_path=db_path,
    )

    assert result["success"] is False
    assert await lookup_caller("caller_test_10", db_path=db_path) is None


@pytest.mark.asyncio
async def test_database_errors_do_not_crash_lookup_or_save(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)

    with patch("caller_memory.sqlite3.connect", side_effect=sqlite3.OperationalError("locked")):
        lookup_result = await lookup_caller("caller_test_11", db_path=db_path)
        save_result = await save_caller_memory(
            "caller_test_11",
            "Ramesh",
            "Hindi",
            {"digital_safety_interest": True},
            db_path=db_path,
        )

    assert lookup_result is None
    assert save_result["success"] is False


@pytest.mark.asyncio
async def test_agent_does_not_claim_memory_saved_on_failure(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    initialize_database(db_path)

    assistant = Assistant(user_id="caller_test_12", db_path=db_path)
    assistant.memory_consent_granted = True

    with patch("agent.db_save_caller_memory", new=AsyncMock(return_value={"success": False, "message": "failed"})):
        result = await assistant.save_caller_memory(
            None,
            "caller_test_12",
            "Ramesh",
            "Hindi",
            {"digital_safety_interest": True},
        )

    assert result["success"] is False
    assert "saved" not in result["message"].lower()


def test_gitignore_excludes_sqlite_database() -> None:
    root = Path(__file__).resolve().parents[2]
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")

    assert "backend/data/*.sqlite3" in gitignore
    assert "backend/data/*.sqlite3-shm" in gitignore
    assert "backend/data/*.sqlite3-wal" in gitignore


def test_prompt_mentions_memory_lookup_and_consent() -> None:
    prompt = build_system_prompt(
        {
            "name": "Ramesh",
            "language_preference": "Hindi",
            "facts": {"schemes_discussed": ["PMJDY"]},
        }
    )

    assert "lookup_caller(user_id)" in prompt
    assert "save_caller_memory(user_id, name, language_preference, facts)" in prompt
    assert "Ramesh" in prompt
    assert "Hindi" in prompt


@pytest.mark.asyncio
async def test_returning_caller_is_greeted_by_name_in_correct_language() -> None:
    async with (
        _llm() as model,
        AgentSession(llm=model) as session,
    ):
        assistant = Assistant(
            user_id="caller_test_13",
            initial_memory={
                "name": "Ramesh",
                "language_preference": "Hindi",
                "facts": {"schemes_discussed": ["PMJDY"]},
            },
        )
        await session.start(assistant)

        result = await session.run(user_input="Hello")

        await (
            result.expect.next_event()
            .is_message(role="assistant")
            .judge(
                model,
                intent="Greet the returning caller by name in Hindi or Hinglish without exposing any internal ID.",
            )
        )

        result.expect.no_more_events()
