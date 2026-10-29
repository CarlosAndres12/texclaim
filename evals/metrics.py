"""Per-verdict precision and recall with Wilson 95% intervals (PLAN §14)."""

from __future__ import annotations

import math
from collections import Counter

VERDICTS = ["SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "NOT_FOUND", "UNCHECKABLE"]
FLAGGING = {"CONTRADICTED", "PARTIALLY_SUPPORTED", "NOT_FOUND"}
RELEASE_BAR = {"contradicted_precision": 0.8, "false_alarm_rate": 0.10}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials; (0, 1) when n == 0."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def _ratio(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"value": (k / n) if n else None, "k": k, "n": n, "ci95": [round(lo, 4), round(hi, 4)]}


def evaluate(pairs: list[tuple[str, str]]) -> dict:
    """pairs: (gold label, predicted verdict)."""
    conf: dict[str, Counter] = {g: Counter() for g in VERDICTS}
    for gold, pred in pairs:
        conf[gold][pred] += 1
    per = {}
    for v in VERDICTS:
        tp = conf[v][v]
        predicted = sum(conf[g][v] for g in VERDICTS)
        actual = sum(conf[v].values())
        per[v] = {
            "precision": _ratio(tp, predicted),
            "recall": _ratio(tp, actual),
            "support": actual,
        }
    supported = sum(conf["SUPPORTED"].values())
    false_alarms = sum(conf["SUPPORTED"][v] for v in FLAGGING)
    return {
        "n": len(pairs),
        "confusion": {g: dict(conf[g]) for g in VERDICTS},
        "per_verdict": per,
        "false_alarm_rate": _ratio(false_alarms, supported),
    }


def release_bar(metrics: dict) -> dict:
    """Compare against the v1 bar; numbers are recorded either way."""
    prec = metrics["per_verdict"]["CONTRADICTED"]["precision"]
    fa = metrics["false_alarm_rate"]
    checks = {
        "contradicted_precision": {
            "value": prec["value"], "ci95": prec["ci95"], "n": prec["n"],
            "required": RELEASE_BAR["contradicted_precision"],
            "pass": prec["value"] is not None
            and prec["value"] >= RELEASE_BAR["contradicted_precision"],
        },
        "false_alarm_rate": {
            "value": fa["value"], "ci95": fa["ci95"], "n": fa["n"],
            "required_max": RELEASE_BAR["false_alarm_rate"],
            "pass": fa["value"] is not None and fa["value"] <= RELEASE_BAR["false_alarm_rate"],
        },
    }  # fmt: skip
    return {"checks": checks, "pass": all(c["pass"] for c in checks.values())}
