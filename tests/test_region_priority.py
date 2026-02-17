"""Tests for region classification and source priority."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from quake_stream.region_priority import classify_region, get_source_priority
from quake_stream.deduplicator import (
    cluster_events, _compute_quality_metrics, EventRecord, Cluster,
)


# ── Region classification tests ─────────────────────────────────────────


class TestClassifyRegion:
    def test_americas(self):
        # California
        assert classify_region(34.0, -118.0) == "americas"
        # Chile
        assert classify_region(-33.0, -70.5) == "americas"

    def test_europe(self):
        # Paris
        assert classify_region(48.9, 2.3) == "europe"
        # Greece
        assert classify_region(38.0, 23.7) == "europe"

    def test_africa(self):
        # Nairobi
        assert classify_region(-1.3, 36.8) == "africa"
        # Lagos
        assert classify_region(6.5, 3.4) == "africa"

    def test_asia_pacific(self):
        # Tokyo
        assert classify_region(35.7, 139.7) == "asia_pacific"
        # New Zealand
        assert classify_region(-41.3, 174.8) == "asia_pacific"

    def test_global_fallback(self):
        # North Atlantic (between Americas and Europe/Africa)
        region = classify_region(50.0, -25.0)
        assert region in ("americas", "global", "europe")  # boundary region


class TestGetSourcePriority:
    def test_americas_priority(self):
        priority = get_source_priority(34.0, -118.0)
        assert priority[0] == "usgs"  # USGS best for Americas

    def test_europe_priority(self):
        priority = get_source_priority(48.9, 2.3)
        assert priority[0] == "emsc"  # EMSC best for Europe

    def test_africa_priority(self):
        priority = get_source_priority(-1.3, 36.8)
        assert priority[0] == "isc"  # ISC best for Africa

    def test_asia_pacific_priority(self):
        priority = get_source_priority(35.7, 139.7)
        assert priority[0] == "isc"  # ISC best for Asia

    def test_all_sources_present(self):
        """Every priority list should contain all 6 sources."""
        for lat, lon in [(34, -118), (48.9, 2.3), (-1.3, 36.8), (35.7, 139.7)]:
            priority = get_source_priority(lat, lon)
            assert len(priority) == 6
            assert set(priority) == {"usgs", "emsc", "gfz", "isc", "ipgp", "geonet"}


# ── Quality metrics tests ────────────────────────────────────────────────


def _make_record(uid="usgs:a", source="usgs", time_utc=None, lat=35.0, lon=-120.0,
                 depth=10.0, mag=5.0, status="automatic"):
    if time_utc is None:
        time_utc = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    return EventRecord(
        event_uid=uid, source=source, origin_time_utc=time_utc,
        latitude=lat, longitude=lon, depth_km=depth,
        magnitude_value=mag, magnitude_type="mw",
        place=None, region=None, status=status,
    )


class TestQualityMetrics:
    def test_single_source(self):
        cluster = Cluster(members=[_make_record()])
        metrics = _compute_quality_metrics(cluster)
        assert metrics["magnitude_std"] == 0.0
        assert metrics["location_spread_km"] == 0.0
        assert metrics["source_agreement_score"] == 1.0

    def test_three_member_cluster(self):
        t = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        a = _make_record(uid="usgs:eq1", source="usgs", time_utc=t, mag=5.0)
        b = _make_record(uid="emsc:eq1", source="emsc", time_utc=t + timedelta(seconds=5), mag=5.2)
        c = _make_record(uid="gfz:eq1", source="gfz", time_utc=t + timedelta(seconds=8), mag=4.8)
        cluster = Cluster(members=[a, b, c])

        metrics = _compute_quality_metrics(cluster)
        # 3 unique sources / 3 members = 1.0
        assert metrics["source_agreement_score"] == 1.0
        # magnitude_std should be > 0 (different magnitudes)
        assert metrics["magnitude_std"] > 0
        # All at same lat/lon -> spread = 0
        assert metrics["location_spread_km"] == 0.0

    def test_location_spread(self):
        a = _make_record(uid="usgs:eq1", source="usgs", lat=35.0, lon=-120.0)
        b = _make_record(uid="emsc:eq1", source="emsc", lat=35.1, lon=-120.0)
        cluster = Cluster(members=[a, b])

        metrics = _compute_quality_metrics(cluster)
        # ~11 km apart
        assert 10 < metrics["location_spread_km"] < 12

    def test_duplicate_sources(self):
        """Two events from same source should have lower agreement."""
        a = _make_record(uid="usgs:eq1", source="usgs", mag=5.0)
        b = _make_record(uid="usgs:eq2", source="usgs", mag=5.1)
        cluster = Cluster(members=[a, b])

        metrics = _compute_quality_metrics(cluster)
        # 1 unique source / 2 members = 0.5
        assert metrics["source_agreement_score"] == 0.5


# ── DBSCAN clustering tests ─────────────────────────────────────────────


class TestDBSCANClustering:
    def test_two_sources_same_event(self):
        a = _make_record(uid="usgs:eq1", source="usgs")
        b = _make_record(uid="emsc:eq1", source="emsc")
        clusters = cluster_events([a, b])
        assert len(clusters) == 1
        assert len(clusters[0].members) == 2

    def test_two_distinct_events(self):
        a = _make_record(uid="usgs:eq1", source="usgs", lat=35.0, lon=-120.0)
        b = _make_record(
            uid="usgs:eq2", source="usgs", lat=50.0, lon=10.0,
            time_utc=datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
        )
        clusters = cluster_events([a, b])
        assert len(clusters) == 2

    def test_three_sources_one_event(self):
        t = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        a = _make_record(uid="usgs:eq1", source="usgs", time_utc=t)
        b = _make_record(uid="emsc:eq1", source="emsc", time_utc=t + timedelta(seconds=5))
        c = _make_record(uid="gfz:eq1", source="gfz", time_utc=t + timedelta(seconds=8))
        clusters = cluster_events([a, b, c])
        assert len(clusters) == 1
        assert len(clusters[0].members) == 3

    def test_empty_input(self):
        assert cluster_events([]) == []
