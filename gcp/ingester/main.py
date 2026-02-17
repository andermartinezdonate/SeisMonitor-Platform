"""Cloud Run entrypoint — HTTP handler for scheduled earthquake ingestion.

Supports two modes:
- Per-source: Set SOURCE_NAME env var to run a single-source pipeline (new architecture)
- All-sources: Legacy mode, fetches all sources and deduplicates (deprecated)
"""

from __future__ import annotations

import asyncio
import logging
import os

from flask import Flask, jsonify, request

app = Flask(__name__)

from quake_stream.logging_config import configure_logging
configure_logging()

logger = logging.getLogger(__name__)

# Per-source mode: set by deploy.sh per Cloud Run service
SOURCE_NAME = os.environ.get("SOURCE_NAME", "")


@app.route("/ingest", methods=["POST"])
def ingest():
    """Triggered by Cloud Scheduler."""
    try:
        if SOURCE_NAME:
            # Per-source mode (new architecture)
            from source_pipeline import run_source_pipeline
            result = asyncio.run(run_source_pipeline(SOURCE_NAME))
        else:
            # Legacy all-sources mode (deprecated)
            from pipeline import run_pipeline
            result = asyncio.run(run_pipeline())
        logger.info("Pipeline OK: %s", result)
        return jsonify(result), 200
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.route("/health", methods=["GET"])
def health():
    from datetime import datetime, timezone
    return jsonify({
        "status": "ok",
        "source": SOURCE_NAME or "all",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200


@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "service": f"quake-ingest-{SOURCE_NAME}" if SOURCE_NAME else "quake-ingester",
        "status": "running",
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
