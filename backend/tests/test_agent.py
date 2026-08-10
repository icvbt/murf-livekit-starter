from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from livekit.agents import AgentSession, inference, llm

from agent import Assistant
from caller_memory import initialize_database, lookup_caller, save_caller_memory
from scheme_eligibility import check_scheme_eligibility
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


def test_valid_scheme_lookup_returns_structured_result() -> None:
    result = check_scheme_eligibility(
        "PMJDY",
        {
            "age": 24,
            "state_or_union_territory": "Karnataka",
        },
    )

    assert result["success"] is True
    assert result["scheme_id"] == "pmjdy"
    assert result["scheme_name"] == "Pradhan Mantri Jan Dhan Yojana"
    assert result["result"] == "appears_possible"
    assert result["source_name"] == "myScheme"
    assert result["source_url"] == "https://www.myscheme.gov.in/"
    assert result["data_status"] == "local_curated_dataset"
    assert result["retrieved_at"] == "2026-08-10"
    assert result["last_verified"] == "2026-08-10"
    assert result["document_checklist"]


def test_appears_possible_result_for_apy() -> None:
    result = check_scheme_eligibility("APY", {"age": 30})

    assert result["success"] is True
    assert result["result"] == "appears_possible"
    assert result["scheme_name"] == "Atal Pension Yojana"
    assert result["matched_rules"]
    assert "official approval" in result["disclaimer"].lower()


def test_appears_unlikely_result_for_pmsby() -> None:
    result = check_scheme_eligibility("PMSBY", {"age": 75})

    assert result["success"] is True
    assert result["result"] == "appears_unlikely"
    assert result["unmatched_rules"]


def test_missing_answers_returns_followup_needed() -> None:
    result = check_scheme_eligibility("PMJDY", {"age": 21})

    assert result["success"] is True
    assert result["result"] == "needs_more_information"
    assert "state_or_union_territory" in result["missing_answers"]


def test_unknown_scheme_returns_scheme_not_found() -> None:
    result = check_scheme_eligibility("unknown-scheme", {"age": 21})

    assert result["success"] is False
    assert result["result"] == "scheme_not_found"


@pytest.mark.parametrize(
    "answers",
    [
        "not-a-dict",
        {"age": "abc"},
        {"age_group": "very_young"},
    ],
)
def test_invalid_input_returns_validation_error(answers) -> None:
    result = check_scheme_eligibility("PMJDY", answers)

    assert result["success"] is False
    assert result["result"] == "validation_error"


@pytest.mark.parametrize(
    "answers",
    [
        {"aadhaar_number": "123456789012"},
        {"pan": "ABCDE1234F"},
        {"account_number": "123456789012345"},
        {"otp": "123456"},
        {"pin": "1234"},
        {"password": "secret"},
        {"cvv": "123"},
    ],
)
def test_sensitive_field_rejection(answers) -> None:
    result = check_scheme_eligibility("PMJDY", answers)

    assert result["success"] is False
    assert result["result"] == "validation_error"


def test_source_and_data_date_in_response() -> None:
    result = check_scheme_eligibility("SSY", {"age": 4, "is_girl_child_scheme": True})

    assert result["source_name"] == "myScheme"
    assert result["source_url"] == "https://www.myscheme.gov.in/"
    assert result["retrieved_at"] == "2026-08-10"
    assert result["last_verified"] == "2026-08-10"
    assert result["effective_from"] is None


def test_local_dataset_fallback_returns_source_unavailable() -> None:
    with patch("scheme_eligibility._load_dataset", side_effect=OSError("broken")):
        result = check_scheme_eligibility("PMJDY", {"age": 21, "state_or_union_territory": "Karnataka"})

    assert result["success"] is False
    assert result["result"] == "source_unavailable"


@pytest.mark.asyncio
async def test_agent_calls_tool_for_eligibility_question() -> None:
    async with (
        _llm() as model,
        AgentSession(llm=model) as session,
    ):
        assistant = Assistant(user_id="caller_test_14")
        await session.start(assistant)

        with patch(
            "agent.check_scheme_eligibility",
            return_value={
                "success": True,
                "scheme_id": "pmjdy",
                "scheme_name": "Pradhan Mantri Jan Dhan Yojana",
                "result": "appears_possible",
                "matched_rules": ["General guidance matches the available rules."],
                "missing_answers": [],
                "unmatched_rules": [],
                "document_checklist": ["Verify currently accepted documents with the participating bank."],
                "next_steps": ["Confirm current eligibility through the official source or participating bank."],
                "source_name": "myScheme",
                "source_url": "https://www.myscheme.gov.in/",
                "data_status": "local_curated_dataset",
                "retrieved_at": "2026-08-10",
                "last_verified": "2026-08-10",
                "effective_from": None,
                "disclaimer": "This is general guidance, not official approval.",
                "spoken_response": "आपके द्वारा दी गई सामान्य जानकारी के आधार पर, यह स्कीम आपके लिए संभव हो सकती है। यह official approval नहीं है। कृपया final eligibility official government portal या participating bank से verify करें।",
            },
        ) as mock_tool:
            result = await session.run(user_input="Am I eligible for PMJDY? I am 24 and live in Karnataka.")

            result.expect.next_event().is_function_call(name="check_scheme_eligibility")
            result.expect.next_event().is_function_call_output()

            await (
                result.expect.next_event()
                .is_message(role="assistant")
                .judge(
                    model,
                    intent=(
                        "Respond naturally in Hindi or Hinglish, mention that this is not official approval,"
                        " and do not read raw JSON aloud."
                    ),
                )
            )

            assert mock_tool.called


@pytest.mark.asyncio
async def test_agent_does_not_call_tool_for_account_question() -> None:
    async with (
        _llm() as model,
        AgentSession(llm=model) as session,
    ):
        assistant = Assistant(user_id="caller_test_15")
        await session.start(assistant)

        with patch("agent.check_scheme_eligibility", wraps=check_scheme_eligibility) as mock_tool:
            result = await session.run(user_input="What is my bank balance?")

            await (
                result.expect.next_event()
                .is_message(role="assistant")
                .judge(
                    model,
                    intent=(
                        "Refuse safely, avoid account access claims, and direct the user to an official bank channel."
                    ),
                )
            )

            assert not mock_tool.called
