from app.score import DIMENSION_KEYS
from app.repository import list_results

WEAK_THRESHOLD = 6


def load_results() -> list:
    return list_results()


def score_bands(results: list) -> dict:
    bands = {"strong": [], "needs_improvement": [], "at_risk": []}
    critical = []
    unreliable = []

    for r in results:
        ev = r["evaluation"]
        pct = ev["composite_score"] / ev["max_possible"] if ev["max_possible"] else 0
        if pct >= 0.85:
            bands["strong"].append(r["call_id"])
        elif pct >= 0.65:
            bands["needs_improvement"].append(r["call_id"])
        else:
            bands["at_risk"].append(r["call_id"])

        if ev.get("critical_failure"):
            critical.append(r["call_id"])
        if r.get("diarization_warning"):
            unreliable.append(r["call_id"])

    return {
        "bands": {name: {"count": len(ids), "call_ids": ids} for name, ids in bands.items()},
        "critical": {"count": len(critical), "call_ids": critical},
        "unreliable": {"count": len(unreliable), "call_ids": unreliable},
    }


def failure_profile(results: list) -> dict:
    dimensions = {}
    for key in DIMENSION_KEYS:
        scored = [r["evaluation"]["scores"][key]["score"] for r in results
                  if r["evaluation"]["scores"].get(key, {}).get("score") is not None]
        weak_calls = [r["call_id"] for r in results
                      if (s := r["evaluation"]["scores"].get(key, {}).get("score")) is not None and s <= WEAK_THRESHOLD]
        dimensions[key] = {
            "avg_score": round(sum(scored) / len(scored), 2) if scored else None,
            "calls_scored": len(scored),
            "weak_count": len(weak_calls),
            "weak_call_ids": weak_calls,
        }

    fraud_calls = [r["call_id"] for r in results if r["evaluation"].get("fraud_flags")]
    critical_count = sum(1 for r in results if r["evaluation"].get("critical_failure"))

    return {
        "dimensions": dimensions,
        "fraud_flag_count": len(fraud_calls),
        "fraud_flag_call_ids": fraud_calls,
        "critical_failure_count": critical_count,
    }


def fact_error_aggregation(results: list) -> dict:
    total_claims = 0
    verdict_counts = {"correct": 0, "incorrect": 0, "not_found": 0}
    mismatch_by_fact = {}

    for r in results:
        fc = r["fact_check"]
        total_claims += fc["claims_checked"]
        for claim_result in fc.get("results", []):
            verdict = claim_result.get("verdict")
            if verdict in verdict_counts:
                verdict_counts[verdict] += 1
            if verdict == "incorrect":
                fact = claim_result.get("kb_fact") or claim_result.get("claim")
                mismatch_by_fact[fact] = mismatch_by_fact.get(fact, 0) + 1

    top_mismatches = sorted(
        ({"kb_fact": fact, "count": count} for fact, count in mismatch_by_fact.items()),
        key=lambda x: x["count"],
        reverse=True
    )

    total_mismatches = verdict_counts["incorrect"]

    return {
        "total_claims_checked": total_claims,
        "total_mismatches": total_mismatches,
        "mismatch_rate": round(total_mismatches / total_claims, 3) if total_claims else None,
        "verdict_counts": verdict_counts,
        "top_mismatched_facts": top_mismatches,
    }


def resolution_funnel(results: list) -> dict:
    stages = {"resolved": [], "partially_resolved": [], "unresolved": []}

    for r in results:
        score = r["evaluation"]["scores"].get("resolution_rate", {}).get("score")
        if score is None:
            continue
        if score >= 8:
            stages["resolved"].append(r["call_id"])
        elif score >= 5:
            stages["partially_resolved"].append(r["call_id"])
        else:
            stages["unresolved"].append(r["call_id"])

    critical_count = sum(1 for r in results if r["evaluation"].get("critical_failure"))

    return {
        "stages": {name: {"count": len(ids), "call_ids": ids} for name, ids in stages.items()},
        "critical_failure_count": critical_count,
    }


def compute_analytics() -> dict:
    results = load_results()
    return {
        "total_calls": len(results),
        "score_bands": score_bands(results),
        "failure_profile": failure_profile(results),
        "fact_error_aggregation": fact_error_aggregation(results),
        "resolution_funnel": resolution_funnel(results),
    }
