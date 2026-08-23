import io
import os
import json
import chromadb
from json_repair import repair_json
from pypdf import PdfReader
from dotenv import load_dotenv

from app.llm import chat

load_dotenv()

# Persistent ChromaDB. Defaults to ./chroma_db for local dev; deployments
# point CHROMA_PATH at a mounted disk so the KB survives restarts.
chroma_client = chromadb.PersistentClient(path=os.getenv("CHROMA_PATH", "chroma_db"))

COLLECTION_NAME = "loan_kb"
PARAGRAPH_CHUNK_CHARS = 800


def get_collection():
    return chroma_client.get_or_create_collection(name=COLLECTION_NAME)


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


def ingest_files(files: list, mode: str = "append") -> list:
    """Ingests (filename, bytes) pairs into the KB collection.
    mode="replace" drops the whole collection first. Returns per-file
    chunk counts: [{"filename": ..., "chunk_count": ...}, ...]."""
    if mode == "replace":
        try:
            chroma_client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass

    collection = get_collection()
    ingested = []

    for filename, file_bytes in files:
        chunks = _extract_chunks(filename, file_bytes)
        if not chunks:
            ingested.append({"filename": filename, "chunk_count": 0})
            continue

        # Re-uploading a file replaces its previous chunks
        collection.delete(where={"source": filename})
        collection.upsert(
            ids=[f"{filename}:{i}" for i in range(len(chunks))],
            documents=chunks,
            metadatas=[{"source": filename} for _ in chunks],
        )
        ingested.append({"filename": filename, "chunk_count": len(chunks)})

    return ingested


def clear_knowledge_base():
    try:
        chroma_client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass


def kb_chunk_count() -> int:
    return get_collection().count()


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


def fact_check_claims(claims: list) -> list:
    """Checks each agent claim against the knowledge base."""
    collection = get_collection()
    results = []

    for claim in claims:
        # Retrieve most relevant KB chunks
        query_result = collection.query(query_texts=[claim], n_results=2)
        kb_context = "\n\n".join(query_result["documents"][0])

        prompt = f"""KNOWLEDGE BASE:
{kb_context}

AGENT CLAIM: "{claim}"

Does the knowledge base support this claim? Respond with JSON only:
{{"verdict": "correct" | "incorrect" | "not_found", "explanation": "<1 sentence>", "kb_fact": "<the actual fact from KB, or null>"}}"""

        raw = chat(prompt)
        verdict = json.loads(repair_json(raw))
        verdict["claim"] = claim
        results.append(verdict)

    return results


def run_fact_check(transcript: str) -> dict:
    """Full fact-check: extract claims, verify each, summarize."""
    if kb_chunk_count() == 0:
        return {"claims_checked": 0, "mismatches": [], "results": [], "warning": "no_knowledge_base"}

    claims = extract_agent_claims(transcript)

    if not claims:
        return {"claims_checked": 0, "mismatches": [], "results": []}

    results = fact_check_claims(claims)
    mismatches = [r for r in results if r["verdict"] == "incorrect"]

    return {
        "claims_checked": len(claims),
        "mismatches": mismatches,
        "results": results
    }
