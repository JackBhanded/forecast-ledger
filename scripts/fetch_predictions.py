#!/usr/bin/env python3
"""Snapshot today's predictions from every tracked source.

Run once per day at a fixed time (06:00 IST via GitHub Actions).
The timestamped snapshot IS the prediction of record — it is never
edited after the fact. That discipline is the whole project.

Writes: docs/data/sun/YYYY-MM-DD/predictions.json
        docs/data/weather/YYYY-MM-DD/predictions.json
Updates: docs/data/manifest.json
"""
import json
import sys
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config" / "config.json").read_text())
DATA = ROOT / "docs" / "data"
UA = {"User-Agent": "forecast-ledger (open, non-commercial; github)"}


def today_ist() -> dt.date:
    return dt.datetime.now(ZoneInfo(CONFIG["timezone"])).date()


def get_json(url: str, params: dict | None = None):
    r = requests.get(url, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- sun

def fetch_sun_predictions(date: dt.date) -> dict:
    """SWPC's own forecasts, captured verbatim + distilled into claims."""
    claims, raw = [], {}

    # 3-day Kp forecast (list-of-lists; row 0 is the header)
    try:
        kp_fc = get_json(CONFIG["endpoints"]["swpc_kp_forecast"])
        raw["kp_forecast"] = kp_fc
        header, rows = kp_fc[0], kp_fc[1:]
        # Columns: time_tag, kp, observed, noaa_scale — future rows have
        # observed == "predicted" (or "estimated" for the current period).
        by_day: dict[str, list[float]] = {}
        for row in rows:
            rec = dict(zip(header, row))
            if str(rec.get("observed", "")).lower() != "predicted":
                continue
            day = str(rec["time_tag"])[:10]
            by_day.setdefault(day, []).append(float(rec["kp"]))
        for day, kps in sorted(by_day.items()):
            target = dt.date.fromisoformat(day)
            lead = (target - date).days
            if lead < 0:
                continue
            kp_max = max(kps)
            claims.append({
                "id": f"sun-{day}-swpc-kpmax",
                "source": "NOAA_SWPC",
                "type": "MODEL",
                "metric": "kp_daily_max",
                "target_date": day,
                "lead_days": lead,
                "predicted_value": kp_max,
                "statement": f"SWPC predicts daily max Kp {kp_max:.2f} for {day}",
            })
            claims.append({
                "id": f"sun-{day}-swpc-storm",
                "source": "NOAA_SWPC",
                "type": "WATCH" if kp_max >= 5 else "MODEL",
                "metric": "geomagnetic_storm_g1plus",
                "target_date": day,
                "lead_days": lead,
                "predicted_value": kp_max >= 5,
                "statement": (
                    f"SWPC {'predicts' if kp_max >= 5 else 'does not predict'} "
                    f"a G1+ storm (Kp>=5) on {day}"
                ),
            })
    except Exception as e:  # noqa: BLE001 — record the gap, never fake data
        raw["kp_forecast_error"] = str(e)

    # Daily flare probabilities — the calibration goldmine.
    try:
        probs = get_json(CONFIG["endpoints"]["swpc_flare_probabilities"])
        raw["flare_probabilities"] = probs
        if probs:
            p0 = probs[0]  # most recent issuance, day-1 outlook
            target = str(p0.get("date", date.isoformat()))[:10]
            for cls, key in (("M", "m_class_1_day"), ("X", "x_class_1_day")):
                if key in p0 and p0[key] is not None:
                    claims.append({
                        "id": f"sun-{target}-swpc-flare{cls}",
                        "source": "NOAA_SWPC",
                        "type": "PROB",
                        "metric": f"flare_{cls.lower()}_class",
                        "target_date": target,
                        "lead_days": max(
                            (dt.date.fromisoformat(target) - date).days, 0
                        ),
                        "probability": float(p0[key]) / 100.0,
                        "statement": (
                            f"SWPC: {p0[key]}% chance of {cls}-class flare on {target}"
                        ),
                    })
    except Exception as e:  # noqa: BLE001
        raw["flare_probabilities_error"] = str(e)

    # Active watches (verbatim, for the ledger's WATCH hit-rate).
    try:
        alerts = get_json(CONFIG["endpoints"]["swpc_alerts"])
        raw["active_watches"] = [
            a for a in alerts
            if "WATCH" in str(a.get("product_id", "")).upper()
        ][:10]
    except Exception as e:  # noqa: BLE001
        raw["alerts_error"] = str(e)

    return {"date": date.isoformat(), "domain": "sun",
            "snapshot_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "claims": claims, "raw": raw}


# ------------------------------------------------------------- weather

def fetch_weather_predictions(date: dt.date) -> dict:
    """Per-model forecasts for each tracked location, per lead day."""
    claims, raw = [], {}
    for loc in CONFIG["locations"]:
        for model in CONFIG["weather_models"]:
            try:
                data = get_json(CONFIG["endpoints"]["open_meteo_forecast"], {
                    "latitude": loc["latitude"],
                    "longitude": loc["longitude"],
                    "daily": "precipitation_sum,precipitation_probability_max,"
                             "temperature_2m_max,temperature_2m_min",
                    "forecast_days": max(CONFIG["weather_lead_days"]) + 1,
                    "models": model,
                    "timezone": CONFIG["timezone"],
                })
                raw[f"{loc['id']}:{model}"] = data.get("daily", {})
                daily = data["daily"]
                for i, day in enumerate(daily["time"]):
                    lead = (dt.date.fromisoformat(day) - date).days
                    if lead not in CONFIG["weather_lead_days"]:
                        continue
                    base = f"wx-{day}-{loc['id']}-{model}"
                    p = daily.get("precipitation_probability_max", [None])[i]
                    if p is not None:
                        claims.append({
                            "id": f"{base}-rainprob",
                            "source": model, "location": loc["id"],
                            "type": "PROB", "metric": "rain_event",
                            "target_date": day, "lead_days": lead,
                            "probability": float(p) / 100.0,
                            "statement": f"{model}: {p}% rain chance, "
                                         f"{loc['name']}, {day}",
                        })
                    t = daily.get("temperature_2m_max", [None])[i]
                    if t is not None:
                        claims.append({
                            "id": f"{base}-tmax",
                            "source": model, "location": loc["id"],
                            "type": "MODEL", "metric": "tmax_c",
                            "target_date": day, "lead_days": lead,
                            "predicted_value": float(t),
                            "statement": f"{model}: max {t}°C, "
                                         f"{loc['name']}, {day}",
                        })
            except Exception as e:  # noqa: BLE001
                raw[f"{loc['id']}:{model}:error"] = str(e)
    return {"date": date.isoformat(), "domain": "weather",
            "snapshot_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "claims": claims, "raw": raw}


# ------------------------------------------------------------ manifest

def update_manifest(date: dt.date, domains: list[str]) -> None:
    path = DATA / "manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() else {"days": []}
    entry = {"date": date.isoformat(), "domains": domains}
    manifest["days"] = [d for d in manifest["days"]
                        if d["date"] != entry["date"]] + [entry]
    manifest["days"].sort(key=lambda d: d["date"], reverse=True)
    path.write_text(json.dumps(manifest, indent=1))


def main() -> int:
    date = today_ist()
    for domain, fetch in (("sun", fetch_sun_predictions),
                          ("weather", fetch_weather_predictions)):
        out = fetch(date)
        day_dir = DATA / domain / date.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / "predictions.json").write_text(json.dumps(out, indent=1))
        print(f"[{domain}] {len(out['claims'])} claims recorded for {date}")
    update_manifest(date, ["sun", "weather"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
