# usgs-quake-stream

## Project overview
Real-time earthquake data pipeline: USGS GeoJSON API → Kafka → consumer display.

## Tech stack
- Python 3.10+, confluent-kafka, httpx, click, rich
- Apache Kafka (KRaft mode, no Zookeeper) via Docker

## Key commands
- `pip install -e ".[dev]"` — install with dev deps
- `docker compose up -d` — start Kafka
- `pytest -v` — run tests
- `quake recent` — fetch earthquakes directly (no Kafka)
- `quake produce` — start Kafka producer
- `quake consume` — start Kafka consumer

## Project structure
- `src/quake_stream/` — main package
  - `models.py` — Earthquake dataclass with JSON serialization
  - `usgs_client.py` — HTTP client for USGS API
  - `producer.py` — Kafka producer
  - `consumer.py` — Kafka consumer
  - `cli.py` — Click CLI entrypoint
- `tests/` — pytest tests (use pytest-httpx for mocking)
- `docker-compose.yml` — Kafka KRaft single-node

## Conventions
- Use `httpx` for HTTP (not requests)
- Use `rich` for terminal output
- Use `click` for CLI
- Kafka topic name: `earthquakes`
