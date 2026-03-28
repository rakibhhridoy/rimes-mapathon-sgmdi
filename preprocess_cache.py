"""
Pre-build fast binary caches from GeoJSON/GeoTIFF files.
Run once after deployment or data update:
    python preprocess_cache.py

Converts:
  - 71MB risk_grid.geojson      → ~8MB  risk_grid.parquet
  - 18MB risk_ranked_assets     → ~2MB  risk_ranked_assets.parquet
  - 584KB union_risk_summary    → ~60KB union_risk_summary.parquet
  - hotspot_clusters.geojson    → hotspot_clusters.parquet
  - Raster overlays (GeoTIFF)   → pre-rendered PNG base64 JSON
"""

import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np

OUTPUT_DIR = Path("data/output")
PROCESSED_DIR = Path("data/processed")
CACHE_DIR = Path("data/cache")


def convert_geojson_to_parquet():
    """Convert large GeoJSON files to GeoParquet for 5-10x faster loading."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    files = [
        "risk_grid.geojson",
        "risk_ranked_assets.geojson",
        "union_risk_summary.geojson",
        "hotspot_clusters.geojson",
        "upazila_risk_summary.geojson",
        "top50_risk_assets.geojson",
    ]

    for fname in files:
        src = OUTPUT_DIR / fname
        dst = CACHE_DIR / fname.replace(".geojson", ".parquet")
        if not src.exists():
            print(f"  SKIP {fname} (not found)")
            continue

        t0 = time.time()
        print(f"  Converting {fname} ({src.stat().st_size / 1024 / 1024:.1f}MB)...", end=" ", flush=True)
        gdf = gpd.read_file(src)

        # Simplify geometry for grid (reduce coordinate precision)
        if "risk_grid" in fname:
            gdf.geometry = gdf.geometry.simplify(tolerance=0.001, preserve_topology=True)

        gdf.to_parquet(dst)
        dt = time.time() - t0
        print(f"→ {dst.name} ({dst.stat().st_size / 1024 / 1024:.1f}MB) [{dt:.1f}s]")


def prerender_raster_overlays():
    """Pre-render raster overlays as base64 PNG and save to JSON cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    raster_map = {
        "dem": PROCESSED_DIR / "dem_reprojected.tif",
        "slope": PROCESSED_DIR / "slope.tif",
        "hand": PROCESSED_DIR / "hand.tif",
        "flood_risk": OUTPUT_DIR / "flood_risk_kriged.tif",
    }

    cmap_map = {
        "dem": "terrain",
        "slope": "YlOrRd",
        "hand": "Blues_r",
        "flood_risk": "RdYlGn_r",
    }

    for name, path in raster_map.items():
        dst = CACHE_DIR / f"raster_{name}.json"
        if not path.exists():
            print(f"  SKIP raster {name} (not found)")
            continue

        t0 = time.time()
        print(f"  Pre-rendering {name}...", end=" ", flush=True)

        try:
            import rasterio
            import base64
            from io import BytesIO
            from matplotlib import cm
            from PIL import Image

            with rasterio.open(path) as src:
                data = src.read(1).astype(np.float32)
                bounds = src.bounds

                nodata = src.nodata
                if nodata is not None:
                    data[data == nodata] = np.nan

                valid = data[~np.isnan(data)]
                if len(valid) == 0:
                    print("SKIP (no valid data)")
                    continue

                vmin, vmax = np.percentile(valid, [2, 98])
                if vmax - vmin < 1e-6:
                    print("SKIP (no range)")
                    continue

                norm = np.clip((data - vmin) / (vmax - vmin), 0, 1)
                cmap = cm.get_cmap(cmap_map[name])
                rgba = cmap(norm)
                rgba[np.isnan(data)] = [0, 0, 0, 0]
                rgba[:, :, 3] *= 0.6

                img = Image.fromarray((rgba * 255).astype(np.uint8))
                buf = BytesIO()
                img.save(buf, format="PNG", optimize=True)
                img_base64 = base64.b64encode(buf.getvalue()).decode()

                result = {
                    "image_base64": img_base64,
                    "bounds": [
                        [bounds.bottom, bounds.left],
                        [bounds.top, bounds.right],
                    ],
                    "name": name,
                }

                with open(dst, "w") as f:
                    json.dump(result, f)

                dt = time.time() - t0
                print(f"→ {dst.name} ({dst.stat().st_size / 1024 / 1024:.1f}MB) [{dt:.1f}s]")
        except Exception as e:
            print(f"ERROR: {e}")


def precompute_heatmap_data():
    """Extract heatmap points from risk_grid so we don't iterate 71MB at runtime."""
    src = OUTPUT_DIR / "risk_grid.geojson"
    dst = CACHE_DIR / "heatmap_points.json"
    if not src.exists():
        print("  SKIP heatmap (risk_grid not found)")
        return

    t0 = time.time()
    print("  Extracting heatmap points...", end=" ", flush=True)

    gdf = gpd.read_file(src)
    if "composite_risk" not in gdf.columns:
        print("SKIP (no composite_risk column)")
        return

    centroids = gdf.geometry.centroid
    risks = gdf["composite_risk"].values
    mask = risks > 0.1

    points = [
        [round(float(centroids.iloc[i].y), 5),
         round(float(centroids.iloc[i].x), 5),
         round(float(risks[i]), 3)]
        for i in range(len(gdf)) if mask[i]
    ]

    with open(dst, "w") as f:
        json.dump(points, f)

    dt = time.time() - t0
    print(f"→ {dst.name} ({len(points)} points) [{dt:.1f}s]")


if __name__ == "__main__":
    print("=== Fermium HazMapper — Pre-processing Cache ===\n")

    print("[1/3] Converting GeoJSON → GeoParquet:")
    convert_geojson_to_parquet()

    print("\n[2/3] Pre-rendering raster overlays:")
    prerender_raster_overlays()

    print("\n[3/3] Pre-computing heatmap data:")
    precompute_heatmap_data()

    print("\nDone! Cache files in data/cache/")
