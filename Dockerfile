FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations/ migrations/
COPY app/ app/

# Migrations run here rather than in a Render preDeployCommand, which the free
# instance type doesn't support. Safe because of --workers 1 below: one process,
# migrating once, before uvicorn binds the port. `upgrade head` is a no-op when
# the schema is already current, which is every cold start after the first.
#
# --workers 1: the job pool (app/jobs.py) is in-process, so a second worker
# would keep its own executor and its own partial view of queued work.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
