from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from livekit.agents import AgentSession, inference, llm

from agent import Assistant
from prompt import build_system_prompt
from scheme_specialist import (
    HANDOFF_ANNOUNCEMENT_EN,
    HANDOFF_ANNOUNCEMENT_HI,
    SchemeSpecialist,
    build_safe_handoff_context,
    build_specialist_prompt,
    handoff_announcement,
)


def _llm() -> llm.LLM:
    return inference.LLM(model="openai/gpt-4.1-mini")


def _main_agent_tool_names() -> list[str]:
    return [tool.info.name for tool in Assistant(user_id="handoff_register_1")._tools]


def _handoff_tool_description() -> str:
    for tool in Assistant(user_id="handoff_register_1")._tools:
        if tool.info.name == "transfer_to_scheme_specialist":
            return tool.info.description or ""
    raise AssertionError("transfer_to_scheme_specialist tool not found")


class _FakeSession:
    def __init__(self) -> None:
        self.announced: list[str] = []
        self.updated_with = None

    async def say(self, text: str, **kwargs) -> None:
        self.announced.append(text)

    def update_agent(self, agent) -> None:
        self.updated_with = agent


class _FakeContext:
    def __init__(self) -> None:
        self.session = _FakeSession()


def test_handoff_tool_is_registered_on_main_agent() -> None:
    assert "transfer_to_scheme_specialist" in _main_agent_tool_names()


def test_handoff_tool_has_clear_description() -> None:
    description = _handoff_tool_description()
    assert "Government Scheme Eligibility Specialist" in description
    assert "scheme-specific" in description


def test_specialist_is_a_separate_agent_with_own_instructions() -> None:
    main_prompt = build_system_prompt(None)
    specialist_prompt = build_specialist_prompt(
        user_question="Am I eligible for PMJDY?",
        conversation_summary="Caller wants PMJDY guidance.",
        language_preference="Hinglish",
        scheme_name="PMJDY",
    )

    assert specialist_prompt != main_prompt
    assert "Government Scheme Eligibility Specialist" in specialist_prompt
    assert "ArthSakhi" in specialist_prompt
    assert "Am I eligible for PMJDY?" in specialist_prompt


def test_specialist_role_is_narrower_than_main_agent() -> None:
    specialist_prompt = build_specialist_prompt(
        user_question="Am I eligible for PMJDY?",
        conversation_summary="Caller wants PMJDY guidance.",
        language_preference="English",
        scheme_name="PMJDY",
    )

    assert "Your only job" in specialist_prompt
    assert "YOU MUST NOT" in specialist_prompt
    assert "Eligibility" in specialist_prompt
    assert "documents" in specialist_prompt


def test_specialist_does_not_request_sensitive_information() -> None:
    specialist_prompt = build_specialist_prompt(
        user_question="Am I eligible for PMJDY?",
        conversation_summary="Caller wants PMJDY guidance.",
        language_preference="English",
        scheme_name="PMJDY",
    )

    assert "Ask only non-sensitive questions" in specialist_prompt
    assert "OTPs, PINs, passwords, CVVs, card numbers, or bank account numbers" in specialist_prompt
    assert "Aadhaar, PAN, or other government ID numbers" in specialist_prompt


def test_specialist_has_only_the_eligibility_tool() -> None:
    specialist = SchemeSpecialist(
        user_question="Am I eligible for PMJDY?",
        conversation_summary="Caller wants PMJDY guidance.",
        language_preference="English",
        scheme_name="PMJDY",
    )

    assert [tool.info.name for tool in specialist._tools] == ["check_scheme_eligibility"]
    assert specialist.id == "scheme_specialist"


def test_handoff_context_preserves_question_summary_language_and_scheme() -> None:
    context = build_safe_handoff_context(
        user_question="Am I eligible for PMJDY, and what documents do I need?",
        conversation_summary="Caller wants PMJDY eligibility and documents guidance.",
        language_preference="Hinglish",
        scheme_name="PMJDY",
        known_non_sensitive_answers={
            "age": 30,
            "state_or_union_territory": "Karnataka",
        },
    )

    assert context["user_question"] == "Am I eligible for PMJDY, and what documents do I need?"
    assert "PMJDY" in context["conversation_summary"]
    assert context["language_preference"] == "Hinglish"
    assert context["scheme_name"] == "PMJDY"
    assert context["known_non_sensitive_answers"] == {
        "age": 30,
        "state_or_union_territory": "Karnataka",
    }


def test_sensitive_data_is_excluded_from_handoff_context() -> None:
    context = build_safe_handoff_context(
        user_question="What documents do I need for PMJDY?",
        conversation_summary="The caller shared an OTP 123456 and a PAN ABCDE1234F.",
        language_preference="English",
        known_non_sensitive_answers={
            "age": 30,
            "otp": "123456",
            "pin": "1234",
            "account_number": "123456789012345",
            "pan_number": "ABCDE1234F",
            "state_or_union_territory": "Uttar Pradesh",
        },
    )

    assert context["known_non_sensitive_answers"] == {
        "age": 30,
        "state_or_union_territory": "Uttar Pradesh",
    }
    assert "123456" not in json.dumps(context)
    assert "ABCDE1234F" not in json.dumps(context)
    assert "1234" not in json.dumps(context)


def test_handoff_context_requires_a_user_question() -> None:
    with pytest.raises(ValueError):
        build_safe_handoff_context(
            user_question="   ",
            conversation_summary="Caller wants PMJDY guidance.",
            language_preference="English",
        )


def test_handoff_announcement_uses_the_required_message() -> None:
    assert handoff_announcement("English") == HANDOFF_ANNOUNCEMENT_EN
    assert "I'll connect you to our government-scheme eligibility specialist" in (
        HANDOFF_ANNOUNCEMENT_EN
    )
    assert handoff_announcement("Hindi") == HANDOFF_ANNOUNCEMENT_HI
    assert handoff_announcement("Hinglish") == HANDOFF_ANNOUNCEMENT_HI
    assert handoff_announcement("unknown") == HANDOFF_ANNOUNCEMENT_EN


@pytest.mark.asyncio
async def test_handoff_tool_switches_agent_and_announces() -> None:
    assistant = Assistant(user_id="handoff_direct_1")
    context = _FakeContext()

    result = await assistant.transfer_to_scheme_specialist(
        context,
        user_question="Am I eligible for PMJDY?",
        conversation_summary="Caller wants PMJDY guidance.",
        language_preference="English",
        scheme_name="PMJDY",
    )

    assert result["success"] is True
    assert context.session.announced == [HANDOFF_ANNOUNCEMENT_EN]
    assert isinstance(context.session.updated_with, SchemeSpecialist)
    assert "PMJDY" in context.session.updated_with.instructions


@pytest.mark.asyncio
async def test_handoff_tool_uses_language_matched_announcement() -> None:
    assistant = Assistant(user_id="handoff_direct_2")
    context = _FakeContext()

    result = await assistant.transfer_to_scheme_specialist(
        context,
        user_question="Kya main PMJDY ke liye eligible hoon?",
        conversation_summary="Caller wants PMJDY guidance.",
        language_preference="Hindi",
        scheme_name="PMJDY",
    )

    assert result["success"] is True
    assert context.session.announced == [HANDOFF_ANNOUNCEMENT_HI]


@pytest.mark.asyncio
async def test_handoff_tool_does_not_create_duplicate_records() -> None:
    assistant = Assistant(user_id="handoff_records_1")
    context = _FakeContext()

    with (
        patch("agent.db_save_caller_memory", new=AsyncMock()) as save_mock,
        patch("agent.db_create_escalation", new=AsyncMock()) as escalation_mock,
    ):
        result = await assistant.transfer_to_scheme_specialist(
            context,
            user_question="Am I eligible for PMSBY?",
            conversation_summary="Caller wants PMSBY guidance.",
            language_preference="Hindi",
            scheme_name="PMSBY",
        )

    assert result["success"] is True
    save_mock.assert_not_called()
    escalation_mock.assert_not_called()
    assert isinstance(context.session.updated_with, SchemeSpecialist)


@pytest.mark.asyncio
async def test_handoff_tool_returns_failure_without_a_question() -> None:
    assistant = Assistant(user_id="handoff_direct_3")
    context = _FakeContext()

    result = await assistant.transfer_to_scheme_specialist(
        context,
        user_question="",
        conversation_summary="",
        language_preference="English",
    )

    assert result["success"] is False
    assert context.session.updated_with is None


@pytest.mark.asyncio
async def test_general_question_stays_with_main_agent() -> None:
    async with (
        _llm() as model,
        AgentSession(llm=model) as session,
    ):
        assistant = Assistant(user_id="handoff_eval_general_1")
        await session.start(assistant)

        result = await session.run(user_input="What does financial literacy mean?")

        calls = [ev.item.name for ev in result.events if ev.type == "function_call"]
        assert "transfer_to_scheme_specialist" not in calls

        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                model,
                intent=(
                    "Explain what financial literacy means directly, in simple language, "
                    "without handing off to another agent."
                ),
            )
        )


@pytest.mark.asyncio
async def test_scheme_question_triggers_specialist_handoff() -> None:
    async with (
        _llm() as model,
        AgentSession(llm=model) as session,
    ):
        assistant = Assistant(user_id="handoff_eval_scheme_1")
        await session.start(assistant)

        result = await session.run(
            user_input="Am I eligible for PMJDY, and what documents do I need?"
        )

        result.expect.contains_function_call(name="transfer_to_scheme_specialist")
        result.expect.contains_agent_handoff(new_agent_type=SchemeSpecialist)

        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                model,
                intent=(
                    "As the government scheme eligibility specialist, introduce yourself "
                    "and address the caller's PMJDY eligibility and required-documents "
                    "question without asking the caller to repeat the whole problem."
                ),
            )
        )


@pytest.mark.asyncio
async def test_fraud_question_uses_existing_escalation_flow() -> None:
    async with (
        _llm() as model,
        AgentSession(llm=model) as session,
    ):
        assistant = Assistant(user_id="handoff_eval_fraud_1")
        await session.start(assistant)

        result = await session.run(
            user_input="I received a suspicious message asking for my OTP. What should I do?"
        )

        calls = [ev.item.name for ev in result.events if ev.type == "function_call"]
        assert "transfer_to_scheme_specialist" not in calls

        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                model,
                intent=(
                    "Refuse to help share OTP details, keep the fraud discussion with "
                    "the main agent, and direct the caller to the bank's official fraud "
                    "channel without transferring to a scheme specialist."
                ),
            )
        )
