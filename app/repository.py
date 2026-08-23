import time

from app.db import SessionLocal, Call, CallSegment, DeadAirInstance, FactCheckResult, DimensionScore, KbDocument, ProcessingJob


def _call_to_dict(call: Call) -> dict:
    fact_check_results = [
        {
            "claim": r.claim,
            "verdict": r.verdict,
            "explanation": r.explanation,
            "kb_fact": r.kb_fact,
        }
        for r in call.fact_check_results
    ]

    return {
        "call_id": call.call_id,
        "processed_at": call.processed_at,
        "labeled_transcript": call.labeled_transcript,
        "detected_language": call.detected_language,
        "original_transcript": call.original_transcript,
        "summary": call.summary,
        "diarization_warning": call.diarization_warning,
        "segments": [
            {"start": s.start, "end": s.end, "speaker": s.speaker, "text": s.text}
            for s in call.segments
        ],
        "dead_air": {
            "total_dead_air_seconds": call.dead_air_total_seconds,
            "instances": [
                {"start": d.start, "end": d.end, "duration": d.duration}
                for d in call.dead_air_instances
            ],
        },
        "fact_check": {
            "claims_checked": call.claims_checked,
            "mismatches": [r for r in fact_check_results if r["verdict"] == "incorrect"],
            "results": fact_check_results,
        },
        "evaluation": {
            "scores": {
                d.dimension_key: {"score": d.score, "reasoning": d.reasoning}
                for d in call.dimension_scores
            },
            "composite_score": call.composite_score,
            "max_possible": call.max_possible,
            "fraud_flags": call.fraud_flags,
            "critical_failure": call.critical_failure,
        },
    }


def save_result(result: dict) -> None:
    with SessionLocal() as session:
        existing = session.get(Call, result["call_id"])
        if existing:
            session.delete(existing)
            session.flush()

        call = Call(
            call_id=result["call_id"],
            processed_at=result["processed_at"],
            labeled_transcript=result["labeled_transcript"],
            detected_language=result.get("detected_language"),
            original_transcript=result.get("original_transcript"),
            summary=result["evaluation"].get("summary"),
            dead_air_total_seconds=result["dead_air"]["total_dead_air_seconds"],
            diarization_warning=result.get("diarization_warning"),
            composite_score=result["evaluation"]["composite_score"],
            max_possible=result["evaluation"]["max_possible"],
            critical_failure=result["evaluation"]["critical_failure"],
            fraud_flags=result["evaluation"].get("fraud_flags") or [],
            claims_checked=result["fact_check"]["claims_checked"],
        )

        call.segments = [
            CallSegment(ordinal=i, start=s["start"], end=s["end"], speaker=s["speaker"], text=s["text"])
            for i, s in enumerate(result["segments"])
        ]
        call.dead_air_instances = [
            DeadAirInstance(start=inst["start"], end=inst["end"], duration=inst["duration"])
            for inst in result["dead_air"]["instances"]
        ]
        call.fact_check_results = [
            FactCheckResult(
                claim=r["claim"], verdict=r["verdict"],
                explanation=r["explanation"], kb_fact=r.get("kb_fact")
            )
            for r in result["fact_check"]["results"]
        ]
        call.dimension_scores = [
            DimensionScore(dimension_key=key, score=val["score"], reasoning=val["reasoning"])
            for key, val in result["evaluation"]["scores"].items()
        ]

        session.add(call)
        session.commit()


def get_result(call_id: str) -> dict | None:
    with SessionLocal() as session:
        call = session.get(Call, call_id)
        return _call_to_dict(call) if call else None


def delete_result(call_id: str) -> bool:
    with SessionLocal() as session:
        call = session.get(Call, call_id)
        if call is None:
            return False
        session.delete(call)
        session.commit()
        return True


def list_results() -> list[dict]:
    with SessionLocal() as session:
        calls = session.query(Call).order_by(Call.call_id).all()
        return [_call_to_dict(c) for c in calls]


def list_kb_documents() -> list[dict]:
    with SessionLocal() as session:
        docs = session.query(KbDocument).order_by(KbDocument.uploaded_at).all()
        return [
            {"filename": d.filename, "uploaded_at": d.uploaded_at, "chunk_count": d.chunk_count}
            for d in docs
        ]


def save_kb_documents(ingested: list[dict], mode: str = "append") -> None:
    """Records ingested files. mode="replace" wipes the list first; a
    re-uploaded filename always replaces its previous entry (mirroring
    how ingest_files replaces that file's chunks in Chroma)."""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with SessionLocal() as session:
        if mode == "replace":
            session.query(KbDocument).delete()
        else:
            names = [d["filename"] for d in ingested]
            session.query(KbDocument).filter(KbDocument.filename.in_(names)).delete()
        for d in ingested:
            session.add(KbDocument(filename=d["filename"], uploaded_at=now, chunk_count=d["chunk_count"]))
        session.commit()


def clear_kb_documents() -> None:
    with SessionLocal() as session:
        session.query(KbDocument).delete()
        session.commit()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _job_to_dict(job: ProcessingJob) -> dict:
    return {
        "id": job.id,
        "filename": job.filename,
        "status": job.status,
        "error": job.error,
        "call_id": job.call_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def create_job(filename: str) -> dict:
    with SessionLocal() as session:
        job = ProcessingJob(filename=filename, status="queued", created_at=_now(), updated_at=_now())
        session.add(job)
        session.commit()
        return _job_to_dict(job)


def update_job(job_id: int, status: str, error: str | None = None, call_id: str | None = None) -> None:
    with SessionLocal() as session:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            return
        job.status = status
        job.error = error
        job.call_id = call_id
        job.updated_at = _now()
        session.commit()


def list_jobs(finished_limit: int = 20) -> list[dict]:
    """All active jobs plus the most recent finished ones, newest first."""
    with SessionLocal() as session:
        active = (
            session.query(ProcessingJob)
            .filter(ProcessingJob.status.in_(["queued", "processing"]))
            .order_by(ProcessingJob.id.desc())
            .all()
        )
        finished = (
            session.query(ProcessingJob)
            .filter(ProcessingJob.status.in_(["done", "failed"]))
            .order_by(ProcessingJob.id.desc())
            .limit(finished_limit)
            .all()
        )
        return [_job_to_dict(j) for j in active + finished]


def fail_stale_jobs() -> int:
    """Marks jobs left queued/processing by a previous server run as failed."""
    with SessionLocal() as session:
        stale = (
            session.query(ProcessingJob)
            .filter(ProcessingJob.status.in_(["queued", "processing"]))
            .all()
        )
        for job in stale:
            job.status = "failed"
            job.error = "server restarted while job was in progress"
            job.updated_at = _now()
        session.commit()
        return len(stale)
