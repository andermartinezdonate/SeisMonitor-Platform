# SeisMonitor-Platform

Multi-source earthquake monitoring platform with real-time ingestion from **6 global seismic agencies**: USGS, EMSC (SeismicPortal), GFZ GEOFON, ISC, IPGP, and GeoNet NZ. Events are normalized to a canonical schema, deduplicated using DBSCAN clustering, scored with quality metrics, and visualized in a Streamlit dashboard.

## Architecture

### GCP Serverless (Per-Source Cloud Run)
```
Cloud Scheduler
  ├── ingest-usgs   (every 1 min)  ─┐
  ├── ingest-emsc   (every 2 min)   │
  ├── ingest-gfz    (every 3 min)   ├── BigQuery raw_events
  ├── ingest-isc    (every 5 min)   │
  └── ingest-ipgp   (every 3 min)  ─┘
                                     │
  └── quake-dedup   (every 5 min) ───┤── BigQuery unified_events
                                     │
  └── quake-dashboard ───────────────┘── Streamlit UI
```

### Local (Kafka + PostgreSQL)
```
USGS / EMSC / GFZ / ISC / IPGP / GeoNet
  → Kafka (per-source topics: raw_usgs, raw_emsc, ...)
  → Normalizer → Deduplicator → PostgreSQL
  → Streamlit
```

## Sources

| Source | Coverage | Format | Poll Interval |
|--------|----------|--------|---------------|
| **USGS** | Global (Americas focus) | GeoJSON | 1 min |
| **EMSC** | Euro-Mediterranean | GeoJSON | 2 min |
| **GFZ** | Global (Europe focus) | FDSN Text | 3 min |
| **ISC** | Global (Africa/Asia) | QuakeML | 5 min |
| **IPGP** | French territories | QuakeML | 3 min |
| **GeoNet** | New Zealand/Pacific | QuakeML | 3 min |

## Deduplication

Events from different sources reporting the same earthquake are clustered using **DBSCAN** with haversine metric (100 km spatial threshold). Sub-clustering by time (30s) and magnitude (0.5) separates aftershocks. Region-aware source priority selects the best estimate (e.g., USGS preferred for Americas, EMSC for Europe, ISC for Africa/Asia).

### Quality Metrics
- **magnitude_std** — standard deviation of magnitudes across sources
- **location_spread_km** — max pairwise distance between source locations
- **source_agreement_score** — unique sources / total cluster members

## Quick start — Local

```bash
pip install -e ".[dev]"
docker compose up -d          # Kafka + PostgreSQL

quake init-db-v2              # create multi-source tables
quake multi-produce           # poll all 6 sources → per-source Kafka topics
quake normalize               # raw_{source} topics → normalized_events
quake deduplicate             # normalized → unified_events (DBSCAN)
quake web                     # Streamlit dashboard on :8501
```

## Quick start — GCP

```bash
export GCP_PROJECT_ID=your-project-id
bash gcp/deploy.sh            # deploys per-source ingesters + dedup + dashboard
```

## Dashboard Features

- **Source filtering** — multiselect sidebar to filter by agency
- **Per-source KPI cards** — event counts colored by source
- **Source Coverage tab** — geographic scatter map colored by source
- **Source Comparison tab** — quality metric histograms, multi-source delta table
- **Pipeline Health tab** — per-source status (green/yellow/red), dead letter monitoring
- **Analytics tabs** — frequency, magnitude, depth, regional distribution

## Tests

```bash
pytest -v
```
