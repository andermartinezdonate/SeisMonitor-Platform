"""Parser for QuakeML 1.2 XML format (ISC, IPGP, GeoNet, etc.)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from quake_stream.models_v2 import NormalizedEvent
from quake_stream.parsers.base import EventParser

# QuakeML 1.2 namespaces
_NS = {
    "q": "http://quakeml.org/xmlns/quakeml/1.2",
    "bed": "http://quakeml.org/xmlns/bed/1.2",
}

# Magnitude type preference order for ISC (no preferredMagnitudeID)
_MAG_PREFERENCE = ["mw", "mb", "ms"]


class QuakeMLParser(EventParser):
    """Parse QuakeML 1.2 XML response -> list of NormalizedEvent.

    Reusable for any FDSN-compliant service that returns QuakeML XML
    (ISC, IPGP, GeoNet NZ, etc.).
    """

    def __init__(self, default_source: str = "isc"):
        self.default_source = default_source

    def parse(self, raw_payload: str, fetched_at: datetime) -> list[NormalizedEvent]:
        if not raw_payload or not raw_payload.strip():
            return []

        try:
            root = ET.fromstring(raw_payload)
        except ET.ParseError:
            return []

        events: list[NormalizedEvent] = []

        # Try with namespace first, then without
        event_elements = root.findall(".//bed:event", _NS)
        if not event_elements:
            event_elements = root.findall(".//{http://quakeml.org/xmlns/bed/1.2}event")
        if not event_elements:
            # Fallback: no namespace
            event_elements = root.findall(".//event")

        for event_el in event_elements:
            try:
                parsed = self._parse_event(event_el, fetched_at)
                if parsed is not None:
                    events.append(parsed)
            except (ValueError, KeyError, IndexError, AttributeError):
                continue

        return events

    def _parse_event(self, event_el: ET.Element, fetched_at: datetime) -> NormalizedEvent | None:
        """Parse a single <event> element."""
        # Extract event ID from publicID attribute
        public_id = event_el.get("publicID", "")
        source_event_id = self._extract_event_id(public_id)
        if not source_event_id:
            return None

        # Get preferred origin/magnitude IDs
        pref_origin_id = self._text(event_el, "bed:preferredOriginID")
        pref_mag_id = self._text(event_el, "bed:preferredMagnitudeID")

        # Find the correct origin
        origin = self._find_preferred(event_el, "bed:origin", pref_origin_id)
        if origin is None:
            return None

        # Find the correct magnitude
        if pref_mag_id:
            magnitude_el = self._find_preferred(event_el, "bed:magnitude", pref_mag_id)
        else:
            # ISC quirk: no preferredMagnitudeID — use preference order
            magnitude_el = self._select_best_magnitude(event_el)
        if magnitude_el is None:
            return None

        # Parse origin fields
        time_str = self._text(origin, "bed:time/bed:value")
        if not time_str:
            return None
        origin_time = self._parse_time(time_str)

        lat_str = self._text(origin, "bed:latitude/bed:value")
        lon_str = self._text(origin, "bed:longitude/bed:value")
        depth_str = self._text(origin, "bed:depth/bed:value")
        if not lat_str or not lon_str:
            return None

        latitude = float(lat_str)
        longitude = float(lon_str)
        # QuakeML depth is in METERS — convert to km
        depth_km = float(depth_str) / 1000.0 if depth_str else 0.0

        # Normalize longitude
        if longitude > 180:
            longitude -= 360
        elif longitude < -180:
            longitude += 360

        # Parse magnitude
        mag_str = self._text(magnitude_el, "bed:mag/bed:value")
        mag_type_str = self._text(magnitude_el, "bed:type")
        if not mag_str:
            return None
        magnitude_value = float(mag_str)
        magnitude_type = (mag_type_str or "ml").lower()

        # Status from evaluationMode / evaluationStatus
        eval_mode = self._text(origin, "bed:evaluationMode")
        eval_status = self._text(origin, "bed:evaluationStatus")
        status = self._map_status(eval_mode, eval_status)

        # Place/region from <description>
        place = self._extract_description(event_el)

        # Uncertainty fields
        lat_error = self._float_or_none(origin, "bed:latitude/bed:uncertainty")
        lon_error = self._float_or_none(origin, "bed:longitude/bed:uncertainty")
        depth_error = self._float_or_none(origin, "bed:depth/bed:uncertainty")
        if depth_error is not None:
            depth_error = depth_error / 1000.0  # meters -> km
        mag_error = self._float_or_none(magnitude_el, "bed:mag/bed:uncertainty")

        # Author
        author_el = origin.find("bed:creationInfo/bed:author", _NS)
        if author_el is None:
            author_el = origin.find("{http://quakeml.org/xmlns/bed/1.2}creationInfo/"
                                    "{http://quakeml.org/xmlns/bed/1.2}author")
        author = author_el.text if author_el is not None and author_el.text else None

        return NormalizedEvent(
            event_uid=f"{self.default_source}:{source_event_id}",
            source=self.default_source,
            source_event_id=source_event_id,
            origin_time_utc=origin_time,
            latitude=latitude,
            longitude=longitude,
            depth_km=depth_km,
            magnitude_value=magnitude_value,
            magnitude_type=magnitude_type,
            place=place,
            region=place,
            lat_error_km=lat_error,
            lon_error_km=lon_error,
            depth_error_km=depth_error,
            mag_error=mag_error,
            status=status,
            author=author,
            fetched_at=fetched_at,
            raw_payload="",
        )

    @staticmethod
    def _extract_event_id(public_id: str) -> str:
        """Extract event ID from publicID URI.

        Handles ISC format: smi:ISC/evid=600516598 -> 600516598
        Generic: smi:org/something/12345 -> 12345
        Plain: ev12345 -> ev12345
        """
        if not public_id:
            return ""
        # ISC format: smi:ISC/evid=NNN
        if "evid=" in public_id:
            return public_id.split("evid=")[-1]
        # Generic smi URI: take last path segment
        if "/" in public_id:
            return public_id.rsplit("/", 1)[-1]
        # Opaque URI with #
        if "#" in public_id:
            return public_id.rsplit("#", 1)[-1]
        return public_id

    def _find_preferred(self, event_el: ET.Element, tag: str, preferred_id: str | None) -> ET.Element | None:
        """Find element matching preferredID, or fallback to first."""
        elements = event_el.findall(tag, _NS)
        if not elements:
            # Try without namespace prefix
            ns_tag = tag.replace("bed:", "{http://quakeml.org/xmlns/bed/1.2}")
            elements = event_el.findall(ns_tag)
        if not elements:
            return None

        if preferred_id:
            for el in elements:
                if el.get("publicID") == preferred_id:
                    return el

        return elements[0]

    def _select_best_magnitude(self, event_el: ET.Element) -> ET.Element | None:
        """Select best magnitude when no preferredMagnitudeID (ISC quirk)."""
        magnitudes = event_el.findall("bed:magnitude", _NS)
        if not magnitudes:
            magnitudes = event_el.findall("{http://quakeml.org/xmlns/bed/1.2}magnitude")
        if not magnitudes:
            return None

        # Score each by preference
        def score(mag_el: ET.Element) -> int:
            mt = self._text(mag_el, "bed:type")
            if mt:
                mt = mt.lower()
                if mt in _MAG_PREFERENCE:
                    return _MAG_PREFERENCE.index(mt)
            return len(_MAG_PREFERENCE)

        return min(magnitudes, key=score)

    @staticmethod
    def _map_status(eval_mode: str | None, eval_status: str | None) -> str:
        """Map QuakeML evaluationMode/Status to our status enum."""
        if eval_mode:
            mode = eval_mode.lower()
            if mode == "manual":
                return "reviewed"
            if mode == "automatic":
                return "automatic"
        if eval_status:
            status = eval_status.lower()
            if status in ("reviewed", "confirmed", "final"):
                return "reviewed"
        return "automatic"

    @staticmethod
    def _extract_description(event_el: ET.Element) -> str | None:
        """Extract place/region from <description> elements."""
        for desc in event_el.findall("bed:description", _NS):
            dtype = desc.findtext("bed:type", namespaces=_NS)
            text = desc.findtext("bed:text", namespaces=_NS)
            if dtype and dtype.lower() in ("flinn-engdahl region", "region name") and text:
                return text
        # Fallback: try without namespace
        for desc in event_el.findall("{http://quakeml.org/xmlns/bed/1.2}description"):
            dtype_el = desc.find("{http://quakeml.org/xmlns/bed/1.2}type")
            text_el = desc.find("{http://quakeml.org/xmlns/bed/1.2}text")
            if dtype_el is not None and text_el is not None:
                if dtype_el.text and dtype_el.text.lower() in ("flinn-engdahl region", "region name"):
                    return text_el.text
        # Last resort: any description text
        for desc in event_el.findall("bed:description", _NS):
            text = desc.findtext("bed:text", namespaces=_NS)
            if text:
                return text
        for desc in event_el.findall("{http://quakeml.org/xmlns/bed/1.2}description"):
            text_el = desc.find("{http://quakeml.org/xmlns/bed/1.2}text")
            if text_el is not None and text_el.text:
                return text_el.text
        return None

    def _text(self, el: ET.Element, path: str) -> str | None:
        """Get text content of a sub-element, trying with and without namespace."""
        node = el.find(path, _NS)
        if node is not None and node.text:
            return node.text.strip()
        # Fallback: explicit namespace
        ns_path = path.replace("bed:", "{http://quakeml.org/xmlns/bed/1.2}")
        node = el.find(ns_path)
        if node is not None and node.text:
            return node.text.strip()
        return None

    def _float_or_none(self, el: ET.Element, path: str) -> float | None:
        """Get float from sub-element or None."""
        txt = self._text(el, path)
        if txt:
            try:
                return float(txt)
            except ValueError:
                pass
        return None

    @staticmethod
    def _parse_time(time_str: str) -> datetime:
        """Parse ISO 8601 time from QuakeML."""
        time_str = time_str.replace("Z", "+00:00")
        # Normalize fractional seconds
        if "." in time_str:
            base, rest = time_str.split(".", 1)
            frac = ""
            tz_suffix = ""
            for i, ch in enumerate(rest):
                if ch in "+-" or rest[i:] == "+00:00":
                    frac = rest[:i]
                    tz_suffix = rest[i:]
                    break
            else:
                frac = rest
            frac = frac.ljust(6, "0")[:6]
            time_str = f"{base}.{frac}{tz_suffix}"
        result = datetime.fromisoformat(time_str)
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result
