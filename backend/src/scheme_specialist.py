from __future__ import annotations

import json
from typing import Any

from livekit.agents import Agent, RunContext, function_tool

from scheme_eligibility import (
    ALLOWED_ANSWER_KEYS,
    SENSITIVE_FIELD_NAMES,
    SENSITIVE_VALUE_PATTERNS,
    SchemeEligibilityAnswers,
    check_scheme_eligibility,
)

HANDOFF_ANNOUNCEMENT_EN = (
    "I'll connect you to our government-scheme eligibility specialist "
    "so you can receive more focused guidance."
)
HANDOFF_ANNOUNCEMENT_HI = (
    "Main aapko government scheme eligibility specialist se jod rahi hoon, "
    "taaki aapko aur focused guidance mil sake."
)

SPECIALIST_SYSTEM_PROMPT_TEMPLATE = """\
IDENTITY

You are ArthSakhi's Government Scheme Eligibility Specialist (ArthSakhi ki
government scheme eligibility specialist).

Your only job is to help callers understand supported Indian government
financial schemes, basic eligibility requirements, commonly required documents,
and basic scheme-specific guidance.

You are not a bank employee, government officer, financial advisor, or approval
authority. You never make official eligibility decisions.

CONTINUITY

The caller already spoke with the main ArthSakhi agent. Continue naturally from
the context below. Introduce yourself, mention the caller's question, and do not
ask the caller to repeat the problem.

CALLER CONTEXT
- user_question: {user_question}
- conversation_summary: {conversation_summary}
- language_preference: {language_preference}
- scheme_name: {scheme_name}
- known_non_sensitive_answers: {known_non_sensitive_answers}

YOU MAY
- Explain the purpose of a supported government scheme.
- Ask only non-sensitive questions (age, age group, state or Union Territory,
  residency status, occupation category, girl-child related) needed for a basic
  eligibility check.
- Use the verified check_scheme_eligibility tool.
- Explain the result in simple language.
- Provide the common document checklist.
- Say that final eligibility and approval belong to the official government
  authority or participating bank.

YOU MUST NOT
- Ask for OTPs, PINs, passwords, CVVs, card numbers, or bank account numbers.
- Ask for Aadhaar, PAN, or other government ID numbers.
- Handle suspected fraud or unauthorized transactions.
- Handle account-specific banking issues, balances, or transactions.
- Handle outbound reminder requests.
- Create a human-escalation request unless the existing approved flow requires it.
- Give personalized investment, tax, or legal advice.
- Invent scheme rules or eligibility information.
- Claim access to bank records, application status, approvals, or government
  databases.
- Promise that an application will be approved.
- Present tool output as official approval.

If verified scheme data is unavailable, say clearly that you cannot verify the
information at this moment. Never invent an answer.

LANGUAGE

Mirror the caller's language preference: Hindi, Hinglish, or English. Use
respectful forms such as aap. Keep voice responses short and conversational.

FIRST MESSAGE

After taking over, introduce yourself like this example and continue without
asking the caller to repeat the question:
"Namaste, main ArthSakhi ki government scheme eligibility specialist hoon. Mujhe
bataya gaya hai ki aap PMJDY eligibility aur required documents ke baare mein
jaan-na chahte hain. Main aapko guide karungi."
Use the caller's language preference.
"""


def build_specialist_prompt(
    *,
    user_question: str,
    conversation_summary: str,
    language_preference: str,
    scheme_name: str | None = None,
    known_non_sensitive_answers: dict[str, Any] | None = None,
) -> str:
    return SPECIALIST_SYSTEM_PROMPT_TEMPLATE.format(
        user_question=user_question or "(not provided)",
        conversation_summary=conversation_summary or "(no summary)",
        language_preference=language_preference or "unknown",
        scheme_name=scheme_name or "unknown",
        known_non_sensitive_answers=json.dumps(
            known_non_sensitive_answers or {}, ensure_ascii=False
        ),
    )


def _redact_sensitive_values(value: str) -> str:
    redacted = value
    for pattern in SENSITIVE_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


def _clean_text(value: Any, *, max_length: int) -> str:
    if not isinstance(value, str):
        return ""
    return _redact_sensitive_values(value.strip())[:max_length]


def normalize_language_preference(value: Any) -> str:
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in {"hindi", "हिन्दी", "हिंदी"}:
            return "Hindi"
        if candidate in {"hinglish"}:
            return "Hinglish"
        if candidate in {"english", "en"}:
            return "English"
    return "unknown"


def _sanitize_non_sensitive_answers(answers: Any) -> dict[str, Any]:
    if not isinstance(answers, dict):
        return {}
    clean: dict[str, Any] = {}
    for raw_key, value in answers.items():
        key = raw_key.strip().lower() if isinstance(raw_key, str) else ""
        if not key or key in SENSITIVE_FIELD_NAMES or key not in ALLOWED_ANSWER_KEYS:
            continue
        if isinstance(value, str):
            candidate = value.strip()
            if any(pattern.search(candidate) for pattern in SENSITIVE_VALUE_PATTERNS):
                continue
            value = candidate[:200]
        clean[key] = value
    return clean


def build_safe_handoff_context(
    *,
    user_question: str,
    conversation_summary: str,
    language_preference: str,
    scheme_name: str | None = None,
    known_non_sensitive_answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    question = _clean_text(user_question, max_length=500)
    if not question:
        raise ValueError("user_question is required")

    summary = _clean_text(conversation_summary, max_length=500)
    scheme = _clean_text(scheme_name, max_length=50) if scheme_name else ""

    return {
        "user_question": question,
        "conversation_summary": summary,
        "language_preference": normalize_language_preference(language_preference),
        "scheme_name": scheme or None,
        "known_non_sensitive_answers": _sanitize_non_sensitive_answers(
            known_non_sensitive_answers
        ),
    }


def handoff_announcement(language_preference: str) -> str:
    if normalize_language_preference(language_preference) in {"Hindi", "Hinglish"}:
        return HANDOFF_ANNOUNCEMENT_HI
    return HANDOFF_ANNOUNCEMENT_EN


class SchemeSpecialist(Agent):
    def __init__(
        self,
        *,
        user_question: str,
        conversation_summary: str,
        language_preference: str,
        scheme_name: str | None = None,
        known_non_sensitive_answers: dict[str, Any] | None = None,
    ) -> None:
        instructions = build_specialist_prompt(
            user_question=user_question,
            conversation_summary=conversation_summary,
            language_preference=language_preference,
            scheme_name=scheme_name,
            known_non_sensitive_answers=known_non_sensitive_answers,
        )
        super().__init__(instructions=instructions)

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions=(
                "Introduce yourself as ArthSakhi ki government scheme eligibility "
                "specialist, briefly mention the caller's existing question from the "
                "context, and continue without asking them to repeat it. Mirror the "
                "caller's language preference."
            )
        )

    @function_tool
    async def check_scheme_eligibility(
        self,
        context: RunContext,
        scheme_id: str,
        answers: SchemeEligibilityAnswers,
    ) -> dict[str, Any]:
        """Check general, non-binding eligibility guidance for a supported Indian
        government financial scheme using non-sensitive information voluntarily
        provided by the caller. Call it when the caller asks whether they may
        qualify, asks for general eligibility information, or asks about commonly
        required documents and next steps. Do not call it for account status,
        application tracking, approval confirmation, transaction status, loan
        decisions, personalized investment advice, or requests involving OTPs,
        PINs, passwords, card details, account numbers, Aadhaar, PAN, or other
        sensitive identifiers. The result is informational only and includes dated
        source information.
        """
        return check_scheme_eligibility(scheme_id, dict(answers))
