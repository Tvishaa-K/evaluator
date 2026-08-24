# Deploying to Render (free tier)

The app is stateless — no persistent disk — so it runs on Render's free
instance type. Postgres lives on Neon rather than Render, because Render's free
database is deleted 30 days after creation.

Everything below happens in a browser, because creating accounts can't be
automated.

## 1. Create the database (Neon)

https://neon.com → new project → copy the connection string.

Neon's free plan gives 0.5 GB storage and 100 CU-hours/month, and does not
expire. It scales to zero after 5 minutes idle; the `pool_pre_ping` in
`app/db.py` handles the reconnect, so the only cost is a brief wake on the
first query.

Paste the URL as-is. `_normalize_db_url()` in `app/db.py` rewrites the scheme to
`postgresql+psycopg://` and leaves Neon's required `?sslmode=require` intact.

## 2. Create the web service (Render)

Dashboard → **New** → **Blueprint** → connect the `evaluator` repo. Render reads
`render.yaml`: a free Docker web service in Singapore, health check at
`/healthz`, pre-deploy `alembic upgrade head`.

Set the five `sync: false` vars:

| Var | Value |
|---|---|
| `DATABASE_URL` | the Neon URL from step 1 |
| `DEEPGRAM_API_KEY` | from your local `.env` |
| `SARVAM_API_KEY` | from your local `.env` |
| `BASIC_AUTH_USER` | pick one |
| `BASIC_AUTH_PASS` | pick a strong one |

`GROQ_API_KEY` and `HF_TOKEN` are dead — Groq and pyannote were removed from the
pipeline. Don't carry them over.

## 3. Seed the knowledge base

The database starts empty, so fact-checking is skipped until you load it.
Visit `/kb-manager`, authenticate, upload `kb/loan_terms.md`. Expect **9 chunks**.

Until then, processed calls return a `no_knowledge_base` warning.

## 4. Verify

1. `GET /healthz` → `{"status":"ok"}` with no credentials. This is what Render's
   health checker hits; it is deliberately exempt from basic auth.
2. `GET /` with no credentials → `401`. With credentials → the dashboard.
3. Upload a call from `calls/` at `/upload`. Budget 60-120s; Sarvam is slow. The
   dashboard polls `/jobs` every 4s and refreshes on completion.
4. Leave it 15+ minutes, then load it again. The first request takes ~1 minute
   (cold start) and the KB and call log must both still be there. That is the
   proof nothing was relying on local disk.

## How fact-checking works

There is no vector database. The entire knowledge base is passed into each
fact-check prompt (`app/rag.py: fact_check_claims`).

At 2.3 KB / ~573 tokens this is cheaper, simpler, and more accurate than the
ChromaDB top-2 retrieval it replaced — retrieval was scoring correct claims as
`not_found` and even `incorrect` when the relevant fact lived under a heading
that similarity search didn't surface.

If the KB grows past `KB_PROMPT_CHAR_LIMIT` (40,000 chars), `run_fact_check`
truncates and returns a `kb_too_large` warning. That is the signal to reintroduce
real retrieval — and because the app is now stateless, you can point it at a
hosted vector store without going back to a persistent disk.

## Operational notes

- **Cold starts.** Free services spin down after 15 min idle; waking takes about
  a minute. Neon adds a short wake on top.
- **750 instance-hours/month** covers one service running continuously (744 h).
  Exhausting it suspends free services until the next month.
- **Jobs can die on spin-down.** The dashboard polls `/jobs` every 4s, which keeps
  the service warm while the tab is open. Close the tab mid-run and the job may
  be killed. `repository.fail_stale_jobs()` marks orphans failed at next startup,
  so nothing hangs, but the call needs re-uploading.
- **`POST /process` will time out.** It runs the pipeline inline, past Render's
  proxy idle timeout. The UI uses `/process/batch`, which returns immediately.
  Don't build on `/process`.
- **Stored results keep their original verdicts.** Calls processed before the
  retrieval change still carry the old fact-check output. Re-upload the audio to
  rescore them.
