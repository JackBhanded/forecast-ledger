# The Forecast Ledger

**Predictions with receipts.** Every morning at 06:00 IST this repo snapshots
what each forecast source predicts. Every next morning it fetches what
actually happened, stamps each claim **HIT / PARTIAL / MISS**, computes
Brier scores for probabilistic claims, and updates a public scoreboard —
per source, per metric, per lead time. Forever, in git history, where
nobody can quietly edit yesterday.

Read [PLEDGE.md](PLEDGE.md) first. Free forever. No ads, no hooks.

## Domains (day 1)

| Domain  | Predictions tracked | Ground truth |
|---------|--------------------|--------------|
| ☀️ Sun  | NOAA SWPC Kp forecast, G1+ storm calls, M/X flare probabilities | SWPC observed Kp, GOES flare list |
| 🌧️ Weather | ECMWF, GFS, ICON + best-match rain probability & Tmax for Pune and Kalaburagi, 1–3 day leads | Open-Meteo past-days analysis |

The founding motivation is in `docs/data/sun/_seed/` — a hand audit of
August 2026 in which **0 of 9** flagged geomagnetic-storm days verified,
while the month's 2 real storms fell on unflagged days.

## Setup (one time, ~10 minutes)

1. Create a **public** GitHub repo and push these files.
2. Repo **Settings → Pages** → Source: *Deploy from a branch* →
   Branch `main`, folder `/docs`. Save.
3. Repo **Settings → Actions → General** → Workflow permissions →
   **Read and write permissions**. Save.
4. **Actions** tab → *Daily ledger run* → **Run workflow** (first snapshot).
5. Tomorrow it runs itself at 06:00 IST. Day 2 produces the first verdicts.

Local preview of the dashboard: `cd docs && python3 -m http.server`
(fetch() needs http, not file://).

## Anatomy

```
scripts/fetch_predictions.py  # 06:00 IST snapshot — the prediction of record
scripts/fetch_observed.py     # ground truth for a date (default: yesterday)
scripts/score.py              # verdicts + Brier + scoreboard
config/config.json            # locations, models, endpoints, thresholds
docs/index.html               # the public dashboard (GitHub Pages)
docs/data/                    # the ledger itself (CC-BY-4.0)
.github/workflows/daily.yml   # the daily robot
```

## Claim types (the honesty taxonomy)

- **OBSERVED** — already measured when stated
- **WATCH** — an agency alert ("conditions possible"); scored, because
  relaying watches as predictions is how forecasts become gossip
- **MODEL** — a numeric model output (Kp max, Tmax)
- **PROB** — a stated probability; scored with Brier, the metric that
  punishes both overconfidence and cowardice

## Scoring rules (config-driven)

- Kp daily max: HIT within ±1, PARTIAL within ±2
- G1+ storm call: binary — did observed Kp reach 5?
- Flare & rain probabilities: Brier = (p − outcome)²; categorical
  verdict at the 50% line
- Tmax: HIT within ±2 °C, PARTIAL within ±3 °C
- Rain event = ≥1 mm observed

## Extending

Add a domain = one fetch function producing claims with
`{id, source, type, metric, target_date, lead_days, predicted_value|probability}`,
one observe function, one scorer branch. Candidates on the roadmap:
AQI, IMD district bulletins, monsoon onset dates.

## Credits

Space weather: NOAA Space Weather Prediction Center.
Weather: [Open-Meteo.com](https://open-meteo.com) (CC-BY-4.0),
aggregating ECMWF, NOAA, DWD and other national services.
Verification philosophy: Brier (1950), and every farmer who ever
looked at a forecast and asked *"but can I trust it?"*

MIT (code) · CC-BY-4.0 (data)
