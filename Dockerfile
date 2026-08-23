FROM python:3.12-slim

# Chroma caches its ONNX embedding model under $HOME/.cache/chroma. Pin HOME so
# the model baked in below is still found at runtime.
ENV HOME=/opt/apphome \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake all-MiniLM-L6-v2 into the image. Without this, Chroma pulls an 83MB
# tarball on the first embed of every deploy, stalling the first KB upload.
RUN mkdir -p "$HOME" \
 && python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction; DefaultEmbeddingFunction()(['warmup'])"

COPY alembic.ini .
COPY migrations/ migrations/
COPY app/ app/

# --workers 1 is required: the job pool (app/jobs.py) is in-process, and two
# processes writing Chroma's SQLite file on one disk risks corruption.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
