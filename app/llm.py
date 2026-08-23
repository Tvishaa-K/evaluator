import os
import re
import time

from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()

client = SarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY", ""))

MODEL = os.getenv("SARVAM_CHAT_MODEL", "sarvam-105b")

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)

RETRIES = 2
BACKOFF_SECONDS = 3


def chat(prompt: str, system: str | None = None, temperature: float = 0.0) -> str:
    """Single-turn chat against Sarvam. Strips the hybrid-reasoning
    <think> block if the model emits one, so callers get answer text only."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_error = None
    for attempt in range(RETRIES + 1):
        try:
            response = client.chat.completions(
                messages=messages,
                model=MODEL,
                temperature=temperature,
                reasoning_effort="low",
            )
            content = response.choices[0].message.content or ""
            content = THINK_BLOCK.sub("", content).strip()
            # Sarvam occasionally returns an empty completion (e.g. the token
            # budget was consumed by hidden reasoning) — retry instead of
            # handing callers an unparseable empty string.
            if not content:
                raise ValueError("empty completion from Sarvam")
            return content
        except Exception as e:
            last_error = e
            if attempt < RETRIES:
                time.sleep(BACKOFF_SECONDS * (attempt + 1))

    raise last_error
