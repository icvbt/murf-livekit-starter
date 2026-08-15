from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AgentStateChangedEvent,
    CloseEvent,
    JobContext,
    JobProcess,
    RunContext,
    UserInputTranscribedEvent,
    cli,
    function_tool,
    room_io,
    tokenize,
)
from livekit.plugins import deepgram, google, murf, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from call_recorder import record_call_finished as db_record_call_finished
from call_recorder import record_call_started as db_record_call_started
from caller_memory import lookup_caller as db_lookup_caller
from caller_memory import save_caller_memory as db_save_caller_memory
from escalation_store import create_escalation as db_create_escalation
from prompt import build_system_prompt
from scheme_eligibility import SchemeEligibilityAnswers, check_scheme_eligibility
from scheme_specialist import (
    SchemeSpecialist,
    build_safe_handoff_context,
    handoff_announcement,
)

logger = logging.getLogger("agent")

load_dotenv(".env.local")

HINDI_KEYWORDS = {
    "kya",
    "hai",
    "aur",
    "main",
    "haan",
    "nahin",
    "nahi",
    "aap",
    "namaste",
    "shukriya",
    "yojana",
    "batao",
    "bataiye",
    "samjhao",
    "dhan",
    "suraksha",
    "bima",
    "pension",
    "mein",
    "ke",
    "ki",
    "se",
    "ko",
    "ka",
    "jo",
    "toh",
    "bhi",
    "ho",
    "kar",
    "raha",
    "rahi",
    "rha",
    "rhi",
    "mujhe",
    "mera",
    "meri",
    "hum",
    "tum",
    "apna",
    "apni",
    "karke",
    "karo",
    "karna",
    "tha",
    "thi",
    "the",
    "ab",
    "kab",
    "tab",
    "sab",
}
AFFIRMATIVE_PATTERNS = (
    r"\b(haan|ha|yes|yeah|yep|sure|okay|ok|ji|theek hai|theek|save it|remember it|yaad rakh|yaad rakho|yaad rakhiye|you can remember that)\b",
)
NEGATIVE_PATTERNS = (
    r"\b(no|nahin|nahi|not now|abhi nahi|skip|don't save|do not save|mat rakho|mat yaad rakho)\b",
)


def _is_hindi_like(transcript: str) -> bool:
    if any(0x0900 <= ord(character) <= 0x097F for character in transcript):
        return True
    words = set(transcript.split())
    return not words.isdisjoint(HINDI_KEYWORDS)


def _is_clear_affirmative(transcript: str) -> bool:
    return bool(re.search(AFFIRMATIVE_PATTERNS[0], transcript)) and not bool(
        re.search(NEGATIVE_PATTERNS[0], transcript)
    )


def _is_clear_negative(transcript: str) -> bool:
    return bool(re.search(NEGATIVE_PATTERNS[0], transcript))


def _memory_context_text(memory: dict[str, Any] | None) -> str:
    if not memory:
        return ""

    facts = memory.get("facts", {})
    name = memory.get("name") or ""
    language_preference = memory.get("language_preference") or ""
    fact_lines = []
    for key, value in facts.items():
        fact_lines.append(f"- {key}: {value}")
    fact_block = "\n".join(fact_lines) if fact_lines else "- none"

    return (
        "Approved caller memory is available for continuity.\n"
        f"- name: {name}\n"
        f"- language_preference: {language_preference}\n"
        f"- facts:\n{fact_block}"
    )


async def _wait_for_remote_participant(room: rtc.Room, timeout_seconds: float = 8.0):
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if room.remote_participants:
            return next(iter(room.remote_participants.values()))
        await asyncio.sleep(0.1)
    return None


_finalize_tasks: set[asyncio.Task] = set()


async def _finalize_call_record(call_id: str, call_state: dict[str, Any]) -> None:
    if not call_state.get("started_recorded"):
        return

    close_error = call_state.get("close_error")
    agent_spoke = call_state.get("agent_spoke", False)

    if agent_spoke and close_error is None:
        await db_record_call_finished(
            call_id,
            outcome="success",
            success_reason="Agent produced a spoken response and the call ended without error.",
        )
    else:
        failure_parts = [f"close_reason={call_state.get('close_reason')}"]
        if close_error is not None:
            failure_parts.append(type(close_error).__name__)
        if not agent_spoke:
            failure_parts.append("no spoken response was produced")
        await db_record_call_finished(
            call_id,
            outcome="failed",
            failure_reason="; ".join(failure_parts),
        )


def _schedule_call_finalize(call_id: str, call_state: dict[str, Any]) -> None:
    task = asyncio.create_task(_finalize_call_record(call_id, call_state))
    _finalize_tasks.add(task)
    task.add_done_callback(_finalize_tasks.discard)


class Assistant(Agent):
    def __init__(
        self,
        user_id: str | None = None,
        initial_memory: dict[str, Any] | None = None,
        db_path: str | None = None,
    ) -> None:
        self.user_id = user_id
        self.initial_memory = initial_memory
        self.db_path = db_path
        self.memory_consent_granted = False
        self.escalation_consent_granted = False
        self.last_user_transcript = ""
        instructions = build_system_prompt(initial_memory)
        super().__init__(instructions=instructions)

    @function_tool
    async def lookup_caller(self, context: RunContext, user_id: str) -> dict[str, Any] | None:
        validated_user_id = user_id.strip() if isinstance(user_id, str) else ""
        if self.user_id and validated_user_id != self.user_id:
            validated_user_id = self.user_id
        if not validated_user_id:
            return None
        return await db_lookup_caller(validated_user_id, db_path=self.db_path)

    @function_tool
    async def save_caller_memory(
        self,
        context: RunContext,
        user_id: str,
        name: str,
        language_preference: str,
        schemes_discussed: list[str] | None = None,
        preferred_explanation_style: str | None = None,
        digital_safety_interest: bool | None = None,
    ) -> dict[str, Any]:
        if not self.memory_consent_granted:
            return {
                "success": False,
                "message": (
                    "Main is samay aapki information save nahi kar rahi hoon, lekin hum "
                    "conversation continue kar sakte hain."
                ),
            }

        validated_user_id = user_id.strip() if isinstance(user_id, str) else ""
        if self.user_id and validated_user_id != self.user_id:
            validated_user_id = self.user_id
        if not validated_user_id:
            return {
                "success": False,
                "message": "Main is samay aapki information save nahi kar pa rahi hoon, lekin hum conversation continue kar sakte hain.",
            }

        result = await db_save_caller_memory(
            validated_user_id,
            name,
            language_preference,
            {
                "schemes_discussed": schemes_discussed or [],
                "preferred_explanation_style": preferred_explanation_style,
                "digital_safety_interest": digital_safety_interest,
            },
            db_path=self.db_path,
        )

        if result.get("success"):
            self.memory_consent_granted = False
        return result

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


    @function_tool
    async def create_escalation(
        self,
        context: RunContext,
        issue_type: str,
        summary: str,
        checked_information: list[str],
        urgency: str,
        language_preference: str,
        preferred_follow_up_method: str,
        consent_given: bool,
    ) -> dict[str, Any]:
        """
        Create a limited human-support request only when the caller reports suspected
        fraud, an unauthorized transaction, an account-specific issue, a disputed
        charge, an application decision, or a request for professional financial advice.

        Ask for explicit permission before using this tool. Share only a short summary,
        what ArthSakhi already checked, urgency, language, and preferred follow-up method.

        Never include OTPs, UPI PINs, ATM PINs, passwords, CVVs, card numbers,
        bank-account numbers, Aadhaar, PAN, transaction IDs, balances, loan numbers,
        insurance policy numbers, or full conversation transcripts.

        Do not use this tool for normal financial education, scheme explanations,
        or general eligibility questions.
        """

        if not consent_given or not self.escalation_consent_granted:
            return {
                "success": False,
                "error": "consent_required",
                "message": (
                    "I need the caller's clear permission before creating a "
                    "human-support request."
                ),
            }

        validated_user_id = self.user_id or "unknown-session"

        result = await asyncio.to_thread(
            db_create_escalation,
            validated_user_id,
            issue_type,
            summary,
            checked_information,
            urgency,
            language_preference,
            preferred_follow_up_method,
            True,
        )

        self.escalation_consent_granted = False
        return result

    @function_tool
    async def transfer_to_scheme_specialist(
        self,
        context: RunContext,
        user_question: str,
        conversation_summary: str,
        language_preference: str,
        scheme_name: str | None = None,
        known_non_sensitive_answers: SchemeEligibilityAnswers | None = None,
    ) -> dict[str, Any]:
        """Transfer the caller to the Government Scheme Eligibility Specialist when
        the caller asks a scheme-specific question about a supported Indian
        government scheme's eligibility, required documents, or basic
        scheme-specific application guidance.

        Use this tool only for scheme-specific questions.

        Do not use it for general financial-literacy questions, fraud or
        unauthorized transactions, account-specific banking issues, OTPs, PINs,
        passwords, CVVs, card numbers, account numbers, Aadhaar, PAN, outbound
        reminders, or general human escalation.

        Pass the caller's latest question, a short safe conversation summary,
        language preference, scheme name if known, and any already-collected
        non-sensitive answers. Never pass sensitive data, full transcripts, or
        raw audio.
        """
        try:
            safe_context = build_safe_handoff_context(
                user_question=user_question,
                conversation_summary=conversation_summary,
                language_preference=language_preference,
                scheme_name=scheme_name,
                known_non_sensitive_answers=known_non_sensitive_answers,
            )
        except ValueError:
            return {
                "success": False,
                "message": (
                    "A safe summary of the caller's question is required before "
                    "transferring."
                ),
            }

        specialist = SchemeSpecialist(**safe_context)

        await context.session.say(
            handoff_announcement(safe_context["language_preference"]),
            allow_interruptions=False,
        )

        context.session.update_agent(specialist)

        return {
            "success": True,
            "message": (
                "The conversation has been handed to the Government Scheme "
                "Eligibility Specialist."
            ),
        }

server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    await ctx.connect()
    remote_participant = await _wait_for_remote_participant(ctx.room)

    caller_id = remote_participant.identity if remote_participant else f"session-{uuid.uuid4()}"
    initial_memory = await db_lookup_caller(caller_id) if remote_participant else None

    call_id = ctx.room.name or f"call-{uuid.uuid4()}"
    channel = (
        "sip"
        if remote_participant
        and remote_participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
        else "browser"
    )
    language_preference = (
        initial_memory.get("language_preference") if initial_memory else None
    )
    call_state: dict[str, Any] = {
        "started_recorded": False,
        "agent_spoke": False,
        "close_reason": None,
        "close_error": None,
    }

    started_result = await db_record_call_started(
        call_id=call_id,
        channel=channel,
        language_preference=language_preference,
    )
    call_state["started_recorded"] = started_result.get("success", False)

    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="multi"),
        llm=google.LLM(
            model="gemini-3.5-flash",
        ),
        tts=murf.TTS(
            voice="Anisha",
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    assistant = Assistant(user_id=caller_id, initial_memory=initial_memory)

    if initial_memory and initial_memory.get("language_preference") in {"Hindi", "Hinglish"}:
        session.tts.update_options(voice="hi-IN-anisha")
    elif initial_memory and initial_memory.get("language_preference") == "English":
        session.tts.update_options(voice="en-IN-anisha")

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(ev: UserInputTranscribedEvent):
        transcript = ev.transcript.strip()
        lowered_transcript = transcript.lower()
        if not transcript:
            return

        assistant.last_user_transcript = transcript
        if _is_clear_affirmative(lowered_transcript):
            assistant.memory_consent_granted = True
            assistant.escalation_consent_granted = True
        elif _is_clear_negative(lowered_transcript):
            assistant.memory_consent_granted = False
            assistant.escalation_consent_granted = False

        if _is_hindi_like(lowered_transcript):
            logger.info("Detected Hindi/Hinglish speech. Switching TTS to hi-IN-anisha.")
            session.tts.update_options(voice="hi-IN-anisha")
        else:
            logger.info("Detected English speech. Switching TTS to en-IN-anisha.")
            session.tts.update_options(voice="en-IN-anisha")

    @session.on("agent_state_changed")
    def on_agent_state_changed(ev: AgentStateChangedEvent):
        if ev.new_state == "speaking":
            call_state["agent_spoke"] = True

    @session.on("close")
    def on_close(ev: CloseEvent):
        call_state["close_reason"] = ev.reason.value
        call_state["close_error"] = ev.error
        if call_state["started_recorded"]:
            _schedule_call_finalize(call_id, call_state)

    await session.start(
        agent=assistant,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )


if __name__ == "__main__":
    cli.run_app(server)
