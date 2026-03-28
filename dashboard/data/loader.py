"""
Central data loader — tries real pipeline outputs first, falls back to
mock data from constants.py. Dashboard components call these functions
so they never break regardless of pipeline state.
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import streamlit as st

from dashboard.data.constants import (
    DATA_SOURCES,
    MOCK_UPAZILA_RISK,
    MOCK_LANDSLIDE_UPAZILA,
    EMERGENCY_SHELTERS,
    LANDSLIDE_DATA,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("data/output")
PROCESSED_DIR = Path("data/processed")
RAW_DIR = Path("data/raw")
CACHE_DIR = Path("data/cache")


# ── Fast GeoDataFrame loader (parquet > geojson) ────────────────────────────

@st.cache_data(ttl=600)
def load_gdf_fast(name: str) -> gpd.GeoDataFrame:
    """Load GeoDataFrame from parquet cache, falling back to GeoJSON."""
    parquet_path = CACHE_DIR / f"{name}.parquet"
    geojson_path = OUTPUT_DIR / f"{name}.geojson"

    if parquet_path.exists():
        gdf = gpd.read_parquet(parquet_path)
        gdf.columns = [str(c) for c in gdf.columns]
        return gdf
    elif geojson_path.exists():
        gdf = gpd.read_file(geojson_path)
        gdf.columns = [str(c) for c in gdf.columns]
        return gdf
    return gpd.GeoDataFrame()


@st.cache_data(ttl=600)
def load_heatmap_points() -> list:
    """Load pre-computed heatmap points from cache."""
    cache_path = CACHE_DIR / "heatmap_points.json"
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)
    return []


@st.cache_data(ttl=600)
def load_cached_raster_overlay(raster_name: str) -> dict | None:
    """Load pre-rendered raster overlay from cache."""
    cache_path = CACHE_DIR / f"raster_{raster_name}.json"
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)
    return None


# ── Pipeline metadata / confidence ────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_pipeline_metadata() -> dict | None:
    """Load pipeline_metadata.json if available."""
    path = OUTPUT_DIR / "pipeline_metadata.json"
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load pipeline metadata: {e}")
    return None


@st.cache_data(ttl=300)
def get_confidence_metrics() -> dict:
    """
    Return real confidence metrics from pipeline metadata,
    or computed fallback values from available outputs.
    """
    meta = load_pipeline_metadata()
    if meta and meta.get("kriging_variance_mean") is not None:
        return {
            "kriging_var": round(meta["kriging_variance_mean"], 3),
            "gnn_ci_width": round(meta.get("gnn_ci90_width") or 0.118, 3),
            "ensemble_iqr": round(meta.get("ensemble_iqr") or 0.072, 3),
            "data_density": round(meta.get("data_density_pct") or 87.4, 1),
            "source": "pipeline_metadata",
        }

    # Fallback: compute from raw outputs
    result = {
        "kriging_var": 0.043,
        "gnn_ci_width": 0.118,
        "ensemble_iqr": 0.072,
        "data_density": 87.4,
        "source": "fallback",
    }

    scores_path = OUTPUT_DIR / "gnn_risk_scores.npy"
    if scores_path.exists():
        try:
            scores = np.load(scores_path)
            q25, q75 = np.percentile(scores, [25, 75])
            result["ensemble_iqr"] = round(float(q75 - q25), 3)
            result["kriging_var"] = round(float(np.var(scores)), 3)
            result["source"] = "gnn_scores_fallback"
        except Exception:
            pass

    return result


# ── Kriging variance preload ─────────────────────────────────────────────────

@st.cache_resource
def _load_kriging_raster():
    """Preload kriging variance raster once into memory."""
    variance_path = OUTPUT_DIR / "kriging_variance.tif"
    if variance_path.exists():
        try:
            import rasterio
            with rasterio.open(variance_path) as src:
                return {
                    "data": src.read(1),
                    "transform": src.transform,
                    "crs": src.crs,
                    "nodata": src.nodata,
                    "bounds": src.bounds,
                }
        except Exception:
            pass
    return None


def get_kriging_ci_at_point(lat: float, lon: float,
                            fallback_score: float = 0.5) -> float:
    """
    Sample kriging variance at a point. Returns CI width.
    Falls back to score * 0.12 approximation.
    """
    raster = _load_kriging_raster()
    if raster is not None:
        try:
            import rasterio
            row, col = rasterio.transform.rowcol(raster["transform"], lon, lat)
            data = raster["data"]
            if 0 <= row < data.shape[0] and 0 <= col < data.shape[1]:
                val = data[row, col]
                if val != raster["nodata"] and not np.isnan(val):
                    return round(float(2 * 1.96 * np.sqrt(val)), 3)
        except Exception:
            pass

    return round(fallback_score * 0.12, 3)


# ── Batch kriging CI (for popups) ────────────────────────────────────────────

@st.cache_data(ttl=300)
def get_kriging_ci_batch(coords_and_scores: tuple) -> list[float]:
    """Compute kriging CI for a batch of (lat, lon, score) tuples at once."""
    raster = _load_kriging_raster()
    results = []
    for lat, lon, score in coords_and_scores:
        if raster is not None:
            try:
                import rasterio
                row, col = rasterio.transform.rowcol(raster["transform"], lon, lat)
                data = raster["data"]
                if 0 <= row < data.shape[0] and 0 <= col < data.shape[1]:
                    val = data[row, col]
                    if val != raster["nodata"] and not np.isnan(val):
                        results.append(round(float(2 * 1.96 * np.sqrt(val)), 3))
                        continue
            except Exception:
                pass
        results.append(round(score * 0.12, 3))
    return results


# ── Regional assets ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def get_regional_assets(region_key: str, center: tuple = None,
                        radius_deg: float = 0.5) -> list[tuple]:
    """
    Get infrastructure assets near a region center.
    Tries real risk_ranked_assets.geojson first, falls back to mock_assets.

    Returns list of (lat, lon, name, asset_type, risk_score) tuples.
    """
    geojson_path = OUTPUT_DIR / "risk_ranked_assets.geojson"
    if geojson_path.exists() and center is not None:
        try:
            gdf = gpd.read_file(geojson_path)
            lat_c, lon_c = center
            mask = (
                (gdf.geometry.y >= lat_c - radius_deg) &
                (gdf.geometry.y <= lat_c + radius_deg) &
                (gdf.geometry.x >= lon_c - radius_deg) &
                (gdf.geometry.x <= lon_c + radius_deg)
            )
            nearby = gdf[mask].head(20)
            if len(nearby) > 0:
                return [
                    (
                        row.geometry.y,
                        row.geometry.x,
                        row.get("name", "Unknown"),
                        row.get("asset_type", "unknown"),
                        float(row.get("flood_risk", 0.5)),
                    )
                    for _, row in nearby.iterrows()
                ]
        except Exception as e:
            logger.warning(f"Could not load real assets for {region_key}: {e}")

    # Fallback to mock
    region = DATA_SOURCES.get(region_key, {})
    return region.get("mock_assets", [])


# ── Upazila risk ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def get_upazila_risk(region_key: str) -> list[dict]:
    """
    Get upazila-level risk data.
    Tries real upazila_risk_summary.csv first, falls back to MOCK_UPAZILA_RISK.
    """
    csv_path = OUTPUT_DIR / "upazila_risk_summary.csv"
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            results = []
            for _, row in df.iterrows():
                name = row.get("admin_name") or row.get("NAME_2", "Unknown")
                mean_risk = float(row.get("mean_risk", 0))
                results.append({
                    "upazila": name,
                    "cvi": round(mean_risk * 0.9, 2),
                    "flood_risk": round(mean_risk, 2),
                    "pop_exposed": int(row.get("total_assets", 0) * 500),
                    "class": _risk_to_class(mean_risk),
                })
            if results:
                return results
        except Exception as e:
            logger.warning(f"Could not load real upazila risk: {e}")

    return MOCK_UPAZILA_RISK.get(region_key, [])


def _risk_to_class(risk: float) -> int:
    if risk >= 0.8:
        return 5
    elif risk >= 0.6:
        return 4
    elif risk >= 0.4:
        return 3
    elif risk >= 0.2:
        return 2
    return 1


# ── Landslide upazila ─────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def get_landslide_upazila() -> list[dict]:
    """
    Get landslide upazila data.
    Tries real landslide_upazila.json first, falls back to MOCK_LANDSLIDE_UPAZILA.
    """
    json_path = OUTPUT_DIR / "landslide_upazila.json"
    if json_path.exists():
        try:
            with open(json_path) as f:
                data = json.load(f)
            results = []
            for d in data:
                results.append({
                    "upazila": d.get("upazila", "Unknown"),
                    "susceptibility": d.get("susceptibility_mean", 0),
                    "pop_exposed": d.get("exposed_population", 0),
                    "class": d.get("cvi_class", 3),
                })
            if results:
                return results
        except Exception as e:
            logger.warning(f"Could not load real landslide data: {e}")

    return MOCK_LANDSLIDE_UPAZILA


# ── Emergency shelters ────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def get_emergency_shelters() -> list[dict]:
    """
    Get emergency shelter data from real infrastructure or fallback.
    """
    infra_path = RAW_DIR / "infrastructure_raw.gpkg"
    if infra_path.exists():
        try:
            gdf = gpd.read_file(str(infra_path))
            shelters = gdf[gdf["asset_type"] == "flood_shelter"]
            if len(shelters) > 0:
                scores_path = OUTPUT_DIR / "gnn_risk_scores.npy"
                all_scores = None
                if scores_path.exists():
                    all_scores = np.load(scores_path)

                results = []
                for i, (_, row) in enumerate(shelters.iterrows()):
                    pt = row.geometry.representative_point()
                    risk = float(all_scores[row.name]) if all_scores is not None and row.name < len(all_scores) else 0.5
                    results.append({
                        "name": row.get("name", f"Flood Shelter {i+1}"),
                        "region": row.get("division", "Unknown"),
                        "lat": pt.y,
                        "lon": pt.x,
                        "capacity": 1500,
                        "status": "OPEN",
                        "cvi_class": _risk_to_class(risk),
                    })
                if results:
                    return results
        except Exception as e:
            logger.warning(f"Could not load real shelter data: {e}")

    return EMERGENCY_SHELTERS


# ── Population density ────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def get_pop_density_points(center: tuple, radius_deg: float = 0.3,
                           n_points: int = 200) -> list[tuple]:
    """
    Sample real population density from WorldPop raster.
    Returns list of (lat, lon, density) tuples for heatmap.
    Falls back to random distribution.
    """
    pop_path = RAW_DIR / "worldpop_popdens.tif"
    if pop_path.exists():
        try:
            import rasterio
            lat_c, lon_c = center
            with rasterio.open(pop_path) as src:
                grid_side = int(n_points**0.5)
                lats = np.linspace(lat_c - radius_deg, lat_c + radius_deg, grid_side)
                lons = np.linspace(lon_c - radius_deg, lon_c + radius_deg, grid_side)
                coords = [(lon, lat) for lat in lats for lon in lons]

                vals = list(src.sample(coords))
                results = []
                for (lon, lat), v in zip(coords, vals):
                    density = float(v[0]) if v[0] != src.nodata and not np.isnan(v[0]) else 0
                    if density > 0:
                        results.append((lat, lon, density))

                if results:
                    max_d = max(r[2] for r in results)
                    if max_d > 0:
                        results = [(lat, lon, d / max_d) for lat, lon, d in results]
                    return results[:n_points]
        except Exception as e:
            logger.warning(f"Could not sample WorldPop: {e}")

    # Fallback: random
    rng = np.random.default_rng(42)
    lat_c, lon_c = center
    return [
        (lat_c + rng.normal(0, radius_deg * 0.3),
         lon_c + rng.normal(0, radius_deg * 0.3),
         rng.random())
        for _ in range(n_points)
    ]


# ── AlphaEarth clusters ──────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def get_alphaearth_clusters() -> dict | None:
    """
    Load AlphaEarth cluster GeoJSON if available.
    Returns parsed GeoJSON dict or None.
    """
    path = OUTPUT_DIR / "alphaearth_clusters.geojson"
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load AlphaEarth clusters: {e}")
    return None


# ── Raster overlay ────────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def get_raster_overlay(raster_name: str, _bounds: tuple = None) -> dict | None:
    """
    Read a GeoTIFF raster and return data for folium ImageOverlay.
    Checks pre-rendered cache first for instant loading.

    Returns dict with 'image_base64', 'bounds', 'name' or None.
    """
    # Try pre-rendered cache first (instant)
    cached = load_cached_raster_overlay(raster_name)
    if cached is not None:
        return cached

    raster_map = {
        "dem": PROCESSED_DIR / "dem_reprojected.tif",
        "slope": PROCESSED_DIR / "slope.tif",
        "hand": PROCESSED_DIR / "hand.tif",
        "flood_risk": OUTPUT_DIR / "flood_risk_kriged.tif",
        "kriging_variance": OUTPUT_DIR / "kriging_variance.tif",
        "landslide": OUTPUT_DIR / "landslide_susceptibility.tif",
    }

    path = raster_map.get(raster_name)
    if path is None or not path.exists():
        return None

    try:
        import rasterio
        import base64
        from io import BytesIO
        from matplotlib import cm
        from PIL import Image

        with rasterio.open(path) as src:
            data = src.read(1).astype(np.float32)
            raster_bounds = src.bounds

            # Handle nodata
            nodata = src.nodata
            if nodata is not None:
                data[data == nodata] = np.nan

            # Normalize to [0, 1]
            valid = data[~np.isnan(data)]
            if len(valid) == 0:
                return None
            vmin, vmax = np.percentile(valid, [2, 98])
            if vmax - vmin < 1e-6:
                return None
            norm = np.clip((data - vmin) / (vmax - vmin), 0, 1)

            # Colormap
            cmap_name = {
                "dem": "terrain",
                "slope": "YlOrRd",
                "hand": "Blues_r",
                "flood_risk": "RdYlGn_r",
                "kriging_variance": "Purples",
                "landslide": "OrRd",
            }.get(raster_name, "viridis")

            cmap = cm.get_cmap(cmap_name)
            rgba = cmap(norm)
            rgba[np.isnan(data)] = [0, 0, 0, 0]
            rgba[:, :, 3] *= 0.6

            img = Image.fromarray((rgba * 255).astype(np.uint8))
            buf = BytesIO()
            img.save(buf, format="PNG", optimize=True)
            img_base64 = base64.b64encode(buf.getvalue()).decode()

            return {
                "image_base64": img_base64,
                "bounds": [
                    [raster_bounds.bottom, raster_bounds.left],
                    [raster_bounds.top, raster_bounds.right],
                ],
                "name": raster_name,
            }
    except Exception as e:
        logger.warning(f"Could not create raster overlay for {raster_name}: {e}")
        return None
