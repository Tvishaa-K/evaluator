from json_repair import repair_json
import json

from app.llm import chat

SYSTEM_PROMPT = """You are a quality evaluator for AI voice agents deployed in customer support.
You will receive a labeled call transcript and return scores for 8 dimensions.
Respond ONLY with a valid JSON object. No preamble, no explanation outside the JSON."""

DIMENSION_KEYS = {
    "resolution_rate", "compliance", "customer_understanding", "dead_air",
    "fact_checking", "data_confirmation", "interruption_handling", "escalation_analysis"
}

def build_prompt(transcript: str, dead_air_seconds: float = 0.0, fact_check: dict = None) -> str:
    fact_check = fact_check or {}
    claims_checked = fact_check.get("claims_checked", 0)
    kb_mismatches = fact_check.get("mismatches", [])

    if claims_checked == 0:
        kb_section = "No factual claims were made by the agent to check. Score dimension 5 as null."
    elif kb_mismatches:
        kb_section = f"Knowledge base mismatches:\n{json.dumps(kb_mismatches, indent=2)}"
    else:
        kb_section = f"Knowledge base checked: {claims_checked} claim(s) verified, all correct."

    return f"""Evaluate this voice agent call transcript across 8 dimensions.
Each dimension scored out of 10. Return JSON only.

TRANSCRIPT:
{transcript}

ADDITIONAL SIGNALS:
- Agent-side dead air (silences >5s): {dead_air_seconds} seconds total
- {kb_section}

Return exactly this JSON structure:
{{
  "scores": {{
    "resolution_rate":        {{"score": <0-10>, "reasoning": "<1-2 sentences>"}},
    "compliance":             {{"score": <0-10>, "reasoning": "<1-2 sentences>"}},
    "customer_understanding": {{"score": <0-10>, "reasoning": "<1-2 sentences>"}},
    "dead_air":               {{"score": <0-10>, "reasoning": "<1-2 sentences>"}},
    "fact_checking":          {{"score": <0-10 or null>, "reasoning": "<1-2 sentences>"}},
    "data_confirmation":      {{"score": <0-10>, "reasoning": "<1-2 sentences>"}},
    "interruption_handling":  {{"score": <0-10>, "reasoning": "<1-2 sentences>"}},
    "escalation_analysis":    {{"score": <0-10>, "reasoning": "<1-2 sentences>"}}
  }},
  "composite_score": <sum of non-null scores>,
  "summary": "<2-3 plain sentences: what the customer called about, what happened, and how it ended>",
  "fraud_flags": [],
  "critical_failure": false
}}

Scoring guidance:
- resolution_rate: 10 = issue fully resolved, 0 = unresolved
- compliance: check for required disclosures, consent, data handling
- customer_understanding: did agent correctly interpret every request?
- dead_air: 0s = 10, penalize proportionally, >30s = 0
- fact_checking: null only if no factual claims were made to check; otherwise score based on the knowledge base signal above
- data_confirmation: 10 = always confirmed collected data, 10 if no data collected
- interruption_handling: 10 = always stopped and adapted, 0 = ignored interruptions
- escalation_analysis: 10 = no escalation needed or handled perfectly
- summary: neutral, plain language, no scores or jargon — what was the call about and how did it end
- fraud_flags: flag if agent asked for OTP, PIN, CVV, passwords, remote access"""


def score_transcript(transcript: str, dead_air_seconds: float = 0.0, fact_check: dict = None) -> dict:
    fact_check = fact_check or {}
    raw = chat(
        build_prompt(transcript, dead_air_seconds, fact_check),
        system=SYSTEM_PROMPT,
    )
    fixed = repair_json(raw)
    parsed = json.loads(fixed)

    scores = parsed["scores"]

    fraud_flags = parsed.get("fraud_flags", [])
    critical_failure = parsed.get("critical_failure", False)
    summary = parsed.get("summary")

    # Clean up: malformed JSON (e.g. a missing brace) can leave these fields
    # sitting as siblings inside "scores" instead of at the top level.
    for key in list(scores.keys()):
        if key not in DIMENSION_KEYS:
            val = scores.pop(key)
            if key == "fraud_flags":
                fraud_flags = val
            elif key == "critical_failure":
                critical_failure = val
            elif key == "summary":
                summary = val

    # Or nested one level too deep, inside an individual dimension's dict
    for dim in scores.values():
        if not isinstance(dim, dict):
            continue
        if "fraud_flags" in dim:
            fraud_flags = dim.pop("fraud_flags")
        if "critical_failure" in dim:
            critical_failure = dim.pop("critical_failure")
        if "composite_score" in dim:
            dim.pop("composite_score")

    # Compute composite ourselves (ignore null scores)
    composite = sum(d["score"] for d in scores.values() if d.get("score") is not None)

    return {
        "scores": scores,
        "composite_score": composite,
        "max_possible": 80 if fact_check.get("claims_checked", 0) > 0 else 70,
        "summary": summary,
        "fraud_flags": fraud_flags,
        "critical_failure": critical_failure
    }