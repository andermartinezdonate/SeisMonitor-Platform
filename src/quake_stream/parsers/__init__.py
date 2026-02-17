"""Parsers for converting raw earthquake data to NormalizedEvent."""

from quake_stream.parsers.usgs_geojson import USGSGeoJSONParser
from quake_stream.parsers.emsc_geojson import EMSCGeoJSONParser
from quake_stream.parsers.fdsn_text import FDSNTextParser
from quake_stream.parsers.quakeml import QuakeMLParser

PARSER_MAP = {
    "usgs": USGSGeoJSONParser(),
    "emsc": EMSCGeoJSONParser(),
    "gfz": FDSNTextParser(default_source="gfz"),
    "isc": QuakeMLParser(default_source="isc"),
    "ipgp": QuakeMLParser(default_source="ipgp"),
    "geonet": QuakeMLParser(default_source="geonet"),
}

__all__ = [
    "PARSER_MAP",
    "USGSGeoJSONParser", "EMSCGeoJSONParser", "FDSNTextParser", "QuakeMLParser",
]
