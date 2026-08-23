"""One-off: generates summaries for calls saved before the summary field existed."""
import sys
sys.path.insert(0, ".")

from app.db import SessionLocal, Call
from app.llm import chat


def summarize(transcript: str) -> str:
    prompt = f"""Summarize this customer support call in 2-3 plain sentences: what the customer called about, what happened, and how it ended. Neutral tone, no scores or jargon. Reply with the summary only.

TRANSCRIPT:
{transcript}"""
    return chat(prompt)


def main():
    with SessionLocal() as session:
        calls = session.query(Call).filter(Call.summary.is_(None)).all()
        print(f"{len(calls)} calls need summaries")
        for call in calls:
            try:
                call.summary = summarize(call.labeled_transcript)
                session.commit()
                print(f"  {call.call_id}: {call.summary[:80]}...")
            except Exception as e:
                session.rollback()
                print(f"  {call.call_id} FAILED: {e}")


if __name__ == "__main__":
    main()
