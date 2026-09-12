import os
import re
import time

from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()

client = SarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY", ""))

# sarvam-105b-conversations, not sarvam-105b. Both are hybrid reasoning models,
# but only -conversations answers without first emitting a chain of thought.
# On sarvam-105b every structured-output prompt here spent its whole completion
# budget on reasoning and returned nothing: 2048 tokens consumed,
# finish_reason="length", content empty. reasoning_effort has no "off" setting
# (the API accepts only low/medium/high), so the model choice IS the fix.
#
# Measured on the call4 scoring prompt: 449 completion tokens / 21s here,
# versus 6950 tokens / 99s on sarvam-105b once given a budget big enough to
# finish. sarvam-30b and sarvam-m are deprecated and now rejected outright.
MODEL = os.getenv("SARVAM_CHAT_MODEL", "sarvam-105b-conversations")

# Sent explicitly so behaviour doesn't ride on a server-side default (2048 at
# time of writing) that can change under us.
MAX_TOKENS = int(os.getenv("SARVAM_MAX_TOKENS", "4096"))

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)

RETRIES = 2
BACKOFF_SECONDS = 3


class CompletionBudgetExhausted(RuntimeError):
    """The model spent its entire completion budget on hidden reasoning and
    returned no answer text. Deterministic for a given prompt and model, so
    retrying the identical request only burns time and tokens."""


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
                max_tokens=MAX_TOKENS,
            )
            choice = response.choices[0]
            content = choice.message.content or ""
            content = THINK_BLOCK.sub("", content).strip()
            if content:
                return content

            # Reasoning models return their chain of thought in
            # reasoning_content, not inline in content, so an empty content
            # with finish_reason="length" means the trace ate the budget
            # before the answer began. Same prompt, same model, same result:
            # fail loudly instead of retrying twice for nothing.
            if getattr(choice, "finish_reason", None) == "length":
                reasoning = getattr(choice.message, "reasoning_content", None) or ""
                raise CompletionBudgetExhausted(
                    f"{MODEL} produced no answer: the completion budget "
                    f"(max_tokens={MAX_TOKENS}) was consumed by "
                    f"{len(reasoning)} chars of hidden reasoning. Use a "
                    f"non-reasoning model or raise SARVAM_MAX_TOKENS."
                )

            # Genuinely empty for some other reason — that one is worth a retry.
            raise ValueError("empty completion from Sarvam")
        except CompletionBudgetExhausted:
            raise
        except Exception as e:
            last_error = e
            if attempt < RETRIES:
                time.sleep(BACKOFF_SECONDS * (attempt + 1))

    raise last_error
