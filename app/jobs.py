import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from app.pipeline import run_pipeline
from app import repository

# Pipeline stages are blocking HTTP calls (Deepgram, Sarvam), so a small
# thread pool gives real batch parallelism without hammering rate limits.
executor = ThreadPoolExecutor(max_workers=int(os.getenv("PIPELINE_WORKERS", "2")))


def _run_job(job_id: int, file_bytes: bytes, filename: str) -> None:
    repository.update_job(job_id, "processing")
    try:
        result = run_pipeline(file_bytes, filename)
        result["call_id"] = f"{Path(filename).stem}-{uuid4().hex[:8]}"
        result["processed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        repository.save_result(result)
        repository.update_job(job_id, "done", call_id=result["call_id"])
    except Exception as e:
        repository.update_job(job_id, "failed", error=str(e)[:500])


def submit(file_bytes: bytes, filename: str) -> dict:
    """Creates a job record and queues the pipeline run. Returns the job dict."""
    job = repository.create_job(filename)
    executor.submit(_run_job, job["id"], file_bytes, filename)
    return job
