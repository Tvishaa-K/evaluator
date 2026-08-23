import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, ForeignKey, ARRAY, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

load_dotenv()

def _normalize_db_url(url: str) -> str:
    """Managed Postgres providers hand out postgres:// or postgresql:// URLs.
    SQLAlchemy 2.0 rejects the first outright, and resolves the second to
    psycopg2 — which we don't install, only psycopg 3. Already-qualified
    postgresql+psycopg:// URLs pass through untouched."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


# pool_pre_ping/pool_recycle: managed Postgres drops idle connections, so
# without these the first request after a quiet period raises.
engine = create_engine(
    _normalize_db_url(os.environ["DATABASE_URL"]),
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Call(Base):
    __tablename__ = "calls"

    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    processed_at: Mapped[str] = mapped_column(String)
    labeled_transcript: Mapped[str] = mapped_column(String)
    detected_language: Mapped[str | None] = mapped_column(String, nullable=True)
    original_transcript: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    dead_air_total_seconds: Mapped[float] = mapped_column()
    diarization_warning: Mapped[str | None] = mapped_column(String, nullable=True)
    composite_score: Mapped[int] = mapped_column()
    max_possible: Mapped[int] = mapped_column()
    critical_failure: Mapped[bool] = mapped_column()
    fraud_flags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    claims_checked: Mapped[int] = mapped_column()

    segments: Mapped[list["CallSegment"]] = relationship(
        back_populates="call", cascade="all, delete-orphan", order_by="CallSegment.ordinal"
    )
    dead_air_instances: Mapped[list["DeadAirInstance"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )
    fact_check_results: Mapped[list["FactCheckResult"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )
    dimension_scores: Mapped[list["DimensionScore"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # queued | processing | done | failed
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)


class KbDocument(Base):
    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String)
    uploaded_at: Mapped[str] = mapped_column(String)
    chunk_count: Mapped[int] = mapped_column()


class CallSegment(Base):
    __tablename__ = "call_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.call_id"))
    ordinal: Mapped[int] = mapped_column()
    start: Mapped[float] = mapped_column()
    end: Mapped[float] = mapped_column()
    speaker: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)

    call: Mapped["Call"] = relationship(back_populates="segments")


class DeadAirInstance(Base):
    __tablename__ = "dead_air_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.call_id"))
    start: Mapped[float] = mapped_column()
    end: Mapped[float] = mapped_column()
    duration: Mapped[float] = mapped_column()

    call: Mapped["Call"] = relationship(back_populates="dead_air_instances")


class FactCheckResult(Base):
    __tablename__ = "fact_check_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.call_id"))
    claim: Mapped[str] = mapped_column(String)
    verdict: Mapped[str] = mapped_column(String)
    explanation: Mapped[str] = mapped_column(String)
    kb_fact: Mapped[str | None] = mapped_column(String, nullable=True)

    call: Mapped["Call"] = relationship(back_populates="fact_check_results")


class DimensionScore(Base):
    __tablename__ = "dimension_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.call_id"))
    dimension_key: Mapped[str] = mapped_column(String)
    score: Mapped[int | None] = mapped_column(nullable=True)
    reasoning: Mapped[str] = mapped_column(String)

    call: Mapped["Call"] = relationship(back_populates="dimension_scores")
