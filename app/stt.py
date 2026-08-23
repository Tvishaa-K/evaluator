import os

from deepgram import DeepgramClient, PrerecordedOptions
from dotenv import load_dotenv

load_dotenv()

client = DeepgramClient(os.getenv("DEEPGRAM_API_KEY", ""))


def transcribe_and_diarize(file_bytes: bytes, filename: str) -> dict:
    """Single Deepgram call returns speaker-labeled, timestamped utterances,
    so no separate diarization/merge step is needed."""
    options = PrerecordedOptions(
        model="nova-3",
        smart_format=True,
        punctuate=True,
        diarize=True,
        utterances=True,
        detect_language=True,
    )

    response = client.listen.rest.v("1").transcribe_file(
        {"buffer": file_bytes}, options, timeout=300
    )
    results = response.results

    segments = [
        {
            "start": round(u.start, 2),
            "end": round(u.end, 2),
            "speaker": f"SPEAKER_{u.speaker:02d}",
            "text": u.transcript.strip(),
        }
        for u in (results.utterances or [])
    ]

    detected_language = "en"
    if results.channels:
        detected_language = getattr(results.channels[0], "detected_language", None) or "en"

    return {"segments": segments, "detected_language": detected_language}


def determine_agent_speaker(segments: list, min_duration: float = 1.0) -> str:
    """Raw diarization speaker labels (SPEAKER_00, SPEAKER_01, ...) are arbitrary
    per file, not stable identities. In this inbound call-center context the
    agent always greets the caller first, so whoever speaks first is the agent.
    Sub-second blips (breath/noise misclassified as a distinct speaker turn)
    are ignored so they don't get mistaken for the opening greeting."""
    real_segments = [s for s in segments if s["end"] - s["start"] >= min_duration]
    candidates = real_segments or segments
    return min(candidates, key=lambda s: s["start"])["speaker"]


def is_single_speaker(segments: list, min_duration: float = 1.0) -> bool:
    """A speaker whose only appearances are sub-second blips (diarization noise)
    doesn't count as a real second speaker for this check."""
    real_segments = [s for s in segments if s["end"] - s["start"] >= min_duration]
    return len({s["speaker"] for s in real_segments}) < 2


def label_segments(segments: list, agent_speaker: str) -> list:
    return [
        {
            "start": s["start"],
            "end": s["end"],
            "speaker": "AGENT" if s["speaker"] == agent_speaker else "CUSTOMER",
            "text": s["text"],
        }
        for s in segments
    ]


def format_labeled_transcript(labeled_segments: list) -> str:
    lines = []
    for seg in labeled_segments:
        lines.append(f"[{seg['speaker']}]: {seg['text']}")
    return "\n".join(lines)
