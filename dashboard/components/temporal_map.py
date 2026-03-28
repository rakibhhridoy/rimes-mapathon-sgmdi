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
    """Render temporal risk map with fully client-side JS animation.

    All play/pause/slider/speed logic runs in the browser — zero server
    round-trips during playback.
    """
    import json
    import streamlit.components.v1 as components
    from dashboard.data.loader import get_regional_assets
    from dashboard.components.map_view import _get_map_imports

    _get_map_imports()

    center = region_data.get("center", [23.68, 90.35])
    zoom = region_data.get("zoom", 9)
    assets = get_regional_assets(region_key, tuple(center), radius_deg=0.5)

    if not assets:
        st.info("No assets available for temporal animation.")
        return

    temporal_key = _get_temporal_keys(region_key)
    multipliers = TEMPORAL_RISK.get(temporal_key, {})

    # Build time index
    time_labels = []
    time_keys = []
    for year in [2024, 2025]:
        for month_idx in range(1, 13):
            time_labels.append(f"{MONTH_LABELS[month_idx-1]} {year}")
            time_keys.append(f"{year}-{month_idx:02d}")

    # Pre-compute multipliers per frame
    mults = [multipliers.get(k, 0.1) for k in time_keys]

    # Serialize asset data for JS
    assets_js = json.dumps([
        {"lat": a[0], "lon": a[1], "name": a[2], "type": a[3], "score": a[4]}
        for a in assets
    ])

    html = _build_temporal_player_html(
        center=center,
        zoom=zoom,
        assets_json=assets_js,
        labels_json=json.dumps(time_labels),
        mults_json=json.dumps(mults),
        map_id=map_key.replace("-", "_"),
    )

    components.html(html, height=530, scrolling=False)


def _build_temporal_player_html(center, zoom, assets_json, labels_json,
                                 mults_json, map_id):
    """Build a self-contained HTML page with Leaflet map + JS animation."""
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0a0e14;font-family:Inter,system-ui,sans-serif}}
  #map{{width:100%;height:400px;border-radius:8px;border:1px solid #1e3a52}}
  .ctrl-bar{{display:flex;align-items:center;gap:8px;padding:6px 0;margin-bottom:4px}}
  .ctrl-btn{{background:rgba(13,24,34,0.9);border:1px solid #1e3a52;border-radius:6px;
    color:#8ab4d4;font-size:11px;font-family:Inter,sans-serif;padding:5px 14px;
    cursor:pointer;transition:all .2s}}
  .ctrl-btn:hover{{border-color:#00d4ff;color:#00d4ff}}
  .ctrl-btn.active{{background:#0d2e3e;border-color:#00d4ff;color:#00d4ff}}
  .speed-sel{{background:#0a0e14;border:1px solid #1e3a52;border-radius:4px;
    color:#8ab4d4;font-size:11px;padding:4px 6px;font-family:Inter,sans-serif}}
  .slider-row{{display:flex;align-items:center;gap:10px;padding:4px 0}}
  .slider-row input[type=range]{{flex:1;accent-color:#00d4ff;height:6px}}
  .badge{{display:flex;align-items:center;gap:12px;margin-bottom:6px}}
  .badge-label{{color:#8ab4d4;font-size:12px;font-family:'DM Mono',monospace}}
  .badge-level{{padding:2px 10px;border-radius:10px;font-size:11px;font-weight:700;
    font-family:Inter,sans-serif}}
  .leaflet-control-attribution{{display:none!important}}
</style>
</head>
<body>
<div class="badge" id="badge_{map_id}"></div>
<div class="ctrl-bar">
  <button class="ctrl-btn" id="play_{map_id}">&#9654; Play</button>
  <button class="ctrl-btn" id="reset_{map_id}">&#9198; Reset</button>
  <select class="speed-sel" id="speed_{map_id}">
    <option value="0.5">0.5&times;</option>
    <option value="1" selected>1&times;</option>
    <option value="2">2&times;</option>
    <option value="3">3&times;</option>
  </select>
  <span style="color:#5a8ab0;font-size:10px;margin-left:auto" id="counter_{map_id}"></span>
</div>
<div class="slider-row">
  <input type="range" min="0" max="23" value="0" id="slider_{map_id}">
</div>
<div id="map" style="margin-top:4px"></div>

<script>
(function(){{
  var ASSETS = {assets_json};
  var LABELS = {labels_json};
  var MULTS  = {mults_json};
  var CENTER = {center};
  var ZOOM   = {zoom};
  var MID    = "{map_id}";
  var N      = LABELS.length;

  // Init map
  var map = L.map("map",{{attributionControl:false}}).setView(CENTER, ZOOM);
  L.tileLayer("https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png",
    {{subdomains:"abcd",maxZoom:19}}).addTo(map);

  var heatLayer = null;
  var markerLayer = L.layerGroup().addTo(map);

  function riskColor(r){{
    return r>=0.7?"#ef4444":r>=0.5?"#f59e0b":r>=0.3?"#eab308":"#22c55e";
  }}
  function riskLevel(m){{
    if(m>=0.7) return ["CRITICAL","#ef4444"];
    if(m>=0.5) return ["HIGH","#f59e0b"];
    if(m>=0.3) return ["MODERATE","#eab308"];
    return ["LOW","#22c55e"];
  }}

  function renderFrame(idx){{
    var mult = MULTS[idx];
    var label = LABELS[idx];
    var rl = riskLevel(mult);

    // Badge
    document.getElementById("badge_"+MID).innerHTML =
      '<span class="badge-label">'+label+'</span>'+
      '<span class="badge-level" style="background:'+rl[1]+'20;color:'+rl[1]+'">'+
      rl[0]+' ('+(mult*100).toFixed(0)+'%)</span>';

    // Counter
    document.getElementById("counter_"+MID).textContent =
      (idx+1)+' / '+N;

    // Slider
    document.getElementById("slider_"+MID).value = idx;

    // Clear old markers
    markerLayer.clearLayers();

    // Build heat + markers
    var heatPts = [];
    ASSETS.forEach(function(a){{
      var risk = Math.min(1.0, a.score * mult / 0.7);
      if(risk > 0.05) heatPts.push([a.lat, a.lon, risk]);
      var c = riskColor(risk);
      var r = Math.max(4, Math.min(14, risk*18));
      L.circleMarker([a.lat, a.lon], {{
        radius: r, color: c, fillColor: c, fillOpacity: 0.7,
        weight: 1.5
      }}).bindTooltip(a.name+' ('+a.type+') — Risk: '+risk.toFixed(2))
        .addTo(markerLayer);
    }});

    // Update heat
    if(heatLayer) map.removeLayer(heatLayer);
    if(heatPts.length > 0){{
      heatLayer = L.heatLayer(heatPts, {{
        radius:25, blur:15, minOpacity:0.2, maxZoom:17,
        gradient:{{0.2:"#0ea5e9",0.4:"#22c55e",0.6:"#eab308",0.8:"#f59e0b",1.0:"#ef4444"}}
      }}).addTo(map);
    }}
  }}

  // Controls
  var playing = false;
  var timer = null;
  var curIdx = 0;
  var playBtn = document.getElementById("play_"+MID);
  var resetBtn = document.getElementById("reset_"+MID);
  var speedSel = document.getElementById("speed_"+MID);
  var slider = document.getElementById("slider_"+MID);

  function getDelay(){{
    var spd = parseFloat(speedSel.value) || 1;
    return Math.max(200, 1200 / spd);
  }}

  function startPlay(){{
    playing = true;
    playBtn.innerHTML = "&#9208; Pause";
    playBtn.classList.add("active");
    step();
  }}
  function stopPlay(){{
    playing = false;
    clearTimeout(timer);
    timer = null;
    playBtn.innerHTML = "&#9654; Play";
    playBtn.classList.remove("active");
  }}
  function step(){{
    if(!playing) return;
    curIdx = (curIdx + 1) % N;
    renderFrame(curIdx);
    timer = setTimeout(step, getDelay());
  }}

  playBtn.addEventListener("click", function(){{
    if(playing) stopPlay(); else startPlay();
  }});
  resetBtn.addEventListener("click", function(){{
    stopPlay();
    curIdx = 0;
    renderFrame(0);
  }});
  slider.addEventListener("input", function(){{
    stopPlay();
    curIdx = parseInt(this.value);
    renderFrame(curIdx);
  }});

  // Initial render
  renderFrame(0);
}})();
</script>
</body>
</html>
"""


def render_temporal_chart(region_key: str, chart_key: str = ""):
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
    fig.add_hline(y=0.7, line_dash="dash", line_color="rgba(239,68,68,0.4)",
                  annotation_text="Critical", annotation_position="right")
    fig.add_hline(y=0.5, line_dash="dash", line_color="rgba(245,158,11,0.27)",
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

    _key = f"temporal_chart_{temporal_key}_{chart_key}" if chart_key else f"temporal_chart_{temporal_key}"
    st.plotly_chart(fig, use_container_width=True, key=_key)
