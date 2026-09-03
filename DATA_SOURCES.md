# Data Sources

Mapped onto the 4-phase agentic flow in [README.md](README.md).

**Status legend:** ✅ verified live & keyless (tested 3 Sep 2026) · 🔑 free key/registration required · ⚠️ unverified

**Working assumption:** the agent serves a *beneficiary-facing* supply chain — a food bank / community
fridge / clinic stockroom — not a generic corporate warehouse. Same architecture, but it answers the
problem statement's "decide who it serves" and "leaves people genuinely better off." Swap the domain
freely; the source list below is mostly domain-agnostic.

---

## PHASE 1 · SENSE

### Tool Call 1 — Primary (live system state)

There is **no public API for a real charity's inventory**, and judges do not expect one. Stand up your
own `GET /inventory` over a seeded Postgres/SQLite table and treat it as the system of record.

What matters for scoring is that the *shape* is credible: `sku, name, category, on_hand, unit,
reorder_point, avg_daily_draw, expiry_date, unit_cost, lead_time_days, preferred_vendor_id`.

Ground the seed in real published numbers so the pitch isn't hand-waving:

| Dataset | ID | Use |
|---|---|---|
| Households Assisted Through ComCare Schemes, Annual | `d_5521441aca9643a2021417e096ea65d0` | Beneficiary population → demand baseline |
| Annual Receipts Of Charities By Sector And Source | `d_524c03c89930eb0c98ce56990904f84a` | Budget ceiling for the approval guardrail |
| Total Donations By Sector, Annual | `d_782fa154f552a3ff9910b76bc06876c9` | Seasonality in incoming supply |
| Local Production, Annual | `d_c02f75e7dd48f2e24f61e007033c28ca` | Local vs import mix |

Fetch any dataset by ID (both routes verified):
```bash
# Route A — JSON rows
curl "https://data.gov.sg/api/action/datastore_search?resource_id=<ID>&limit=100"
# Route B — full CSV via short-lived signed S3 URL
curl "https://api-open.data.gov.sg/v1/public/api/datasets/<ID>/poll-download"
```

Browse all 4,624 datasets: `https://api-production.data.gov.sg/v2/public/api/datasets?page=N` (463 pages).

> **Gotcha:** `poll-download` is **rate-limited** — it returned `429` after a handful of calls in quick
> succession, and the signed S3 URL it hands back expires. Do not call it per-agent-run. Pull each CSV
> once into `data/`, cache it, and have the agent read the cache. `datastore_search` (Route A) is far
> more tolerant and is the better choice for anything on the hot path.

### Tool Call 2 — Context (external variables)

**✅ Commodity prices — the single most valuable feed you have.**
Domestic Supply Price Index, 3-digit commodity group, monthly — `d_20e2fa37d1c8c19357a3f888487ab9f4`

Real Singapore import price indices, **1980 → Jun 2026**, 174 commodity rows including Rice,
Vegetables (fresh & prepared), Fish, Meat & Edible Meat Offal, Fruit & Nuts, Fixed Vegetable Fats &
Oils, Sugars, Coffee, Non-Alcoholic Beverages, Feeding Stuff For Animals.

Verified sample — `Rice`, most recent six months:

| 2026Jan | 2026Feb | 2026Mar | 2026Apr | 2026May | 2026Jun |
|---|---|---|---|---|---|
| 93.829 | 92.859 | 93.701 | 93.49 | 94.57 | 95.706 |

> **Gotcha:** wide format. 631 columns, one per month, ordered **newest-first** (`2026Jun` … `1990Jan`),
> with `DataSeries` as the commodity in column 1. Melt to long before touching it. Some commodity
> labels contain commas and are quoted — use a real CSV parser, not `split(',')`.

This gives the agent a genuine *"rice is up 3.1% over four months, buy now"* signal — that reasoning
step is what separates you from a team that hardcoded a price.

**✅ Weather — keyless, live, Singapore-specific**
```bash
curl "https://api-open.data.gov.sg/v2/real-time/api/twenty-four-hr-forecast"   # regional: north/south/east/west/central
curl "https://api-open.data.gov.sg/v2/real-time/api/rainfall"                  # ~20 stations, 5-min totals, mm
```
Also on the same base: `/two-hr-forecast`, `/air-temperature`, `/relative-humidity`, `/wind-speed`, `/pm25`.

**✅ Weather forecast, keyless, no registration at all** — good fallback / non-SG demo
```bash
curl "https://api.open-meteo.com/v1/forecast?latitude=1.35&longitude=103.82&hourly=temperature_2m,precipitation&forecast_days=3"
curl "https://marine-api.open-meteo.com/v1/marine?latitude=1.26&longitude=103.8&hourly=wave_height&forecast_days=1"
```

**✅ Trade flows — UN Comtrade public preview, keyless**
```bash
# reporterCode 702 = Singapore; flowCode M = imports
curl "https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=702&period=2023&cmdCode=TOTAL&flowCode=M"
```
Swap `cmdCode` for an HS chapter (`10` cereals, `07` vegetables, `03` fish) to source-diversify: if the
agent sees a price spike, it can name *which* origin country the supply normally comes from.

**✅ Macro context — World Bank, keyless**
```bash
curl "https://api.worldbank.org/v2/country/SGP/indicator/NY.GDP.MKTP.CD?format=json&per_page=5"
```

**✅ Humanitarian datasets — HDX/OCHA, keyless**
```bash
curl "https://data.humdata.org/api/3/action/package_search?q=food+security&rows=5"
```

**🔑 Free key required**
- **FRED** — global commodity/PPI series, far better granularity than DSPI. Confirmed it rejects
  keyless requests (`400: Variable api_key is not set`). Key is instant and free:
  https://fred.stlouisfed.org/docs/api/api_key.html
- **LTA DataMall** — live traffic incidents, road speed bands. Relevant if the agent routes a
  *delivery* leg: https://datamall.lta.gov.sg/
- **aisstream.io** — free global AIS over websocket, for port-congestion-driven lead-time slip.
- **ReliefWeb** — now rejects generic appnames (`403 AccessDeniedHttpException`). Request one at
  https://apidoc.reliefweb.int/parameters#appname before relying on it.

**⚠️ GDELT** — news/disruption signal, normally keyless. Connection reset on all three attempts from
this machine; likely local egress rather than an outage. Retry yourself before designing it in:
```bash
curl "https://api.gdeltproject.org/api/v2/doc/doc?query=supply+chain+disruption&mode=artlist&maxrecords=5&format=json"
```

---

## PHASE 2 · PREDICT

No external data. Baselines are **your** constants, and they should be explicit and defensible in the
pitch, because Phase 4 reads them back to the human:

```python
BASELINES = {
    "min_days_cover": 10,
    "monthly_budget_sgd": 5_000,
    "max_single_order_sgd": 1_500,   # above this → mandatory human approval
    "expiry_buffer_days": 14,
}
```

Forecast = `days_cover = on_hand / avg_daily_draw`, adjusted by the price trend from DSPI and any
weather/disruption signal. Keep it simple and legible — the LLM's job is the *plan*, not the
regression. A judge will trust visible arithmetic over an opaque model.

---

## PHASE 3 · ACT & ADAPT

**There is no free real B2B ordering API.** You must mock the vendor layer — every team will, and
that's fine. But make the mock earn its keep:

Build `POST /vendor/{id}/quote` and `POST /vendor/{id}/order` that **deliberately fail** in realistic
ways, because Phase 3's adaptation loop is worth more rubric points than the happy path:

- `409 OUT_OF_STOCK` → agent must fall back to the secondary vendor
- `400 MOQ_NOT_MET` → agent must raise quantity or split the order
- `422 LEAD_TIME_EXCEEDED` → agent must re-plan against the shortfall date
- `429` + `Retry-After` → agent must back off, not crash

Seed the mock's prices from the DSPI index so vendor quotes move with real market data — then a
retry genuinely lands on a different number. That single detail makes the demo look alive.

---

## PHASE 4 · HUMAN APPROVAL

No external data. LangGraph `interrupt()` before any committing call. Two things to get right:

1. **Persist the checkpoint.** Use `SqliteSaver`/`PostgresSaver`, not `MemorySaver` — if the demo
   video shows a reload that preserves a pending approval, that reads as production-grade.
2. **Surface the reasoning trace**, not just the decision. Render what it sensed → what it predicted →
   what it queued → *which adaptations it had to make*. That last line is the whole story of your build.

For the ACT-on-approve side, keep it free and demoable: Gmail API or Resend free tier for the actual
PO email, Slack incoming webhook for the approval card.

---

## Smoke test

`./scripts/check_sources.sh` — verifies every keyless endpoint above still responds.
