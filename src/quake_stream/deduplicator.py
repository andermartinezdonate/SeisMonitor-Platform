"""Periodic batch deduplicator for earthquake events.

Runs every N minutes, queries normalized_events, clusters events that represent
the same physical earthquake, and writes unified_events + event_crosswalk.

Uses DBSCAN for spatial clustering with haversine metric, then sub-clusters
by time and magnitude to separate aftershocks at the same location.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from quake_stream.geo import haversine_km
from quake_stream.region_priority import get_source_priority

logger = logging.getLogger(__name__)

# Matching thresholds
MAX_TIME_DIFF_SEC = 30.0
MAX_DISTANCE_KM = 100.0
MAX_MAG_DIFF = 0.5
MATCH_SCORE_THRESHOLD = 0.6


@dataclass
class EventRecord:
    """Lightweight record for clustering (loaded from normalized_events)."""
    event_uid: str
    source: str
    origin_time_utc: datetime
    latitude: float
    longitude: float
    depth_km: float
    magnitude_value: float
    magnitude_type: str
    place: str | None
    region: str | None
    status: str


@dataclass
class Cluster:
    """Group of events representing the same physical earthquake."""
    members: list[EventRecord]
    best_score: float = 0.0

    @property
    def anchor(self) -> EventRecord:
        return self.members[0]


def compute_match_score(a: EventRecord, b: EventRecord) -> float:
    """Compute similarity score between two events (0 -> 1)."""
    dt = abs((a.origin_time_utc - b.origin_time_utc).total_seconds())
    if dt > MAX_TIME_DIFF_SEC:
        return 0.0

    dist = haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)
    if dist > MAX_DISTANCE_KM:
        return 0.0

    dmag = abs(a.magnitude_value - b.magnitude_value)
    if dmag > MAX_MAG_DIFF:
        return 0.0

    score = (
        0.4 * max(0.0, 1.0 - dt / MAX_TIME_DIFF_SEC)
        + 0.4 * max(0.0, 1.0 - dist / MAX_DISTANCE_KM)
        + 0.2 * max(0.0, 1.0 - dmag / MAX_MAG_DIFF)
    )
    return score


def cluster_events(events: list[EventRecord]) -> list[Cluster]:
    """DBSCAN-based clustering with haversine metric.

    1. Build numpy array of [lat_rad, lon_rad]
    2. Run DBSCAN(eps=100km in radians, min_samples=1, metric='haversine')
    3. Group by spatial cluster label
    4. Sub-cluster within each spatial group by time (30s) and magnitude (0.5)
    """
    if not events:
        return []

    # Lazy import to avoid making sklearn a hard dependency for ingester images
    try:
        import numpy as np
        from sklearn.cluster import DBSCAN
    except ImportError:
        logger.warning("scikit-learn not available, falling back to greedy clustering")
        return _cluster_events_greedy(events)

    events_sorted = sorted(events, key=lambda e: e.origin_time_utc)

    # Build coordinate array in radians for haversine metric
    coords = np.array([
        [math.radians(e.latitude), math.radians(e.longitude)]
        for e in events_sorted
    ])

    # DBSCAN: eps = 100km / Earth radius in radians
    eps_rad = MAX_DISTANCE_KM / 6371.0
    db = DBSCAN(eps=eps_rad, min_samples=1, metric="haversine")
    spatial_labels = db.fit_predict(coords)

    # Group by spatial cluster
    spatial_groups: dict[int, list[EventRecord]] = {}
    for label, event in zip(spatial_labels, events_sorted):
        spatial_groups.setdefault(label, []).append(event)

    # Sub-cluster within each spatial group by time and magnitude
    clusters: list[Cluster] = []
    for members in spatial_groups.values():
        sub_clusters = _sub_cluster_time_mag(members)
        clusters.extend(sub_clusters)

    return clusters


def _sub_cluster_time_mag(events: list[EventRecord]) -> list[Cluster]:
    """Sub-cluster spatially co-located events by time and magnitude.

    Handles aftershocks at the same location that should be separate clusters.
    Uses greedy chronological assignment within the spatial group.
    """
    events_sorted = sorted(events, key=lambda e: e.origin_time_utc)
    clusters: list[Cluster] = []

    for event in events_sorted:
        best_cluster: Cluster | None = None
        best_score = 0.0

        for cluster in clusters:
            anchor = cluster.anchor
            dt = abs((event.origin_time_utc - anchor.origin_time_utc).total_seconds())
            dmag = abs(event.magnitude_value - anchor.magnitude_value)

            if dt <= MAX_TIME_DIFF_SEC and dmag <= MAX_MAG_DIFF:
                score = compute_match_score(event, anchor)
                if score >= MATCH_SCORE_THRESHOLD and score > best_score:
                    best_cluster = cluster
                    best_score = score

        if best_cluster is not None:
            best_cluster.members.append(event)
            best_cluster.best_score = max(best_cluster.best_score, best_score)
        else:
            clusters.append(Cluster(members=[event]))

    return clusters


def _cluster_events_greedy(events: list[EventRecord]) -> list[Cluster]:
    """Greedy chronological clustering (fallback when sklearn unavailable).

    Each event either joins the best-scoring existing cluster or starts a new one.
    """
    events_sorted = sorted(events, key=lambda e: e.origin_time_utc)
    clusters: list[Cluster] = []

    for event in events_sorted:
        best_cluster: Cluster | None = None
        best_score = 0.0

        for cluster in clusters:
            score = compute_match_score(event, cluster.anchor)
            if score >= MATCH_SCORE_THRESHOLD and score > best_score:
                best_cluster = cluster
                best_score = score

        if best_cluster is not None:
            best_cluster.members.append(event)
            best_cluster.best_score = max(best_cluster.best_score, best_score)
        else:
            clusters.append(Cluster(members=[event]))

    return clusters


def _select_preferred(cluster: Cluster) -> EventRecord:
    """Select the preferred event from a cluster.

    Priority: reviewed > automatic. Among same status, use region-aware source priority.
    """
    reviewed = [m for m in cluster.members if m.status == "reviewed"]
    candidates = reviewed if reviewed else cluster.members

    # Use region-aware priority based on cluster centroid
    avg_lat = sum(m.latitude for m in cluster.members) / len(cluster.members)
    avg_lon = sum(m.longitude for m in cluster.members) / len(cluster.members)
    priority = get_source_priority(avg_lat, avg_lon)

    def source_rank(e: EventRecord) -> int:
        try:
            return priority.index(e.source)
        except ValueError:
            return len(priority)

    return min(candidates, key=source_rank)


def _compute_unified_id(cluster: Cluster) -> str:
    """Generate a stable unified event ID from cluster members."""
    uids = sorted(m.event_uid for m in cluster.members)
    content = "|".join(uids)
    return "UE-" + hashlib.sha256(content.encode()).hexdigest()[:16]


def _weighted_mean(cluster: Cluster) -> tuple[float, float, float]:
    """Compute weighted mean lat/lon/depth. Region-aware source priority = weight."""
    avg_lat = sum(m.latitude for m in cluster.members) / len(cluster.members)
    avg_lon = sum(m.longitude for m in cluster.members) / len(cluster.members)
    priority = get_source_priority(avg_lat, avg_lon)

    total_weight = 0.0
    lat_sum = lon_sum = depth_sum = 0.0

    for member in cluster.members:
        try:
            rank = priority.index(member.source)
        except ValueError:
            rank = len(priority)
        weight = max(1.0, len(priority) - rank)

        lat_sum += member.latitude * weight
        lon_sum += member.longitude * weight
        depth_sum += member.depth_km * weight
        total_weight += weight

    if total_weight == 0:
        m = cluster.anchor
        return m.latitude, m.longitude, m.depth_km

    return lat_sum / total_weight, lon_sum / total_weight, depth_sum / total_weight


def _compute_quality_metrics(cluster: Cluster) -> dict:
    """Compute quality metrics for a cluster.

    Returns:
        magnitude_std: Standard deviation of magnitudes across sources.
        location_spread_km: Maximum pairwise haversine distance in cluster.
        source_agreement_score: Fraction of unique sources vs total members.
    """
    members = cluster.members

    # Magnitude std
    if len(members) > 1:
        mags = [m.magnitude_value for m in members]
        mean_mag = sum(mags) / len(mags)
        variance = sum((m - mean_mag) ** 2 for m in mags) / len(mags)
        magnitude_std = variance ** 0.5
    else:
        magnitude_std = 0.0

    # Location spread: max pairwise distance
    location_spread_km = 0.0
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            dist = haversine_km(
                members[i].latitude, members[i].longitude,
                members[j].latitude, members[j].longitude,
            )
            location_spread_km = max(location_spread_km, dist)

    # Source agreement
    unique_sources = len(set(m.source for m in members))
    source_agreement_score = unique_sources / len(members) if members else 0.0

    return {
        "magnitude_std": round(magnitude_std, 4),
        "location_spread_km": round(location_spread_km, 2),
        "source_agreement_score": round(source_agreement_score, 4),
    }


def run_deduplicator(
    interval_seconds: int = 300,
    lookback_hours: int = 6,
) -> None:
    """Periodically cluster normalized events and write unified events."""
    import click
    click.echo(
        f"Deduplicator started — running every {interval_seconds}s, "
        f"looking back {lookback_hours}h"
    )

    while True:
        try:
            _run_dedup_cycle(lookback_hours)
        except Exception as exc:
            logger.error("Dedup cycle error: %s", exc)

        time.sleep(interval_seconds)


def _run_dedup_cycle(lookback_hours: int) -> None:
    """Single deduplication cycle."""
    import click
    from quake_stream.db import get_connection
    conn = get_connection()

    # Load normalized events from the lookback window
    with conn.cursor() as cur:
        cur.execute("""
            SELECT event_uid, source, origin_time_utc, latitude, longitude,
                   depth_km, magnitude_value, magnitude_type, place, region, status
            FROM normalized_events
            WHERE origin_time_utc >= NOW() - INTERVAL '%s hours'
            ORDER BY origin_time_utc
        """, (lookback_hours,))
        rows = cur.fetchall()

    if not rows:
        return

    events = [
        EventRecord(
            event_uid=r[0], source=r[1],
            origin_time_utc=r[2] if r[2].tzinfo else r[2].replace(tzinfo=timezone.utc),
            latitude=r[3], longitude=r[4], depth_km=r[5],
            magnitude_value=r[6], magnitude_type=r[7],
            place=r[8], region=r[9], status=r[10],
        )
        for r in rows
    ]

    clusters = cluster_events(events)

    # Write unified events and crosswalk
    with conn.cursor() as cur:
        for cluster in clusters:
            preferred = _select_preferred(cluster)
            unified_id = _compute_unified_id(cluster)
            lat, lon, depth = _weighted_mean(cluster)
            metrics = _compute_quality_metrics(cluster)

            # Upsert unified event
            cur.execute("""
                INSERT INTO unified_events (
                    unified_event_id, origin_time_utc, latitude, longitude, depth_km,
                    magnitude_value, magnitude_type, place, region, status,
                    num_sources, preferred_source, preferred_event_uid,
                    magnitude_std, location_spread_km, source_agreement_score,
                    updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (unified_event_id) DO UPDATE SET
                    origin_time_utc = EXCLUDED.origin_time_utc,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    depth_km = EXCLUDED.depth_km,
                    magnitude_value = EXCLUDED.magnitude_value,
                    magnitude_type = EXCLUDED.magnitude_type,
                    place = EXCLUDED.place,
                    region = EXCLUDED.region,
                    status = EXCLUDED.status,
                    num_sources = EXCLUDED.num_sources,
                    preferred_source = EXCLUDED.preferred_source,
                    preferred_event_uid = EXCLUDED.preferred_event_uid,
                    magnitude_std = EXCLUDED.magnitude_std,
                    location_spread_km = EXCLUDED.location_spread_km,
                    source_agreement_score = EXCLUDED.source_agreement_score,
                    updated_at = NOW()
            """, (
                unified_id, preferred.origin_time_utc, lat, lon, depth,
                preferred.magnitude_value, preferred.magnitude_type,
                preferred.place, preferred.region, preferred.status,
                len(set(m.source for m in cluster.members)),
                preferred.source, preferred.event_uid,
                metrics["magnitude_std"],
                metrics["location_spread_km"],
                metrics["source_agreement_score"],
            ))

            # Upsert crosswalk entries
            for member in cluster.members:
                score = compute_match_score(member, preferred) if member != preferred else 1.0
                is_preferred = member.event_uid == preferred.event_uid
                cur.execute("""
                    INSERT INTO event_crosswalk (event_uid, unified_event_id, match_score, is_preferred)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (event_uid, unified_event_id) DO UPDATE SET
                        match_score = EXCLUDED.match_score,
                        is_preferred = EXCLUDED.is_preferred
                """, (member.event_uid, unified_id, score, is_preferred))

    conn.commit()
    conn.close()

    multi_source = sum(1 for c in clusters if len(set(m.source for m in c.members)) > 1)
    click.echo(
        f"Dedup cycle: {len(events)} events -> {len(clusters)} clusters "
        f"({multi_source} multi-source)"
    )
