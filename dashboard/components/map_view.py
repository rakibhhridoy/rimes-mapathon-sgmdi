"""
Interactive Folium map with:
  - Color-coded circle markers sized by risk
  - Donut-style cluster icons
  - Rich gauge-style popups
  - Risk heatmap, admin boundaries, hotspot overlays
  - Kriging interpolation rings (from Fermium-HazMapper)
  - AlphaEarth cluster overlay + population density (from Fermium-HazMapper)
"""

import re

import streamlit as st


def _get_map_imports():
    """Lazy import folium and related heavy libs."""
    import folium
    from folium.plugins import MarkerCluster, HeatMap
    from streamlit_folium import st_folium

    # Fix LayerControl template: replace 'let' with 'var' at the class level.
    # Folium uses 'let' which causes SyntaxError when st_folium re-evaluates
    # the script on Streamlit reruns (let can't be re-declared in same scope).
    if not getattr(folium.LayerControl, '_template_patched', False):
        from folium.template import Template
        folium.LayerControl._template = Template("""
        {% macro script(this,kwargs) %}
            var {{ this.get_name() }}_layers = {
                base_layers : {
                    {%- for key, val in this.base_layers.items() %}
                    {{ key|tojson }} : {{val}},
                    {%- endfor %}
                },
                overlays :  {
                    {%- for key, val in this.overlays.items() %}
                    {{ key|tojson }} : {{val}},
                    {%- endfor %}
                },
            };
            var {{ this.get_name() }} = L.control.layers(
                {{ this.get_name() }}_layers.base_layers,
                {{ this.get_name() }}_layers.overlays,
                {{ this.options|tojavascript }}
            ).addTo({{this._parent.get_name()}});

            {%- if this.draggable %}
            new L.Draggable({{ this.get_name() }}.getContainer()).enable();
            {%- endif %}

        {% endmacro %}
        """)
        folium.LayerControl._template_patched = True

    return folium, MarkerCluster, HeatMap, st_folium


# JS guard injected directly into folium HTML — runs in the iframe before
# any map code, so it works regardless of Python-side patching.
_BROWSER_JS_GUARD = """
<script>
(function(){
    // Guard HeatMap: prevent getImageData on 0-width canvas
    if(typeof L!=="undefined"&&L.HeatLayer){
        var _origDraw=L.HeatLayer.prototype._draw;
        L.HeatLayer.prototype._draw=function(){
            if(this._canvas&&this._canvas.width>0&&this._canvas.height>0){
                _origDraw.call(this);
            }
        };
    }
    // Guard Map: prevent "already initialized" error
    if(typeof L!=="undefined"&&L.Map){
        var _origInit=L.Map.prototype.initialize;
        L.Map.prototype.initialize=function(id,options){
            var container=typeof id==='string'?document.getElementById(id):id;
            if(container&&container._leaflet_id){
                container._leaflet_id=null;
                container.innerHTML='';
            }
            return _origInit.call(this,id,options);
        };
    }
})();
</script>
"""


def _inject_js_guards(m):
    """Inject browser-side JS guards into the folium map HTML."""
    import folium
    m.get_root().html.add_child(folium.Element(_BROWSER_JS_GUARD))
    return m


from dashboard.data.loader import (
    get_alphaearth_clusters,
    get_pop_density_points,
    get_kriging_ci_at_point,
    get_kriging_ci_batch,
    get_raster_overlay,
    load_heatmap_points,
)


# Asset type → (emoji, default color)
TYPE_COLORS = {
    "hospital": "#ef4444",
    "school": "#3b82f6",
    "bridge": "#f59e0b",
    "road": "#6b7280",
    "flood_shelter": "#10b981",
    "embankment": "#059669",
    "railway": "#8b5cf6",
    "ferry_ghat": "#0ea5e9",
    "cropland": "#22c55e",
    "fishpond": "#67e8f9",
    "irrigation": "#06b6d4",
    "market": "#f43f5e",
    "shelter": "#10b981",
}

TYPE_EMOJI = {
    "hospital": "H", "school": "S", "bridge": "B", "road": "R",
    "flood_shelter": "FS", "embankment": "E", "railway": "Rl",
    "ferry_ghat": "F", "cropland": "C", "fishpond": "FP",
    "irrigation": "I", "market": "M", "shelter": "Sh",
}

RISK_COLOR_STOPS = [
    (0.00, "#1a6b52"),
    (0.25, "#3a9a3a"),
    (0.50, "#dea03c"),
    (0.75, "#de7a3c"),
    (1.00, "#de3c3c"),
]


def _risk_color(score) -> str:
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "#64748b"
    if score >= 0.7:
        return "#ef4444"
    elif score >= 0.5:
        return "#f59e0b"
    elif score >= 0.3:
        return "#eab308"
    return "#22c55e"


def _risk_to_color(score: float) -> str:
    """Gradient risk color from Fermium-HazMapper."""
    for i in range(len(RISK_COLOR_STOPS) - 1):
        lo_val, lo_col = RISK_COLOR_STOPS[i]
        hi_val, hi_col = RISK_COLOR_STOPS[i + 1]
        if lo_val <= score <= hi_val:
            return hi_col if score > (lo_val + hi_val) / 2 else lo_col
    return "#de3c3c"


def _risk_label(score) -> str:
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "N/A"
    if score >= 0.7:
        return "CRITICAL"
    elif score >= 0.5:
        return "HIGH"
    elif score >= 0.3:
        return "MODERATE"
    return "LOW"


def _kriging_rings(folium, m, lat, lon, score):
    """Draw concentric risk rings to simulate Kriging interpolation surface."""
    for r, alpha, offset in [
        (5000, 0.08, 0.0),
        (3000, 0.12, 0.05),
        (1500, 0.18, 0.10),
        (600,  0.28, 0.15),
    ]:
        folium.Circle(
            location=[lat, lon],
            radius=r,
            color=_risk_to_color(min(1.0, score + offset)),
            fill=True,
            fill_opacity=alpha,
            weight=0.5,
        ).add_to(m)


def _factor_bar(label, value, color, max_val=1.0) -> str:
    """Single horizontal factor bar for popup."""
    pct = min(value / max_val * 100, 100) if max_val > 0 else 0
    return (
        f'<div style="display:flex;align-items:center;gap:6px;margin:3px 0;">'
        f'<span style="color:#8ab4d4;font-size:9px;width:52px;text-align:right;'
        f'font-family:Inter,sans-serif;">{label}</span>'
        f'<div style="flex:1;background:#1e293b;border-radius:3px;height:6px;overflow:hidden;">'
        f'<div style="background:linear-gradient(90deg,{color}88,{color});'
        f'width:{pct:.0f}%;height:6px;border-radius:3px;"></div></div>'
        f'<span style="color:#f0f6ff;font-size:9px;font-family:DM Mono,monospace;'
        f'width:32px;">{value:.2f}</span></div>'
    )


def _gauge_popup(name, atype, risk, rank, division="", kriging_ci=None) -> str:
    """Rich HTML popup with gauge, factor breakdown bars, and action hints."""
    color = _risk_color(risk)
    label = _risk_label(risk)
    emoji = TYPE_EMOJI.get(atype, "?")
    risk_val = f"{risk:.3f}" if isinstance(risk, (int, float)) and risk > 0 else "N/A"
    rank_val = f"#{int(rank)}" if isinstance(rank, (int, float)) and rank > 0 else "—"
    pct = min(float(risk) * 100, 100) if isinstance(risk, (int, float)) else 0
    ci_str = f"{kriging_ci:.3f}" if kriging_ci is not None else "N/A"
    cvi_class = "IV" if isinstance(risk, (int, float)) and risk > 0.75 else "III" if isinstance(risk, (int, float)) and risk > 0.55 else "II"

    # Derive factor scores from composite risk
    r = float(risk) if isinstance(risk, (int, float)) else 0.5
    hazard_score = min(1.0, r * 1.15)
    exposure_score = min(1.0, r * 0.90)
    vuln_score = min(1.0, r * 0.75)

    gauge_svg = f"""
    <svg width="100" height="55" viewBox="0 0 100 55">
      <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke="#1e293b" stroke-width="8" stroke-linecap="round"/>
      <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke="{color}" stroke-width="8" stroke-linecap="round"
            stroke-dasharray="{pct * 1.26} 126"/>
      <text x="50" y="45" text-anchor="middle" font-size="14" font-weight="bold" fill="{color}"
            font-family="DM Mono,monospace">{risk_val}</text>
    </svg>
    """

    factors_html = (
        _factor_bar("Hazard", hazard_score, "#ef4444") +
        _factor_bar("Exposure", exposure_score, "#f59e0b") +
        _factor_bar("Vuln.", vuln_score, "#8b5cf6")
    )

    return f"""
    <div style="font-family:Inter,'Segoe UI',sans-serif; min-width:230px; padding:4px;">
        <div style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">
            <span style="font-size:13px;font-weight:700;background:{color}22;color:{color};
                         padding:2px 7px;border-radius:5px;font-family:DM Mono,monospace;">{emoji}</span>
            <div>
                <div style="font-size:13px; font-weight:600; color:#1e293b; line-height:1.2;">
                    {name}
                </div>
                <div style="font-size:10px; color:#64748b;">
                    {atype.replace('_',' ').title()} {('| ' + division) if division else ''}
                </div>
            </div>
        </div>

        <div style="text-align:center; margin:2px 0 4px 0;">
            {gauge_svg}
        </div>

        <div style="background:#f8fafc;border-radius:6px;padding:6px 8px;margin:4px 0;">
            {factors_html}
        </div>

        <div style="display:flex;gap:8px;font-size:9px;color:#64748b;margin-top:5px;
                    font-family:DM Mono,monospace;">
            <span>CI: +/-{ci_str}</span>
            <span>CVI: {cvi_class}</span>
            <span>Rank: {rank_val}</span>
        </div>

        <div style="display:flex; justify-content:space-between; margin-top:6px;">
            <span style="
                background:{color}15; color:{color}; padding:2px 10px;
                border-radius:10px; font-weight:600; font-size:10px;
                letter-spacing:0.03em;
            ">{label}</span>
        </div>
    </div>
    """


def _fullscreen_toggle_css():
    """Inject CSS for the floating fullscreen toggle button on the map."""
    st.markdown("""
    <style>
    .map-fs-btn {
        display: inline-flex; align-items: center; gap: 6px;
        background: rgba(13,24,34,0.85); backdrop-filter: blur(10px);
        border: 1px solid #1e3a52; border-radius: 8px;
        color: #8ab4d4; font-size: 11px; font-family: 'Inter', sans-serif;
        font-weight: 500; padding: 6px 12px; cursor: pointer;
        transition: all 0.2s ease; letter-spacing: 0.03em;
    }
    .map-fs-btn:hover {
        border-color: #00d4ff; color: #00d4ff;
        box-shadow: 0 0 14px rgba(0,212,255,0.15);
    }
    .map-fs-btn svg { width: 14px; height: 14px; }
    </style>
    """, unsafe_allow_html=True)


def render_map(infra,
                grid_gdf=None,
                union_gdf=None,
                hotspot_gdf=None,
                cfg=None,
                is_dark=True,
                layers=None):
    """Render the main interactive map with all overlays and fullscreen toggle."""
    if layers is None:
        layers = {}

    # _fullscreen_toggle_css()  # hidden — expand map toggle disabled

    # if "map_fullscreen" not in st.session_state:
    #     st.session_state.map_fullscreen = False
    #
    # st.checkbox(
    #     "Expand map",
    #     value=st.session_state.map_fullscreen,
    #     key="_map_fs_toggle",
    #     on_change=lambda: st.session_state.update(
    #         map_fullscreen=st.session_state._map_fs_toggle
    #     ),
    # )

    map_h = 620

    # Refresh button — reloads map iframe via JS, no Streamlit rerun
    st.markdown(
        """
        <button onclick="
            var iframes = parent.document.querySelectorAll('iframe[title*=\\'streamlit_folium\\']');
            iframes.forEach(function(f){ f.contentWindow.location.reload(); });
        " style="
            background:rgba(13,24,34,0.85); backdrop-filter:blur(10px);
            border:1px solid #1e3a52; border-radius:6px;
            color:#8ab4d4; font-size:11px; font-family:Inter,sans-serif;
            padding:5px 14px; cursor:pointer; margin-bottom:8px;
            transition:all 0.2s ease;
        " onmouseover="this.style.borderColor='#00d4ff';this.style.color='#00d4ff'"
          onmouseout="this.style.borderColor='#1e3a52';this.style.color='#8ab4d4'"
        >Refresh Map</button>
        """,
        unsafe_allow_html=True,
    )

    _, _, _, st_folium_fn = _get_map_imports()
    m = _build_main_map(infra, grid_gdf, union_gdf, hotspot_gdf, cfg, is_dark, layers)
    st_folium_fn(m, width=None, height=map_h, returned_objects=[])


def _build_main_map(infra, grid_gdf, union_gdf, hotspot_gdf, cfg, is_dark, layers):
    """Build the folium Map object with all layers."""
    folium, MarkerCluster, HeatMap, _ = _get_map_imports()

    center = cfg.get("dashboard", {}).get("map_center", [25.5, 89.0]) if cfg else [25.5, 89.0]
    zoom = cfg.get("dashboard", {}).get("map_zoom", 8) if cfg else 8

    m = folium.Map(location=center, zoom_start=zoom, tiles=None,
                   control_scale=False)

    _inject_js_guards(m)

    # Hide Leaflet attribution watermark
    m.get_root().html.add_child(folium.Element(
        "<style>.leaflet-control-attribution{display:none !important;}</style>"
    ))

    # Base layers
    if is_dark:
        folium.TileLayer(
            tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
            attr=" ", name="Dark",
        ).add_to(m)
    else:
        folium.TileLayer("OpenStreetMap", name="Street", attr=" ").add_to(m)

    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", overlay=False, attr=" ").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr=" ", name="Satellite", overlay=False,
    ).add_to(m)

    # --- Kriging interpolation rings ---
    if layers.get("show_hand", True) or layers.get("show_cvi", True):
        if infra is not None and len(infra) > 0 and "flood_risk" in infra.columns:
            high_risk = infra[infra["flood_risk"] >= 0.6].head(20)
            for _, row in high_risk.iterrows():
                lat = row.get("lat", None)
                lon = row.get("lon", None)
                if lat is not None and lon is not None:
                    _kriging_rings(folium, m, lat, lon, row["flood_risk"])

    # --- AlphaEarth cluster overlay ---
    if layers.get("show_alphearth", False):
        ae_data = get_alphaearth_clusters()
        if ae_data and "features" in ae_data:
            for feat in ae_data["features"]:
                props = feat.get("properties", {})
                coords = feat["geometry"]["coordinates"]
                color = props.get("color", "#a03cde")
                is_centroid = props.get("is_centroid", False)
                radius = 1500 if is_centroid else 600
                opacity = 0.15 if is_centroid else 0.08
                tooltip = (f"Cluster {props.get('cluster', '?')} centroid "
                          f"({props.get('n_points', '?')} pts)"
                          if is_centroid else
                          f"AlphaEarth cluster {props.get('cluster', '?')}")
                folium.Circle(
                    location=[coords[1], coords[0]],
                    radius=radius,
                    color=color,
                    fill=True,
                    fill_opacity=opacity,
                    weight=0.8 if is_centroid else 0.3,
                    tooltip=tooltip,
                ).add_to(m)
        else:
            folium.Marker(
                location=center,
                icon=folium.DivIcon(html='<div style="color:#a03cde;font-size:10px;">AlphaEarth: run pipeline</div>'),
            ).add_to(m)

    # --- Population density heatmap ---
    if layers.get("show_popdens", False):
        pop_points = get_pop_density_points(tuple(center), radius_deg=0.3, n_points=200)
        if pop_points:
            heat_data = [[lat, lon, w] for lat, lon, w in pop_points]
            HeatMap(
                heat_data, name="Population Density",
                min_opacity=0.15, radius=12, blur=10,
                gradient={"0.2": "#fce7f3", "0.5": "#f472b6", "0.8": "#db2777", "1.0": "#9d174d"},
            ).add_to(m)

    # --- Raster overlays ---
    for raster_key, layer_key in [("dem", "show_dem"), ("slope", "show_slope"),
                                   ("hand", "show_hand"), ("flood_risk", "show_cvi")]:
        if layers.get(layer_key, False) and raster_key not in ("hand",):
            overlay = get_raster_overlay(raster_key)
            if overlay:
                folium.raster_layers.ImageOverlay(
                    image=f"data:image/png;base64,{overlay['image_base64']}",
                    bounds=overlay["bounds"],
                    name=raster_key.replace("_", " ").title(),
                    opacity=0.6,
                ).add_to(m)

    # --- Circle markers (color by type, size by risk) ---
    if infra is not None and len(infra) > 0:
        marker_cluster = MarkerCluster(
            name="Infrastructure",
            options={
                "maxClusterRadius": 40,
                "spiderfyOnMaxZoom": True,
                "showCoverageOnHover": False,
            },
        )

        # Vectorized layer filtering before iterating
        display_infra = infra.copy(deep=False)
        if "asset_type" in display_infra.columns:
            exclude_types = set()
            if not layers.get("osm_hospitals", True):
                exclude_types.add("hospital")
            if not layers.get("osm_bridges", True):
                exclude_types.add("bridge")
            if not layers.get("osm_schools", True):
                exclude_types.add("school")
            if not layers.get("osm_roads", True):
                exclude_types.update(("road", "railway"))
            if exclude_types:
                display_infra = display_infra[~display_infra["asset_type"].isin(exclude_types)]

        # Cap markers at 2000 (sorted by risk desc) for performance
        if len(display_infra) > 2000 and "flood_risk" in display_infra.columns:
            display_infra = display_infra.nlargest(2000, "flood_risk")

        # Pre-compute kriging CIs in batch
        ci_coords = []
        marker_rows = []
        for _, row in display_infra.iterrows():
            lat = row.get("lat", None)
            lon = row.get("lon", None)
            if lat is None or lon is None:
                pt = row.geometry.representative_point()
                lat, lon = pt.y, pt.x

            risk = row.get("flood_risk", 0)
            ci_coords.append((lat, lon, float(risk) if isinstance(risk, (int, float)) else 0.5))
            marker_rows.append((lat, lon, row))

        # Batch kriging CI lookup
        ci_values = get_kriging_ci_batch(tuple(ci_coords)) if ci_coords else []

        for i, (lat, lon, row) in enumerate(marker_rows):
            atype = row.get("asset_type", "other")
            risk = row.get("flood_risk", 0)
            name = row.get("name", "unnamed")
            rank = row.get("risk_rank", 0)
            division = row.get("division", "")

            type_color = TYPE_COLORS.get(atype, "#64748b")
            risk_radius = max(4, min(12, float(risk) * 15)) if isinstance(risk, (int, float)) and risk > 0 else 5

            popup_html = _gauge_popup(name, atype, risk, rank, division,
                                      kriging_ci=ci_values[i] if i < len(ci_values) else None)

            folium.CircleMarker(
                location=[lat, lon],
                radius=risk_radius,
                color=type_color,
                fill=True,
                fill_color=type_color,
                fill_opacity=0.7,
                weight=1.5,
                popup=folium.Popup(popup_html, max_width=240),
                tooltip=f"{TYPE_EMOJI.get(atype, '')} {name}",
            ).add_to(marker_cluster)

        marker_cluster.add_to(m)

    # --- Risk heatmap (pre-computed or vectorized fallback) ---
    heat_data = load_heatmap_points()
    if not heat_data and grid_gdf is not None and "composite_risk" in grid_gdf.columns:
        centroids = grid_gdf.geometry.centroid
        risks = grid_gdf["composite_risk"].values
        mask = risks > 0.1
        if mask.any():
            heat_data = list(zip(
                centroids[mask].y.tolist(),
                centroids[mask].x.tolist(),
                risks[mask].tolist(),
            ))
    if heat_data:
        HeatMap(
            heat_data, name="Flood Risk Heatmap",
            min_opacity=0.25, radius=18, blur=12,
            gradient={"0.2": "#0ea5e9", "0.4": "#22c55e",
                      "0.6": "#eab308", "0.8": "#f59e0b", "1.0": "#ef4444"},
        ).add_to(m)

    # --- Admin boundaries ---
    if union_gdf is not None and len(union_gdf) > 0:
        folium.GeoJson(
            union_gdf.to_json(),
            name="Union Boundaries",
            style_function=lambda f: {
                "fillColor": _risk_color(f["properties"].get("mean_risk", 0)),
                "color": "#94a3b8" if is_dark else "#475569",
                "weight": 1,
                "fillOpacity": 0.25,
                "dashArray": "4",
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["admin_name", "mean_risk", "risk_rank"],
                aliases=["Union:", "Risk:", "Rank:"],
            ),
        ).add_to(m)

    # --- Hotspots ---
    if hotspot_gdf is not None and len(hotspot_gdf) > 0:
        if "is_hotspot" in hotspot_gdf.columns:
            hotspots = hotspot_gdf[hotspot_gdf["is_hotspot"] == True]
        else:
            hotspots = hotspot_gdf
        if len(hotspots) > 0:
            folium.GeoJson(
                hotspots.to_json(),
                name="Hotspots (Gi*)",
                style_function=lambda x: {
                    "fillColor": "#ef4444",
                    "color": "#ef4444",
                    "weight": 2,
                    "fillOpacity": 0.35,
                },
            ).add_to(m)

    # --- LULC legend ---
    if layers.get("show_lulc", False):
        legend_html = """
        <div style="position:fixed;bottom:30px;left:30px;z-index:9999;
                    background:#0d1f2d;border:1px solid #1e3a52;border-radius:6px;
                    padding:8px 12px;font-size:10px;font-family:monospace;color:#a0c0d8;">
          <b style="color:#00d4ff;">LULC</b><br>
          <span style="color:#3cdea0;">|</span> Cropland &nbsp;
          <span style="color:#00d4ff;">|</span> Water &nbsp;
          <span style="color:#8a6a1a;">|</span> Built-up &nbsp;
          <span style="color:#4a7a4a;">|</span> Forest
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

    # --- DEM legend ---
    if layers.get("show_dem", False):
        dem_html = """
        <div style="position:fixed;bottom:30px;right:30px;z-index:9999;
                    background:#0d1f2d;border:1px solid #1e3a52;border-radius:6px;
                    padding:8px 12px;font-size:10px;font-family:monospace;color:#a0c0d8;">
          <b style="color:#00d4ff;">Elevation (SRTM 30m)</b><br>
          Low ------- High<br>
          <span style="color:#5a8ab0;">0m to 100m+ (simulated)</span>
        </div>
        """
        m.get_root().html.add_child(folium.Element(dem_html))

    # --- Risk color legend ---
    risk_legend = """
    <div style="position:fixed;top:80px;right:10px;z-index:9999;
                background:#0d1f2d;border:1px solid #1e3a52;border-radius:6px;
                padding:8px 12px;font-size:10px;font-family:monospace;color:#a0c0d8;">
      <b style="color:#00d4ff;">Risk Score</b><br>
      <span style="color:#3cdea0;">o</span> Very Low (&lt;0.20)<br>
      <span style="color:#3a9a3a;">o</span> Low (0.20-0.40)<br>
      <span style="color:#dea03c;">o</span> Moderate (0.40-0.60)<br>
      <span style="color:#de7a3c;">o</span> High (0.60-0.80)<br>
      <span style="color:#de3c3c;">o</span> Very High (&gt;0.80)
    </div>
    """
    m.get_root().html.add_child(folium.Element(risk_legend))

    folium.LayerControl(collapsed=True).add_to(m)
    return m


def render_region_map(region_key: str, region_data: dict, layers: dict, map_key: str = "region_map"):
    """Render an interactive Folium map for a specific region — unified with pipeline style."""
    folium, MarkerCluster, HeatMap, st_folium_fn = _get_map_imports()
    from dashboard.data.loader import get_regional_assets

    center = region_data.get("center", [23.68, 90.35])
    zoom   = region_data.get("zoom",   9)
    assets = get_regional_assets(region_key, tuple(center), radius_deg=0.5)

    m = folium.Map(
        location=center,
        zoom_start=zoom,
        tiles=None,
        control_scale=False,
    )

    _inject_js_guards(m)

    # Hide Leaflet attribution watermark
    m.get_root().html.add_child(folium.Element(
        "<style>.leaflet-control-attribution{display:none !important;}</style>"
    ))

    # Base layers — same as pipeline map
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr=" ", name="Dark",
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", overlay=False, attr=" ").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr=" ", name="Satellite", overlay=False,
    ).add_to(m)

    # Kriging risk surface rings (only top-risk assets)
    if layers.get("show_hand", True) or layers.get("show_cvi", True):
        high_risk_assets = sorted(assets, key=lambda a: a[4], reverse=True)[:20]
        for asset in high_risk_assets:
            if asset[4] >= 0.6:
                _kriging_rings(folium, m, asset[0], asset[1], asset[4])

    # AlphaEarth cluster overlay
    if layers.get("show_alphearth", False):
        ae_data = get_alphaearth_clusters()
        if ae_data and "features" in ae_data:
            for feat in ae_data["features"]:
                coords = feat["geometry"]["coordinates"]
                props = feat.get("properties", {})
                if (abs(coords[1] - center[0]) < 0.5 and
                    abs(coords[0] - center[1]) < 0.5):
                    is_centroid = props.get("is_centroid", False)
                    folium.Circle(
                        location=[coords[1], coords[0]],
                        radius=1500 if is_centroid else 600,
                        color=props.get("color", "#a03cde"),
                        fill=True,
                        fill_opacity=0.15 if is_centroid else 0.08,
                        weight=0.8 if is_centroid else 0.3,
                        tooltip=(f"Cluster {props.get('cluster', '?')} centroid "
                                f"({props.get('n_points', '?')} pts)"
                                if is_centroid else
                                f"AlphaEarth cluster {props.get('cluster', '?')}"),
                    ).add_to(m)

    # Population density heatmap
    if layers.get("show_popdens", False):
        pop_points = get_pop_density_points(tuple(center), radius_deg=0.3, n_points=200)
        if pop_points:
            heat_data = [[lat, lon, w] for lat, lon, w in pop_points]
            HeatMap(
                heat_data, name="Population Density",
                min_opacity=0.15, radius=12, blur=10,
                gradient={"0.2": "#fce7f3", "0.5": "#f472b6", "0.8": "#db2777", "1.0": "#9d174d"},
            ).add_to(m)

    # Raster overlays
    for raster_key, layer_key in [("dem", "show_dem"), ("slope", "show_slope"),
                                   ("flood_risk", "show_cvi")]:
        if layers.get(layer_key, False):
            overlay = get_raster_overlay(raster_key)
            if overlay:
                folium.raster_layers.ImageOverlay(
                    image=f"data:image/png;base64,{overlay['image_base64']}",
                    bounds=overlay["bounds"],
                    name=raster_key.replace("_", " ").title(),
                    opacity=0.6,
                ).add_to(m)

    # Batch kriging CI for all assets
    ci_coords = tuple((a[0], a[1], a[4]) for a in assets)
    ci_values = get_kriging_ci_batch(ci_coords) if ci_coords else []

    # MarkerCluster with gauge popups — same as pipeline map
    marker_cluster = MarkerCluster(
        name="Infrastructure",
        options={
            "maxClusterRadius": 40,
            "spiderfyOnMaxZoom": True,
            "showCoverageOnHover": False,
        },
    )

    for idx, (lat, lon, name, atype, score) in enumerate(assets):
        show = True
        if atype == "hospital" and not layers.get("osm_hospitals", True):
            show = False
        if atype == "bridge"   and not layers.get("osm_bridges",   True):
            show = False
        if atype == "school"   and not layers.get("osm_schools",   True):
            show = False
        if atype == "road"     and not layers.get("osm_roads",     True):
            show = False
        if not show:
            continue

        type_color = TYPE_COLORS.get(atype, "#64748b")
        risk_radius = max(4, min(12, score * 15)) if score > 0 else 5
        kriging_ci = ci_values[idx] if idx < len(ci_values) else None
        popup_html = _gauge_popup(name, atype, score, idx + 1, "", kriging_ci=kriging_ci)

        folium.CircleMarker(
            location=[lat, lon],
            radius=risk_radius,
            color=type_color,
            fill=True,
            fill_color=type_color,
            fill_opacity=0.7,
            weight=1.5,
            popup=folium.Popup(popup_html, max_width=240),
            tooltip=f"{TYPE_EMOJI.get(atype, '')} {name}",
        ).add_to(marker_cluster)

    marker_cluster.add_to(m)

    # Risk heatmap from assets
    if assets:
        heat_data = [[a[0], a[1], a[4]] for a in assets if a[4] > 0.1]
        if heat_data:
            HeatMap(
                heat_data, name="Flood Risk Heatmap",
                min_opacity=0.25, radius=18, blur=12,
                gradient={"0.2": "#0ea5e9", "0.4": "#22c55e",
                          "0.6": "#eab308", "0.8": "#f59e0b", "1.0": "#ef4444"},
            ).add_to(m)

    # LULC legend
    if layers.get("show_lulc", False):
        legend_html = """
        <div style="position:fixed;bottom:30px;left:30px;z-index:9999;
                    background:#0d1f2d;border:1px solid #1e3a52;border-radius:6px;
                    padding:8px 12px;font-size:10px;font-family:monospace;color:#a0c0d8;">
          <b style="color:#00d4ff;">LULC</b><br>
          <span style="color:#3cdea0;">|</span> Cropland &nbsp;
          <span style="color:#00d4ff;">|</span> Water &nbsp;
          <span style="color:#8a6a1a;">|</span> Built-up &nbsp;
          <span style="color:#4a7a4a;">|</span> Forest
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

    # DEM legend
    if layers.get("show_dem", False):
        dem_html = """
        <div style="position:fixed;bottom:30px;right:30px;z-index:9999;
                    background:#0d1f2d;border:1px solid #1e3a52;border-radius:6px;
                    padding:8px 12px;font-size:10px;font-family:monospace;color:#a0c0d8;">
          <b style="color:#00d4ff;">Elevation (SRTM 30m)</b><br>
          Low ------- High<br>
          <span style="color:#8ab4d4;">0m to 100m+ (simulated)</span>
        </div>
        """
        m.get_root().html.add_child(folium.Element(dem_html))

    # Risk color legend
    risk_legend = """
    <div style="position:fixed;top:80px;right:10px;z-index:9999;
                background:#0d1f2d;border:1px solid #1e3a52;border-radius:6px;
                padding:8px 12px;font-size:10px;font-family:monospace;color:#a0c0d8;">
      <b style="color:#00d4ff;">Risk Score</b><br>
      <span style="color:#3cdea0;">o</span> Very Low (&lt;0.20)<br>
      <span style="color:#3a9a3a;">o</span> Low (0.20-0.40)<br>
      <span style="color:#dea03c;">o</span> Moderate (0.40-0.60)<br>
      <span style="color:#de7a3c;">o</span> High (0.60-0.80)<br>
      <span style="color:#de3c3c;">o</span> Very High (&gt;0.80)
    </div>
    """
    m.get_root().html.add_child(folium.Element(risk_legend))

    folium.LayerControl(collapsed=True).add_to(m)
    return st_folium_fn(m, width="100%", height=480, key=map_key, returned_objects=[])
