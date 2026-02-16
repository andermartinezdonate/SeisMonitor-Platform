# usgs-quake-stream

Real-time USGS earthquake data pipeline using Apache Kafka.

## Quick start

```bash
pip install -e ".[dev]"
docker compose up -d
quake recent              # no Kafka needed
quake produce             # start publishing to Kafka
quake consume             # start reading from Kafka
```

## Architecture

- **Producer** polls the USGS GeoJSON feed and publishes events to a Kafka topic.
- **Consumer** reads from Kafka and displays earthquakes in a rich terminal table.
- **CLI** (`quake recent`) fetches directly from USGS for quick inspection.

## Tests

```bash
pytest -v
```
