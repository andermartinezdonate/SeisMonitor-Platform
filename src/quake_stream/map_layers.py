"""Map rendering logic for the earthquake dashboard.

Provides two map modes:
- Globe view: Plotly Scattergeo with orthographic projection
- Interactive map: Plotly Scattermapbox with WebGL + tile layers

Depth-based scientific color scale and magnitude-based sizing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from quake_stream.tectonic import boundaries_to_traces, load_plate_boundaries

# ── Depth color scale (scientific: red=shallow → blue=deep) ──────────────
# Focused on 0-100 km range (covers >95% of earthquakes):
#   0-10 km  = very shallow (most damaging)
#   10-33 km = shallow crustal
#   33-70 km = intermediate
#   70-100 km = deep crustal / upper mantle
# Shallow=red (dangerous) and deep=blue (less surface impact)
DEPTH_COLORSCALE = [
    [0.00, "#d73027"],  # 0 km   — red (very shallow, most damaging)
    [0.10, "#f46d43"],  # 10 km
    [0.25, "#fdae61"],  # 25 km
    [0.33, "#fee08b"],  # 33 km  — shallow/intermediate boundary
    [0.50, "#d9ef8b"],  # 50 km
    [0.70, "#91cf60"],  # 70 km  — intermediate/deep boundary
    [0.85, "#1a9850"],  # 85 km
    [1.00, "#313695"],  # 100 km — deep blue
]

# Alternative: viridis-like for depth
DEPTH_COLORSCALE_VIRIDIS = [
    [0.0, "#fde725"],
    [0.2, "#5ec962"],
    [0.4, "#21918c"],
    [0.6, "#3b528b"],
    [0.8, "#472d7b"],
    [1.0, "#440154"],
]

# Magnitude color scale (green→yellow→red)
MAG_COLORSCALE = [
    [0.0, "#1a9641"],
    [0.25, "#a6d96a"],
    [0.45, "#fee08b"],
    [0.65, "#fdae61"],
    [0.80, "#f46d43"],
    [1.0, "#d73027"],
]

# ── Tectonic plate styling ────────────────────────────────────────────────
PLATE_LINE_STYLE_GLOBE = dict(width=1.2, color="rgba(255, 165, 0, 0.4)")
PLATE_LINE_STYLE_MAPBOX = dict(width=1.0, color="rgba(255, 165, 0, 0.5)")

# ── Map style options ─────────────────────────────────────────────────────
MAPBOX_STYLES = {
    "Dark": "carto-darkmatter",
    "Satellite": "open-street-map",
    "Terrain": "stamen-terrain",
    "Minimal": "carto-positron",
}

# Dark theme layout defaults
DARK_GEO_LAYOUT = dict(
    showland=True,
    landcolor="#1a1d24",
    showocean=True,
    oceancolor="#0a0f1a",
    showcountries=True,
    countrycolor="rgba(255,255,255,0.15)",
    countrywidth=0.5,
    showcoastlines=True,
    coastlinecolor="rgba(255,255,255,0.25)",
    coastlinewidth=0.8,
    showlakes=True,
    lakecolor="#0a0f1a",
    showrivers=False,
    bgcolor="rgba(0,0,0,0)",
    showsubunits=True,
    subunitcolor="rgba(255,255,255,0.08)",
    subunitwidth=0.3,
)

# ── State boundaries GeoJSON URL ──────────────────────────────────────────
US_STATES_GEOJSON_URL = (
    "https://raw.githubusercontent.com/PublicaMundi/"
    "MappingAPI/master/data/geojson/us-states.json"
)


def magnitude_to_size(magnitudes: pd.Series, min_size: float = 3, max_size: float = 35) -> pd.Series:
    """Map earthquake magnitudes to marker sizes.

    Uses an exponential scale since magnitude is logarithmic.
    M0 → ~3px, M5 → ~18px, M8 → ~35px
    """
    # Clamp negatives to 0
    mag = magnitudes.clip(lower=0)
    # Exponential scaling: size = min + (max-min) * (mag/max_mag)^1.8
    max_mag = max(mag.max(), 8.0)
    normalized = (mag / max_mag) ** 1.8
    return min_size + normalized * (max_size - min_size)


def depth_to_normalized(depths: pd.Series, max_depth: float = 100.0) -> pd.Series:
    """Normalize depth values for color mapping (0-100km range)."""
    return depths.clip(lower=0, upper=max_depth) / max_depth


def build_hover_text(df: pd.DataFrame) -> list[str]:
    """Build rich hover tooltips for earthquake markers."""
    texts = []
    for _, row in df.iterrows():
        texts.append(
            f"<b>M {row.magnitude:.1f}</b> — {row.place}<br>"
            f"<b>Depth:</b> {row.depth:.1f} km<br>"
            f"<b>Time:</b> {row.time:%Y-%m-%d %H:%M:%S UTC}<br>"
            f"<b>Coords:</b> {row.latitude:.3f}, {row.longitude:.3f}<br>"
            f"<b>ID:</b> {row.id}"
        )
    return texts


def _add_tectonic_traces_geo(fig: go.Figure) -> None:
    """Add tectonic plate boundary lines to a Scattergeo figure."""
    geojson = load_plate_boundaries()
    traces = boundaries_to_traces(geojson)

    for i, segment in enumerate(traces):
        fig.add_trace(go.Scattergeo(
            lon=segment["lon"],
            lat=segment["lat"],
            mode="lines",
            line=PLATE_LINE_STYLE_GLOBE,
            hoverinfo="skip",
            showlegend=i == 0,
            name="Tectonic Plates" if i == 0 else None,
            legendgroup="plates",
        ))


def _add_tectonic_traces_mapbox(fig: go.Figure) -> None:
    """Add tectonic plate boundary lines to a Scattermapbox figure."""
    geojson = load_plate_boundaries()
    traces = boundaries_to_traces(geojson)

    for i, segment in enumerate(traces):
        fig.add_trace(go.Scattermapbox(
            lon=segment["lon"],
            lat=segment["lat"],
            mode="lines",
            line=PLATE_LINE_STYLE_MAPBOX,
            hoverinfo="skip",
            showlegend=i == 0,
            name="Tectonic Plates" if i == 0 else None,
            legendgroup="plates",
        ))


def build_globe_map(
    df: pd.DataFrame,
    show_plates: bool = True,
    color_by: str = "depth",
    projection: str = "orthographic",
    rotation_lon: float = 0,
    rotation_lat: float = 20,
) -> go.Figure:
    """Build a Plotly Scattergeo globe map.

    Args:
        df: DataFrame with earthquake data
        show_plates: Whether to show tectonic plate boundaries
        color_by: "depth" or "magnitude" for marker coloring
        projection: Map projection type
        rotation_lon/lat: Initial globe rotation
    """
    fig = go.Figure()

    # Tectonic plates (add first so earthquakes render on top)
    if show_plates:
        _add_tectonic_traces_geo(fig)

    if df.empty:
        fig.update_geos(projection_type=projection, **DARK_GEO_LAYOUT)
        fig.update_layout(height=650, margin=dict(l=0, r=0, t=0, b=0))
        return fig

    # Marker sizing
    sizes = magnitude_to_size(df["magnitude"])

    # Color configuration
    if color_by == "depth":
        color_values = df["depth"]
        colorscale = DEPTH_COLORSCALE
        cbar_title = "Depth (km)"
        cmin, cmax = 0, 100
    else:
        color_values = df["magnitude"]
        colorscale = MAG_COLORSCALE
        cbar_title = "Magnitude"
        cmin, cmax = 0, max(df["magnitude"].max(), 6)

    # Earthquake markers
    fig.add_trace(go.Scattergeo(
        lon=df["longitude"],
        lat=df["latitude"],
        mode="markers",
        marker=dict(
            size=sizes,
            color=color_values,
            colorscale=colorscale,
            cmin=cmin,
            cmax=cmax,
            colorbar=dict(
                title=dict(text=cbar_title, font=dict(color="#c9d1d9", size=12)),
                tickfont=dict(color="#8b949e", size=10),
                bgcolor="rgba(0,0,0,0)",
                borderwidth=0,
                len=0.5,
                x=1.01,
                thickness=12,
            ),
            opacity=0.85,
            line=dict(width=0.5, color="rgba(255,255,255,0.3)"),
            sizemode="diameter",
        ),
        text=build_hover_text(df),
        hoverinfo="text",
        showlegend=False,
    ))

    # Geo layout
    fig.update_geos(
        projection_type=projection,
        projection_rotation=dict(lon=rotation_lon, lat=rotation_lat),
        **DARK_GEO_LAYOUT,
    )

    fig.update_layout(
        height=650,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        geo=dict(framecolor="rgba(255,255,255,0.05)", framewidth=1),
        legend=dict(
            font=dict(color="#8b949e", size=11),
            bgcolor="rgba(0,0,0,0.3)",
            bordercolor="rgba(255,255,255,0.1)",
            borderwidth=1,
            x=0.01, y=0.99,
        ),
    )

    return fig


def build_mapbox_map(
    df: pd.DataFrame,
    show_plates: bool = True,
    color_by: str = "depth",
    map_style: str = "carto-darkmatter",
    center_lat: float = 20.0,
    center_lon: float = 0.0,
    zoom: float = 1.5,
) -> go.Figure:
    """Build a Plotly Scattermapbox interactive map with WebGL.

    Args:
        df: DataFrame with earthquake data
        show_plates: Whether to show tectonic plate boundaries
        color_by: "depth" or "magnitude" for marker coloring
        map_style: Mapbox tile style
        center_lat/lon: Initial map center
        zoom: Initial zoom level
    """
    fig = go.Figure()

    # Tectonic plates
    if show_plates:
        _add_tectonic_traces_mapbox(fig)

    if df.empty:
        fig.update_layout(
            mapbox=dict(style=map_style, center=dict(lat=center_lat, lon=center_lon), zoom=zoom),
            height=650, margin=dict(l=0, r=0, t=0, b=0),
        )
        return fig

    # Marker sizing (slightly smaller for mapbox)
    sizes = magnitude_to_size(df["magnitude"], min_size=3, max_size=28)

    # Color configuration
    if color_by == "depth":
        color_values = df["depth"]
        colorscale = DEPTH_COLORSCALE
        cbar_title = "Depth (km)"
        cmin, cmax = 0, 100
    else:
        color_values = df["magnitude"]
        colorscale = MAG_COLORSCALE
        cbar_title = "Magnitude"
        cmin, cmax = 0, max(df["magnitude"].max(), 6)

    # Earthquake markers
    fig.add_trace(go.Scattermapbox(
        lon=df["longitude"],
        lat=df["latitude"],
        mode="markers",
        marker=dict(
            size=sizes,
            color=color_values,
            colorscale=colorscale,
            cmin=cmin,
            cmax=cmax,
            colorbar=dict(
                title=dict(text=cbar_title, font=dict(color="#c9d1d9", size=12)),
                tickfont=dict(color="#8b949e", size=10),
                bgcolor="rgba(13,17,23,0.8)",
                borderwidth=0,
                len=0.5,
                x=1.01,
                thickness=12,
            ),
            opacity=0.85,
            sizemode="diameter",
        ),
        text=build_hover_text(df),
        hoverinfo="text",
        showlegend=False,
    ))

    fig.update_layout(
        mapbox=dict(
            style=map_style,
            center=dict(lat=center_lat, lon=center_lon),
            zoom=zoom,
        ),
        height=650,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(
            font=dict(color="#8b949e", size=11),
            bgcolor="rgba(0,0,0,0.5)",
            bordercolor="rgba(255,255,255,0.1)",
            borderwidth=1,
            x=0.01, y=0.99,
        ),
    )

    return fig
