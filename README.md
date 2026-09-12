# Voice Agent Evaluator

Automated quality assurance for AI voice agents in loan servicing. Upload a call
recording and get back a scored evaluation: what the agent got right, where it
went silent, and — critically — whether anything it told the customer was
actually true.

Built for inbound call-center audio, including code-mixed and non-English calls
(Hindi, Tamil, and 20 other Indian languages), which are transcribed and
translated to English before scoring.

## The problem

Voice agents are deployed at a scale no human QA team can review. Sampling 2% of
calls by hand misses the failure that matters: an agent confidently quoting a
foreclosure charge that doesn't exist. Correctness against company policy is not
something a generic LLM rubric can judge — it needs the policy in hand.

This evaluates every call, on eight dimensions, against the actual loan terms.

## Pipeline

Each call runs through six stages (`app/pipeline.py`):

```
audio file
    │
    ▼
1. Transcribe + diarize ──── Deepgram nova-3
    │                        speaker-labeled, timestamped utterances
    ▼                        + automatic language detection
2. Identify the agent ────── first substantial speaker = agent
    │                        (inbound calls: the agent greets first)
    ▼
3. Translate (if needed) ─── Sarvam, per segment, preserving labels
    │                        skipped for English calls
    ▼
4. Detect dead air ───────── gaps >5s where the customer finished
    │                        and the agent hadn't yet replied
    ▼
5. Fact-check ────────────── extract the agent's factual claims,
    │                        verify each against the knowledge base
    ▼
6. Score ─────────────────── 8 dimensions, 0-10 each, with reasoning
    │
    ▼
stored evaluation
```

Stages 5 and 6 are LLM calls against Sarvam (`sarvam-105b-conversations`,
temperature 0). The non-reasoning variant is deliberate: `sarvam-105b` reasons
before every answer and the trace exhausts the completion budget before any JSON
is emitted, so it returns empty content on these structured-output prompts. See
`app/llm.py`.

### Speaker identification

Diarization returns arbitrary labels — `SPEAKER_00`, `SPEAKER_01` — that carry no
identity and aren't stable between files. Since these are inbound calls where the
agent always greets first, whoever speaks first is the agent
(`stt.determine_agent_speaker`).

Sub-second segments are filtered out before applying that rule, because
diarization routinely misclassifies a breath or a line-noise burst as a distinct
speaker turn, and one of those at the top of the file would otherwise hijack the
agent label. The same filter backs `is_single_speaker`, which sets a
`diarization_warning` when a call has no real second speaker — a signal that the
scores for that call are unreliable.

### Fact-checking

Two LLM passes (`app/rag.py`):

1. `extract_agent_claims` pulls every factual assertion the agent made about
   rates, fees, timelines, or rules — ignoring greetings and questions.
2. `fact_check_claims` checks each one against the knowledge base and returns
   `correct`, `incorrect`, or `not_found`, with the supporting fact.

**There is no vector database.** The entire knowledge base is passed into every
fact-check prompt. This replaced a ChromaDB top-2 retrieval setup that was
actively producing wrong verdicts: a correct claim about the Rs. 500 bounce
charge scored `not_found` because similarity search surfaced the "EMI Rules" and
"Late Payment" sections instead of "Charges Summary", where the fee actually
lives.

At 2.3 KB (~573 tokens) the whole document costs less than the embedding call it
replaced, and it can't miss. Past `KB_PROMPT_CHAR_LIMIT` (40,000 chars) the KB is
truncated and a `kb_too_large` warning is returned — the explicit signal that real
retrieval needs to come back, rather than silently degrading.

## Scoring

Eight dimensions, 0-10 each (`app/score.py`):

| Dimension | Measures |
|---|---|
| `resolution_rate` | Was the customer's issue actually resolved? |
| `compliance` | Required disclosures, consent, data handling |
| `customer_understanding` | Did the agent correctly interpret every request? |
| `dead_air` | Scored from measured silence, not the LLM's impression |
| `fact_checking` | Driven by the knowledge base verdicts |
| `data_confirmation` | Was collected data read back and confirmed? |
| `interruption_handling` | Did the agent stop and adapt when interrupted? |
| `escalation_analysis` | Was escalation needed, and handled well? |

Also returned: a plain-language `summary`, `fraud_flags` (raised if the agent
asked for an OTP, PIN, CVV, password, or remote access), and `critical_failure`.

Two deliberate choices:

**Measured signals beat asked-for ones.** Dead air is computed from timestamps in
`app/dead_air.py` and handed to the model as a fact, rather than asking the model
to judge silence it cannot hear. Same for fact-checking: the verdicts are
computed, and the model scores the dimension from them.

**The composite is computed, not trusted.** The model is asked for a composite,
but `score_transcript` ignores it and sums the dimensions itself. `max_possible`
is 80 normally, or 70 when the agent made no factual claims — in which case
`fact_checking` is null and is excluded rather than scored as a zero, so a call
with nothing to fact-check isn't punished for it.

LLM JSON output is repaired (`json-repair`) and then structurally normalized:
malformed responses tend to leave `fraud_flags`, `critical_failure`, and
`summary` nested one level too deep, inside `scores`, so they're lifted back out.

## Stack

- **FastAPI** + **uvicorn** — API and static dashboard
- **Postgres** (SQLAlchemy 2.0 + Alembic) — all state; the app holds none
- **Deepgram** `nova-3` — transcription, diarization, language detection
- **Sarvam** — translation (`sarvam-translate:v1`) and scoring
  (`sarvam-105b-conversations`)

Seven tables: `calls` with `call_segments`, `dead_air_instances`,
`fact_check_results`, and `dimension_scores` hanging off it, plus
`kb_documents` and `processing_jobs`.

## Running locally

Requires Python 3.12 and a Postgres database.

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # fill in DATABASE_URL, DEEPGRAM_API_KEY, SARVAM_API_KEY
alembic upgrade head

uvicorn app.main:app --reload
```

Then, in order:

1. **Load the knowledge base** at `/kb-manager` — upload `kb/loan_terms.md`
   (9 chunks). Until this is done, fact-checking is skipped and every call comes
   back with a `no_knowledge_base` warning.
2. **Upload calls** at `/upload`. Budget 60-120s per call; translation is the
   slow part.
3. **Review** at `/`.

`batch.py` runs the same pipeline over every `.mp3` in `calls/` from the command
line, saving to the database and skipping calls already processed.

### Authentication

Set `BASIC_AUTH_USER` and `BASIC_AUTH_PASS` to put HTTP basic auth in front of
every route except `/healthz` (which is exempt so deployment health checks can
reach it). Leave both unset for local development and the middleware no-ops.

This matters in deployment: without it, anyone with the URL can clear the
knowledge base, delete calls, and burn Deepgram and Sarvam credits.

## API

| Method | Route | |
|---|---|---|
| `GET` | `/` `/upload` `/kb-manager` | Dashboard, upload, KB manager UIs |
| `GET` | `/healthz` | Liveness — unauthenticated, doesn't touch Postgres |
| `POST` | `/process/batch` | Queue files, return job records immediately |
| `GET` | `/jobs` | Job status — the dashboard polls this every 4s |
| `GET` | `/results` | All calls, summarized |
| `GET` | `/results/{call_id}` | One call, in full |
| `DELETE` | `/results/{call_id}` | Delete a call |
| `GET` | `/analytics` | Score bands, failure profile, resolution funnel |
| `GET` | `/kb` | KB files and chunk count |
| `POST` | `/kb/upload` | Ingest documents (`mode=append\|replace`) |
| `DELETE` | `/kb` | Clear the KB |
| `POST` | `/process` | Synchronous single-file processing |
| `POST` | `/score` | Score a transcript directly, no audio |

`POST /process` runs the pipeline inline and will exceed most proxy idle
timeouts. It's kept for local and scripted use — the UI uses `/process/batch`.

Batch jobs run in an in-process `ThreadPoolExecutor` (`PIPELINE_WORKERS`,
default 2), sized small because every stage is a blocking third-party HTTP call
and the limit is provider rate limits, not CPU. Jobs orphaned by a restart are
marked failed at startup by `repository.fail_stale_jobs()`, so nothing hangs in
`processing` forever.

## Deployment

Runs as a Docker container on Render's free tier with Postgres on Neon. The app
is fully stateless — no disk, no local vector store — so it survives being spun
down and restarted. See [DEPLOY.md](DEPLOY.md) for the full runbook.
