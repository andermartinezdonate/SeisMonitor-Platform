# SeisMonitor-Platform

## Project overview
Multi-source earthquake monitoring platform: USGS + EMSC + GFZ + ISC + IPGP + GeoNet ingestion, normalization, DBSCAN deduplication with quality metrics. Supports two deployment modes: local (Kafka + PostgreSQL) and GCP serverless (per-source Cloud Run + BigQuery + Cloud Scheduler).

## Tech stack
- Python 3.10+, confluent-kafka, httpx, click, rich, scikit-learn, scipy
- Apache Kafka (KRaft mode, no Zookeeper) via Docker

## Key commands
- `pip install -e ".[dev]"` — install with dev deps
- `docker compose up -d` — start Kafka + PostgreSQL
- `pytest -v` — run tests
- `quake recent` — fetch earthquakes directly (no Kafka)
- `quake produce` — start legacy single-source Kafka producer
- `quake consume` — start Kafka consumer

### Multi-source pipeline (v2)
- `quake init-db-v2` — create multi-source database tables
- `quake multi-produce` — start multi-source Kafka producer (6 sources, per-source topics)
- `quake normalize` — start normalizer (raw_{source} topics → normalized_events)
- `quake deduplicate` — start deduplicator (DBSCAN clustering → unified_events)

## Project structure
- `src/quake_stream/` — main package
  - `models.py` — Legacy Earthquake dataclass
  - `models_v2.py` — NormalizedEvent, UnifiedEvent (with quality metrics), RawEventEnvelope
  - `usgs_client.py` — Legacy HTTP client for USGS API
  - `producer.py` — Legacy single-source Kafka producer
  - `multi_producer.py` — Async multi-source Kafka producer (per-source topics)
  - `normalizer.py` — Kafka consumer: raw_{source} → normalized + validation
  - `deduplicator.py` — DBSCAN clustering + region-aware priority + quality metrics
  - `region_priority.py` — Continent classifier + region-aware source priority
  - `logging_config.py` — Structured JSON logging for Cloud Run
  - `consumer.py` — Kafka consumer (display)
  - `db.py` — PostgreSQL database layer (legacy + v2 functions)
  - `db_consumer.py` — Kafka → PostgreSQL consumer
  - `dashboard_web.py` — Streamlit web dashboard (legacy + unified view toggle)
  - `map_layers.py` — Map rendering (globe + interactive mapbox views)
  - `tectonic.py` — PB2002 tectonic plate data loading/caching
  - `dashboard.py` — Rich terminal dashboard
  - `cli.py` — Click CLI entrypoint
  - `geo.py` — Haversine distance (pure Python)
  - `sources/` — SourceConfig dataclass + SOURCES registry (6 sources)
  - `clients/fdsn_client.py` — Generic async FDSN HTTP client with retry + rate limiting
  - `parsers/` — Event parsers (USGS GeoJSON, EMSC GeoJSON, FDSN text, QuakeML)
  - `migrations/001_multi_source.sql` — DDL for 5 new tables
- `tests/` — pytest tests (use pytest-httpx for mocking)
- `docker-compose.yml` — Kafka KRaft single-node + PostgreSQL

## Kafka topics
- `earthquakes` — legacy single-source USGS events
- `raw_usgs`, `raw_emsc`, `raw_gfz`, `raw_isc`, `raw_ipgp`, `raw_geonet` — per-source raw events

## Database tables
- `earthquakes` — legacy USGS-only events
- `raw_events` — immutable append-only log of raw API responses
- `normalized_events` — per-source cleaned events (canonical schema)
- `unified_events` — deduplicated best-estimate events (with quality metrics)
- `event_crosswalk` — mapping: normalized → unified with match scores
- `dead_letter_events` — events that failed validation

## GCP Serverless Pipeline
- `gcp/` — Cloud Run + BigQuery + Cloud Scheduler deployment
  - `gcp/ingester/` — Flask app: per-source ingestion (SOURCE_NAME env var)
    - `source_pipeline.py` — Single-source fetch → normalize → store raw events
    - `pipeline.py` — Legacy all-source pipeline (deprecated)
  - `gcp/dedup/` — Dedicated dedup Cloud Run service (DBSCAN + quality metrics)
  - `gcp/dashboard/` — Streamlit app with source filtering, coverage, comparison, health tabs
  - `gcp/bigquery/schema.sql` — BigQuery table DDL (with quality metric columns)
  - `gcp/bigquery/migrations/002_quality_metrics.sql` — Migration for quality columns
  - `gcp/deploy.sh` — Per-source deployment (5 ingester services + dedup + dashboard)
- Deploy: `export GCP_PROJECT_ID=your-project && bash gcp/deploy.sh`

## Sources (6 total)
- USGS — Americas focus, GeoJSON, 1 min poll
- EMSC (SeismicPortal) — Euro-Mediterranean, GeoJSON, 2 min poll
- GFZ (GEOFON) — Europe, FDSN text, 3 min poll
- ISC — Global (Africa/Asia), QuakeML, 5 min poll
- IPGP — French territories, QuakeML, 3 min poll
- GeoNet — New Zealand/Pacific, QuakeML, 3 min poll

## Conventions
- Use `httpx` for HTTP (not requests)
- Use `rich` for terminal output
- Use `click` for CLI
- Parsers: USGS GeoJSON, EMSC GeoJSON, FDSN Text, QuakeML (ISC/IPGP/GeoNet)
- Deduplication: DBSCAN with haversine metric, region-aware source priority
- sklearn imported lazily in deduplicator to avoid hard dep for ingester images
