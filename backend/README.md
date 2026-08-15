# Backend — ArthSakhi Voice Agent with Murf Falcon TTS

The Python backend for ArthSakhi. It runs a real-time voice AI pipeline using [LiveKit Agents](https://docs.livekit.io/agents), connecting Murf Falcon TTS, Deepgram STT, and Google Gemini into a single conversational agent.

## How It Works

```
User speaks → [Deepgram STT] → text → [Gemini LLM] → response → [Murf Falcon TTS] → audio → User hears
```

LiveKit handles the real-time audio transport. The agent connects to LiveKit as a participant, listens for user speech, and responds with synthesized audio.

## Day 5: Scheme Eligibility Tool

Day 5 adds one real financial-domain function call: `check_scheme_eligibility`.

### Tool signature

```python
check_scheme_eligibility(scheme_id: str, answers: dict) -> dict
```

### Tool description

This function checks general, non-binding eligibility guidance for a supported Indian government financial scheme using non-sensitive information voluntarily provided by the caller. Call it when the caller asks whether they may qualify, asks for general eligibility information, or asks about commonly required documents and next steps. Do not call it for account status, application tracking, approval confirmation, transaction status, loan decisions, personalized investment advice, or requests involving OTPs, PINs, passwords, card details, account numbers, Aadhaar, PAN, or other sensitive identifiers. The result is informational only and includes dated source information.

### Supported schemes

- PMJDY
- PMSBY
- PMJJBY
- APY
- SSY

### Accepted inputs

The tool accepts only non-sensitive fields such as:

- `age`
- `age_group`
- `state_or_union_territory`
- `residency_status`
- `occupation_category`
- `is_girl_child_scheme`
- `is_girl_child`

### Rejected inputs

The tool rejects sensitive financial or identity data, including:

- Aadhaar number
- PAN number
- Bank-account number
- Card number
- OTP
- UPI PIN
- ATM PIN
- Password
- CVV
- Loan account number
- Insurance policy number
- Transaction ID
- Account balance
- Full phone number
- Login credentials

### Data source

Day 5 uses a local curated dataset because a stable documented government eligibility API was not configured. Each record includes its source URL and verification date. Results are informational only. Users must verify current eligibility, documents, benefits, and application steps through the official government portal or participating bank.

The dataset lives at [data/schemes.json](data/schemes.json) and is marked as `local_curated_dataset`.

Source URL: `https://www.myscheme.gov.in/`

Retrieval and verification dates:

- `retrieved_at`: `2026-08-10`
- `last_verified`: `2026-08-10`
- `effective_from`: `null`

### How the agent calls it

The Gemini prompt instructs the agent to call `check_scheme_eligibility` automatically when the user asks a supported eligibility question, and not to call it for account/balance/transaction/approval questions. The returned structured data is summarized into natural speech. Raw JSON is never spoken.

### Spoken responses

Examples:

- Appears possible: “आपके द्वारा दी गई सामान्य जानकारी के आधार पर, यह स्कीम आपके लिए संभव हो सकती है। यह official approval नहीं है। कृपया final eligibility official government portal या participating bank से verify करें।”
- Appears unlikely: “आपके द्वारा दी गई जानकारी के आधार पर, यह स्कीम शायद match नहीं करती। Final confirmation official source या concerned bank ही दे सकता है।”
- Needs more information: “Eligibility समझने के लिए मुझे एक और सामान्य जानकारी चाहिए। आपकी state या Union Territory कौन-सी है?”
- Source unavailable: “इस समय scheme data उपलब्ध नहीं है। मैं अनुमान लगाकर जवाब नहीं दूंगी। कृपया official government portal या bank branch से जानकारी verify करें।”

### Failure behavior

The tool handles missing files, invalid JSON, invalid inputs, and source failures without exposing stack traces. If the dataset cannot be loaded, the function returns `source_unavailable` and the assistant speaks a fallback instead of inventing an answer.

### Limitations

- The Day 5 implementation uses a local curated dataset, not a live official API.
- The result is guidance only, not official approval.
- Users still need to verify current rules, documents, and application steps with the official portal or participating bank.

## Day 9: Government Scheme Eligibility Specialist (Agent Handoff)

Day 9 adds a second agent: the **Government Scheme Eligibility Specialist** (`SchemeSpecialist`), defined in [`src/scheme_specialist.py`](src/scheme_specialist.py).

### Role of the specialist

Its only job is to help callers with:

- Government-scheme eligibility.
- Required documents.
- Basic scheme-specific guidance.

It must not handle general financial-literacy questions, fraud or unauthorized transactions, account-specific banking issues, OTPs/PINs/passwords/CVVs/account numbers/Aadhaar/PAN, outbound reminders, or general human escalation.

### Handoff tool

The main ArthSakhi agent (`Assistant`) exposes the tool:

```
transfer_to_scheme_specialist(
    user_question, conversation_summary, language_preference,
    scheme_name?, known_non_sensitive_answers?
)
```

The tool:

1. Builds a safe context from the caller's latest question, a short conversation summary, language preference, scheme name (if known), and only non-sensitive eligibility answers.
2. Speaks the required announcement — *"I'll connect you to our government-scheme eligibility specialist so you can receive more focused guidance."* (or the Hindi/Hinglish variant) — before switching.
3. Uses the installed LiveKit Agents `AgentSession.update_agent(...)` API to switch to the specialist in the same call. No second call, no disconnect, same room and participant.

### Routing conditions

- **Handle in the main agent (no handoff):** general financial-literacy explanations ("What does financial literacy mean?"), general scam-avoidance education, general scheme explanations.
- **Transfer to the specialist:** "Am I eligible for PMJDY?", "What documents are needed for PMSBY?", "Can I apply for this government financial scheme?", "What are the basic requirements for this scheme?".
- **Never transfer:** fraud, unauthorized transactions, account-specific issues, OTP/PIN/password/card/account questions, outbound reminders, general human escalation (these use the existing Day 7 escalation flow).

### Context passed

The specialist receives only:

- `user_question` — the caller's latest question.
- `conversation_summary` — a short safe summary.
- `language_preference` — Hindi, Hinglish, or English.
- `scheme_name` — if known.
- `known_non_sensitive_answers` — only non-sensitive eligibility fields already collected.

Sensitive data is filtered: disallowed answer keys, sensitive value patterns (OTPs, PINs, Aadhaar, PAN, card/account numbers, etc.) and full transcripts/audio are never passed. The specialist continues without asking the caller to repeat the problem.

### Reuse

The specialist reuses the existing Day 5 `check_scheme_eligibility` function and the same `data/schemes.json` dataset. No duplicate eligibility logic was added.

### Handoff method used

`AgentSession.update_agent(specialist)` — the in-call agent-switch API of the installed `livekit-agents ~1.4` SDK. Confirmed by inspecting the installed version. The handoff inserts an `AgentHandoff` item into the session chat context and keeps the conversation, room, and audio pipeline intact.

## Setup

### 1. Install dependencies

```bash
cd backend
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env.local
```

Fill in your keys in `.env.local`:

| Variable             | Where to get it                                           |
| -------------------- | --------------------------------------------------------- |
| `LIVEKIT_URL`        | [LiveKit Cloud](https://cloud.livekit.io/) → Settings     |
| `LIVEKIT_API_KEY`    | [LiveKit Cloud](https://cloud.livekit.io/) → Settings     |
| `LIVEKIT_API_SECRET` | [LiveKit Cloud](https://cloud.livekit.io/) → Settings     |
| `MURF_API_KEY`       | [murf.ai/api/dashboard](https://murf.ai/api/dashboard)    |
| `DEEPGRAM_API_KEY`   | [deepgram.com](https://console.deepgram.com/)             |
| `GOOGLE_API_KEY`     | [aistudio.google.com](https://aistudio.google.com/apikey) |

For LiveKit Cloud users, you can auto-populate LiveKit credentials:

```bash
lk cloud auth
lk app env -w -d .env.local
```

### 3. Download models

```bash
uv run python src/agent.py download-files
```

This downloads Silero VAD and the LiveKit turn detector models.

### 4. Run the agent

```bash
# Development mode (auto-reload)
uv run python src/agent.py dev

# Or test directly in your terminal (no frontend needed)
uv run python src/agent.py console

# Production
uv run python src/agent.py start
```

## Configuration

All configuration lives in [`src/agent.py`](src/agent.py).

### System prompt

The `SYSTEM_PROMPT` constant at the top of `agent.py` controls what your agent does. Change it to build any voice-powered use case.

#### Example prompts

**Customer Support (default):**

```
You are a friendly and efficient customer support agent for a tech company. Help users with account issues, billing questions, and product troubleshooting. Be concise, empathetic, and solution-oriented. If you don't know something, say so honestly and offer to escalate.
```

**Language Tutor:**

```
You are a patient and encouraging language tutor helping the user practice conversational Spanish. Speak primarily in Spanish but switch to English to explain grammar or vocabulary when needed. Correct mistakes gently and suggest better phrasing. Keep conversations natural and fun.
```

**AI Receptionist:**

```
You are a professional receptionist for a medical clinic. Help callers schedule appointments, answer questions about office hours and services, and take messages for doctors. Be warm but efficient. Ask for the caller's name and reason for calling upfront.
```

**Interview Coach:**

```
You are an experienced interview coach. Conduct mock interviews with the user for software engineering roles. Ask one behavioral or technical question at a time, let the user answer fully, then give specific feedback on their response — what was strong, what could improve, and a suggested reframe. Keep the tone encouraging but honest.
```

**Sales Assistant:**

```
You are a knowledgeable sales assistant for an electronics store. Help customers find the right product by asking about their needs, budget, and preferences. Compare options clearly, highlight trade-offs, and make a recommendation. Never be pushy — focus on helping the customer make the best decision for them.
```

**Fitness Coach:**

```
You are an upbeat personal fitness coach. Help users plan workouts, suggest exercises for specific muscle groups, and answer questions about form and technique. Ask about their fitness level and any injuries before recommending exercises. Keep instructions clear and motivating.
```

**Storyteller / Bedtime Narrator:**

```
You are a creative storyteller who tells original bedtime stories for children aged 4–8. Ask the child (or parent) for a character name, a favorite animal, and a setting, then weave a short, calming story. Use vivid but simple language. End each story on a peaceful, sleepy note.
```

**Meeting Summarizer:**

```
You are a meeting assistant. The user will describe what happened in a meeting or read you their notes. Summarize the key decisions, action items (with owners if mentioned), and any open questions. Be concise and structured. Ask clarifying questions if something is ambiguous.
```

**Trivia Game Host:**

```
You are an enthusiastic trivia game host. Ask the user one trivia question at a time from a mix of categories — science, history, pop culture, geography, and sports. Wait for their answer, tell them if they're right or wrong, give a brief fun fact, then move to the next question. Keep score and announce it every 5 questions.
```

**Mental Health Check-in Companion:**

```
You are a gentle, non-clinical wellness companion. Help users talk through their day, reflect on how they're feeling, and practice simple grounding exercises like deep breathing or gratitude lists. You are not a therapist — if the user expresses serious distress or mentions self-harm, gently encourage them to reach out to a professional or crisis helpline.
```

### Voice

Set the `voice` argument in the `murf.TTS(...)` call:

```python
tts=murf.TTS(
    voice="en-US-matthew",    # Change this
    style="Conversation",
    tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
    text_pacing=True
)
```

Some voice options:

| Voice ID | Description                      |
| -------- | -------------------------------- |
| `Anisha` | Indian English, female (default) |
| `Pooja`  | Indian English, female           |
| `Samar`  | Indian English, male             |
| `Amara`  | US English, female               |
| `Hazel`  | UK English, female               |
| `Bertie` | UK English, male                 |
| `Gordon` | US English, male                 |

Browse all 150+ voices: [Murf Voice Library](https://murf.ai/api/docs/voices-styles/voice-library).

### STT (Speech-to-Text)

Default is Deepgram Nova-3. Change in the `AgentSession(stt=...)` call:

```python
stt=deepgram.STT(model="nova-3")
```

### LLM

Default is Google Gemini. To switch:

- **Gemini (default):** Set `GOOGLE_API_KEY` in `.env.local`
- **OpenAI:** Set `OPENAI_API_KEY`, install `livekit-agents[openai]`, and change the `llm=` argument

## Testing

The project includes an eval suite based on the LiveKit Agents [testing framework](https://docs.livekit.io/agents/build/testing/):

```bash
uv run pytest
```

Tests are in [`tests/test_agent.py`](tests/test_agent.py) and use LLM-as-judge evaluations to verify the agent behaves correctly (friendly greetings, grounding, refusing harmful requests).

Day 5 adds direct tests for the scheme eligibility helper, source metadata, validation failures, local dataset fallback, and two agent-level behavior checks: one for eligibility questions and one for account/balance questions.

Day 9 adds [`tests/test_scheme_specialist.py`](tests/test_scheme_specialist.py) with focused tests that verify:

- The `transfer_to_scheme_specialist` tool is registered and has a clear description.
- The specialist is a separate agent with its own narrower instructions.
- Handoff context preserves the question, summary, language, and scheme name.
- Sensitive data is excluded from the handoff context.
- No duplicate call-outcome/memory/escalation records are created on handoff.
- A general question stays with the main agent (no handoff).
- A scheme question triggers the specialist handoff (LLM-judged, exercises the real `update_agent` switch).
- A fraud question uses the existing escalation flow (no handoff).

To run just the backend checks:

```bash
uv run python -m compileall src
uv run pytest
```

The eligibility tests do not require a live government API because the project uses the local curated dataset described above.

To run tests in CI, you'll need to add `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` as repository secrets.

## Deployment

### Railway

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/tIVCF1?referralCode=cNjn2P&utm_medium=integration&utm_source=template&utm_campaign=generic)

Set these environment variables in Railway:

- `MURF_API_KEY`
- `DEEPGRAM_API_KEY`
- `GOOGLE_API_KEY`
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`

### Docker

A production-ready [Dockerfile](Dockerfile) is included:

```bash
docker build -t murf-voice-agent .
docker run --env-file .env.local murf-voice-agent
```

## Project Structure

```
backend/
├── src/
│   └── agent.py          # Agent entrypoint — pipeline, prompt, config
├── tests/
│   └── test_agent.py     # LLM-judged eval suite
├── .env.example           # Environment variable template
├── pyproject.toml         # Python dependencies (uv)
├── Dockerfile             # Production container
└── railway.toml           # Railway deploy config
```

## Links

- [Murf Falcon TTS Docs](https://murf.ai/api/docs/text-to-speech/streaming)
- [Murf Voice Library](https://murf.ai/api/docs/voices-styles/voice-library)
- [LiveKit Agents Docs](https://docs.livekit.io/agents)
- [Deepgram Nova-3 Docs](https://developers.deepgram.com)

## License

MIT — see [LICENSE](LICENSE).
