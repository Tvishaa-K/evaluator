"""Regression tests for app.llm.chat().

Covers the failure that took down call3/call4/call5 in production: sarvam-105b
spending its whole completion budget on hidden reasoning and returning empty
content, which surfaced as a bare "empty completion from Sarvam".

Run: venv/bin/python -m unittest discover tests -v
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SARVAM_API_KEY", "test-key-not-used")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import llm  # noqa: E402


def response(content, finish_reason="stop", reasoning=""):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content, reasoning_content=reasoning),
        )]
    )


class ChatTests(unittest.TestCase):

    def test_budget_exhaustion_fails_fast_without_retrying(self):
        """The production bug. Reasoning eats the budget, content comes back
        empty with finish_reason='length'. Retrying is futile — the request is
        deterministic — so chat() must raise on the first attempt."""
        calls = []

        def completions(**kwargs):
            calls.append(kwargs)
            return response(None, finish_reason="length", reasoning="x" * 8155)

        with patch.object(llm.client.chat, "completions", side_effect=completions), \
             patch.object(llm.time, "sleep") as sleep:
            with self.assertRaises(llm.CompletionBudgetExhausted) as ctx:
                llm.chat("score this transcript")

        self.assertEqual(len(calls), 1, "must not retry a deterministic failure")
        sleep.assert_not_called()
        # The message has to name the real cause, not just "empty completion".
        self.assertIn("8155", str(ctx.exception))
        self.assertIn("reasoning", str(ctx.exception))

    def test_default_model_does_not_reason(self):
        """sarvam-105b reasons on every prompt and cannot be told not to
        (reasoning_effort accepts only low/medium/high), so the default must be
        the -conversations variant."""
        self.assertEqual(llm.MODEL, "sarvam-105b-conversations")

    def test_max_tokens_sent_explicitly(self):
        """Pinned in the request so a change to the server-side default can't
        silently reintroduce the truncation."""
        calls = []

        def completions(**kwargs):
            calls.append(kwargs)
            return response('{"ok": true}')

        with patch.object(llm.client.chat, "completions", side_effect=completions):
            llm.chat("hello")

        self.assertEqual(calls[0]["max_tokens"], llm.MAX_TOKENS)
        self.assertEqual(calls[0]["model"], "sarvam-105b-conversations")

    def test_transient_empty_completion_is_retried(self):
        """An empty body with finish_reason='stop' is a different animal — a
        transient blip, worth the existing retry budget."""
        calls = []

        def completions(**kwargs):
            calls.append(kwargs)
            if len(calls) < 3:
                return response("", finish_reason="stop")
            return response('{"recovered": true}')

        with patch.object(llm.client.chat, "completions", side_effect=completions), \
             patch.object(llm.time, "sleep"):
            self.assertEqual(llm.chat("hello"), '{"recovered": true}')

        self.assertEqual(len(calls), 3)

    def test_think_block_stripped(self):
        """Kept as defence in depth: a model that inlines <think> instead of
        using reasoning_content must not leak it to json.loads()."""
        with patch.object(llm.client.chat, "completions",
                          return_value=response('<think>hmm</think>{"a": 1}')):
            self.assertEqual(llm.chat("hello"), '{"a": 1}')


if __name__ == "__main__":
    unittest.main()
