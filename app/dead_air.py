def detect_dead_air(diarization_segments: list, agent_speaker: str = "SPEAKER_00", threshold: float = 5.0) -> dict:
    """
    Finds gaps > threshold seconds where the agent should have been speaking:
    i.e., after a customer segment ends, before the agent's next segment starts.
    """
    if not diarization_segments:
        return {"total_dead_air_seconds": 0.0, "instances": []}

    segments = sorted(diarization_segments, key=lambda s: s["start"])
    instances = []

    for i in range(len(segments) - 1):
        current = segments[i]
        nxt = segments[i + 1]

        gap = nxt["start"] - current["end"]

        # Dead air = customer finished, agent took too long to respond
        if gap > threshold and current["speaker"] != agent_speaker and nxt["speaker"] == agent_speaker:
            instances.append({
                "start": round(current["end"], 2),
                "end": round(nxt["start"], 2),
                "duration": round(gap, 2)
            })

    total = round(sum(inst["duration"] for inst in instances), 2)

    return {
        "total_dead_air_seconds": total,
        "instances": instances
    }