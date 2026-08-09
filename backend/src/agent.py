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
    JobContext,
    JobProcess,
    RunContext,
    UserInputTranscribedEvent,
    cli,
    function_tool,
    tokenize,
    room_io,
)
from livekit.plugins import deepgram, google, murf, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from caller_memory import lookup_caller as db_lookup_caller
from caller_memory import save_caller_memory as db_save_caller_memory
from prompt import build_system_prompt

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
        elif _is_clear_negative(lowered_transcript):
            assistant.memory_consent_granted = False

        if _is_hindi_like(lowered_transcript):
            logger.info("Detected Hindi/Hinglish speech. Switching TTS to hi-IN-anisha.")
            session.tts.update_options(voice="hi-IN-anisha")
        else:
            logger.info("Detected English speech. Switching TTS to en-IN-anisha.")
            session.tts.update_options(voice="en-IN-anisha")

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
