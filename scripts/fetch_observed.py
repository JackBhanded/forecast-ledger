#!/usr/bin/env python3
"""Fetch observed ground truth for a target date (default: yesterday IST).

Ground truth comes from *observation* endpoints, never forecast ones:
  sun     — SWPC observed Kp + GOES X-ray flare list
  weather — Open-Meteo past-days analysis (station-initialized model
            analysis; ERA5 archive refines it later if ever needed)

Writes: docs/data/{domain}/YYYY-MM-DD/observed.json
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


def get_json(url: str, params: dict | None = None):
    r = requests.get(url, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def observe_sun(date: dt.date) -> dict:
    obs: dict = {"date": date.isoformat(), "domain": "sun"}

    # Observed Kp — daily max from the 3-hour bins of the target date.
    kp = get_json(CONFIG["endpoints"]["swpc_kp_observed"])
    header, rows = kp[0], kp[1:]
    day_kps = []
    for row in rows:
        rec = dict(zip(header, row))
        if str(rec["time_tag"]).startswith(date.isoformat()):
            try:
                day_kps.append(float(rec["Kp"] if "Kp" in rec else rec["kp"]))
            except (KeyError, ValueError):
                continue
    obs["kp_daily_max"] = max(day_kps) if day_kps else None
    obs["kp_bins"] = day_kps
    obs["g1plus_storm_occurred"] = (
        max(day_kps) >= CONFIG["scoring"]["storm_kp_threshold"]
        if day_kps else None
    )

    # Observed flares — did an M / X class event begin on the target date?
    try:
        flares = get_json(CONFIG["endpoints"]["swpc_xray_flares_7day"])
        m_hit = x_hit = False
        biggest = None
        for f in flares:
            begin = str(f.get("begin_time") or f.get("time_tag") or "")
            cls = str(f.get("max_class") or f.get("current_class") or "")
            if begin.startswith(date.isoformat()) and cls:
                if cls[0] in "MX":
                    m_hit = True
                if cls[0] == "X":
                    x_hit = True
                if biggest is None or cls > biggest:
                    biggest = cls
        obs["flare_m_occurred"] = m_hit
        obs["flare_x_occurred"] = x_hit
        obs["largest_flare"] = biggest
    except Exception as e:  # noqa: BLE001
        obs["flare_error"] = str(e)

    return obs


def observe_weather(date: dt.date) -> dict:
    obs: dict = {"date": date.isoformat(), "domain": "weather",
                 "locations": {}}
    for loc in CONFIG["locations"]:
        data = get_json(CONFIG["endpoints"]["open_meteo_forecast"], {
            "latitude": loc["latitude"],
            "longitude": loc["longitude"],
            "daily": "precipitation_sum,temperature_2m_max",
            "past_days": 5, "forecast_days": 1,
            "timezone": CONFIG["timezone"],
        })
        daily = data["daily"]
        if date.isoformat() in daily["time"]:
            i = daily["time"].index(date.isoformat())
            precip = daily["precipitation_sum"][i]
            tmax = daily["temperature_2m_max"][i]
            obs["locations"][loc["id"]] = {
                "precipitation_sum_mm": precip,
                "rain_event_occurred": (
                    precip is not None
                    and precip >= CONFIG["scoring"]["precip_event_mm"]
                ),
                "tmax_c": tmax,
            }
    return obs


def main() -> int:
    if len(sys.argv) > 1:
        date = dt.date.fromisoformat(sys.argv[1])
    else:
        date = (dt.datetime.now(ZoneInfo(CONFIG["timezone"]))
                - dt.timedelta(days=1)).date()

    for domain, observe in (("sun", observe_sun),
                            ("weather", observe_weather)):
        try:
            out = observe(date)
            out["fetched_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            day_dir = DATA / domain / date.isoformat()
            day_dir.mkdir(parents=True, exist_ok=True)
            (day_dir / "observed.json").write_text(json.dumps(out, indent=1))
            print(f"[{domain}] observations recorded for {date}")
        except Exception as e:  # noqa: BLE001
            print(f"[{domain}] FAILED for {date}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
