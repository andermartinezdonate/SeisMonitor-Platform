"""Single-source pipeline: fetch -> normalize -> validate -> store raw events.

Each per-source Cloud Run service runs this pipeline for exactly one source.
Deduplication is handled by the separate dedup service.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta

import httpx

from quake_stream.models_v2 import NormalizedEvent
from quake_stream.parsers import PARSER_MAP
from quake_stream.parsers.base import EventParser
from quake_stream.sources import SOURCES

from bq_client import (
    insert_raw_events,
    insert_dead_letter,
    log_pipeline_run,
)

logger = logging.getLogger(__name__)

# FDSN format parameter per source
FORMAT_MAP = {
    "usgs": "geojson",
    "emsc": "json",
    "gfz": "text",
    "isc": "xml",
    "ipgp": "xml",
    "geonet": "xml",
}

LOOKBACK_MINUTES = 10


async def _fetch_source(
    client: httpx.AsyncClient,
    name: str,
    start: datetime,
    end: datetime,
) -> str:
    """Fetch events from one FDSN source with retry."""
    config = SOURCES[name]
    params = {
        "format": FORMAT_MAP.get(name, "xml"),
        "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime": end.strftime("%Y-%m-%dT%H:%M:%S"),
        "minmagnitude": "0.0",
        "orderby": "time",
    }

    last_exc: Exception | None = None
    for attempt in range(config.max_retries + 1):
        try:
            resp = await client.get(
                config.base_url,
                params=params,
                timeout=config.timeout_seconds,
            )
            if resp.status_code == 204:
                return ""
            resp.raise_for_status()
            return resp.text
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            last_exc = exc
            if attempt < config.max_retries:
                backoff = config.retry_backoff_base ** attempt
                logger.warning(
                    "[%s] attempt %d/%d failed: %s — retrying in %.1fs",
                    name, attempt + 1, config.max_retries + 1, exc, backoff,
                )
                await asyncio.sleep(backoff)

    raise RuntimeError(f"[{name}] all attempts failed") from last_exc


async def run_source_pipeline(source_name: str) -> dict:
    """Execute one fetch-normalize-store cycle for a single source.

    Does NOT run deduplication — that is handled by the dedup service.
    """
    run_id = str(uuid.uuid4())[:8]
    t0 = time.monotonic()
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=LOOKBACK_MINUTES)

    logger.info("[%s][%s] Source pipeline starting — window %s to %s",
                run_id, source_name, start, now)

    if source_name not in SOURCES:
        raise ValueError(f"Unknown source: {source_name}")

    # Fetch
    async with httpx.AsyncClient() as client:
        raw_text = await _fetch_source(client, source_name, start, now)

    if not raw_text.strip():
        result = {
            "run_id": run_id,
            "source": source_name,
            "raw_events": 0,
            "dead_letters": 0,
            "duration_s": round(time.monotonic() - t0, 2),
        }
        log_pipeline_run(
            run_id, now, "ok", [source_name], 0, 0, 0, None,
            time.monotonic() - t0, source_name=source_name,
        )
        return result

    # Parse + normalize + validate
    fetched_at = now
    parser = PARSER_MAP.get(source_name)
    if parser is None:
        raise ValueError(f"No parser registered for source: {source_name}")

    all_events: list[NormalizedEvent] = []
    dead_letters: list[dict] = []

    try:
        events = parser.parse(raw_text, fetched_at)
    except Exception as exc:
        logger.error("[%s] parse error: %s", source_name, exc)
        dead_letters.append({
            "source": source_name,
            "source_event_id": None,
            "raw_payload": raw_text[:10000],
            "errors": [f"Parse error: {exc}"],
        })
        events = []

    for event in events:
        errors = EventParser.validate(event)
        if errors:
            dead_letters.append({
                "source": source_name,
                "source_event_id": event.source_event_id,
                "raw_payload": event.raw_payload[:5000] if event.raw_payload else "",
                "errors": errors,
            })
        else:
            all_events.append(event)

    logger.info("[%s][%s] Parsed %d events (%d dead-lettered)",
                run_id, source_name, len(all_events), len(dead_letters))

    # Write raw events to BigQuery (append-only)
    raw_count = 0
    if all_events:
        raw_count = insert_raw_events(all_events)

    # Write dead letters
    if dead_letters:
        insert_dead_letter(dead_letters)

    duration = time.monotonic() - t0
    result = {
        "run_id": run_id,
        "source": source_name,
        "raw_events": raw_count,
        "dead_letters": len(dead_letters),
        "duration_s": round(duration, 2),
    }

    log_pipeline_run(
        run_id, now, "ok", [source_name],
        raw_count, 0, len(dead_letters), None, duration,
        source_name=source_name,
    )

    logger.info("[%s][%s] Source pipeline complete in %.1fs: %s",
                run_id, source_name, duration, result)
    return result
