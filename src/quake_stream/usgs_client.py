"""HTTP client for the USGS Earthquake Hazards API."""

from __future__ import annotations

import httpx

from quake_stream.models import Earthquake

BASE_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary"

FEEDS = {
    "hour": f"{BASE_URL}/all_hour.geojson",
    "day": f"{BASE_URL}/all_day.geojson",
    "week": f"{BASE_URL}/all_week.geojson",
    "significant": f"{BASE_URL}/significant_month.geojson",
}


def fetch_earthquakes(period: str = "hour", min_magnitude: float = 0.0) -> list[Earthquake]:
    """Fetch recent earthquakes from USGS GeoJSON feed.

    Args:
        period: One of 'hour', 'day', 'week', 'significant'.
        min_magnitude: Filter quakes below this magnitude.

    Returns:
        List of Earthquake objects sorted by time descending.
    """
    url = FEEDS.get(period)
    if url is None:
        raise ValueError(f"Unknown period '{period}'. Choose from: {list(FEEDS.keys())}")

    resp = httpx.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    quakes = [
        Earthquake.from_geojson_feature(f)
        for f in data["features"]
    ]

    if min_magnitude > 0:
        quakes = [q for q in quakes if q.magnitude >= min_magnitude]

    return sorted(quakes, key=lambda q: q.time, reverse=True)
