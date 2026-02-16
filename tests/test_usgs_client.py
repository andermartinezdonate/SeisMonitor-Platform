"""Tests for the USGS client."""

import pytest
from quake_stream.models import Earthquake
from quake_stream.usgs_client import fetch_earthquakes

SAMPLE_GEOJSON = {
    "type": "FeatureCollection",
    "metadata": {"count": 2},
    "features": [
        {
            "type": "Feature",
            "id": "us7000test1",
            "properties": {
                "mag": 4.5,
                "place": "10km NE of Somewhere",
                "time": 1700000000000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test1",
            },
            "geometry": {"type": "Point", "coordinates": [-118.5, 34.0, 10.0]},
        },
        {
            "type": "Feature",
            "id": "us7000test2",
            "properties": {
                "mag": 2.1,
                "place": "5km SW of Elsewhere",
                "time": 1699999000000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test2",
            },
            "geometry": {"type": "Point", "coordinates": [-117.2, 33.5, 5.5]},
        },
    ],
}


class TestEarthquakeModel:
    def test_from_geojson_feature(self):
        quake = Earthquake.from_geojson_feature(SAMPLE_GEOJSON["features"][0])
        assert quake.id == "us7000test1"
        assert quake.magnitude == 4.5
        assert quake.place == "10km NE of Somewhere"
        assert quake.depth == 10.0

    def test_json_roundtrip(self):
        quake = Earthquake.from_geojson_feature(SAMPLE_GEOJSON["features"][0])
        restored = Earthquake.from_json(quake.to_json())
        assert restored == quake


class TestFetchEarthquakes:
    def test_fetch_parses_response(self, httpx_mock):
        httpx_mock.add_response(json=SAMPLE_GEOJSON)
        quakes = fetch_earthquakes(period="hour")
        assert len(quakes) == 2
        assert quakes[0].magnitude == 4.5  # sorted by time desc

    def test_fetch_filters_by_magnitude(self, httpx_mock):
        httpx_mock.add_response(json=SAMPLE_GEOJSON)
        quakes = fetch_earthquakes(period="hour", min_magnitude=3.0)
        assert len(quakes) == 1
        assert quakes[0].magnitude == 4.5

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError, match="Unknown period"):
            fetch_earthquakes(period="invalid")
