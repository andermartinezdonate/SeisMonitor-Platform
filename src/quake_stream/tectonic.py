"""Tectonic plate boundary data from Peter Bird's PB2002 dataset.

Source: Hugo Ahlenius' GeoJSON digitization of PB2002
https://github.com/fraxen/tectonicplates
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import streamlit as st

PLATE_BOUNDARIES_URL = (
    "https://raw.githubusercontent.com/fraxen/tectonicplates/"
    "master/GeoJSON/PB2002_boundaries.json"
)
PLATE_PLATES_URL = (
    "https://raw.githubusercontent.com/fraxen/tectonicplates/"
    "master/GeoJSON/PB2002_plates.json"
)
CACHE_DIR = Path(__file__).parent / ".cache"


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / name


@st.cache_data(ttl=86400)
def load_plate_boundaries() -> dict:
    """Load tectonic plate boundaries as GeoJSON FeatureCollection.

    Downloads from GitHub on first call, then caches locally for 24h.
    """
    cache_file = _cache_path("PB2002_boundaries.json")

    # Try local cache first
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    # Download
    try:
        resp = httpx.get(PLATE_BOUNDARIES_URL, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        geojson = resp.json()
        cache_file.write_text(json.dumps(geojson))
        return geojson
    except Exception:
        # Return empty collection on failure
        return {"type": "FeatureCollection", "features": []}


@st.cache_data(ttl=86400)
def load_plate_polygons() -> dict:
    """Load tectonic plate polygons (filled areas) as GeoJSON."""
    cache_file = _cache_path("PB2002_plates.json")

    if cache_file.exists():
        return json.loads(cache_file.read_text())

    try:
        resp = httpx.get(PLATE_PLATES_URL, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        geojson = resp.json()
        cache_file.write_text(json.dumps(geojson))
        return geojson
    except Exception:
        return {"type": "FeatureCollection", "features": []}


def boundaries_to_traces(geojson: dict) -> list[dict]:
    """Convert GeoJSON boundaries to lists of (lons, lats) for Plotly traces.

    Returns list of dicts with keys 'lon' and 'lat', one per LineString segment.
    Handles both LineString and MultiLineString geometries.
    """
    traces = []
    for feature in geojson.get("features", []):
        geom = feature.get("geometry", {})
        geom_type = geom.get("type")
        coords = geom.get("coordinates", [])

        if geom_type == "LineString":
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            traces.append({"lon": lons, "lat": lats})
        elif geom_type == "MultiLineString":
            for line in coords:
                lons = [c[0] for c in line]
                lats = [c[1] for c in line]
                traces.append({"lon": lons, "lat": lats})

    return traces
