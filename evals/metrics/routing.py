"""Custom metric: did the expected specialist answer?

agents-cli inlines this file into the grading process, so it must be self-contained
(standard library only) and define evaluate(instance).
"""


def evaluate(instance):
    expected = instance.get("expected_agent")
    if not expected:
        return {"score": 1.0, "explanation": "no expected agent"}
    expected = expected if isinstance(expected, list) else [expected]
    answered_by = None
    for turn in (instance.get("agent_data") or {}).get("turns") or []:
        for event in turn.get("events") or []:
            parts = (event.get("content") or {}).get("parts") or []
            if any(p.get("text") for p in parts) and event.get("author") not in (None, "user"):
                answered_by = event.get("author")
    score = 1.0 if answered_by in expected else 0.0
    return {"score": score, "explanation": f"answered by {answered_by}, expected {expected}"}
