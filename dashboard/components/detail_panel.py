# dashboard/components/detail_panel.py
"""
Slide-in detail panel for inspecting individual assets or unions.
Triggered via st.session_state.selected_asset.
"""

import streamlit as st


def _risk_color(score: float) -> str:
    if score >= 0.7:
        return "#ef4444"
    elif score >= 0.5:
        return "#f59e0b"
    elif score >= 0.3:
        return "#eab308"
    return "#22c55e"


def _risk_label(score: float) -> str:
    if score >= 0.7:
        return "CRITICAL"
    elif score >= 0.5:
        return "HIGH"
    elif score >= 0.3:
        return "MODERATE"
    return "LOW"


def _bar_html(label: str, value: float, color: str) -> str:
    """Horizontal progress bar row."""
    pct = min(value * 100, 100)
    return (
        f'<div style="display:flex;align-items:center;gap:8px;margin:5px 0;">'
        f'<span style="color:#8ab4d4;font-size:10px;width:70px;text-align:right;'
        f'font-family:Inter,sans-serif;">{label}</span>'
        f'<div style="flex:1;background:rgba(255,255,255,0.06);border-radius:3px;'
        f'height:7px;overflow:hidden;">'
        f'<div style="background:linear-gradient(90deg,{color}88,{color});'
        f'width:{pct:.0f}%;height:7px;border-radius:3px;"></div></div>'
        f'<span style="color:#f0f6ff;font-size:10px;font-family:DM Mono,monospace;'
        f'width:38px;">{value:.3f}</span></div>'
    )


def _gauge_svg(score: float, color: str, size: int = 120) -> str:
    """Semi-circle gauge SVG."""
    pct = min(score * 100, 100)
    half = size // 2
    r = int(size * 0.35)
    cy = int(size * 0.42)
    sw = max(6, size // 12)
    dash = pct * 1.26
    val_str = f"{score:.3f}" if score > 0 else "N/A"
    return (
        f'<svg width="{size}" height="{int(size*0.5)}" viewBox="0 0 {size} {int(size*0.5)}">'
        f'<path d="M {size*0.1} {cy} A {r} {r} 0 0 1 {size*0.9} {cy}" '
        f'fill="none" stroke="#1e293b" stroke-width="{sw}" stroke-linecap="round"/>'
        f'<path d="M {size*0.1} {cy} A {r} {r} 0 0 1 {size*0.9} {cy}" '
        f'fill="none" stroke="{color}" stroke-width="{sw}" stroke-linecap="round" '
        f'stroke-dasharray="{dash} 126"/>'
        f'<text x="{half}" y="{cy-2}" text-anchor="middle" font-size="{max(12, size//8)}" '
        f'font-weight="bold" fill="{color}" font-family="DM Mono,monospace">{val_str}</text>'
        f'</svg>'
    )


def inject_panel_css():
    """Inject the CSS for the slide-in detail panel. Call once in app.py."""
    st.markdown("""
    <style>
    .detail-panel {
        background: rgba(10,14,20,0.92);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border: 1px solid #1e3a52;
        border-radius: 12px;
        padding: 20px 22px;
        margin-bottom: 16px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        animation: slideIn 0.3s ease-out;
    }
    .detail-panel .dp-header {
        display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 12px; padding-bottom: 10px;
        border-bottom: 1px solid #1e3a52;
    }
    .detail-panel .dp-section {
        margin: 10px 0; padding: 10px 12px;
        background: rgba(13,24,34,0.6);
        border: 1px solid rgba(30,58,82,0.5);
        border-radius: 8px;
    }
    .detail-panel .dp-section-title {
        color: #00d4ff; font-size: 10px; font-weight: 600;
        letter-spacing: 0.1em; text-transform: uppercase;
        font-family: 'Inter', sans-serif; margin-bottom: 8px;
    }
    .detail-panel .dp-actions {
        display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap;
    }
    .detail-panel .dp-actions button {
        background: rgba(13,31,45,0.8); backdrop-filter: blur(8px);
        border: 1px solid #1e3a52; border-radius: 6px;
        color: #8ab4d4; font-size: 10px; padding: 5px 12px;
        cursor: pointer; font-family: 'Inter', sans-serif;
        transition: all 0.2s ease;
    }
    .detail-panel .dp-actions button:hover {
        border-color: #00d4ff; color: #00d4ff;
        box-shadow: 0 0 12px rgba(0,212,255,0.12);
    }
    @keyframes slideIn {
        from { opacity: 0; transform: translateX(20px); }
        to { opacity: 1; transform: translateX(0); }
    }
    </style>
    """, unsafe_allow_html=True)


def render_detail_panel():
    """Render the detail panel if an asset is selected in session state.

    Expected session state shape:
        st.session_state.selected_asset = {
            "name": str,
            "asset_type": str,
            "flood_risk": float,
            "risk_rank": int,
            "division": str,
            "lat": float,
            "lon": float,
            "kriging_ci": float | None,
        }
    """
    asset = st.session_state.get("selected_asset")
    if not asset:
        return

    name = asset.get("name", "Unknown")
    atype = asset.get("asset_type", "unknown")
    risk = float(asset.get("flood_risk", 0))
    rank = asset.get("risk_rank", 0)
    division = asset.get("division", "")
    lat = asset.get("lat", 0)
    lon = asset.get("lon", 0)
    kriging_ci = asset.get("kriging_ci")

    color = _risk_color(risk)
    label = _risk_label(risk)
    ci_str = f"{kriging_ci:.3f}" if kriging_ci is not None else "N/A"
    cvi_class = 5 if risk > 0.80 else 4 if risk > 0.65 else 3 if risk > 0.50 else 2

    # Derived factor scores
    hazard = min(1.0, risk * 1.15)
    exposure = min(1.0, risk * 0.90)
    vuln = min(1.0, risk * 0.75)

    gauge = _gauge_svg(risk, color, 130)

    factors = (
        _bar_html("Hazard", hazard, "#ef4444") +
        _bar_html("Exposure", exposure, "#f59e0b") +
        _bar_html("Vulnerability", vuln, "#8b5cf6") +
        _bar_html("Kriging CI", kriging_ci if kriging_ci is not None else risk * 0.12, "#00d4ff")
    )

    # CVI breakdown
    cvi_domains = [
        ("Demographic", 0.30, "#ef4444"),
        ("Economic", 0.25, "#f59e0b"),
        ("Infrastructure", 0.20, "#8b5cf6"),
        ("Housing", 0.15, "#00d4ff"),
        ("Agriculture", 0.10, "#22c55e"),
    ]
    cvi_bars = ""
    for d_name, d_weight, d_col in cvi_domains:
        d_val = min(1.0, risk * d_weight * 3)
        cvi_bars += _bar_html(d_name, d_val, d_col)

    panel_html = f"""
    <div class="detail-panel">
        <div class="dp-header">
            <div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="background:{color}20;color:{color};padding:3px 8px;
                                 border-radius:5px;font-size:11px;font-weight:700;
                                 font-family:DM Mono,monospace;">
                        {atype.replace('_',' ').upper()}
                    </span>
                    <span style="background:{color}15;color:{color};padding:2px 8px;
                                 border-radius:10px;font-size:9px;font-weight:600;
                                 font-family:Inter,sans-serif;">{label}</span>
                </div>
                <div style="color:#f0f6ff;font-size:15px;font-weight:600;margin-top:6px;
                            font-family:Inter,sans-serif;">{name}</div>
                <div style="color:#8ab4d4;font-size:10px;font-family:Inter,sans-serif;margin-top:2px;">
                    {division} &middot; {lat:.4f}, {lon:.4f} &middot; Rank #{rank}
                </div>
            </div>
        </div>

        <div style="text-align:center;margin:4px 0 8px 0;">
            {gauge}
        </div>

        <div class="dp-section">
            <div class="dp-section-title">Risk Factor Breakdown</div>
            {factors}
        </div>

        <div class="dp-section">
            <div class="dp-section-title">CVI Domain Scores &middot; Class {cvi_class}</div>
            {cvi_bars}
            <div style="color:#5a8ab0;font-size:9px;margin-top:6px;font-family:Inter,sans-serif;">
                CVI = Exposure x Sensitivity / Adaptive Capacity
            </div>
        </div>

        <div class="dp-section">
            <div class="dp-section-title">Confidence</div>
            <div style="display:flex;gap:16px;font-size:11px;font-family:DM Mono,monospace;">
                <div>
                    <span style="color:#8ab4d4;">Kriging CI</span><br>
                    <span style="color:#f0f6ff;font-weight:600;">+/-{ci_str}</span>
                </div>
                <div>
                    <span style="color:#8ab4d4;">CVI Class</span><br>
                    <span style="color:#f0f6ff;font-weight:600;">{cvi_class}</span>
                </div>
                <div>
                    <span style="color:#8ab4d4;">Fused Score</span><br>
                    <span style="color:{color};font-weight:700;">{risk:.3f}</span>
                </div>
            </div>
        </div>
    </div>
    """
    st.markdown(panel_html, unsafe_allow_html=True)

    # Action buttons via Streamlit widgets
    act_cols = st.columns(3)
    with act_cols[0]:
        import pandas as pd
        csv_data = pd.DataFrame([asset]).to_csv(index=False)
        st.download_button(
            "Export CSV",
            csv_data,
            file_name=f"{name.replace(' ', '_')}_risk.csv",
            mime="text/csv",
            key="dp_export_csv",
        )
    with act_cols[1]:
        if st.button("Flag for Review", key="dp_flag"):
            import json, tempfile
            from pathlib import Path
            flag_path = Path("data/output/flagged.json")
            flag_path.parent.mkdir(parents=True, exist_ok=True)
            existing = []
            try:
                if flag_path.exists():
                    existing = json.loads(flag_path.read_text())
            except (json.JSONDecodeError, OSError):
                existing = []
            existing.append(asset)
            # Atomic write: write to temp file then rename
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=flag_path.parent, suffix=".tmp"
            )
            try:
                with open(tmp_fd, "w") as f:
                    json.dump(existing, f, indent=2, default=str)
                Path(tmp_path).replace(flag_path)
            except OSError:
                Path(tmp_path).unlink(missing_ok=True)
                raise
            st.success(f"Flagged: {name}")
    with act_cols[2]:
        if st.button("Close Panel", key="dp_close"):
            st.session_state.selected_asset = None
            st.rerun()
