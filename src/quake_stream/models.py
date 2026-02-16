"""Earthquake data models."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass(frozen=True)
class Earthquake:
    """Represents a single earthquake event from USGS."""

    id: str
    magnitude: float
    place: str
    time: datetime
    longitude: float
    latitude: float
    depth: float
    url: str

    @classmethod
    def from_geojson_feature(cls, feature: dict) -> Earthquake:
        props = feature["properties"]
        coords = feature["geometry"]["coordinates"]
        return cls(
            id=feature["id"],
            magnitude=props["mag"] or 0.0,
            place=props["place"] or "Unknown",
            time=datetime.fromtimestamp(props["time"] / 1000, tz=timezone.utc),
            longitude=coords[0],
            latitude=coords[1],
            depth=coords[2],
            url=props["url"] or "",
        )

    def to_json(self) -> str:
        d = asdict(self)
        d["time"] = self.time.isoformat()
        return json.dumps(d)

    @classmethod
    def from_json(cls, raw: str) -> Earthquake:
        d = json.loads(raw)
        d["time"] = datetime.fromisoformat(d["time"])
        return cls(**d)
