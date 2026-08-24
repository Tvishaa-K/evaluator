import io
import os
import json
from json_repair import repair_json
from pypdf import PdfReader
from dotenv import load_dotenv

from app.llm import chat
from app import repository

load_dotenv()

PARAGRAPH_CHUNK_CHARS = 800

# Fact-checking passes the entire knowledge base into every prompt rather than
# retrieving top-k chunks. Past this size that stops being viable on cost and
# context, and the KB needs real retrieval again — see the kb_too_large warning.
KB_PROMPT_CHAR_LIMIT = 40_000


def _chunk_by_headers(text: str) -> list:
    """Chunks markdown/plain text by ## section headers."""
    chunks = []
    current = []
    for line in text.split("\n"):
        if line.startswith("## ") and current:
            chunks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current).strip())
    return [c for c in chunks if c]


def _chunk_by_paragraphs(text: str, max_chars: int = PARAGRAPH_CHUNK_CHARS) -> list:
    """Groups paragraphs into chunks of at most max_chars."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = ""
    for p in paragraphs:
        if current and len(current) + len(p) + 2 > max_chars:
            chunks.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        chunks.append(current)
    return chunks


def _extract_chunks(filename: str, file_bytes: bytes) -> list:
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(file_bytes))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        return _chunk_by_paragraphs(text)

    text = file_bytes.decode("utf-8", errors="replace")
    if any(line.startswith("## ") for line in text.split("\n")):
        return _chunk_by_headers(text)
    return _chunk_by_paragraphs(text)


def ingest_files(files: list) -> list:
    """Extracts text from (filename, bytes) pairs. Pure — persistence is
    repository.save_kb_documents()'s job, so there is exactly one writer.
    Returns [{"filename": ..., "chunk_count": ..., "content": ...}, ...].

    chunk_count still reflects document structure and drives the KB manager UI;
    it is no longer a retrieval unit."""
    ingested = []
    for filename, file_bytes in files:
        chunks = _extract_chunks(filename, file_bytes)
        ingested.append({
            "filename": filename,
            "chunk_count": len(chunks),
            "content": "\n\n".join(chunks),
        })
    return ingested


def kb_chunk_count() -> int:
    return repository.kb_total_chunks()


def load_knowledge_base() -> str:
    return repository.load_kb_content()


def extract_agent_claims(transcript: str) -> list:
    """Uses the LLM to pull out factual claims the agent made."""
    prompt = f"""From this call transcript, extract every factual claim the AGENT made about rates, fees, charges, timelines, rules, or policies.
Only claims with specific facts (numbers, timeframes, rules). Ignore greetings and questions.

TRANSCRIPT:
{transcript}

Respond with JSON only:
{{"claims": ["<claim 1>", "<claim 2>", ...]}}
If no factual claims, return {{"claims": []}}"""

    raw = chat(prompt)
    parsed = json.loads(repair_json(raw))
    return parsed.get("claims", [])


def fact_check_claims(claims: list, kb_text: str | None = None) -> list:
    """Checks each agent claim against the full knowledge base.

    Passing the whole KB avoids the retrieval misses top-2 search produced: a
    correct claim about the Rs. 500 bounce charge scored not_found because
    similarity surfaced the "EMI Rules" and "Late Payment" sections instead of
    "Charges Summary", where the fee is actually listed."""
    if kb_text is None:
        kb_text = load_knowledge_base()

    results = []

    for claim in claims:
        prompt = f"""KNOWLEDGE BASE:
{kb_text}

AGENT CLAIM: "{claim}"

Does the knowledge base support this claim? Respond with JSON only:
{{"verdict": "correct" | "incorrect" | "not_found", "explanation": "<1 sentence>", "kb_fact": "<the actual fact from KB, or null>"}}"""

        raw = chat(prompt)
        verdict = json.loads(repair_json(raw))
        verdict["claim"] = claim
        results.append(verdict)

    return results


def run_fact_check(transcript: str) -> dict:
    """Full fact-check: extract claims, verify each against the whole KB,
    summarize. The KB is loaded once and reused across claims."""
    kb_text = load_knowledge_base()
    if not kb_text.strip():
        return {"claims_checked": 0, "mismatches": [], "results": [], "warning": "no_knowledge_base"}

    warning = None
    if len(kb_text) > KB_PROMPT_CHAR_LIMIT:
        # Fail loudly rather than silently degrade: the KB has outgrown
        # prompt-stuffing and needs a real vector store again.
        kb_text = kb_text[:KB_PROMPT_CHAR_LIMIT]
        warning = "kb_too_large"

    claims = extract_agent_claims(transcript)

    if not claims:
        result = {"claims_checked": 0, "mismatches": [], "results": []}
        if warning:
            result["warning"] = warning
        return result

    results = fact_check_claims(claims, kb_text)
    mismatches = [r for r in results if r["verdict"] == "incorrect"]

    result = {
        "claims_checked": len(claims),
        "mismatches": mismatches,
        "results": results
    }
    if warning:
        result["warning"] = warning
    return result
