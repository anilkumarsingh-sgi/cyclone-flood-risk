"""
Update 'Final STFI Data latlong FM global Updated.xlsx' with a new column
"Risk by our model" computed from the flood model (JRC GloFAS RP100) for each
(Latitude, Longitude) pair, in every sheet. Preserves all existing columns.
"""
import os
import re
import sys
import time
import pandas as pd
import ee
from openpyxl import load_workbook


_COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def parse_coord(value, is_lat: bool):
    """Parse coord that may be float or string like '30.9010° N' / '75.8573° E'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if pd.isna(value):
            return None
        return float(value)
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    m = _COORD_RE.search(s)
    if not m:
        return None
    val = float(m.group(1))
    up = s.upper()
    if is_lat and "S" in up:
        val = -abs(val)
    if (not is_lat) and "W" in up:
        val = -abs(val)
    return val

SRC = r"F:\Cyclone and Flood\Final STFI Data latlong FM global Updated.xlsx"
OUT = r"F:\Cyclone and Flood\Final STFI Data latlong FM global Updated_with_model.xlsx"
NEW_COL = "Risk by our model"
BAND = "RP100_depth"
BUFFER_M = 1000  # 1 km buffer to catch nearby riverine pixels


def init_ee():
    try:
        ee.Initialize(project="ee-singhanil854")
    except Exception:
        ee.Authenticate()
        ee.Initialize(project="ee-singhanil854")


def classify_depth(depth_m: float) -> str:
    if depth_m is None or depth_m <= 0:
        return "No Risk"
    if depth_m < 0.5:
        return "Low"
    if depth_m < 2.0:
        return "Moderate"
    if depth_m < 4.0:
        return "High"
    return "Severe"


# Slope-based flood risk (lower slope = water pools = higher risk).
# Thresholds in degrees, derived from common hydrology practice on SRTM 30m.
def classify_slope(slope_deg):
    if slope_deg is None:
        return "Unknown"
    if slope_deg < 1.0:
        return "Severe"      # near-flat: ponding / inundation prone
    if slope_deg < 3.0:
        return "High"
    if slope_deg < 8.0:
        return "Moderate"
    if slope_deg < 15.0:
        return "Low"
    return "No Risk"          # steep terrain, water runs off


_RISK_RANK = {"No Risk": 0, "Low": 1, "Moderate": 2, "High": 3, "Severe": 4, "Unknown": 0}
_RANK_RISK = {v: k for k, v in _RISK_RANK.items() if k != "Unknown"}


def combine_risk(flood_level: str, slope_level: str) -> str:
    """Combined model risk = max of flood-depth risk and slope risk."""
    f = _RISK_RANK.get(flood_level, 0)
    s = _RISK_RANK.get(slope_level, 0)
    return _RANK_RISK[max(f, s)]


def get_slope(lat: float, lon: float, slope_image) -> float | None:
    """Local terrain slope (mean within ~90 m of the point) in degrees."""
    point = ee.Geometry.Point([lon, lat])
    geom = point.buffer(90)
    sampled = slope_image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom,
        scale=30,
        bestEffort=True,
    )
    result = sampled.getInfo()
    val = result.get("slope")
    if val is None:
        return None
    return round(float(val), 3)


def get_flood_risk(lat: float, lon: float, flood_image) -> dict:
    point = ee.Geometry.Point([lon, lat])
    geom = point.buffer(BUFFER_M) if BUFFER_M > 0 else point
    # Use MAX within buffer so nearby riverine flood pixels dominate (worst-case,
    # similar in spirit to FM Global flood-zone exposure framing).
    sampled = flood_image.reduceRegion(
        reducer=ee.Reducer.max(),
        geometry=geom,
        scale=90,
        bestEffort=True,
    )
    result = sampled.getInfo()
    depth_val = result.get(BAND)
    if depth_val is None:
        return {"depth_m": None, "risk_level": "No Risk"}
    depth_m = round(float(depth_val), 3)
    return {"depth_m": depth_m, "risk_level": classify_depth(depth_m)}


def main():
    print("Initializing Earth Engine...")
    init_ee()
    flood_image = ee.ImageCollection("JRC/CEMS_GLOFAS/FloodHazard/v2_1").mosaic().select(BAND)
    dem = ee.Image("USGS/SRTMGL1_003")
    slope_image = ee.Terrain.slope(dem).rename("slope")

    xl = pd.ExcelFile(SRC)
    print("Sheets:", xl.sheet_names)

    # Cache by rounded (lat,lon) to avoid duplicate EE calls
    cache: dict = {}

    output_sheets: dict[str, pd.DataFrame] = {}

    for sheet in xl.sheet_names:
        df = pd.read_excel(xl, sheet_name=sheet)
        print(f"\n=== Sheet: {sheet} | rows: {len(df)} ===")

        risk_levels = []
        depths = []
        slopes = []
        slope_levels = []
        flood_levels = []

        for idx, row in df.iterrows():
            lat = row.get("Latitude")
            lon = row.get("Longitude")
            lat_f = parse_coord(lat, is_lat=True)
            lon_f = parse_coord(lon, is_lat=False)
            if lat_f is None or lon_f is None:
                risk_levels.append(None)
                depths.append(None)
                slopes.append(None)
                slope_levels.append(None)
                flood_levels.append(None)
                continue

            key = (round(lat_f, 5), round(lon_f, 5))
            if key in cache:
                res = cache[key]
            else:
                # Retry on transient EE errors
                last_err = None
                res = None
                for attempt in range(3):
                    try:
                        flood = get_flood_risk(lat_f, lon_f, flood_image)
                        slope_deg = get_slope(lat_f, lon_f, slope_image)
                        slope_lvl = classify_slope(slope_deg)
                        combined = combine_risk(flood["risk_level"], slope_lvl)
                        res = {
                            "depth_m": flood["depth_m"],
                            "flood_level": flood["risk_level"],
                            "slope_deg": slope_deg,
                            "slope_level": slope_lvl,
                            "risk_level": combined,
                        }
                        break
                    except Exception as e:
                        last_err = e
                        time.sleep(2 ** attempt)
                if res is None:
                    print(f"  row {idx}: ERROR {last_err}")
                    res = {"depth_m": None, "flood_level": "Error", "slope_deg": None,
                           "slope_level": "Unknown", "risk_level": "Error"}
                cache[key] = res

            risk_levels.append(res["risk_level"])
            depths.append(res["depth_m"])
            slopes.append(res["slope_deg"])
            slope_levels.append(res["slope_level"])
            flood_levels.append(res["flood_level"])
            print(f"  row {idx}: ({lat_f:.4f},{lon_f:.4f}) "
                  f"depth={res['depth_m']}({res['flood_level']}) "
                  f"slope={res['slope_deg']}°({res['slope_level']}) -> {res['risk_level']}")

        # Insert new columns right after the FM Global column for easy comparison
        fm_cols = [c for c in df.columns if "fm global" in c.lower() or "flood exposure" in c.lower()]
        df[NEW_COL] = risk_levels
        df["Flood depth risk (RP100)"] = flood_levels
        df["Flood depth m (RP100)"] = depths
        df["Slope risk"] = slope_levels
        df["Slope (deg)"] = slopes

        new_cols_order = [
            NEW_COL,
            "Flood depth risk (RP100)",
            "Flood depth m (RP100)",
            "Slope risk",
            "Slope (deg)",
        ]

        if fm_cols:
            fm_idx = df.columns.get_loc(fm_cols[0])
            cols = list(df.columns)
            for nc in reversed(new_cols_order):
                cols.remove(nc)
                cols.insert(fm_idx + 1, nc)
            df = df[cols]

        output_sheets[sheet] = df

    print(f"\nWriting output to: {OUT}")
    with pd.ExcelWriter(OUT, engine="openpyxl") as writer:
        for name, df in output_sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)

    print("Done.")


if __name__ == "__main__":
    main()
