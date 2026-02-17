"""Region-aware source priority for earthquake deduplication.

Classifies earthquake locations into broad geographic regions and returns
source priority orders that reflect which agencies provide the best data
for that region.
"""

from __future__ import annotations


def classify_region(lat: float, lon: float) -> str:
    """Classify a lat/lon coordinate into a broad geographic region.

    Returns one of: 'americas', 'europe', 'africa', 'asia_pacific', 'global'.
    """
    # Americas: longitude roughly -170 to -30
    if -170 <= lon <= -30:
        return "americas"

    # Europe: longitude -30 to 45, latitude >= 30
    if -30 < lon <= 45 and lat >= 30:
        return "europe"

    # Africa: longitude -20 to 55, latitude < 30
    if -20 <= lon <= 55 and lat < 30:
        return "africa"

    # Asia/Pacific: longitude > 45 (or far western Pacific)
    if lon > 45 or lon < -170:
        return "asia_pacific"

    return "global"


# Region-specific source priority orders
_REGION_PRIORITIES: dict[str, list[str]] = {
    "americas":     ["usgs", "emsc", "gfz", "isc", "ipgp", "geonet"],
    "europe":       ["emsc", "gfz", "usgs", "isc", "ipgp", "geonet"],
    "africa":       ["isc", "emsc", "ipgp", "usgs", "gfz", "geonet"],
    "asia_pacific":  ["isc", "usgs", "geonet", "emsc", "gfz", "ipgp"],
    "global":       ["usgs", "emsc", "isc", "gfz", "ipgp", "geonet"],
}


def get_source_priority(lat: float, lon: float) -> list[str]:
    """Get source priority order for a given location.

    Returns a list of source names ordered from highest to lowest priority
    for the geographic region containing the given coordinates.
    """
    region = classify_region(lat, lon)
    return _REGION_PRIORITIES.get(region, _REGION_PRIORITIES["global"])
