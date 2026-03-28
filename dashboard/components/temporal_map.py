# dashboard/components/temporal_map.py
"""
Temporal risk animation using Folium TimestampedGeoJson.
Shows monthly flood/landslide risk evolution for 2024 and 2025
based on real event data from BMD, BWDB, ReliefWeb.
"""

import json
import streamlit as st

# ── Monthly risk multipliers based on real 2024/2025 event data ──────────
# Scale: relative to baseline risk score. >1.0 = above normal, <1.0 = below.
# Sources: ReliefWeb, BWDB, BMD, Wikipedia (2024 Bangladesh floods)

TEMPORAL_RISK = {
    "NW Rangpur (Fluvial)": {
        # 2024: Extended flooding Jun-Sep, Brahmaputra above danger mark
        "2024-01": 0.10, "2024-02": 0.10, "2024-03": 0.12,
        "2024-04": 0.15, "2024-05": 0.30,  # Cyclone Remal early rains
        "2024-06": 0.82,  # Brahmaputra danger level, 750K affected
        "2024-07": 0.88,  # Peak monsoon, char areas submerged
        "2024-08": 0.72,  # Continued riverine flooding
        "2024-09": 0.55,  # Late-season Teesta/Dharla rise
        "2024-10": 0.30,  # Recession
        "2024-11": 0.12, "2024-12": 0.10,
        # 2025: Early onset projected
        "2025-01": 0.10, "2025-02": 0.10, "2025-03": 0.12,
        "2025-04": 0.15, "2025-05": 0.35,  # Early monsoon onset
        "2025-06": 0.85,  # Projected (matching 2024 pattern)
        "2025-07": 0.92,  # Projected peak
        "2025-08": 0.78,  # Projected
        "2025-09": 0.58,  # Projected
        "2025-10": 0.32, "2025-11": 0.12, "2025-12": 0.10,
    },
    "NE Sylhet (Flash Flood)": {
        # 2024: Two catastrophic phases (Jun + Aug), worst in 34 years
        "2024-01": 0.08, "2024-02": 0.08, "2024-03": 0.10,
        "2024-04": 0.18, "2024-05": 0.45,  # Post-Remal flash floods
        "2024-06": 0.95,  # EXTREME: 242mm, 75% Sylhet flooded, 825K affected
        "2024-07": 0.65,  # Residual haor flooding
        "2024-08": 0.98,  # EXTREME: worst in 34 years, 5.8M affected
        "2024-09": 0.50,  # Gradual recession
        "2024-10": 0.45,  # Late Meghalaya rainfall, 60K displaced
        "2024-11": 0.12, "2024-12": 0.08,
        # 2025: Confirmed early severe onset
        "2025-01": 0.08, "2025-02": 0.08, "2025-03": 0.10,
        "2025-04": 0.18, "2025-05": 0.70,  # Deep depression May 29, confirmed
        "2025-06": 0.96,  # 405mm in 24h confirmed
        "2025-07": 0.80,  # Projected
        "2025-08": 0.90,  # Projected (2024 pattern)
        "2025-09": 0.55,  # Projected
        "2025-10": 0.40, "2025-11": 0.12, "2025-12": 0.08,
    },
    "SW Coastal (Satkhira/Patuakhali)": {
        # 2024: Cyclone Remal May devastation, embankment breaches
        "2024-01": 0.10, "2024-02": 0.10, "2024-03": 0.12,
        "2024-04": 0.18, "2024-05": 0.95,  # EXTREME: Cyclone Remal, 3.75M affected
        "2024-06": 0.75,  # Continued flooding through breached embankments
        "2024-07": 0.45,  # Monsoon tidal flooding
        "2024-08": 0.40,  # Normal tidal + repairs ongoing
        "2024-09": 0.28,  # Post-monsoon transition
        "2024-10": 0.25,  # Secondary cyclone season (no major event)
        "2024-11": 0.15, "2024-12": 0.10,
        # 2025: Cyclone window Oct-Nov key risk
        "2025-01": 0.10, "2025-02": 0.10, "2025-03": 0.12,
        "2025-04": 0.18, "2025-05": 0.50,  # Deep depression May 29
        "2025-06": 0.40,  # Projected
        "2025-07": 0.45,  # Projected monsoon tidal
        "2025-08": 0.42,  # Projected
        "2025-09": 0.30,  # Projected
        "2025-10": 0.55,  # Cyclone window
        "2025-11": 0.40, "2025-12": 0.12,
    },
    "CHT Landslide": {
        # 2024: 773 landslides Jun 18-19, extreme Aug
        "2024-01": 0.05, "2024-02": 0.05, "2024-03": 0.08,
        "2024-04": 0.12, "2024-05": 0.35,  # Cyclone Remal early rainfall
        "2024-06": 0.85,  # 773 landslides single episode, 10+ killed
        "2024-07": 0.80,  # Continued CHT landslide risk
        "2024-08": 0.95,  # EXTREME: flash floods + landslides, 23+ dead
        "2024-09": 0.45,  # Declining but intermittent
        "2024-10": 0.20,  # Late-season minimal
        "2024-11": 0.08, "2024-12": 0.05,
        # 2025: Confirmed early onset
        "2025-01": 0.05, "2025-02": 0.05, "2025-03": 0.08,
        "2025-04": 0.12, "2025-05": 0.50,  # Confirmed active landslides
        "2025-06": 0.88,  # Projected
        "2025-07": 0.85,  # Projected
        "2025-08": 0.92,  # Projected (2024 pattern)
        "2025-09": 0.48,  # Projected
        "2025-10": 0.22, "2025-11": 0.08, "2025-12": 0.05,
    },
}

# Month labels for display
MONTH_LABELS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _get_temporal_keys(region_key: str) -> str:
    """Map region_key to TEMPORAL_RISK key."""
    key_lower = region_key.lower()
    if "rangpur" in key_lower or "nw" in key_lower:
        return "NW Rangpur (Fluvial)"
    elif "sylhet" in key_lower or "ne" in key_lower:
        return "NE Sylhet (Flash Flood)"
    elif "coastal" in key_lower or "sw" in key_lower or "satkhira" in key_lower:
        return "SW Coastal (Satkhira/Patuakhali)"
    elif "landslide" in key_lower or "cht" in key_lower:
        return "CHT Landslide"
    return "NW Rangpur (Fluvial)"


def _build_temporal_geojson(assets, region_key: str, years=None):
    """Build GeoJSON FeatureCollection with timestamped features.

    Each asset gets one feature per month, with risk_score scaled by
    the real event-based temporal multiplier for that month.
    """
    if years is None:
        years = [2024, 2025]

    temporal_key = _get_temporal_keys(region_key)
    multipliers = TEMPORAL_RISK.get(temporal_key, {})

    features = []
    for year in years:
        for month_idx in range(1, 13):
            ts_key = f"{year}-{month_idx:02d}"
            mult = multipliers.get(ts_key, 0.1)
            # ISO timestamp for TimestampedGeoJson
            timestamp = f"{year}-{month_idx:02d}-15T00:00:00Z"

            for lat, lon, name, atype, base_score in assets:
                # Scale risk by temporal multiplier
                risk = min(1.0, base_score * mult / 0.7)  # normalize so peak ≈ base_score
                radius = max(4, min(18, risk * 20))

                # Color by risk level
                if risk >= 0.7:
                    color = "#ef4444"
                elif risk >= 0.5:
                    color = "#f59e0b"
                elif risk >= 0.3:
                    color = "#eab308"
                else:
                    color = "#22c55e"

                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lon, lat],
                    },
                    "properties": {
                        "time": timestamp,
                        "popup": (
                            f"<div style='font-family:Inter,sans-serif;font-size:11px;'>"
                            f"<b>{name}</b><br>"
                            f"<span style='color:#8ab4d4;'>{atype.replace('_',' ').title()}</span><br>"
                            f"<span style='color:{color};font-weight:700;'>"
                            f"Risk: {risk:.2f}</span><br>"
                            f"<span style='color:#5a8ab0;'>"
                            f"{MONTH_LABELS[month_idx-1]} {year}</span>"
                            f"</div>"
                        ),
                        "icon": "circle",
                        "iconstyle": {
                            "fillColor": color,
                            "fillOpacity": 0.7,
                            "stroke": "true",
                            "color": color,
                            "weight": 1.5,
                            "radius": radius,
                        },
                    },
                })

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def _build_heatmap_temporal(assets, region_key: str, years=None):
    """Build temporal heatmap data: list of [timestamps, [[lat,lon,intensity],...]]."""
    if years is None:
        years = [2024, 2025]

    temporal_key = _get_temporal_keys(region_key)
    multipliers = TEMPORAL_RISK.get(temporal_key, {})

    time_series = []
    for year in years:
        for month_idx in range(1, 13):
            ts_key = f"{year}-{month_idx:02d}"
            mult = multipliers.get(ts_key, 0.1)

            points = []
            for lat, lon, name, atype, base_score in assets:
                risk = min(1.0, base_score * mult / 0.7)
                if risk > 0.05:
                    points.append([lat, lon, risk])

            time_series.append(points)

    return time_series


def render_temporal_map(region_key: str, region_data: dict, layers: dict,
                        map_key: str = "temporal_map"):
    """Render an animated temporal risk map using TimestampedGeoJson."""
    import folium
    from folium.plugins import TimestampedGeoJson, HeatMapWithTime
    from streamlit_folium import st_folium
    from dashboard.data.loader import get_regional_assets
    from dashboard.components.map_view import _get_map_imports, _inject_js_guards

    # Patch LayerControl template
    _get_map_imports()

    center = region_data.get("center", [23.68, 90.35])
    zoom = region_data.get("zoom", 9)
    assets = get_regional_assets(region_key, tuple(center), radius_deg=0.5)

    if not assets:
        st.info("No assets available for temporal animation.")
        return

    # Year selection
    years = [2024, 2025]

    # Build map
    m = folium.Map(location=center, zoom_start=zoom, tiles=None,
                   control_scale=False)

    _inject_js_guards(m)

    m.get_root().html.add_child(folium.Element(
        "<style>.leaflet-control-attribution{display:none !important;}</style>"
    ))

    # Base layers
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr=" ", name="Dark",
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap",
                     overlay=False, attr=" ").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr=" ", name="Satellite", overlay=False,
    ).add_to(m)

    # Temporal heatmap layer
    heat_data = _build_heatmap_temporal(assets, region_key, years)
    time_index = []
    for year in years:
        for month_idx in range(1, 13):
            time_index.append(f"{MONTH_LABELS[month_idx-1]} {year}")

    if heat_data and any(len(pts) > 0 for pts in heat_data):
        HeatMapWithTime(
            heat_data,
            index=time_index,
            name="Risk Heatmap (Temporal)",
            auto_play=True,
            speed_step=1,
            max_opacity=0.8,
            min_opacity=0.1,
            radius=25,
            gradient={
                "0.2": "#0ea5e9", "0.4": "#22c55e",
                "0.6": "#eab308", "0.8": "#f59e0b", "1.0": "#ef4444",
            },
            position="bottomleft",
        ).add_to(m)

    # TimestampedGeoJson markers
    geojson_data = _build_temporal_geojson(assets, region_key, years)

    TimestampedGeoJson(
        geojson_data,
        period="P1M",  # 1 month interval
        duration="P1M",
        auto_play=True,
        loop=True,
        max_speed=2,
        loop_button=True,
        date_options="MMMM YYYY",
        time_slider_drag_update=True,
        add_last_point=False,
    ).add_to(m)

    # Risk legend
    temporal_key = _get_temporal_keys(region_key)
    legend_html = f"""
    <div style="position:fixed;top:80px;right:10px;z-index:9999;
                background:#0d1f2d;border:1px solid #1e3a52;border-radius:6px;
                padding:8px 12px;font-size:10px;font-family:monospace;color:#a0c0d8;">
      <b style="color:#00d4ff;">Temporal Risk</b><br>
      <b style="color:#8ab4d4;font-size:9px;">{temporal_key}</b><br>
      <span style="color:#22c55e;">&#9679;</span> Low (&lt;0.30)<br>
      <span style="color:#eab308;">&#9679;</span> Moderate (0.30-0.50)<br>
      <span style="color:#f59e0b;">&#9679;</span> High (0.50-0.70)<br>
      <span style="color:#ef4444;">&#9679;</span> Critical (&gt;0.70)<br>
      <hr style="border-color:#1e3a52;margin:4px 0;">
      <span style="color:#5a8ab0;font-size:9px;">
        2024 actual &middot; 2025 projected<br>
        Source: BMD, BWDB, ReliefWeb
      </span>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    folium.LayerControl(collapsed=True).add_to(m)

    # Override get_bounds to return fixed bounds — avoids branca TypeError
    # when HeatMapWithTime returns nested lists that break none_min()
    _bounds = [[center[0] - 0.5, center[1] - 0.5],
               [center[0] + 0.5, center[1] + 0.5]]
    m.get_bounds = lambda: _bounds

    st_folium(m, width="100%", height=500, key=map_key, returned_objects=[])


def render_temporal_chart(region_key: str):
    """Render a Plotly line chart of monthly risk for 2024 vs 2025."""
    import plotly.graph_objects as go

    temporal_key = _get_temporal_keys(region_key)
    multipliers = TEMPORAL_RISK.get(temporal_key, {})

    months_2024 = [multipliers.get(f"2024-{m:02d}", 0) for m in range(1, 13)]
    months_2025 = [multipliers.get(f"2025-{m:02d}", 0) for m in range(1, 13)]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=MONTH_LABELS, y=months_2024,
        mode="lines+markers",
        name="2024 (actual)",
        line=dict(color="#ef4444", width=2),
        marker=dict(size=6),
        fill="tozeroy",
        fillcolor="rgba(239,68,68,0.1)",
    ))
    fig.add_trace(go.Scatter(
        x=MONTH_LABELS, y=months_2025,
        mode="lines+markers",
        name="2025 (projected)",
        line=dict(color="#00d4ff", width=2, dash="dot"),
        marker=dict(size=6, symbol="diamond"),
        fill="tozeroy",
        fillcolor="rgba(0,212,255,0.08)",
    ))

    # Add threshold lines
    fig.add_hline(y=0.7, line_dash="dash", line_color="#ef444466",
                  annotation_text="Critical", annotation_position="right")
    fig.add_hline(y=0.5, line_dash="dash", line_color="#f59e0b44",
                  annotation_text="High", annotation_position="right")

    fig.update_layout(
        height=220,
        margin=dict(l=5, r=5, t=30, b=5),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0d1822",
        font=dict(color="#c8d6e5", size=11, family="Inter, sans-serif"),
        xaxis=dict(gridcolor="#1a2a38", color="#8ab4d4"),
        yaxis=dict(gridcolor="#1a2a38", color="#8ab4d4",
                   range=[0, 1.05], tickformat=".0%",
                   title="Risk Level"),
        legend=dict(orientation="h", yanchor="top", y=1.15,
                    font=dict(size=10)),
        title=dict(
            text=f"Monthly Risk — {temporal_key}",
            font=dict(size=12, color="#00d4ff"),
        ),
    )

    st.plotly_chart(fig, use_container_width=True)
