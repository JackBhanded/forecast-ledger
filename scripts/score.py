#!/usr/bin/env python3
"""Score predictions against observations for a target date.

For each claim whose target_date matches, produce a verdict:
  HIT / PARTIAL / MISS   — categorical accuracy
  brier                  — (probability - outcome)^2 for PROB claims;
                           lower is better, 0.25 = coin-flip on a 50% call

Verdicts are appended to docs/data/{domain}/{date}/scores.json and the
running scoreboard (docs/data/scoreboard.json) is updated per
source × metric × lead_days — the calibration record the whole
project exists to build.

Scans ALL prediction days for claims targeting the given date, so
1-, 2- and 3-day-lead claims all get verified when their day arrives.
"""
import json
import sys
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config" / "config.json").read_text())
DATA = ROOT / "docs" / "data"
S = CONFIG["scoring"]


def verdict_from_delta(delta: float, hit_tol: float, part_tol: float) -> str:
    if delta <= hit_tol:
        return "HIT"
    if delta <= part_tol:
        return "PARTIAL"
    return "MISS"


def score_claim(claim: dict, obs: dict) -> dict | None:
    """Return a score record, or None if the observation can't settle it."""
    m = claim["metric"]
    out = {"claim_id": claim["id"], "source": claim["source"],
           "metric": m, "lead_days": claim.get("lead_days"),
           "type": claim["type"], "statement": claim["statement"]}

    if m == "kp_daily_max":
        actual = obs.get("kp_daily_max")
        if actual is None:
            return None
        delta = abs(claim["predicted_value"] - actual)
        out.update(observed_value=actual,
                   verdict=verdict_from_delta(
                       delta, S["kp_hit_tolerance"], S["kp_partial_tolerance"]))

    elif m == "geomagnetic_storm_g1plus":
        actual = obs.get("g1plus_storm_occurred")
        if actual is None:
            return None
        out.update(observed_value=actual,
                   verdict="HIT" if claim["predicted_value"] == actual
                   else "MISS")

    elif m in ("flare_m_class", "flare_x_class"):
        key = ("flare_m_occurred" if m == "flare_m_class"
               else "flare_x_occurred")
        actual = obs.get(key)
        if actual is None:
            return None
        p = claim["probability"]
        out.update(observed_value=actual,
                   brier=round((p - (1.0 if actual else 0.0)) ** 2, 4),
                   verdict="HIT" if (p >= 0.5) == actual else "MISS")

    elif m == "rain_event":
        loc = obs.get("locations", {}).get(claim.get("location", ""), {})
        actual = loc.get("rain_event_occurred")
        if actual is None:
            return None
        p = claim["probability"]
        out.update(observed_value=actual,
                   observed_mm=loc.get("precipitation_sum_mm"),
                   brier=round((p - (1.0 if actual else 0.0)) ** 2, 4),
                   verdict="HIT" if (p >= 0.5) == actual else "MISS")

    elif m == "tmax_c":
        loc = obs.get("locations", {}).get(claim.get("location", ""), {})
        actual = loc.get("tmax_c")
        if actual is None:
            return None
        delta = abs(claim["predicted_value"] - actual)
        out.update(observed_value=actual,
                   verdict=verdict_from_delta(
                       delta, S["tmax_hit_tolerance_c"],
                       S["tmax_partial_tolerance_c"]))
    else:
        return None
    return out


def collect_claims_for(domain: str, target: str) -> list[dict]:
    """Every claim from any snapshot day that targets `target`."""
    claims = []
    root = DATA / domain
    if not root.is_dir():
        return claims
    for day_dir in sorted(root.iterdir()):
        pred = day_dir / "predictions.json"
        if not pred.is_file():
            continue
        for c in json.loads(pred.read_text()).get("claims", []):
            if c.get("target_date") == target:
                claims.append(c)
    return claims


def update_scoreboard(scores: list[dict]) -> None:
    path = DATA / "scoreboard.json"
    board = json.loads(path.read_text()) if path.exists() else {}
    for s in scores:
        key = f"{s['source']}|{s['metric']}|lead{s['lead_days']}"
        row = board.setdefault(key, {
            "source": s["source"], "metric": s["metric"],
            "lead_days": s["lead_days"],
            "n": 0, "hits": 0, "partials": 0, "misses": 0,
            "brier_sum": 0.0, "brier_n": 0,
        })
        row["n"] += 1
        row[{"HIT": "hits", "PARTIAL": "partials",
             "MISS": "misses"}[s["verdict"]]] += 1
        if "brier" in s:
            row["brier_sum"] = round(row["brier_sum"] + s["brier"], 4)
            row["brier_n"] += 1
    for row in board.values():
        row["hit_rate"] = round(row["hits"] / row["n"], 3) if row["n"] else None
        row["mean_brier"] = (round(row["brier_sum"] / row["brier_n"], 4)
                             if row["brier_n"] else None)
    board_sorted = dict(sorted(board.items()))
    path.write_text(json.dumps(board_sorted, indent=1))


def main() -> int:
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        target = ((dt.datetime.now(ZoneInfo(CONFIG["timezone"]))
                   - dt.timedelta(days=1)).date().isoformat())

    all_scores = []
    for domain in ("sun", "weather"):
        obs_path = DATA / domain / target / "observed.json"
        if not obs_path.is_file():
            print(f"[{domain}] no observations for {target}; skipping")
            continue
        obs = json.loads(obs_path.read_text())
        scores = [s for c in collect_claims_for(domain, target)
                  if (s := score_claim(c, obs))]
        (DATA / domain / target / "scores.json").write_text(
            json.dumps({"date": target, "scores": scores}, indent=1))
        hits = sum(1 for s in scores if s["verdict"] == "HIT")
        print(f"[{domain}] {target}: {hits}/{len(scores)} HIT")
        all_scores.extend(scores)

    if all_scores:
        update_scoreboard(all_scores)
        print(f"scoreboard updated with {len(all_scores)} verdicts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
