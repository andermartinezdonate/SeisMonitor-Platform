"""Cloud Run entrypoint for the deduplication service.

Triggered by Cloud Scheduler (every 5 minutes). Reads raw events from BigQuery,
runs DBSCAN clustering, computes quality metrics, and MERGEs into unified_events.
"""

from __future__ import annotations

import asyncio
import logging
import os

from flask import Flask, jsonify

from dedup_pipeline import run_dedup_pipeline

app = Flask(__name__)

from quake_stream.logging_config import configure_logging
configure_logging()

logger = logging.getLogger(__name__)


@app.route("/deduplicate", methods=["POST"])
def deduplicate():
    """Triggered by Cloud Scheduler every 5 minutes."""
    try:
        result = run_dedup_pipeline()
        logger.info("Dedup OK: %s", result)
        return jsonify(result), 200
    except Exception as exc:
        logger.error("Dedup failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "quake-dedup"}), 200


@app.route("/", methods=["GET"])
def root():
    return jsonify({"service": "quake-dedup", "status": "running"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
