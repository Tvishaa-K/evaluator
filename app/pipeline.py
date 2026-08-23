from app.stt import (
    transcribe_and_diarize,
    determine_agent_speaker,
    is_single_speaker,
    label_segments,
    format_labeled_transcript,
)
from app.translate import is_english, translate_segments
from app.dead_air import detect_dead_air
from app.rag import run_fact_check
from app.score import score_transcript


def run_pipeline(file_bytes: bytes, filename: str) -> dict:
    """Full evaluation pipeline: Deepgram STT+diarization, optional Sarvam
    translation to English, dead-air detection, RAG fact-check, LLM scoring.
    Shared by the /process endpoint and batch.py."""
    stt = transcribe_and_diarize(file_bytes, filename)
    raw_segments = stt["segments"]
    detected_language = stt["detected_language"]

    agent_speaker = determine_agent_speaker(raw_segments)
    labeled_segments = label_segments(raw_segments, agent_speaker)

    original_transcript = None
    if not is_english(detected_language):
        original_transcript = format_labeled_transcript(labeled_segments)
        labeled_segments = translate_segments(labeled_segments, source_language=detected_language)

    labeled_transcript = format_labeled_transcript(labeled_segments)

    dead_air = detect_dead_air(raw_segments, agent_speaker=agent_speaker)

    fact_check = run_fact_check(labeled_transcript)

    evaluation = score_transcript(
        labeled_transcript,
        dead_air_seconds=dead_air["total_dead_air_seconds"],
        fact_check=fact_check,
    )

    return {
        "labeled_transcript": labeled_transcript,
        "segments": labeled_segments,
        "detected_language": detected_language,
        "original_transcript": original_transcript,
        "dead_air": dead_air,
        "fact_check": fact_check,
        "evaluation": evaluation,
        "diarization_warning": "single_speaker_detected" if is_single_speaker(raw_segments) else None,
    }
