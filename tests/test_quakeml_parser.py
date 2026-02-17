"""Tests for QuakeML parser (ISC, IPGP, GeoNet formats)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quake_stream.parsers.quakeml import QuakeMLParser
from quake_stream.parsers.base import EventParser


# ── Sample XML payloads ─────────────────────────────────────────────────

SAMPLE_QUAKEML_ISC = """\
<?xml version="1.0" encoding="UTF-8"?>
<q:quakeml xmlns:q="http://quakeml.org/xmlns/quakeml/1.2"
           xmlns="http://quakeml.org/xmlns/bed/1.2">
  <eventParameters publicID="smi:ISC/bulletin">
    <event publicID="smi:ISC/evid=600516598">
      <origin publicID="smi:ISC/origid=100001">
        <time><value>2024-01-15T12:00:00.000Z</value></time>
        <latitude>
          <value>-1.5</value>
          <uncertainty>0.05</uncertainty>
        </latitude>
        <longitude>
          <value>29.2</value>
          <uncertainty>0.08</uncertainty>
        </longitude>
        <depth>
          <value>15000</value>
          <uncertainty>3000</uncertainty>
        </depth>
        <evaluationMode>manual</evaluationMode>
        <evaluationStatus>reviewed</evaluationStatus>
        <creationInfo><author>ISC</author></creationInfo>
      </origin>
      <magnitude publicID="smi:ISC/magid=300001">
        <mag><value>4.8</value><uncertainty>0.2</uncertainty></mag>
        <type>mb</type>
      </magnitude>
      <magnitude publicID="smi:ISC/magid=300002">
        <mag><value>5.1</value><uncertainty>0.15</uncertainty></mag>
        <type>Mw</type>
      </magnitude>
      <magnitude publicID="smi:ISC/magid=300003">
        <mag><value>4.5</value><uncertainty>0.3</uncertainty></mag>
        <type>Ms</type>
      </magnitude>
      <description>
        <type>Flinn-Engdahl region</type>
        <text>Lake Kivu Region</text>
      </description>
    </event>
  </eventParameters>
</q:quakeml>
"""

SAMPLE_QUAKEML_IPGP = """\
<?xml version="1.0" encoding="UTF-8"?>
<q:quakeml xmlns:q="http://quakeml.org/xmlns/quakeml/1.2"
           xmlns="http://quakeml.org/xmlns/bed/1.2">
  <eventParameters>
    <event publicID="smi:ipgp.fr/event/12345">
      <preferredOriginID>smi:ipgp.fr/origin/98765</preferredOriginID>
      <preferredMagnitudeID>smi:ipgp.fr/magnitude/54321</preferredMagnitudeID>
      <origin publicID="smi:ipgp.fr/origin/98765">
        <time><value>2024-03-10T08:30:15.500Z</value></time>
        <latitude><value>14.6</value></latitude>
        <longitude><value>-61.0</value></longitude>
        <depth><value>5000</value></depth>
        <evaluationMode>automatic</evaluationMode>
      </origin>
      <origin publicID="smi:ipgp.fr/origin/99999">
        <time><value>2024-03-10T08:30:20.000Z</value></time>
        <latitude><value>14.7</value></latitude>
        <longitude><value>-61.1</value></longitude>
        <depth><value>6000</value></depth>
      </origin>
      <magnitude publicID="smi:ipgp.fr/magnitude/54321">
        <mag><value>3.2</value></mag>
        <type>ML</type>
      </magnitude>
      <magnitude publicID="smi:ipgp.fr/magnitude/54322">
        <mag><value>3.5</value></mag>
        <type>Mw</type>
      </magnitude>
      <description>
        <type>Flinn-Engdahl region</type>
        <text>Martinique Region</text>
      </description>
    </event>
  </eventParameters>
</q:quakeml>
"""


# ── Parser tests ────────────────────────────────────────────────────────


class TestQuakeMLParserISC:
    def test_parse_isc_format(self):
        """ISC: smi:ISC/evid=NNN, no preferredMagnitudeID, multiple mags."""
        parser = QuakeMLParser(default_source="isc")
        events = parser.parse(SAMPLE_QUAKEML_ISC, datetime.now(timezone.utc))
        assert len(events) == 1
        e = events[0]
        assert e.source == "isc"
        assert e.source_event_id == "600516598"
        assert e.event_uid == "isc:600516598"
        # Should prefer Mw (index 0 in preference) over mb, ms
        assert e.magnitude_type == "mw"
        assert e.magnitude_value == 5.1
        assert e.status == "reviewed"
        assert e.place == "Lake Kivu Region"

    def test_depth_meters_to_km(self):
        """QuakeML depth is in meters — parser should convert to km."""
        parser = QuakeMLParser(default_source="isc")
        events = parser.parse(SAMPLE_QUAKEML_ISC, datetime.now(timezone.utc))
        e = events[0]
        assert e.depth_km == 15.0  # 15000m -> 15.0km

    def test_uncertainty_fields(self):
        """Uncertainty values should be parsed."""
        parser = QuakeMLParser(default_source="isc")
        events = parser.parse(SAMPLE_QUAKEML_ISC, datetime.now(timezone.utc))
        e = events[0]
        assert e.lat_error_km == 0.05
        assert e.lon_error_km == 0.08
        assert e.depth_error_km == 3.0  # 3000m -> 3.0km
        assert e.mag_error == 0.15  # uncertainty of preferred (Mw) mag


class TestQuakeMLParserIPGP:
    def test_parse_with_preferred_ids(self):
        """IPGP: preferredOriginID/MagnitudeID present, should use them."""
        parser = QuakeMLParser(default_source="ipgp")
        events = parser.parse(SAMPLE_QUAKEML_IPGP, datetime.now(timezone.utc))
        assert len(events) == 1
        e = events[0]
        assert e.source == "ipgp"
        assert e.source_event_id == "12345"
        assert e.event_uid == "ipgp:12345"
        # Should use preferred magnitude (ML 3.2), not the Mw 3.5
        assert e.magnitude_value == 3.2
        assert e.magnitude_type == "ml"
        # Should use preferred origin (first one)
        assert e.latitude == 14.6
        assert e.longitude == -61.0
        assert e.depth_km == 5.0  # 5000m -> 5.0km
        assert e.status == "automatic"
        assert e.place == "Martinique Region"


class TestQuakeMLParserEdgeCases:
    def test_parse_empty(self):
        parser = QuakeMLParser()
        assert parser.parse("", datetime.now(timezone.utc)) == []
        assert parser.parse("   ", datetime.now(timezone.utc)) == []

    def test_parse_empty_quakeml(self):
        """Empty eventParameters should return empty list."""
        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<q:quakeml xmlns:q="http://quakeml.org/xmlns/quakeml/1.2"'
               ' xmlns="http://quakeml.org/xmlns/bed/1.2">'
               '<eventParameters></eventParameters></q:quakeml>')
        parser = QuakeMLParser()
        assert parser.parse(xml, datetime.now(timezone.utc)) == []

    def test_no_description_place_none(self):
        """Event without <description> should have place=None."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<q:quakeml xmlns:q="http://quakeml.org/xmlns/quakeml/1.2"
           xmlns="http://quakeml.org/xmlns/bed/1.2">
  <eventParameters>
    <event publicID="smi:test/ev1">
      <origin publicID="smi:test/orig1">
        <time><value>2024-01-15T12:00:00Z</value></time>
        <latitude><value>35.0</value></latitude>
        <longitude><value>-120.0</value></longitude>
        <depth><value>10000</value></depth>
      </origin>
      <magnitude publicID="smi:test/mag1">
        <mag><value>4.0</value></mag>
        <type>ML</type>
      </magnitude>
    </event>
  </eventParameters>
</q:quakeml>
"""
        parser = QuakeMLParser(default_source="isc")
        events = parser.parse(xml, datetime.now(timezone.utc))
        assert len(events) == 1
        assert events[0].place is None

    def test_validation_passes(self):
        """Parsed events should pass validation."""
        parser = QuakeMLParser(default_source="isc")
        events = parser.parse(SAMPLE_QUAKEML_ISC, datetime.now(timezone.utc))
        for event in events:
            errors = EventParser.validate(event)
            assert errors == [], f"Validation errors: {errors}"

    def test_malformed_xml_returns_empty(self):
        """Invalid XML should return empty list, not raise."""
        parser = QuakeMLParser()
        assert parser.parse("<not>valid<xml", datetime.now(timezone.utc)) == []

    def test_event_id_extraction(self):
        """Test various publicID formats."""
        assert QuakeMLParser._extract_event_id("smi:ISC/evid=600516598") == "600516598"
        assert QuakeMLParser._extract_event_id("smi:ipgp.fr/event/12345") == "12345"
        assert QuakeMLParser._extract_event_id("quakeml:org#ev999") == "ev999"
        assert QuakeMLParser._extract_event_id("plain_id") == "plain_id"
        assert QuakeMLParser._extract_event_id("") == ""
