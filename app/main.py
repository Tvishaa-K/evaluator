from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from app.pipeline import run_pipeline
from app import jobs
from app.score import score_transcript
from app.rag import ingest_files, kb_chunk_count
from app.analytics import compute_analytics
from app import repository
from pydantic import BaseModel
import base64
import os
import secrets
import time
from pathlib import Path
from uuid import uuid4

load_dotenv()

ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm"}
ALLOWED_KB_EXTS = {".pdf", ".md", ".txt"}

app = FastAPI()

BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER")
BASIC_AUTH_PASS = os.getenv("BASIC_AUTH_PASS")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Gates every route, including the static mount, behind HTTP basic auth.
    No-ops when the credentials are unset so local dev and batch.py are
    unaffected. Without this, anyone with the URL can clear the knowledge base,
    delete calls, or burn Deepgram/Sarvam credits via /process."""
    # Render's health checker can't send credentials, so a gated /healthz
    # would 401 and get the service marked unhealthy.
    if request.url.path == "/healthz":
        return await call_next(request)

    if not (BASIC_AUTH_USER and BASIC_AUTH_PASS):
        return await call_next(request)

    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            user, _, password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        except Exception:
            user = password = ""
        # Both compared with compare_digest so a bad username and a bad
        # password take the same time.
        user_ok = secrets.compare_digest(user, BASIC_AUTH_USER)
        pass_ok = secrets.compare_digest(password, BASIC_AUTH_PASS)
        if user_ok and pass_ok:
            return await call_next(request)

    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Voice Agent Evaluator"'},
    )


app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.on_event("startup")
async def cleanup_stale_jobs():
    repository.fail_stale_jobs()

@app.get("/healthz")
async def healthz():
    """Liveness only — deliberately does not touch Postgres, so a transient DB
    blip doesn't trigger a restart loop."""
    return {"status": "ok"}


@app.get("/")
async def dashboard():
    return FileResponse("app/static/dashboard.html")

@app.get("/upload")
async def upload_page():
    return FileResponse("app/static/upload.html")

@app.get("/kb-manager")
async def kb_page():
    return FileResponse("app/static/kb.html")

@app.get("/results")
async def list_results():
    calls = []
    for data in repository.list_results():
        calls.append({
            "call_id": data["call_id"],
            "composite_score": data["evaluation"]["composite_score"],
            "max_possible": data["evaluation"]["max_possible"],
            "critical_failure": data["evaluation"]["critical_failure"],
            "claims_checked": data["fact_check"]["claims_checked"],
            "mismatches": len(data["fact_check"]["mismatches"]),
            "dead_air_seconds": data["dead_air"]["total_dead_air_seconds"],
            "detected_language": data.get("detected_language"),
            "diarization_warning": data.get("diarization_warning"),
        })
    return {"calls": calls}

@app.get("/results/{call_id}")
async def get_result(call_id: str):
    data = repository.get_result(call_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return data

@app.delete("/results/{call_id}")
async def delete_result(call_id: str):
    if not repository.delete_result(call_id):
        raise HTTPException(status_code=404, detail="Call not found")
    return {"deleted": call_id}

@app.get("/analytics")
async def analytics():
    return compute_analytics()

class ScoreRequest(BaseModel):
    transcript: str
    dead_air_seconds: float = 0.0
    claims_checked: int = 0
    kb_mismatches: list = []

@app.post("/process")
async def process(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported audio format '{ext}'. Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXTS))}")

    contents = await file.read()
    result = run_pipeline(contents, file.filename)

    result["call_id"] = f"{Path(file.filename).stem}-{uuid4().hex[:8]}"
    result["processed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    repository.save_result(result)
    return result

@app.post("/process/batch")
async def process_batch(files: list[UploadFile] = File(...)):
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_AUDIO_EXTS:
            raise HTTPException(status_code=400, detail=f"Unsupported audio format '{ext}' ({f.filename}). Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXTS))}")

    created = []
    for f in files:
        contents = await f.read()
        created.append(jobs.submit(contents, f.filename))
    return {"jobs": created}

@app.get("/jobs")
async def list_jobs():
    return {"jobs": repository.list_jobs()}

@app.post("/score")
async def score(request: ScoreRequest):
    result = score_transcript(
        transcript=request.transcript,
        dead_air_seconds=request.dead_air_seconds,
        fact_check={"claims_checked": request.claims_checked, "mismatches": request.kb_mismatches or []}
    )
    return result

@app.get("/kb")
async def kb_status():
    return {
        "files": repository.list_kb_documents(),
        "total_chunks": kb_chunk_count(),
    }

@app.post("/kb/upload")
async def kb_upload(files: list[UploadFile] = File(...), mode: str = Form("append")):
    if mode not in ("append", "replace"):
        raise HTTPException(status_code=400, detail="mode must be 'append' or 'replace'")

    payload = []
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_KB_EXTS:
            raise HTTPException(status_code=400, detail=f"Unsupported KB format '{ext}'. Allowed: {', '.join(sorted(ALLOWED_KB_EXTS))}")
        payload.append((f.filename, await f.read()))

    ingested = ingest_files(payload)
    repository.save_kb_documents(ingested, mode=mode)

    return {
        # Strip content — the client only needs the per-file counts, and
        # echoing it back would put the whole KB in the response body.
        "ingested": [{"filename": d["filename"], "chunk_count": d["chunk_count"]} for d in ingested],
        "mode": mode,
        "total_chunks": kb_chunk_count(),
    }

@app.delete("/kb")
async def kb_clear():
    repository.clear_kb_documents()
    return {"cleared": True, "total_chunks": 0}
