# Deploying to Render

The repo is deploy-ready. Everything below happens in the Render dashboard,
because creating an account and attaching a payment method can't be automated.

## Prerequisites

- A Render account (https://dashboard.render.com/register) with a payment method.
  A persistent disk requires a paid instance, and the disk is what makes the
  knowledge base survive restarts.
- The repo: https://github.com/Tvishaa-K/evaluator (private)

## 1. Create the Blueprint

Dashboard → **New** → **Blueprint** → connect the `evaluator` repo.

Render reads `render.yaml` and provisions three things:

| Resource | Config | Why |
|---|---|---|
| Web service `evaluator` | Docker, `starter`, Singapore | Free instances can't mount a disk and sleep when idle, which would kill in-flight pipeline jobs |
| Disk `chroma` | 1 GB at `/data` | Holds the Chroma vector store. Disks can grow but never shrink |
| Postgres `evaluator-db` | `basic-256mb`, Singapore | Must match the web service region for the internal URL to resolve |

## 2. Fill in the secrets

`render.yaml` marks four vars `sync: false`, meaning Render prompts for them
instead of reading them from the repo. Set all four:

| Var | Value |
|---|---|
| `DEEPGRAM_API_KEY` | from your local `.env` |
| `SARVAM_API_KEY` | from your local `.env` |
| `BASIC_AUTH_USER` | pick one |
| `BASIC_AUTH_PASS` | pick a strong one |

`DATABASE_URL`, `CHROMA_PATH`, and `PIPELINE_WORKERS` are wired automatically.

Do **not** copy `GROQ_API_KEY` or `HF_TOKEN` — Groq and pyannote were removed
from the pipeline and neither is read anymore.

## 3. First deploy

Render will, in order: build the Dockerfile, run `alembic upgrade head` as the
pre-deploy command, then start uvicorn.

Watch the build log for the ONNX warm-up step. It downloads ~79 MB and takes
around 3 minutes **once, at build time**. If you ever see that download in the
*runtime* log instead, the `HOME` pinning in the Dockerfile has broken and every
deploy will pay that cost on its first knowledge-base operation.

## 4. Seed the knowledge base

The disk starts empty, so fact-checking is skipped until you load it.

Visit `/kb-manager` on your Render URL, authenticate, and upload
`kb/loan_terms.md`. Expect **9 chunks**. Until this is done, processed calls come
back with a `no_knowledge_base` warning.

## 5. Verify

1. `GET /healthz` → `{"status":"ok"}`, no credentials needed. This is what
   Render's health checker hits; it is deliberately exempt from basic auth.
2. `GET /` without credentials → `401`. With credentials → the dashboard.
3. Upload one call from `calls/` at `/upload`. Budget 60-120s — Sarvam is slow.
   The dashboard polls `/jobs` every 4s and refreshes when it completes.
4. Trigger a manual redeploy and confirm the KB chunk count and call log both
   survive. That is the whole point of the disk.

## Operational notes

- **One instance only.** The disk enforces it; Render caps a disk-attached
  service at a single running instance.
- **Deploys are not zero-downtime.** Render stops the old instance before
  starting the new one, to avoid two writers on one disk.
- **In-flight jobs die on deploy.** `repository.fail_stale_jobs()` runs at
  startup and marks orphans failed, so nothing hangs — but those calls need
  re-uploading.
- **`POST /process` will time out.** It runs the full pipeline inline, past
  Render's proxy idle timeout. The UI never calls it; it uses `/process/batch`,
  which returns immediately and processes in the background. Don't build on
  `/process`.
- **Scaling up means removing the disk.** Move Chroma to a hosted vector store
  first, then the service becomes stateless and can run multiple instances.
