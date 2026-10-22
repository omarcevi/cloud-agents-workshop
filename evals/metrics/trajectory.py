"""Custom metric: were the right tools called with the right arguments?

Every expected call must appear (arguments are a subset match, case-insensitive),
and no forbidden tool may be called. Relative dates in the dataset (@next_friday,
@next_monday) are resolved against today's date in Europe/Istanbul.
Self-contained: agents-cli inlines this file into the grading process.
"""

import datetime as dt
from zoneinfo import ZoneInfo

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4}


def _resolve(value):
    """Return the accepted values for an expected argument."""
    if isinstance(value, str) and value.startswith("@next_"):
        today = dt.datetime.now(ZoneInfo("Europe/Istanbul")).date()
        target = _WEEKDAYS[value.removeprefix("@next_")]
        coming = today + dt.timedelta(days=(target - today.weekday()) % 7 or 7)
        return [coming.isoformat(), (coming + dt.timedelta(days=7)).isoformat()]
    return [value]


def _same(actual, expected):
    return str(actual).strip().lower() in [
        str(v).strip().lower() for v in _resolve(expected)
    ]


def _calls(instance):
    calls = []
    for turn in (instance.get("agent_data") or {}).get("turns") or []:
        for event in turn.get("events") or []:
            for part in (event.get("content") or {}).get("parts") or []:
                call = part.get("function_call")
                if call:
                    calls.append((call.get("name"), call.get("args") or {}))
    return calls


def evaluate(instance):
    calls = _calls(instance)
    expected = instance.get("expected_tool_calls") or []
    forbidden = set(instance.get("forbidden_tools") or [])
    missing = []
    for want in expected:
        args = want.get("args") or {}
        if not any(
            name == want["name"] and all(_same(got.get(k), v) for k, v in args.items())
            for name, got in calls
        ):
            missing.append(
                {
                    "name": want["name"],
                    "args": {k: _resolve(v) for k, v in args.items()},
                }
            )
    used_forbidden = sorted({name for name, _ in calls if name in forbidden})
    found = len(expected) - len(missing)
    score = (found / len(expected) if expected else 1.0) * (
        0.0 if used_forbidden else 1.0
    )
    called = [name for name, _ in calls if name != "transfer_to_agent"]
    return {
        "score": score,
        "explanation": f"called {called}; missing {missing}; forbidden used {used_forbidden}",
    }
