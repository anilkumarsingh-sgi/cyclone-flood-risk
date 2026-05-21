"""
╔══════════════════════════════════════════════════════════════════╗
║   NATURAL CATASTROPHE INSURANCE UNDERWRITING DECISION ENGINE   ║
║   Cyclone & Flood Multi-Peril Risk Assessment Platform         ║
║   Powered by Google Earth Engine + Streamlit                   ║
╚══════════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import ee
import json
import math
import os
import folium
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from streamlit_folium import st_folium
from datetime import datetime, date
from io import BytesIO

import history_db
from pdf_report import build_assessment_pdf, build_history_pdf

# ──────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NatCat Underwriting Engine",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────
# CUSTOM CSS
# ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Global */
    .main .block-container { padding-top: 1rem; max-width: 1400px; }

    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.2rem; border-radius: 12px; color: white;
        text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .metric-card h3 { margin: 0; font-size: 0.85rem; opacity: 0.9; }
    .metric-card h1 { margin: 0.3rem 0 0 0; font-size: 1.8rem; }

    .metric-green  { background: linear-gradient(135deg, #11998e, #38ef7d); }
    .metric-yellow { background: linear-gradient(135deg, #F09819, #EDDE5D); color: #333; }
    .metric-orange { background: linear-gradient(135deg, #eb3349, #f45c43); }
    .metric-red    { background: linear-gradient(135deg, #C33764, #1D2671); }
    .metric-blue   { background: linear-gradient(135deg, #1565C0, #1E88E5); }

    /* Risk badge */
    .risk-badge {
        display: inline-block; padding: 6px 18px; border-radius: 20px;
        font-weight: 700; font-size: 0.95rem; letter-spacing: 0.5px;
    }
    .risk-low      { background: #2ecc71; color: white; }
    .risk-moderate { background: #f1c40f; color: #333; }
    .risk-high     { background: #e67e22; color: white; }
    .risk-veryhigh { background: #e74c3c; color: white; }
    .risk-extreme  { background: #6c3483; color: white; }

    /* Decision banner */
    .decision-accept {
        background: linear-gradient(135deg, #11998e, #38ef7d);
        padding: 2rem; border-radius: 16px; text-align: center; color: white;
    }
    .decision-refer {
        background: linear-gradient(135deg, #F09819, #EDDE5D);
        padding: 2rem; border-radius: 16px; text-align: center; color: #333;
    }
    .decision-decline {
        background: linear-gradient(135deg, #C33764, #1D2671);
        padding: 2rem; border-radius: 16px; text-align: center; color: white;
    }

    /* Section dividers */
    .section-header {
        border-left: 4px solid #1565C0; padding-left: 12px;
        margin: 1.5rem 0 1rem 0;
    }

    /* Table styling */
    .dataframe { font-size: 0.85rem; }

    /* Hide Streamlit branding */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# CONFIGURATION & CONSTANTS
# ══════════════════════════════════════════════════════════════════

# Cyclone risk thresholds (from cyclone.js classification)
CYCLONE_RISK_THRESHOLDS = {
    "Low":       (0, 20),
    "Moderate":  (20, 40),
    "High":      (40, 60),
    "Very High": (60, 80),
    "Extreme":   (80, 100),
}

# Flood depth thresholds (from flood.js classification)
FLOOD_RISK_THRESHOLDS = {
    "No Risk":   (None, 0),
    "Low":       (0, 0.5),
    "Moderate":  (0.5, 2.0),
    "High":      (2.0, 4.0),
    "Severe":    (4.0, float("inf")),
}

# DEM (Digital Elevation Model) risk thresholds (from JAXA ALOS AW3D30 V4_1)
# Low-lying areas (< 50m) have highest flood risk during cyclones & extreme rainfall
DEM_RISK_THRESHOLDS = {
    "Very High Risk":  (None, 10),      # < 10m: Critical flood vulnerability
    "High Risk":       (10, 25),        # 10-25m: Significant inundation risk
    "Moderate Risk":   (25, 50),        # 25-50m: Moderate vulnerability
    "Low Risk":        (50, 100),       # 50-100m: Low vulnerability
    "Very Low Risk":   (100, float("inf")),  # > 100m: Minimal vulnerability
}

# DEM 8-class visualization bands (meters) for separate map view
DEM_MAP_CLASSES = [
    (None, 5, "Class 1: <5m (Extreme Low-Lying)"),
    (5, 10, "Class 2: 5-10m"),
    (10, 20, "Class 3: 10-20m"),
    (20, 35, "Class 4: 20-35m"),
    (35, 50, "Class 5: 35-50m"),
    (50, 100, "Class 6: 50-100m"),
    (100, 200, "Class 7: 100-200m"),
    (200, float("inf"), "Class 8: >200m"),
]

# DEM-based loading factors (elevation affects flood/cyclone damage)
DEM_LOADING = {
    "Very High Risk": 0.40,    # Add 40% to NatCat premiums for areas < 10m
    "High Risk": 0.25,          # Add 25% for 10-25m elevation
    "Moderate Risk": 0.10,      # Add 10% for 25-50m elevation
    "Low Risk": 0.00,           # No additional loading for 50-100m
    "Very Low Risk": -0.05,     # 5% discount for areas > 100m (lower risk)
}

# Return periods available (from flood.js)
RETURN_PERIODS = {
    "10 Year (Frequent)":  "RP10_depth",
    "20 Year":             "RP20_depth",
    "50 Year":             "RP50_depth",
    "75 Year":             "RP75_depth",
    "100 Year":            "RP100_depth",
    "200 Year (Rare)":     "RP200_depth",
    "500 Year (Extreme)":  "RP500_depth",
}

# Premium loading factors by risk level
CYCLONE_LOADING = {
    "Low": 0.00, "Moderate": 0.15, "High": 0.35,
    "Very High": 0.60, "Extreme": 1.00,
}
FLOOD_LOADING = {
    "No Risk": 0.00, "Low": 0.05, "Moderate": 0.20,
    "High": 0.45, "Severe": 0.80,
}

# Construction type factors
CONSTRUCTION_FACTORS = {
    "RCC (Reinforced Concrete)": 1.00,
    "Steel Frame":               1.05,
    "Load Bearing":              1.15,
    "Brick/Masonry":             1.25,
    "Wood Frame":                1.45,
    "Kutcha/Temporary":          1.80,
}

# Occupancy factors
OCCUPANCY_FACTORS = {
    "Residential":              1.00,
    "Commercial - Office":      1.05,
    "Commercial - Retail":      1.10,
    "Industrial - Light":       1.15,
    "Industrial - Heavy":       1.25,
    "Warehouse/Storage":        1.20,
    "Hospital/Healthcare":      1.30,
    "Educational":              1.10,
    "Government":               1.00,
}

# Building age factors
AGE_FACTORS = {
    "0-5 years":   1.00,
    "6-10 years":  1.05,
    "11-20 years": 1.12,
    "21-30 years": 1.20,
    "31-50 years": 1.35,
    "50+ years":   1.50,
}

# Floor level factor (flood specific)
FLOOR_FACTORS = {
    "Basement":      1.60,
    "Ground Floor":  1.40,
    "1st Floor":     1.10,
    "2nd Floor":     1.00,
    "3rd Floor+":    0.95,
}

# Proximity to coast factor (cyclone specific)
COAST_FACTORS = {
    "< 5 km":   1.50,
    "5-20 km":  1.30,
    "20-50 km": 1.15,
    "50-100 km": 1.05,
    "> 100 km": 1.00,
}

# Underwriting decision thresholds
DECISION_MATRIX = {
    "auto_accept":    (0, 30),
    "accept_terms":   (30, 50),
    "refer_senior":   (50, 70),
    "refer_chief":    (70, 85),
    "decline":        (85, 100),
}

# ──────────────────────────────────────────────────────────────────
# HAZARDOUS POI (Places API) CONFIGURATION
# ──────────────────────────────────────────────────────────────────
# High-risk neighbouring assets that increase fire / explosion / spillover
# risk for the insured property. Each category maps to:
#   query   : Google Places "Text Search" query string
#   weight  : per-occurrence risk weight (added to hazard score, capped)
#   color   : marker colour on the folium map
#   icon    : font-awesome icon name
HAZARDOUS_POI_CATEGORIES = {
    "Petrol / Fuel Station":     {"query": "petrol pump OR gas station",        "weight": 6,  "color": "orange",   "icon": "gas-pump"},
    "Oil Refinery":              {"query": "oil refinery",                       "weight": 25, "color": "darkred",  "icon": "industry"},
    "Chemical Factory / Plant":  {"query": "chemical factory OR chemical plant", "weight": 18, "color": "red",      "icon": "flask"},
    "Industrial Factory":        {"query": "factory OR manufacturing plant",     "weight": 8,  "color": "cadetblue","icon": "industry"},
    "LPG / Gas Godown":          {"query": "LPG godown OR gas cylinder agency",  "weight": 15, "color": "orange",   "icon": "fire"},
    "Fuel / Oil Depot":          {"query": "fuel depot OR oil depot",            "weight": 20, "color": "darkred",  "icon": "oil-can"},
    "Power Plant":               {"query": "power plant OR thermal power station","weight": 12,"color": "purple",   "icon": "bolt"},
    "Warehouse / Storage":       {"query": "warehouse OR godown",                "weight": 4,  "color": "blue",     "icon": "warehouse"},
    "Firework / Explosive Unit": {"query": "firework factory OR explosives",     "weight": 22, "color": "darkred",  "icon": "bomb"},
}

# POI hazard score → premium loading mapping
POI_LOADING = {
    "None":      0.00,   # score 0
    "Low":       0.05,   # 1-15
    "Moderate":  0.15,   # 15-35
    "High":      0.30,   # 35-60
    "Severe":    0.50,   # 60+
}

# Distance-based proximity bands (in metres) → risk multiplier on POI weight.
# Very-near hazards contribute their full weight; far hazards contribute very little.
PROXIMITY_BANDS = [
    # (max_distance_m, band_label,    multiplier, color,        marker_color)
    (100,             "Very Near",    1.00,       "#b71c1c",    "darkred"),
    (250,             "Near",         0.70,       "#e64a19",    "red"),
    (400,             "Mid-range",    0.40,       "#f9a825",    "orange"),
    (500,             "Far",          0.15,       "#fbc02d",    "beige"),
]


def classify_proximity(distance_m: float, radius_m: int) -> dict:
    """Map a POI distance to a proximity band (label, multiplier, color)."""
    # Scale band cut-offs to the user-chosen radius (default 500 m).
    scale = radius_m / 500.0
    for max_d, label, mult, color, marker in PROXIMITY_BANDS:
        if distance_m <= max_d * scale:
            return {
                "band": label,
                "multiplier": mult,
                "band_color": color,
                "marker_color": marker,
            }
    # Outside the configured radius (shouldn't happen, but safe default)
    return {"band": "Out of Range", "multiplier": 0.0,
            "band_color": "#9e9e9e", "marker_color": "lightgray"}

# Key Indian cities for quick lookup
REFERENCE_LOCATIONS = {
    "Mumbai":          (19.0760, 72.8777),
    "Chennai":         (13.0827, 80.2707),
    "Kolkata":         (22.5726, 88.3639),
    "Visakhapatnam":   (17.6868, 83.2185),
    "Bhubaneswar":     (20.2961, 85.8245),
    "Puri":            (19.8135, 85.8312),
    "Surat":           (21.1702, 72.8311),
    "Mangalore":       (12.9141, 74.8560),
    "Kochi":           (9.9312, 76.2673),
    "Thiruvananthapuram": (8.5241, 76.9366),
    "Goa (Panaji)":    (15.4909, 73.8278),
    "Puducherry":      (11.9416, 79.8083),
    "Ratnagiri":       (16.9902, 73.3120),
    "Machilipatnam":   (16.1875, 81.1389),
    "Paradip":         (20.3165, 86.6114),
    "New Delhi":       (28.6139, 77.2090),
    "Bengaluru":       (12.9716, 77.5946),
    "Hyderabad":       (17.3850, 78.4867),
    "Ahmedabad":       (23.0225, 72.5714),
    "Jaipur":          (26.9124, 75.7873),
}


# ══════════════════════════════════════════════════════════════════
# EARTH ENGINE INITIALIZATION
# ══════════════════════════════════════════════════════════════════

@st.cache_resource
def init_earth_engine():
    """Initialize Google Earth Engine with authentication."""
    try:
        # Use service account credentials from secrets.toml / Streamlit Cloud.
        # Supports both [earthengine] and [json_key] section names.
        if "earthengine" in st.secrets or "json_key" in st.secrets:  # type: ignore[operator]
            from google.oauth2 import service_account as _sa
            sec = st.secrets.get("earthengine", st.secrets.get("json_key"))  # type: ignore[attr-defined]
            if not sec:
                raise RuntimeError("Missing service account secret block.")

            private_key = sec["private_key"]
            # Handle escaped newlines when key is provided as a single-line string.
            private_key = private_key.replace("\\n", "\n")

            key_dict = {
                "type": sec.get("type", "service_account"),  # type: ignore[union-attr]
                "project_id": sec.get("project_id", "ee-singhanil854"),  # type: ignore[union-attr]
                "client_email": sec["client_email"],
                "private_key": private_key,
                "private_key_id": sec.get("private_key_id", ""),  # type: ignore[union-attr]
                "token_uri": sec.get("token_uri", "https://oauth2.googleapis.com/token"),  # type: ignore[union-attr]
            }
            credentials = _sa.Credentials.from_service_account_info(
                key_dict,
                scopes=["https://www.googleapis.com/auth/earthengine"],
            )
            ee.Initialize(credentials, project=key_dict["project_id"])
            return True, None

        # Support path-based credentials via environment variable.
        # Example: GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if creds_path:
            with open(creds_path, "r", encoding="utf-8") as f:
                key_dict = json.load(f)
            from google.oauth2 import service_account as _sa
            credentials = _sa.Credentials.from_service_account_info(
                key_dict,
                scopes=["https://www.googleapis.com/auth/earthengine"],
            )
            ee.Initialize(credentials, project=key_dict.get("project_id", "ee-singhanil854"))
            return True, None

        # Fall back to local OAuth token
        ee.Initialize(project="ee-singhanil854")
        return True, None
    except Exception as e1:
        try:
            ee.Authenticate()
            ee.Initialize(project="ee-singhanil854")
            return True, None
        except Exception as e2:
            return False, f"Primary error: {e1}\nFallback error: {e2}"


# ══════════════════════════════════════════════════════════════════
# EARTH ENGINE — CYCLONE RISK ENGINE (from cyclone.js)
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def get_cyclone_hazard_stats():
    """Pre-compute percentile stats for cyclone normalization."""
    region = ee.Geometry.Rectangle([40, -5, 110, 35])
    proj = ee.Projection("EPSG:4326").atScale(20000)

    storms = ee.FeatureCollection("NOAA/IBTrACS/v4")
    cyclones = storms.filter(
        ee.Filter.And(ee.Filter.eq("BASIN", "NI"))
    ).filterBounds(region)

    cyclones = cyclones.map(lambda f: f.set("constant", 1))

    frequency = cyclones.reduceToImage(
        properties=["constant"], reducer=ee.Reducer.sum()
    ).reproject(crs=proj)

    intensity = cyclones.reduceToImage(
        properties=["USA_WIND"], reducer=ee.Reducer.mean()
    ).reproject(crs=proj)

    frequency = frequency.focal_mean(radius=90000, units="meters").reproject(crs=proj)
    intensity = intensity.focal_mean(radius=90000, units="meters").reproject(crs=proj)

    hazard = intensity.multiply(frequency).rename("hazard").clip(region)
    hazard = hazard.updateMask(hazard.gt(0))

    stats = hazard.reduceRegion(
        reducer=ee.Reducer.percentile([10, 90]),
        geometry=region,
        scale=20000,
        bestEffort=True,
        maxPixels=int(1e13),
    )
    return stats.getInfo()


def build_cyclone_risk_image():
    """Build the classified cyclone risk image (mirrors cyclone.js)."""
    region = ee.Geometry.Rectangle([40, -5, 110, 35])
    proj = ee.Projection("EPSG:4326").atScale(20000)

    storms = ee.FeatureCollection("NOAA/IBTrACS/v4")
    cyclones = storms.filter(
        ee.Filter.And(ee.Filter.eq("BASIN", "NI"))
    ).filterBounds(region)
    cyclones = cyclones.map(lambda f: f.set("constant", 1))

    frequency = cyclones.reduceToImage(
        properties=["constant"], reducer=ee.Reducer.sum()
    ).reproject(crs=proj)

    intensity = cyclones.reduceToImage(
        properties=["USA_WIND"], reducer=ee.Reducer.mean()
    ).reproject(crs=proj)

    frequency = frequency.focal_mean(radius=90000, units="meters").reproject(crs=proj)
    intensity = intensity.focal_mean(radius=90000, units="meters").reproject(crs=proj)

    hazard = intensity.multiply(frequency).rename("hazard").clip(region)
    hazard = hazard.updateMask(hazard.gt(0))

    stats = hazard.reduceRegion(
        reducer=ee.Reducer.percentile([10, 90]),
        geometry=region, scale=20000,
        bestEffort=True, maxPixels=int(1e13),
    )

    p10 = ee.Number(stats.get("hazard_p10"))
    p90 = ee.Number(stats.get("hazard_p90"))

    risk = (
        hazard.subtract(p10)
        .divide(p90.subtract(p10))
        .clamp(0, 1)
        .multiply(100)
        .rename("risk")
    )

    classified = (
        ee.Image(0)
        .where(risk.gt(0).And(risk.lt(20)), 1)
        .where(risk.gte(20).And(risk.lt(40)), 2)
        .where(risk.gte(40).And(risk.lt(60)), 3)
        .where(risk.gte(60).And(risk.lt(80)), 4)
        .where(risk.gte(80), 5)
        .selfMask()
    )

    return classified, risk


@st.cache_data(ttl=3600, show_spinner=False)
def get_cyclone_risk_at_point(lat: float, lon: float, buffer_radius_m: int = 0) -> dict:
    """Query cyclone risk at lat/lon, optionally averaged within a buffer radius."""
    region = ee.Geometry.Rectangle([40, -5, 110, 35])
    proj = ee.Projection("EPSG:4326").atScale(20000)
    point = ee.Geometry.Point([lon, lat])
    query_geom = point if buffer_radius_m <= 0 else point.buffer(buffer_radius_m)

    storms = ee.FeatureCollection("NOAA/IBTrACS/v4")
    cyclones = storms.filter(
        ee.Filter.And(ee.Filter.eq("BASIN", "NI"))
    ).filterBounds(region)
    cyclones = cyclones.map(lambda f: f.set("constant", 1))

    frequency = cyclones.reduceToImage(
        properties=["constant"], reducer=ee.Reducer.sum()
    ).reproject(crs=proj)

    intensity = cyclones.reduceToImage(
        properties=["USA_WIND"], reducer=ee.Reducer.mean()
    ).reproject(crs=proj)

    frequency = frequency.focal_mean(radius=90000, units="meters").reproject(crs=proj)
    intensity = intensity.focal_mean(radius=90000, units="meters").reproject(crs=proj)

    hazard = intensity.multiply(frequency).rename("hazard").clip(region)
    hazard = hazard.updateMask(hazard.gt(0))

    stats = hazard.reduceRegion(
        reducer=ee.Reducer.percentile([10, 90]),
        geometry=region, scale=20000,
        bestEffort=True, maxPixels=int(1e13),
    )

    p10 = ee.Number(stats.get("hazard_p10"))
    p90 = ee.Number(stats.get("hazard_p90"))

    risk = (
        hazard.subtract(p10)
        .divide(p90.subtract(p10))
        .clamp(0, 1)
        .multiply(100)
        .rename("risk")
    )

    sampled = risk.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=query_geom,
        scale=20000,
        bestEffort=True,
    )
    result = sampled.getInfo()
    risk_val = result.get("risk")

    if risk_val is None:
        return {"risk_score": 0.0, "risk_level": "Low", "raw_value": None}

    risk_score = round(float(risk_val), 2)

    level = "Low"
    for lvl, (lo, hi) in CYCLONE_RISK_THRESHOLDS.items():
        if lo <= risk_score < hi:
            level = lvl
            break
    if risk_score >= 80:
        level = "Extreme"

    return {"risk_score": risk_score, "risk_level": level, "raw_value": risk_val}


# ══════════════════════════════════════════════════════════════════
# EARTH ENGINE — FLOOD RISK ENGINE (from flood.js)
# ══════════════════════════════════════════════════════════════════

def build_flood_risk_image(band: str = "RP100_depth"):
    """Build classified flood risk image (mirrors flood.js)."""
    flood_image = ee.ImageCollection("JRC/CEMS_GLOFAS/FloodHazard/v2_1").mosaic()
    depth = flood_image.select(band)
    flood_only = depth.updateMask(depth.gt(0))

    classified = flood_only.expression(
        "(b(0) > 0 && b(0) < 0.5) ? 2"
        + ": (b(0) < 2) ? 4"
        + ": (b(0) < 4) ? 6"
        + ": 8"
    ).updateMask(flood_only)

    return classified, depth


@st.cache_data(ttl=3600, show_spinner=False)
def get_flood_risk_at_point(
    lat: float,
    lon: float,
    band: str = "RP100_depth",
    buffer_radius_m: int = 0,
) -> dict:
    """Query flood risk at lat/lon, optionally averaged within a buffer radius."""
    point = ee.Geometry.Point([lon, lat])
    query_geom = point if buffer_radius_m <= 0 else point.buffer(buffer_radius_m)

    flood_image = ee.ImageCollection("JRC/CEMS_GLOFAS/FloodHazard/v2_1").mosaic()
    depth_image = flood_image.select(band)

    sampled = depth_image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=query_geom,
        scale=90,
        bestEffort=True,
    )
    result = sampled.getInfo()
    depth_val = result.get(band)

    if depth_val is None or depth_val <= 0:
        return {"depth_m": 0.0, "risk_level": "No Risk", "raw_value": None}

    depth_m = round(float(depth_val), 3)

    if depth_m < 0.5:
        level = "Low"
    elif depth_m < 2.0:
        level = "Moderate"
    elif depth_m < 4.0:
        level = "High"
    else:
        level = "Severe"

    return {"depth_m": depth_m, "risk_level": level, "raw_value": depth_val}


# ══════════════════════════════════════════════════════════════════
# EARTH ENGINE — DEM RISK ENGINE (SRTM)
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def get_dem_elevation_at_point(lat: float, lon: float, buffer_radius_m: int = 100) -> dict:
    """Query elevation (DEM) at lat/lon, averaged within a buffer radius."""
    point = ee.Geometry.Point([lon, lat])
    
    try:
        # SRTM GL1 v003 - widely available public Earth Engine DEM
        dem = ee.Image("USGS/SRTMGL1_003")
        
        sampled = dem.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=point if buffer_radius_m <= 0 else point.buffer(buffer_radius_m),
            scale=30,
            bestEffort=True,
        )
        result = sampled.getInfo()
        elev_val = result.get("elevation")
        
        if elev_val is None:
            raise Exception("SRTM returned no data")
        
        elevation_m = round(float(elev_val), 2)
        return {"elevation_m": elevation_m, "risk_level": "Valid", "source": "USGS/SRTMGL1_003", "raw_value": elev_val}
    
    except Exception as err:
        return {
            "elevation_m": 0.0, 
            "risk_level": "Error", 
            "error": str(err)[:50], 
            "source": "None",
            "raw_value": None
        }


@st.cache_data(ttl=3600, show_spinner=False)
def get_dem_risk_at_point(lat: float, lon: float, buffer_radius_m: int = 100) -> dict:
    """Assess DEM-based (low-lying area) flood vulnerability."""
    dem_data = get_dem_elevation_at_point(lat, lon, buffer_radius_m=buffer_radius_m)
    elevation_m = dem_data["elevation_m"]
    
    # Classify elevation into risk categories
    risk_level = "Unknown"
    for level, (low, high) in DEM_RISK_THRESHOLDS.items():
        if low is None:
            if elevation_m < high:
                risk_level = level
                break
        elif high is None:
            if elevation_m >= low:
                risk_level = level
                break
        else:
            if low <= elevation_m < high:
                risk_level = level
                break
    
    # Convert risk level to numeric score (higher = more risk)
    risk_score_map = {
        "Very High Risk": 80,
        "High Risk": 60,
        "Moderate Risk": 35,
        "Low Risk": 10,
        "Very Low Risk": 0,
        "Unknown": 20,
        "Error": 15,
    }
    
    # Assign the 8-class DEM map band for the separate DEM map page
    class_8 = "Class 8: >200m"
    for lo, hi, label in DEM_MAP_CLASSES:
        if lo is None and elevation_m < hi:
            class_8 = label
            break
        if lo is not None and lo <= elevation_m < hi:
            class_8 = label
            break

    return {
        "elevation_m": elevation_m,
        "risk_level": risk_level,
        "risk_score": risk_score_map.get(risk_level, 20),
        "dem_class_8": class_8,
        "raw_value": dem_data.get("raw_value"),
    }


def build_dem_risk_image():
    """Build an 8-class DEM layer from SRTM for map overlay."""
    dem = ee.Image("USGS/SRTMGL1_003")
    elevation = dem.select("elevation")

    classified = (
        ee.Image(0)
        .where(elevation.lt(5), 1)
        .where(elevation.gte(5).And(elevation.lt(10)), 2)
        .where(elevation.gte(10).And(elevation.lt(20)), 3)
        .where(elevation.gte(20).And(elevation.lt(35)), 4)
        .where(elevation.gte(35).And(elevation.lt(50)), 5)
        .where(elevation.gte(50).And(elevation.lt(100)), 6)
        .where(elevation.gte(100).And(elevation.lt(200)), 7)
        .where(elevation.gte(200), 8)
        .selfMask()
    )

    return classified, elevation


# ══════════════════════════════════════════════════════════════════
# EARTH ENGINE — WATER BODY PROXIMITY (OPERA DSWx-HLS + OSM)
# ══════════════════════════════════════════════════════════════════
#
# Source : ee.ImageCollection("OPERA/DSWX/L3_V1/HLS")
#          Band 'WTR' (Water Classification):
#            0 = Not Water         1 = Open Water (high conf)
#            2 = Partial Surface Water (low conf)
#            3 = Snow/Ice          4 = Cloud/Cloud Shadow
#            252 = No Data
#
# Logic  : 1) Detect any pixel ever classified as water in the search
#             radius (recent ~3 years).
#          2) Find the nearest such pixel to (lat, lon) → distance_m.
#          3) Classify the water body type (River / Stream / Lake /
#             Pond / Reservoir) via OpenStreetMap Overpass at the
#             nearest-water coordinate.
#          4) Risk level = function(type, distance):
#                River / Stream  → flowing → HIGH risk band
#                Reservoir       → MODERATE-HIGH (dam-break exposure)
#                Lake            → LOW-MODERATE risk
#                Pond            → LOW risk

# Distance-based risk ladder driven by the **DSWx WTR class** of the
# nearest water pixel:
#   • Open Water (class 1)            → continuous, persistent water body
#                                        (rivers, large lakes, reservoirs,
#                                        coastal water) → HIGH risk band.
#   • Partial Surface Water (class 2) → seasonal / shallow / mixed water
#                                        (small ponds, marsh, paddy, edges
#                                        of larger bodies) → LOW risk band.
#
# Each list is searched in order; first matching distance wins.
DSWX_RISK_TABLE = {
    "Open Water": [
        (50,    "Severe"),
        (200,   "Very High"),
        (500,   "High"),
        (1000,  "Moderate"),
        (2000,  "Low"),
        (float("inf"), "Very Low"),
    ],
    "Partial Surface Water": [
        (50,    "Moderate"),
        (200,   "Low"),
        (500,   "Very Low"),
        (float("inf"), "Negligible"),
    ],
}

WATER_RISK_SCORE_MAP = {
    "Severe":     95,
    "Very High":  80,
    "High":       65,
    "Moderate":   45,
    "Low":        20,
    "Very Low":   8,
    "Negligible": 0,
    "No Water":   0,
}


def _classify_water_body_osm(lat: float, lon: float, search_radius_m: int = 250) -> dict:
    """Optional: query OpenStreetMap Overpass to attach a human-readable
    name + sub-type (river / lake / pond / reservoir) to the nearest water
    body. Used purely for display — does NOT drive the risk score."""
    overpass_url = "https://overpass-api.de/api/interpreter"
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{search_radius_m},{lat},{lon})["waterway"~"river|stream|canal|drain"];
      way(around:{search_radius_m},{lat},{lon})["natural"="water"];
      relation(around:{search_radius_m},{lat},{lon})["natural"="water"];
      way(around:{search_radius_m},{lat},{lon})["water"];
    );
    out tags;
    """
    try:
        r = requests.post(overpass_url, data={"data": query}, timeout=30)
        if r.status_code != 200:
            return {"osm_type": "Unknown", "name": ""}
        data = r.json()
    except Exception:
        return {"osm_type": "Unknown", "name": ""}

    elements = data.get("elements", [])
    if not elements:
        return {"osm_type": "Unknown", "name": ""}

    has_river = False
    has_stream = False
    water_kind = None
    name = ""
    for el in elements:
        tags = el.get("tags", {}) or {}
        wway = tags.get("waterway")
        if wway == "river":
            has_river = True
            name = tags.get("name", name) or name
        elif wway in ("stream", "canal", "drain"):
            has_stream = True
            name = tags.get("name", name) or name
        if tags.get("natural") == "water" or "water" in tags:
            water_kind = tags.get("water") or water_kind or "lake"
            name = tags.get("name", name) or name

    if has_river:
        return {"osm_type": "River", "name": name}
    if water_kind == "reservoir":
        return {"osm_type": "Reservoir", "name": name}
    if has_stream:
        return {"osm_type": "Stream/Canal", "name": name}
    if water_kind in ("pond", "basin"):
        return {"osm_type": "Pond", "name": name}
    if water_kind:
        return {"osm_type": "Lake", "name": name}
    return {"osm_type": "Water Body", "name": name}


def _level_from_dswx(water_class_label: str, distance_m: float) -> str:
    """Map (DSWx class label, distance) → risk level using DSWX_RISK_TABLE."""
    table = DSWX_RISK_TABLE.get(
        water_class_label, DSWX_RISK_TABLE["Partial Surface Water"]
    )
    for thresh, lvl in table:
        if distance_m <= thresh:
            return lvl
    return "Very Low"


def build_water_body_image(years_back: int = 3):
    """Return a DSWx-HLS water-class image (values 1 or 2 only) using
    `ee.Reducer.mode()` over the past `years_back` years.

    Pixels that are *neither* Open Water (1) nor Partial Surface Water (2)
    are masked out, so .sample() only returns water pixels and we can read
    their class value.
    """
    end = datetime.utcnow().date()
    start = end.replace(year=end.year - years_back)
    coll = (
        ee.ImageCollection("OPERA/DSWX/L3_V1/HLS")
        .filterDate(str(start), str(end))
    )

    def _mask(img):
        wtr = img.select("WTR_Water_classification")
        return wtr.updateMask(wtr.lt(252))

    mode = coll.map(_mask).reduce(ee.Reducer.mode()).rename(
        "WTR_Water_classification"
    )
    # Keep only Open Water (1) and Partial Surface Water (2)
    water_mask = mode.eq(1).Or(mode.eq(2))
    return mode.updateMask(water_mask)


def build_dswx_classified_image(years_back: int = 3):
    """Build the full DSWx classification image (remapped 0–5) for map display.

    Class mapping (from the GEE catalog example):
        0  Not water
        1  Open water
        2  Partial surface water
        252  Snow/ice
        253  Cloud/cloud shadow
        254  Ocean masked
    Remapped to 0..5 for a clean palette.
    """
    end = datetime.utcnow().date()
    start = end.replace(year=end.year - years_back)
    coll = (
        ee.ImageCollection("OPERA/DSWX/L3_V1/HLS")
        .filterDate(str(start), str(end))
    )

    def _mask(img):
        wtr = img.select("WTR_Water_classification")
        return wtr.updateMask(wtr.lt(252))

    mode = coll.map(_mask).reduce(ee.Reducer.mode()).rename(
        "WTR_Water_classification"
    )
    remapped = mode.remap(
        [0, 1, 2, 252, 253, 254],
        [0, 1, 2, 3, 4, 5],
    )
    return remapped


DSWX_PALETTE = [
    "ffffff",  # 0 Not water
    "0000ff",  # 1 Open water
    "0088ff",  # 2 Partial surface water
    "f2f2f2",  # 3 Snow/ice
    "dfdfdf",  # 4 Cloud/cloud shadow
    "da00ff",  # 5 Ocean masked
]


@st.cache_data(ttl=3600, show_spinner=False)
def get_water_body_risk_at_point(
    lat: float,
    lon: float,
    search_radius_m: int = 2000,
) -> dict:
    """Find nearest DSWx-HLS water pixel around (lat, lon), distinguishing
    **Open Water (class 1)** from **Partial Surface Water (class 2)**, and
    assign a risk level driven by class + distance.

    Logic:
      • Sample DSWx-HLS pixels (post mode-reduce) within the buffer, keeping
        each pixel's `WTR_Water_classification` value.
      • Compute nearest-pixel distance for class 1 and class 2 separately.
      • The DRIVING risk is the worst of:
            level(Open Water,            d_open)
            level(Partial Surface Water, d_partial)
        i.e. proximity to a true water body always dominates a nearby
        seasonal/partial pixel.

    Returns:
        {
          'distance_m':          float | None,    # distance to driving pixel
          'water_class':         str,             # 'Open Water' / 'Partial Surface Water' / 'None'
          'open_distance_m':     float | None,
          'partial_distance_m':  float | None,
          'osm_type':            str,             # River / Lake / Pond / ...
          'water_name':          str,
          'risk_level':          str,             # Severe / ... / No Water
          'risk_score':          float,           # 0–100
          'nearest_lat':         float | None,
          'nearest_lon':         float | None,
          'search_radius_m':     int,
        }
    """
    point = ee.Geometry.Point([lon, lat])
    region = point.buffer(search_radius_m)

    try:
        water = build_water_body_image(years_back=3).clip(region)
        sample = water.sample(
            region=region,
            scale=30,
            numPixels=4000,
            geometries=True,
            seed=1,
        )
        info = sample.getInfo()
        feats = info.get("features", []) if info else []
    except Exception as exc:
        return {
            "distance_m": None,
            "water_class": "Error",
            "open_distance_m": None,
            "partial_distance_m": None,
            "osm_type": "Unknown",
            "water_name": "",
            "risk_level": "Unknown",
            "risk_score": 0.0,
            "nearest_lat": None,
            "nearest_lon": None,
            "search_radius_m": search_radius_m,
            "error": str(exc)[:120],
        }

    if not feats:
        return {
            "distance_m": None,
            "water_class": "None",
            "open_distance_m": None,
            "partial_distance_m": None,
            "osm_type": "None",
            "water_name": "",
            "risk_level": "No Water",
            "risk_score": 0.0,
            "nearest_lat": None,
            "nearest_lon": None,
            "search_radius_m": search_radius_m,
        }

    # Track nearest pixel per class
    open_min, open_pt = float("inf"), (None, None)
    part_min, part_pt = float("inf"), (None, None)

    for f in feats:
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates")
        props = f.get("properties") or {}
        cls = props.get("WTR_Water_classification")
        if not coords or len(coords) < 2 or cls is None:
            continue
        flon, flat = coords[0], coords[1]
        d = haversine_m(lat, lon, flat, flon)
        if int(cls) == 1 and d < open_min:
            open_min, open_pt = d, (flat, flon)
        elif int(cls) == 2 and d < part_min:
            part_min, part_pt = d, (flat, flon)

    open_d = open_min if math.isfinite(open_min) else None
    part_d = part_min if math.isfinite(part_min) else None

    if open_d is None and part_d is None:
        return {
            "distance_m": None,
            "water_class": "None",
            "open_distance_m": None,
            "partial_distance_m": None,
            "osm_type": "None",
            "water_name": "",
            "risk_level": "No Water",
            "risk_score": 0.0,
            "nearest_lat": None,
            "nearest_lon": None,
            "search_radius_m": search_radius_m,
        }

    # Worst-of risk between Open Water and Partial Surface Water proximity.
    candidates = []
    if open_d is not None:
        lvl_o = _level_from_dswx("Open Water", open_d)
        candidates.append({
            "class": "Open Water",
            "distance": open_d,
            "level": lvl_o,
            "score": WATER_RISK_SCORE_MAP.get(lvl_o, 0),
            "pt": open_pt,
        })
    if part_d is not None:
        lvl_p = _level_from_dswx("Partial Surface Water", part_d)
        candidates.append({
            "class": "Partial Surface Water",
            "distance": part_d,
            "level": lvl_p,
            "score": WATER_RISK_SCORE_MAP.get(lvl_p, 0),
            "pt": part_pt,
        })

    driver = max(candidates, key=lambda c: c["score"])
    nlat, nlon = driver["pt"]

    # Optional OSM enrichment for display
    osm = _classify_water_body_osm(nlat, nlon, search_radius_m=200)

    return {
        "distance_m": round(driver["distance"], 1),
        "water_class": driver["class"],
        "open_distance_m": round(open_d, 1) if open_d is not None else None,
        "partial_distance_m": round(part_d, 1) if part_d is not None else None,
        "osm_type": osm.get("osm_type", "Unknown"),
        "water_name": osm.get("name", ""),
        "risk_level": driver["level"],
        "risk_score": float(driver["score"]),
        "nearest_lat": nlat,
        "nearest_lon": nlon,
        "search_radius_m": search_radius_m,
    }


# ══════════════════════════════════════════════════════════════════
# UNDERWRITING ENGINE
# ══════════════════════════════════════════════════════════════════

def compute_combined_risk_score(cyclone_score: float, flood_level: str, dem_score: float = 0.0) -> float:
    """
    Combine cyclone risk score (0-100), flood risk level, and DEM risk (0-100)
    into a single composite score (0-100).
    Weights: Cyclone 45%, Flood 35%, DEM (Low-lying Areas) 20%
    (Industry standard for coastal India, enhanced with elevation vulnerability)
    """
    flood_score_map = {
        "No Risk": 0, "Low": 15, "Moderate": 40, "High": 70, "Severe": 95
    }
    flood_numeric = flood_score_map.get(flood_level, 0)
    
    # Weighted combination: Cyclone 45%, Flood 35%, DEM 20%
    combined = 0.45 * cyclone_score + 0.35 * flood_numeric + 0.20 * dem_score
    return round(min(combined, 100), 2)


def calculate_premium(
    tsi: float,
    base_rate: float,
    cyclone_level: str,
    flood_level: str,
    dem_level: str,
    construction: str,
    occupancy: str,
    age: str,
    floor_level: str,
    coast_proximity: str,
    deductible_pct: float,
) -> dict:
    """Calculate loaded premium with full factor breakdown including DEM risk."""
    cyclone_load = CYCLONE_LOADING.get(cyclone_level, 0)
    flood_load = FLOOD_LOADING.get(flood_level, 0)
    dem_load = DEM_LOADING.get(dem_level, 0)
    construction_f = CONSTRUCTION_FACTORS.get(construction, 1.0)
    occupancy_f = OCCUPANCY_FACTORS.get(occupancy, 1.0)
    age_f = AGE_FACTORS.get(age, 1.0)
    floor_f = FLOOR_FACTORS.get(floor_level, 1.0)
    coast_f = COAST_FACTORS.get(coast_proximity, 1.0)

    # Deductible discount (higher deductible = lower premium)
    deductible_discount = 1.0 - (deductible_pct / 100) * 0.5

    # Peril loadings are additive (cyclone, flood, DEM), property factors are multiplicative
    peril_loading = 1.0 + cyclone_load + flood_load + dem_load
    property_factor = construction_f * occupancy_f * age_f * floor_f * coast_f

    gross_rate = base_rate * peril_loading * property_factor * deductible_discount
    gross_premium = tsi * gross_rate / 100

    # Minimum premium floor
    gross_premium = max(gross_premium, 2500.0)

    net_premium = gross_premium
    gst = net_premium * 0.18
    total = net_premium + gst

    return {
        "base_rate_pct": base_rate,
        "cyclone_loading_pct": cyclone_load * 100,
        "flood_loading_pct": flood_load * 100,
        "dem_loading_pct": dem_load * 100,
        "construction_factor": construction_f,
        "occupancy_factor": occupancy_f,
        "age_factor": age_f,
        "floor_factor": floor_f,
        "coast_factor": coast_f,
        "deductible_discount": deductible_discount,
        "peril_loading": peril_loading,
        "property_factor": property_factor,
        "effective_rate_pct": round(gross_rate, 4),
        "net_premium": round(net_premium, 2),
        "gst_18_pct": round(gst, 2),
        "total_premium": round(total, 2),
    }


def make_decision(combined_score: float) -> dict:
    """Underwriting decision based on combined risk score."""
    if combined_score < 30:
        return {
            "decision": "AUTO ACCEPT",
            "class": "accept",
            "color": "#2ecc71",
            "icon": "✅",
            "detail": "Risk within appetite. Auto-bind eligible.",
            "conditions": [],
            "authority": "System (Auto-Underwrite)",
        }
    elif combined_score < 50:
        return {
            "decision": "ACCEPT WITH CONDITIONS",
            "class": "accept",
            "color": "#27ae60",
            "icon": "✅",
            "detail": "Acceptable risk with standard mitigation requirements.",
            "conditions": [
                "Mandatory cyclone-resistant construction certification",
                "Annual property inspection required",
                "Minimum 2% deductible on NatCat perils",
            ],
            "authority": "Underwriter Level 1",
        }
    elif combined_score < 70:
        return {
            "decision": "REFER TO SENIOR UNDERWRITER",
            "class": "refer",
            "color": "#f39c12",
            "icon": "⚠️",
            "detail": "Elevated risk — requires senior review and additional documentation.",
            "conditions": [
                "Structural engineering report required",
                "Flood mitigation measures must be documented",
                "Minimum 5% NatCat deductible",
                "Sub-limit on flood damage (50% of TSI)",
                "Loss history for past 10 years required",
            ],
            "authority": "Senior Underwriter",
        }
    elif combined_score < 85:
        return {
            "decision": "REFER TO CHIEF UNDERWRITER",
            "class": "refer",
            "color": "#e67e22",
            "icon": "🔶",
            "detail": "High risk exposure. Chief Underwriter approval mandatory.",
            "conditions": [
                "Comprehensive risk survey report required",
                "Mandatory flood barriers/drainage documentation",
                "Minimum 10% NatCat deductible",
                "Sub-limit: Cyclone 60% TSI, Flood 40% TSI",
                "Reinsurance facultative placement may be required",
                "Annual risk re-assessment clause",
            ],
            "authority": "Chief Underwriter / CUO",
        }
    else:
        return {
            "decision": "DECLINE",
            "class": "decline",
            "color": "#e74c3c",
            "icon": "❌",
            "detail": "Risk exceeds underwriting appetite. Decline recommended.",
            "conditions": [
                "Risk outside acceptable threshold",
                "Consider government pool / catastrophe program referral",
                "Re-evaluate if significant risk mitigation is implemented",
            ],
            "authority": "Auto-Decline / CUO Override Only",
        }


# ══════════════════════════════════════════════════════════════════
# HAZARDOUS POI — GOOGLE PLACES API (NEW v1)
# ══════════════════════════════════════════════════════════════════

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two lat/lon points."""
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def get_places_api_key() -> str:
    """Resolve Google Places API key from session, secrets, or env."""
    import os
    key = st.session_state.get("google_places_api_key", "").strip()
    if key:
        return key
    try:
        key = st.secrets.get("GOOGLE_PLACES_API_KEY", "")  # type: ignore[attr-defined]
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("GOOGLE_PLACES_API_KEY", "")


@st.cache_data(ttl=3600, show_spinner=False)
def search_hazardous_pois(
    lat: float,
    lon: float,
    radius_m: int,
    api_key: str,
    selected_categories: tuple,
) -> list:
    """
    Query Google Places API (New) Text Search for each selected hazard category
    within `radius_m` of (lat, lon). Returns a flat list of POI dicts:
        {category, name, address, lat, lon, distance_m, weight, color, icon}
    """
    if not api_key:
        return []

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.displayName,places.formattedAddress,"
            "places.location,places.types,places.id"
        ),
    }

    results = []
    for cat in selected_categories:
        meta = HAZARDOUS_POI_CATEGORIES.get(cat)
        if not meta:
            continue
        body = {
            "textQuery": meta["query"],
            "maxResultCount": 20,
            "locationBias": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": float(radius_m),
                }
            },
        }
        try:
            r = requests.post(url, headers=headers, json=body, timeout=20)
            if r.status_code != 200:
                st.warning(
                    f"Places API error for '{cat}' "
                    f"({r.status_code}): {r.text[:200]}"
                )
                continue
            data = r.json()
        except Exception as exc:
            st.warning(f"Places API request failed for '{cat}': {exc}")
            continue

        for place in data.get("places", []):
            loc = place.get("location") or {}
            plat = loc.get("latitude")
            plon = loc.get("longitude")
            if plat is None or plon is None:
                continue
            dist = haversine_m(lat, lon, plat, plon)
            if dist > radius_m:
                continue  # locationBias is a hint, enforce strict radius
            band = classify_proximity(dist, radius_m)
            results.append({
                "category": cat,
                "name": (place.get("displayName") or {}).get("text", "Unknown"),
                "address": place.get("formattedAddress", ""),
                "lat": plat,
                "lon": plon,
                "distance_m": round(dist, 1),
                "weight": meta["weight"],
                "color": band["marker_color"],
                "band_color": band["band_color"],
                "band": band["band"],
                "proximity_multiplier": band["multiplier"],
                "icon": meta["icon"],
                "place_id": place.get("id", ""),
            })

    # Deduplicate by place_id (a location may match multiple queries)
    seen = {}
    for p in results:
        pid = p["place_id"] or f'{p["lat"]:.6f},{p["lon"]:.6f}'
        if pid not in seen or p["weight"] > seen[pid]["weight"]:
            seen[pid] = p
    return sorted(seen.values(), key=lambda x: x["distance_m"])


@st.cache_data(ttl=3600, show_spinner=False)
def geocode_place(query: str, api_key: str) -> list:
    """
    Resolve a free-text place / address to lat,lon via the
    Google Geocoding API. Returns up to 5 candidate dicts:
        {address, lat, lon}
    """
    if not query.strip() or not api_key:
        return []
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    try:
        r = requests.get(
            url,
            params={"address": query, "key": api_key},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    out = []
    for res in data.get("results", [])[:5]:
        loc = (res.get("geometry") or {}).get("location") or {}
        if "lat" in loc and "lng" in loc:
            out.append({
                "address": res.get("formatted_address", ""),
                "lat": loc["lat"],
                "lon": loc["lng"],
            })
    return out


@st.cache_data(ttl=86400, show_spinner=False)
def reverse_geocode_district_state(lat: float, lon: float) -> dict:
    """Resolve district/state for coordinates using OpenStreetMap Nominatim."""
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "format": "jsonv2",
        "lat": lat,
        "lon": lon,
        "zoom": 10,
        "addressdetails": 1,
    }
    headers = {"User-Agent": "natcat-underwriting-engine/1.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            return {"district": "Unknown", "state": "Unknown"}
        addr = (r.json() or {}).get("address") or {}
        district = (
            addr.get("state_district")
            or addr.get("county")
            or addr.get("district")
            or addr.get("city")
            or addr.get("town")
            or "Unknown"
        )
        state = addr.get("state") or "Unknown"
        return {"district": district, "state": state}
    except Exception:
        return {"district": "Unknown", "state": "Unknown"}


def build_google_satellite_static_map_url(lat: float, lon: float, api_key: str) -> str:
    """Build Google static satellite map URL with a red location marker."""
    if not api_key:
        return ""
    return (
        "https://maps.googleapis.com/maps/api/staticmap"
        f"?center={lat:.6f},{lon:.6f}"
        "&zoom=14"
        "&size=1280x720"
        "&scale=2"
        "&maptype=satellite"
        f"&markers=color:red%7Clabel:R%7C{lat:.6f},{lon:.6f}"
        f"&key={api_key}"
    )


def enrich_assessment_for_report(assessment: dict, places_api_key: str = "", ee_ready: bool = True) -> dict:
    """Populate report-ready metadata used by PDF and report exports."""
    inp = assessment.get("inputs", {}) or {}
    lat = inp.get("lat")
    lon = inp.get("lon")
    if lat is None or lon is None:
        return assessment

    lat = float(lat)
    lon = float(lon)
    cyclone = assessment.get("cyclone", {}) or {}
    flood = assessment.get("flood", {}) or {}
    dem = assessment.get("dem", {}) or {}
    decision = assessment.get("decision", {}) or {}

    flood_score_map = {
        "No Risk": 0.0,
        "Low": 20.0,
        "Moderate": 50.0,
        "High": 75.0,
        "Severe": 95.0,
    }
    flood_score = flood_score_map.get(flood.get("risk_level", "No Risk"), 0.0)

    loc_meta = reverse_geocode_district_state(lat, lon)
    static_map_url = build_google_satellite_static_map_url(lat, lon, places_api_key)

    water = assessment.get("water_proximity")
    if not water:
        wa = st.session_state.get("water_assessment")
        if wa and abs(float(wa.get("lat", 0.0)) - lat) < 1e-6 and abs(float(wa.get("lon", 0.0)) - lon) < 1e-6:
            water = wa.get("result")
        elif ee_ready:
            try:
                water = get_water_body_risk_at_point(lat, lon, search_radius_m=2000)
            except Exception:
                water = None

    assessment["report_location"] = {
        "lat": lat,
        "lon": lon,
        "district": loc_meta.get("district", "Unknown"),
        "state": loc_meta.get("state", "Unknown"),
        "risk_level": decision.get("decision", "Unknown"),
        "perils": {
            "cyclone": {
                "score": float(cyclone.get("risk_score", 0.0)),
                "category": cyclone.get("risk_level", "Unknown"),
            },
            "flood": {
                "score": float(flood_score),
                "category": flood.get("risk_level", "Unknown"),
            },
            "dem": {
                "score": float(dem.get("risk_score", 0.0)),
                "category": dem.get("risk_level", "Unknown"),
            },
        },
        "water_proximity": {
            "distance_m": (water or {}).get("distance_m"),
            "risk_level": (water or {}).get("risk_level", "Unknown"),
            "water_class": (water or {}).get("water_class", "Unknown"),
            "water_name": (water or {}).get("water_name", ""),
        },
        "google_static_map_url": static_map_url,
    }

    if water:
        assessment["water_proximity"] = water
    return assessment


def compute_poi_hazard_score(pois: list, radius_m: int) -> dict:
    """
    Aggregate POI hazard score using **distance-banded** weighting.
    Each POI contributes:  weight × proximity_multiplier
    where proximity_multiplier comes from PROXIMITY_BANDS:
        Very Near (≤100 m) → 1.00
        Near      (≤250 m) → 0.70
        Mid-range (≤400 m) → 0.40
        Far       (≤500 m) → 0.15
    Final score is capped at 100.
    """
    if not pois or radius_m <= 0:
        return {
            "score": 0.0, "level": "None", "loading": 0.0,
            "by_category": {}, "by_band": {},
        }

    score = 0.0
    by_category = {}
    by_band = {}
    for p in pois:
        contrib = p["weight"] * p.get("proximity_multiplier", 0.0)
        score += contrib

        by_category.setdefault(p["category"], {"count": 0, "score": 0.0})
        by_category[p["category"]]["count"] += 1
        by_category[p["category"]]["score"] += contrib

        band = p.get("band", "Unknown")
        by_band.setdefault(band, {"count": 0, "score": 0.0})
        by_band[band]["count"] += 1
        by_band[band]["score"] += contrib

    score = min(100.0, round(score, 2))

    if score == 0:
        level = "None"
    elif score < 15:
        level = "Low"
    elif score < 35:
        level = "Moderate"
    elif score < 60:
        level = "High"
    else:
        level = "Severe"

    return {
        "score": score,
        "level": level,
        "loading": POI_LOADING[level],
        "by_category": by_category,
        "by_band": by_band,
    }


# ══════════════════════════════════════════════════════════════════
# MAP BUILDER
# ══════════════════════════════════════════════════════════════════

def create_base_map(lat=20.0, lon=78.0, zoom=5):
    """Create a folium map with professional tiles."""
    m = folium.Map(
        location=[lat, lon],
        zoom_start=zoom,
        tiles="CartoDB positron",
        control_scale=True,
    )
    folium.TileLayer("CartoDB dark_matter", name="Dark").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satellite",
    ).add_to(m)
    return m


def add_ee_layer_to_map(folium_map, ee_image, vis_params, name):
    """Add an Earth Engine image as a tile layer to a folium map."""
    try:
        map_id = ee_image.getMapId(vis_params)
        tile_url = map_id["tile_fetcher"].url_format
        folium.TileLayer(
            tiles=tile_url,
            attr="Google Earth Engine",
            name=name,
            overlay=True,
            control=True,
            opacity=0.7,
        ).add_to(folium_map)
    except Exception as e:
        st.warning(f"Could not load {name} layer: {e}")


def add_point_marker(folium_map, lat, lon, label="Selected Location"):
    """Add a styled marker to the map."""
    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(f"<b>{label}</b><br>Lat: {lat:.4f}<br>Lon: {lon:.4f}", max_width=250),
        icon=folium.Icon(color="red", icon="crosshairs", prefix="fa"),
    ).add_to(folium_map)


def add_buffer_circle(folium_map, lat, lon, buffer_radius_m: int):
    """Draw query buffer around selected point."""
    if buffer_radius_m <= 0:
        return
    folium.Circle(
        location=[lat, lon],
        radius=buffer_radius_m,
        color="#1565C0",
        fill=True,
        fill_opacity=0.08,
        weight=2,
        popup=f"Risk Query Buffer: {buffer_radius_m} m",
    ).add_to(folium_map)


# ══════════════════════════════════════════════════════════════════
# UI HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════

def risk_badge(level: str) -> str:
    """Return HTML for a risk level badge."""
    css_class = {
        "Low": "risk-low", "No Risk": "risk-low",
        "Very Low Risk": "risk-low",
        "Moderate": "risk-moderate",
        "Moderate Risk": "risk-moderate",
        "High": "risk-high",
        "High Risk": "risk-high",
        "Very High": "risk-veryhigh",
        "Very High Risk": "risk-veryhigh",
        "Extreme": "risk-extreme",
        "Severe": "risk-extreme",
    }.get(level, "risk-low")
    return f'<span class="risk-badge {css_class}">{level}</span>'


def metric_card(title, value, css_class=""):
    """Render a styled metric card."""
    return f"""
    <div class="metric-card {css_class}">
        <h3>{title}</h3>
        <h1>{value}</h1>
    </div>
    """


def format_inr(amount: float) -> str:
    """Format number in Indian Rupee style with commas."""
    if amount < 0:
        return f"-₹{format_inr(-amount)[1:]}"
    s = f"{amount:,.2f}"
    return f"₹{s}"


# ══════════════════════════════════════════════════════════════════
# SIDEBAR — INPUT PANEL
# ══════════════════════════════════════════════════════════════════

def render_sidebar():
    """Render the sidebar with all input controls."""
    with st.sidebar:
        st.markdown("## 🛡️ Underwriting Engine")
        st.markdown("---")

        # Navigation
        page = st.radio(
            "Navigation",
            ["📊 Dashboard", "🌀 Cyclone Risk", "🌊 Flood Risk", "🗻 DEM Low-Lying Risk",
             "💧 Water Body Proximity",
             "🏭 Hazard Proximity (POI)",
             "📄 Report", "📜 History"],
            label_visibility="collapsed",
        )

        st.markdown("---")
        st.markdown("### 📍 Location")
        with st.expander("ℹ️ What is this? How to use?"):
            st.markdown("""
            **What:** The geographic coordinates of the property to be insured.

            **Why:** Cyclone and flood risk vary dramatically by location. Coastal areas face higher cyclone winds, while low-lying river basins are more flood-prone. Accurate coordinates ensure the risk score reflects the actual hazard at the site.

            **How to use:**
            - Type a **location name** in search to find a pre-loaded Indian city.
            - Selecting a match auto-fills **Latitude / Longitude**.
            - You can still directly edit **Latitude / Longitude** manually.
            - You can get coordinates from Google Maps (right-click → copy coordinates).
            """)

        # Name search with auto-fill coordinates
        if "lat_input" not in st.session_state:
            st.session_state["lat_input"] = 19.076
        if "lon_input" not in st.session_state:
            st.session_state["lon_input"] = 72.878
        if "selected_location_name" not in st.session_state:
            st.session_state["selected_location_name"] = "Custom"

        location_query = st.text_input(
            "Search Location Name or Paste Lat, Long",
            placeholder="City name  OR  28.6968, 76.9382",
            help="Type a city name to search pre-loaded locations, or paste coordinates as 'lat, lon'.",
        )

        # Detect if the user pasted a lat,lon pair
        import re as _re
        _latlon_pattern = _re.compile(
            r"^\s*(-?\d+(?:\.\d+)?)\s*[,\s]+\s*(-?\d+(?:\.\d+)?)\s*$"
        )
        _latlon_match = _latlon_pattern.match(location_query) if location_query else None

        if _latlon_match:
            _parsed_lat = float(_latlon_match.group(1))
            _parsed_lon = float(_latlon_match.group(2))
            if (
                -90 <= _parsed_lat <= 90 and -180 <= _parsed_lon <= 180
                and st.session_state.get("lat_input") != _parsed_lat
            ):
                st.session_state["lat_input"] = _parsed_lat
                st.session_state["lon_input"] = _parsed_lon
                st.session_state["selected_location_name"] = "Custom"
            st.success(f"Coordinates detected: {_parsed_lat:.6f}, {_parsed_lon:.6f}")
            matches = []
            selected_match = "Custom"
        else:
            matches = [
                name for name in REFERENCE_LOCATIONS.keys()
                if location_query.lower() in name.lower()
            ] if location_query else list(REFERENCE_LOCATIONS.keys())

            if matches:
                selected_match = st.selectbox(
                    "Matching Results",
                    matches,
                    help="Selecting a result auto-fills latitude/longitude.",
                )

                if selected_match != st.session_state.get("selected_location_name"):
                    match_lat, match_lon = REFERENCE_LOCATIONS[selected_match]
                    st.session_state["lat_input"] = match_lat
                    st.session_state["lon_input"] = match_lon
                    st.session_state["selected_location_name"] = selected_match
            else:
                st.info("No location match found. Enter coordinates manually.")
                selected_match = st.session_state.get("selected_location_name", "Custom")

        lat = st.session_state.get("lat_input", 19.076)
        lon = st.session_state.get("lon_input", 72.878)
        city = selected_match if (matches or _latlon_match) else "Custom"

        buffer_radius_m = st.slider(
            "Risk Buffer Radius (meters)",
            min_value=0,
            max_value=5000,
            value=500,
            step=50,
            help="Average risk over an area around the selected lat/lon. 0 = exact point only.",
        )

        # Default policy inputs retained for backend risk/premium compatibility.
        tsi = 50_000_000
        construction = "RCC (Reinforced Concrete)"
        occupancy = "Residential"
        age = "0-5 years"
        floor_level = "2nd Floor"
        coast_proximity = "> 100 km"

        st.markdown("---")
        st.markdown("### 📐 Policy Terms")
        with st.expander("ℹ️ What is this? How to use?"):
            st.markdown("""
            **What:** Flood modeling parameter for this risk assessment.

            **Why:** Flood depth depends on scenario severity. Return period selection controls whether you model frequent or extreme flooding.

            **How to use:**
            - **Flood Return Period:** Statistical recurrence interval for the flood scenario. "100 Year" means a 1% annual probability flood — higher return periods model rarer but more severe events.
            """)

        base_rate = 0.10
        deductible = 2

        flood_rp = st.selectbox(
            "Flood Return Period", list(RETURN_PERIODS.keys()), index=4,
            help="100-Year (1% annual chance) is the industry standard for underwriting.",
        )

        st.markdown("---")
        st.markdown("### 🏭 Hazard Proximity (Google Places)")
        with st.expander("ℹ️ What is this? How to use?"):
            st.markdown("""
            **What:** Detects high-risk neighbouring assets — refineries,
            chemical plants, fuel depots, factories, gas stations, etc. —
            within a configurable radius of the property using the
            **Google Places API**.

            **Why:** A property next to a refinery or fuel depot inherits
            fire / explosion / pollution spillover risk that satellite
            cyclone & flood layers cannot see. This adds a **POI hazard
            loading** to the premium.

            **How to use:**
            1. Paste a **Google Places API key** (kept only in this session).
               You can also set `GOOGLE_PLACES_API_KEY` in `.streamlit/secrets.toml`.
            2. Choose the **scan radius** (default 500 m).
            3. Open the **🏭 Hazard Proximity (POI)** page from the
               navigation above and click *Scan Nearby Hazards*.
            """)
        api_key_input = st.text_input(
            "Google Places API Key",
            value=st.session_state.get("google_places_api_key", ""),
            type="password",
            help="Required for the Hazard Proximity page. Stored only in this session.",
        )
        if api_key_input != st.session_state.get("google_places_api_key", ""):
            st.session_state["google_places_api_key"] = api_key_input

        poi_radius_m = st.slider(
            "POI Scan Radius (meters)",
            min_value=100, max_value=3000, value=500, step=50,
            help="Search radius for hazardous neighbouring POIs around the property.",
        )

        st.markdown("---")

        # Run assessment button
        run = st.button("🔍 Run Risk Assessment", use_container_width=True, type="primary",
                        help="Queries Google Earth Engine for live cyclone & flood hazard data at the selected location.")

        st.markdown("---")
        st.caption("© 2026 NatCat Underwriting Engine v2.0")

    return {
        "page": page,
        "lat": lat,
        "lon": lon,
        "buffer_radius_m": buffer_radius_m,
        "city": city,
        "tsi": tsi,
        "construction": construction,
        "occupancy": occupancy,
        "age": age,
        "floor_level": floor_level,
        "coast_proximity": coast_proximity,
        "base_rate": base_rate,
        "deductible": deductible,
        "flood_rp": flood_rp,
        "flood_band": RETURN_PERIODS[flood_rp],
        "poi_radius_m": poi_radius_m,
        "places_api_key": api_key_input,
        "run": run,
    }


# ══════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ══════════════════════════════════════════════════════════════════

def render_dashboard(inputs, ee_ready, ee_error: str | None = None):
    st.markdown("# 📊 NatCat Underwriting Dashboard")
    st.markdown("*Multi-Peril Natural Catastrophe Risk Assessment for Insurance Underwriting*")

    with st.expander("ℹ️ What is this dashboard? How to use it?", expanded=False):
        st.markdown("""
        **What:** This is the main command center for assessing natural catastrophe (NatCat) insurance risk. It combines cyclone wind hazard and flood inundation data from satellite sources to produce a single underwriting recommendation.

        **Why:** Insurers need a quick, data-driven view of how exposed a property is to cyclones and floods before deciding whether to accept, refer, or decline a risk. This dashboard automates that assessment using real geospatial data.

        **How to use:**
        1. 👈 Set the **location and flood return period** in the left sidebar.
        2. Click **🔍 Run Risk Assessment** — the engine queries Google Earth Engine for live hazard data.
        3. Review the **4 metric cards** (Cyclone Score, Flood Depth, Elevation, Combined Score).
        4. Explore the **interactive risk map** (toggle Cyclone/Flood layers via the layer control icon).
        """)

    if not ee_ready:
        st.error(
            "⚠️ Google Earth Engine not authenticated. "
            "Run `earthengine authenticate` in your terminal, then restart the app."
        )
        if ee_error:
            st.exception(ee_error)
        st.info("The app requires a valid Earth Engine account to query satellite-derived risk data.")
        return

    # ── Assessment execution ──
    if inputs["run"] or "assessment" in st.session_state:
        # Warn if any sidebar input that affects results has changed since
        # the cached assessment was computed.
        if not inputs["run"] and "assessment" in st.session_state:
            cached_inp = (st.session_state["assessment"].get("inputs") or {})
            drift_keys = [
                ("flood_band", "Flood Return Period"),
                ("lat", "Latitude"),
                ("lon", "Longitude"),
                ("buffer_radius_m", "Buffer Radius"),
                ("tsi", "Total Sum Insured"),
                ("construction", "Construction"),
                ("occupancy", "Occupancy"),
                ("age", "Building Age"),
                ("floor_level", "Floor Level"),
                ("coast_proximity", "Coast Proximity"),
                ("base_rate", "Base Rate"),
                ("deductible", "Deductible"),
            ]
            changed = [label for k, label in drift_keys
                       if cached_inp.get(k) != inputs.get(k)]
            if changed:
                st.warning(
                    "⚠️ The following inputs have changed since the last assessment: **"
                    + ", ".join(changed)
                    + "**. Click **🔍 Run Risk Assessment** in the sidebar to refresh."
                )

        if inputs["run"]:
            with st.spinner("🌀 Querying cyclone risk from IBTrACS..."):
                cyclone = get_cyclone_risk_at_point(
                    inputs["lat"],
                    inputs["lon"],
                    buffer_radius_m=inputs["buffer_radius_m"],
                )
            with st.spinner("🌊 Querying flood risk from GloFAS..."):
                flood = get_flood_risk_at_point(
                    inputs["lat"],
                    inputs["lon"],
                    inputs["flood_band"],
                    buffer_radius_m=inputs["buffer_radius_m"],
                )
            with st.spinner("⛰️  Querying elevation data from SRTM DEM..."):
                dem = get_dem_risk_at_point(
                    inputs["lat"],
                    inputs["lon"],
                    buffer_radius_m=inputs["buffer_radius_m"],
                )
            combined = compute_combined_risk_score(
                cyclone["risk_score"], flood["risk_level"], dem["risk_score"]
            )
            decision = make_decision(combined)
            premium = calculate_premium(
                inputs["tsi"], inputs["base_rate"],
                cyclone["risk_level"], flood["risk_level"], dem["risk_level"],
                inputs["construction"], inputs["occupancy"],
                inputs["age"], inputs["floor_level"],
                inputs["coast_proximity"], inputs["deductible"],
            )
            st.session_state["assessment"] = {
                "cyclone": cyclone,
                "flood": flood,
                "dem": dem,
                "combined_score": combined,
                "decision": decision,
                "premium": premium,
                "inputs": inputs,
                "timestamp": datetime.now().isoformat(),
            }

            # Persist to local SQLite history database
            try:
                hid = history_db.save_assessment(st.session_state["assessment"])
                st.session_state["last_history_id"] = hid
            except Exception as _hist_err:
                st.warning(f"Could not save to history database: {_hist_err}")

        data = st.session_state["assessment"]
        cyclone = data["cyclone"]
        flood = data["flood"]
        dem = data["dem"]
        combined = data["combined_score"]
        decision = data["decision"]

        # ── Top metric cards ──
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(metric_card("Cyclone Risk", f"{cyclone['risk_score']:.1f}",
                                    "metric-orange" if cyclone["risk_score"] > 50 else "metric-green"),
                        unsafe_allow_html=True)
        with c2:
            st.markdown(metric_card("Flood Depth", f"{flood['depth_m']:.2f}m",
                                    "metric-blue"), unsafe_allow_html=True)
        with c3:
            st.markdown(metric_card("Elevation", f"{dem['elevation_m']:.0f}m",
                                    "metric-blue"), unsafe_allow_html=True)
        with c4:
            css = "metric-red" if combined > 70 else ("metric-yellow" if combined > 40 else "metric-green")
            st.markdown(metric_card("Combined Score", f"{combined}", css),
                        unsafe_allow_html=True)

        st.markdown("---")

        # ── Map with risk layers ──
        col_map, col_detail = st.columns([3, 2])

        with col_map:
            st.markdown('<div class="section-header"><h3>Risk Map</h3></div>',
                        unsafe_allow_html=True)
            st.caption("💡 Use the layer control (top-right) to toggle Cyclone/Flood/DEM overlays. Switch between Light, Dark, and Satellite base maps.")
            m = create_base_map(inputs["lat"], inputs["lon"], zoom=7)

            try:
                classified_cyclone, _ = build_cyclone_risk_image()
                add_ee_layer_to_map(m, classified_cyclone,
                                    {"min": 1, "max": 5,
                                     "palette": ["#2ecc71", "#f1c40f", "#e67e22", "#e74c3c", "#6c3483"]},
                                    "Cyclone Risk")
            except Exception:
                pass

            try:
                classified_flood, _ = build_flood_risk_image(inputs["flood_band"])
                add_ee_layer_to_map(m, classified_flood,
                                    {"min": 2, "max": 8,
                                     "palette": ["#2ECC71", "#F1C40F", "#E67E22", "#E74C3C"]},
                                    "Flood Risk")
            except Exception:
                pass

            try:
                classified_dem, _ = build_dem_risk_image()
                add_ee_layer_to_map(m, classified_dem,
                                    {"min": 1, "max": 8,
                                     "palette": ["#7f0000", "#b30000", "#d7301f", "#ef6548",
                                                 "#fc8d59", "#fdbb84", "#c7e9b4", "#41ab5d"]},
                                    "DEM Low-Lying Risk (Elevation)")
            except Exception:
                pass

            add_point_marker(m, inputs["lat"], inputs["lon"],
                             inputs.get("city", "Location"))
            add_buffer_circle(m, inputs["lat"], inputs["lon"], inputs["buffer_radius_m"])
            folium.LayerControl().add_to(m)
            st_folium(m, width=None, height=500, returned_objects=[])

        with col_detail:
            st.markdown('<div class="section-header"><h3>Risk Summary</h3></div>',
                        unsafe_allow_html=True)

            loc_label = inputs["city"] if inputs["city"] else "Custom"
            st.markdown(f"**Location:** {loc_label} ({inputs['lat']:.4f}°N, {inputs['lon']:.4f}°E)")
            st.markdown(f"**Buffer Radius:** {inputs['buffer_radius_m']} m")
            st.markdown(f"**Assessment Date:** {datetime.now().strftime('%d %B %Y, %H:%M')}")

            st.markdown("---")

            st.markdown(f"**🌀 Cyclone Risk:** {risk_badge(cyclone['risk_level'])}",
                        unsafe_allow_html=True)
            st.markdown(f"&nbsp;&nbsp;&nbsp;Score: `{cyclone['risk_score']:.1f}` / 100")

            st.markdown(f"**🌊 Flood Risk ({inputs['flood_rp']}):** {risk_badge(flood['risk_level'])}",
                        unsafe_allow_html=True)
            st.markdown(f"&nbsp;&nbsp;&nbsp;Depth: `{flood['depth_m']:.3f}` m")

            st.markdown(f"**⛰️  Elevation (DEM):** {risk_badge(dem['risk_level'])}",
                        unsafe_allow_html=True)
            st.markdown(f"&nbsp;&nbsp;&nbsp;Elevation: `{dem['elevation_m']:.0f}` m | Risk Score: `{dem['risk_score']:.0f}` / 100")

            st.markdown(f"**📊 Combined Score:** `{combined}` / 100 (Cyclone 45%, Flood 35%, DEM 20%)")

    else:
        # No assessment yet
        st.info("👈 Configure location and property details in the sidebar, then click **Run Risk Assessment**.")

        # Show a default map
        m = create_base_map()
        try:
            classified_cyclone, _ = build_cyclone_risk_image()
            add_ee_layer_to_map(m, classified_cyclone,
                                {"min": 1, "max": 5,
                                 "palette": ["#2ecc71", "#f1c40f", "#e67e22", "#e74c3c", "#6c3483"]},
                                "Cyclone Risk")
        except Exception:
            pass
        try:
            classified_dem, _ = build_dem_risk_image()
            add_ee_layer_to_map(m, classified_dem,
                                {"min": 1, "max": 8,
                                 "palette": ["#7f0000", "#b30000", "#d7301f", "#ef6548",
                                             "#fc8d59", "#fdbb84", "#c7e9b4", "#41ab5d"]},
                                "DEM Low-Lying Risk (Elevation)")
        except Exception:
            pass
        add_buffer_circle(m, inputs["lat"], inputs["lon"], inputs["buffer_radius_m"])
        folium.Marker(
            [inputs["lat"], inputs["lon"]],
            tooltip=f"<b>{inputs['city']}</b><br>{inputs['lat']:.5f}, {inputs['lon']:.5f}",
            popup=f"{inputs['city']} ({inputs['lat']:.5f}, {inputs['lon']:.5f})",
            icon=folium.Icon(color="red", icon="map-marker", prefix="fa"),
        ).add_to(m)
        folium.LayerControl().add_to(m)
        st_folium(m, width=None, height=600, returned_objects=[])


# ══════════════════════════════════════════════════════════════════
# PAGE: WATER BODY PROXIMITY
# ══════════════════════════════════════════════════════════════════

def render_water_page(inputs, ee_ready):
    st.markdown("# 💧 Water Body Proximity Risk")
    st.markdown(
        "*Source: `OPERA/DSWX/L3_V1/HLS` (surface water mask) + "
        "OpenStreetMap (water body type)*"
    )

    with st.expander("ℹ️ What is this? How is the risk computed?", expanded=False):
        st.markdown("""
        **What:** Detects the nearest **surface water pixel** to the property
        using NASA's **OPERA Dynamic Surface Water Extent (DSWx-HLS)** and
        classifies it directly using the DSWx **WTR water class**:

        - **Class 1 — Open Water** → continuous, persistent water body
          (rivers, large lakes, reservoirs, coastal water). Treated as
          **HIGH-risk** because such bodies overflow during heavy rain &
          cyclones.
        - **Class 2 — Partial Surface Water** → seasonal / shallow / mixed
          water (small ponds, marsh edges, paddy). Treated as **LOW-risk**
          because exposure to nearby properties is far smaller.

        **Risk by class + distance:**

        | Class | < 50 m | 50–200 m | 200–500 m | 500–1000 m | 1–2 km | > 2 km |
        |-------|--------|----------|-----------|------------|--------|--------|
        | Open Water (1) | Severe | Very High | High | Moderate | Low | Very Low |
        | Partial Surface Water (2) | Moderate | Low | Very Low | Negligible | Negligible | Negligible |

        The driving risk is the **worst-of** Open-Water proximity and
        Partial-Water proximity (i.e. a nearby river always dominates a
        nearby pond). OpenStreetMap is used **only** to display the body's
        name (e.g. "Yamuna River").
        """)

    if not ee_ready:
        st.error("Earth Engine not authenticated.")
        return

    lat = inputs["lat"]
    lon = inputs["lon"]

    c1, c2 = st.columns([1, 1])
    with c1:
        search_radius_m = st.slider(
            "Water search radius (meters)",
            min_value=500, max_value=10000, value=2000, step=250,
            help="How far from the property to scan for water bodies.",
        )
    with c2:
        st.markdown("**Property Location**")
        st.markdown(f"Lat: `{lat:.5f}`  &nbsp;|&nbsp;  Lon: `{lon:.5f}`")
        st.markdown(f"City: **{inputs.get('city', 'Custom')}**")

    run_water = st.button("🔍 Scan Nearest Water Body",
                          type="primary", use_container_width=True)

    if run_water or "water_assessment" in st.session_state:
        if run_water:
            with st.spinner("💧 Scanning OPERA DSWx-HLS for nearest surface water…"):
                result = get_water_body_risk_at_point(
                    lat, lon, search_radius_m=search_radius_m,
                )
            st.session_state["water_assessment"] = {
                "lat": lat, "lon": lon,
                "search_radius_m": search_radius_m,
                "result": result,
            }
        wa = st.session_state["water_assessment"]
        result = wa["result"]
        lat_a, lon_a = wa["lat"], wa["lon"]

        # ── Top metric row ─────────────────────────────────────────
        m1, m2, m3, m4 = st.columns(4)
        dist_text = (f"{result['distance_m']:.0f} m"
                     if result.get("distance_m") is not None else "—")
        with m1:
            st.markdown(metric_card("Nearest Water", dist_text,
                                    "metric-blue"), unsafe_allow_html=True)
        with m2:
            st.markdown(metric_card("DSWx Class",
                                    result.get("water_class", "—"),
                                    "metric-blue"), unsafe_allow_html=True)
        with m3:
            css = ("metric-red" if result["risk_score"] >= 65
                   else "metric-yellow" if result["risk_score"] >= 35
                   else "metric-green")
            st.markdown(metric_card("Risk Score",
                                    f"{result['risk_score']:.0f}/100", css),
                        unsafe_allow_html=True)
        with m4:
            st.markdown(metric_card("Risk Level",
                                    result.get("risk_level", "—"),
                                    css), unsafe_allow_html=True)

        if result.get("error"):
            st.warning(f"DSWx query issue: {result['error']}")

        st.markdown("---")

        col_map, col_detail = st.columns([3, 2])

        with col_map:
            st.markdown("### Map")
            m = create_base_map(lat_a, lon_a, zoom=13)

            # Add DSWx classification layer (remapped 0–5) to map
            try:
                dswx_img = build_dswx_classified_image(years_back=3)
                add_ee_layer_to_map(
                    m, dswx_img,
                    {"min": 0, "max": 5, "palette": DSWX_PALETTE},
                    "OPERA DSWx Water Classification",
                )
            except Exception:
                pass

            # Property marker + search radius
            add_point_marker(m, lat_a, lon_a, inputs.get("city", "Property"))
            folium.Circle(
                [lat_a, lon_a],
                radius=wa["search_radius_m"],
                color="#1565C0", weight=2,
                fill=True, fill_opacity=0.05,
                popup=f"Search radius: {wa['search_radius_m']} m",
            ).add_to(m)

            # Nearest water marker + connecting line
            if result.get("nearest_lat") is not None:
                wclass = result.get("water_class", "Water")
                wname = result.get("water_name", "")
                osm_t = result.get("osm_type", "")
                tooltip = f"Nearest {wclass}"
                if wname:
                    tooltip += f" — {wname}"
                elif osm_t and osm_t not in ("Unknown", "None"):
                    tooltip += f" — {osm_t}"

                popup_html = f"<b>{wclass}</b>"
                if wname:
                    popup_html += f"<br>{wname}"
                if osm_t and osm_t not in ("Unknown", "None"):
                    popup_html += f"<br>OSM: {osm_t}"
                popup_html += (
                    f"<br>Distance: {result['distance_m']:.0f} m"
                    f"<br>Risk: {result['risk_level']}"
                )

                marker_color = "blue" if wclass == "Open Water" else "lightblue"
                folium.Marker(
                    [result["nearest_lat"], result["nearest_lon"]],
                    tooltip=tooltip,
                    popup=folium.Popup(popup_html, max_width=260),
                    icon=folium.Icon(color=marker_color, icon="tint", prefix="fa"),
                ).add_to(m)
                folium.PolyLine(
                    [[lat_a, lon_a],
                     [result["nearest_lat"], result["nearest_lon"]]],
                    color="#1565C0", weight=3, opacity=0.8,
                    dash_array="6,6",
                ).add_to(m)

            folium.LayerControl().add_to(m)
            st_folium(m, width=None, height=520, returned_objects=[])

        with col_detail:
            st.markdown("### Assessment Detail")
            st.markdown(
                f"**Property:** {inputs.get('city', 'Custom')} "
                f"({lat_a:.5f}, {lon_a:.5f})"
            )
            st.markdown(f"**Search Radius:** {wa['search_radius_m']} m")
            st.markdown("---")

            if result.get("distance_m") is None:
                st.success(
                    f"✅ No surface water detected within "
                    f"{wa['search_radius_m']} m. "
                    f"Water body proximity risk: **No Water**."
                )
            else:
                wclass = result["water_class"]
                osm_t = result.get("osm_type", "")
                wname = result.get("water_name", "")

                desc = wclass
                if wname:
                    desc += f" — *{wname}*"
                elif osm_t and osm_t not in ("Unknown", "None"):
                    desc += f" — {osm_t}"
                st.markdown(f"**Nearest Water (DSWx):** {desc}")

                st.markdown(
                    f"**Distance:** `{result['distance_m']:.1f}` m"
                )

                # Show both class distances when both detected
                od = result.get("open_distance_m")
                pd_ = result.get("partial_distance_m")
                if od is not None and pd_ is not None:
                    st.caption(
                        f"Open Water: `{od:.0f}` m  •  "
                        f"Partial Surface Water: `{pd_:.0f}` m  "
                        f"(driving = worst-of)"
                    )

                st.markdown(
                    f"**Risk Level:** "
                    f"{risk_badge(result['risk_level'])}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"**Risk Score:** `{result['risk_score']:.0f}` / 100"
                )

                if wclass == "Open Water":
                    st.warning(
                        "⚠️  **Open Water** detected nearby — persistent "
                        "water body (river / large lake / reservoir / "
                        "coastal water). Proximity sharply increases "
                        "flood and erosion exposure during heavy rain "
                        "and cyclones."
                    )
                else:
                    st.info(
                        "ℹ️  **Partial Surface Water** detected — "
                        "seasonal / shallow water (small ponds, marsh, "
                        "paddy edges). Risk to neighbouring properties "
                        "is comparatively low."
                    )
    else:
        st.info("Configure search radius and click "
                "**🔍 Scan Nearest Water Body** to begin.")


# ══════════════════════════════════════════════════════════════════
# PAGE: DEM LOW-LYING RISK
# ══════════════════════════════════════════════════════════════════

def render_dem_page(inputs, ee_ready):
    st.markdown("# 🗻 DEM Low-Lying Risk Assessment")
    st.markdown("*Based on USGS SRTMGL1_003 Digital Elevation Model*")

    if not ee_ready:
        st.error("Earth Engine not authenticated.")
        return

    with st.expander("📚 Methodology Details"):
        st.markdown("""
        - **Data Source:** USGS SRTMGL1_003
        - **Variable:** Elevation above mean sea level (meters)
        - **Classification:** 8 classes (from <5m to >200m)
        - **Purpose:** Identify low-lying topographic vulnerability for flood/cyclone accumulation
        - **Resolution:** ~30m
        """)

    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("### DEM 8-Class Map")
        m = create_base_map(inputs["lat"], inputs["lon"], zoom=8)

        try:
            classified_dem, _ = build_dem_risk_image()
            add_ee_layer_to_map(
                m,
                classified_dem,
                {
                    "min": 1,
                    "max": 8,
                    "palette": [
                        "#7f0000", "#b30000", "#d7301f", "#ef6548",
                        "#fc8d59", "#fdbb84", "#c7e9b4", "#41ab5d",
                    ],
                },
                "DEM Low-Lying Risk (8 Classes)",
            )
        except Exception as e:
            st.warning(f"Map layer error: {e}")

        add_point_marker(m, inputs["lat"], inputs["lon"])
        add_buffer_circle(m, inputs["lat"], inputs["lon"], inputs["buffer_radius_m"])
        folium.LayerControl().add_to(m)
        st_folium(m, width=None, height=550, returned_objects=[])

        legend_html = """
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
            <span class="risk-badge risk-extreme">C1 &lt;5m</span>
            <span class="risk-badge risk-extreme">C2 5-10m</span>
            <span class="risk-badge risk-veryhigh">C3 10-20m</span>
            <span class="risk-badge risk-high">C4 20-35m</span>
            <span class="risk-badge risk-high">C5 35-50m</span>
            <span class="risk-badge risk-moderate">C6 50-100m</span>
            <span class="risk-badge risk-low">C7 100-200m</span>
            <span class="risk-badge risk-low">C8 &gt;200m</span>
        </div>"""
        st.markdown(legend_html, unsafe_allow_html=True)

    with col2:
        st.markdown("### Point Query")
        dem = get_dem_risk_at_point(
            inputs["lat"],
            inputs["lon"],
            buffer_radius_m=inputs["buffer_radius_m"],
        )

        st.markdown(f"**Elevation:** `{dem['elevation_m']:.2f} m`")
        st.markdown(f"**Buffer Radius:** `{inputs['buffer_radius_m']} m`")
        st.markdown(f"**8-Class Band:** `{dem['dem_class_8']}`")
        st.markdown(f"**Underwriting DEM Risk:** {risk_badge(dem['risk_level'])}", unsafe_allow_html=True)
        st.markdown(f"**DEM Risk Score:** `{dem['risk_score']}` / 100")

        st.markdown("---")
        st.markdown("**Class Meaning**")
        st.markdown("- Classes 1-3: Very low elevation, highest inundation sensitivity")
        st.markdown("- Classes 4-5: Moderate low-lying terrain")
        st.markdown("- Classes 6-8: Relatively elevated terrain")


# ══════════════════════════════════════════════════════════════════
# PAGE: CYCLONE RISK
# ══════════════════════════════════════════════════════════════════

def render_cyclone_page(inputs, ee_ready):
    st.markdown("# 🌀 Cyclone Risk Assessment")
    st.markdown("*Based on NOAA IBTrACS v4 — North Indian Basin historical cyclone tracks*")

    with st.expander("ℹ️ What is this page? How to use it?", expanded=False):
        st.markdown("""
        **What:** A dedicated deep-dive into cyclone (tropical cyclone / hurricane) risk at your selected location. The risk score is derived from historical cyclone track data spanning decades.

        **Why:** Cyclones cause catastrophic wind and storm-surge damage along India's coastline. Understanding the historical frequency and intensity of cyclones passing near a location is critical for pricing wind-peril coverage.

        **How to use:**
        - The **left map** shows the classified cyclone risk layer across the entire North Indian Basin (Arabian Sea + Bay of Bengal).
        - The **right panel** shows the point-specific risk score, risk level badge, and a gauge chart after running an assessment.
        - The **Saffir-Simpson table** provides context on what different wind speeds mean in terms of physical damage.
        - Colors: 🟢 Low (0–20) → 🟡 Moderate (20–40) → 🟠 High (40–60) → 🔴 Very High (60–80) → 🟣 Extreme (80–100).
        """)

    if not ee_ready:
        st.error("Earth Engine not authenticated.")
        return

    with st.expander("📚 Methodology Details"):
        st.markdown("""
        - **Data Source:** NOAA International Best Track Archive (IBTrACS v4)
        - **Basin:** North Indian Ocean (NI) — Arabian Sea + Bay of Bengal
        - **Frequency:** Count of historical cyclone observations per pixel
        - **Intensity:** Mean sustained wind speed (USA_WIND, knots)
        - **Hazard Index:** Frequency × Intensity (smoothed at 90km radius)
        - **Normalization:** Percentile-based (P10–P90) scaled to 0–100
        - **Classification:** 5-tier risk (Low / Moderate / High / Very High / Extreme)
        """)

    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("### Risk Map")
        m = create_base_map(inputs["lat"], inputs["lon"], zoom=5)
        try:
            classified, _ = build_cyclone_risk_image()
            add_ee_layer_to_map(m, classified,
                                {"min": 1, "max": 5,
                                 "palette": ["#2ecc71", "#f1c40f", "#e67e22", "#e74c3c", "#6c3483"]},
                                "Cyclone Risk")
        except Exception as e:
            st.warning(f"Map layer error: {e}")

        add_point_marker(m, inputs["lat"], inputs["lon"])
        add_buffer_circle(m, inputs["lat"], inputs["lon"], inputs["buffer_radius_m"])
        folium.LayerControl().add_to(m)
        st_folium(m, width=None, height=550, returned_objects=[])

        # Legend
        legend_html = """
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:8px">
            <span class="risk-badge risk-low">Low (0-20)</span>
            <span class="risk-badge risk-moderate">Moderate (20-40)</span>
            <span class="risk-badge risk-high">High (40-60)</span>
            <span class="risk-badge risk-veryhigh">Very High (60-80)</span>
            <span class="risk-badge risk-extreme">Extreme (80-100)</span>
        </div>"""
        st.markdown(legend_html, unsafe_allow_html=True)

    with col2:
        st.markdown("### Point Query")
        if inputs["run"] or "assessment" in st.session_state:
            if "assessment" in st.session_state:
                cyclone = st.session_state["assessment"]["cyclone"]
            else:
                with st.spinner("Querying cyclone risk..."):
                    cyclone = get_cyclone_risk_at_point(
                        inputs["lat"],
                        inputs["lon"],
                        buffer_radius_m=inputs["buffer_radius_m"],
                    )

            st.markdown(f"**Risk Level:** {risk_badge(cyclone['risk_level'])}", unsafe_allow_html=True)
            st.markdown(f"**Risk Score:** {cyclone['risk_score']:.1f} / 100")
            st.markdown(f"**Premium Loading:** +{CYCLONE_LOADING.get(cyclone['risk_level'], 0) * 100:.0f}%")

            # Risk gauge
            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=cyclone["risk_score"],
                title={"text": "Cyclone Risk Score"},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"color": "#1565C0"},
                    "steps": [
                        {"range": [0, 20], "color": "#2ecc71"},
                        {"range": [20, 40], "color": "#f1c40f"},
                        {"range": [40, 60], "color": "#e67e22"},
                        {"range": [60, 80], "color": "#e74c3c"},
                        {"range": [80, 100], "color": "#6c3483"},
                    ],
                    "threshold": {
                        "line": {"color": "black", "width": 4},
                        "thickness": 0.75,
                        "value": cyclone["risk_score"],
                    },
                },
            ))
            fig.update_layout(height=300, margin=dict(t=40, b=20, l=30, r=30))
            st.plotly_chart(fig, use_container_width=True)

            # Saffir-Simpson context
            st.markdown("### Wind Speed Context")
            st.markdown("""
            | Category | Wind (kt) | Damage |
            |----------|-----------|--------|
            | TD | < 34 | Minimal |
            | TS | 34-63 | Moderate |
            | Cat 1 | 64-82 | Some |
            | Cat 2 | 83-95 | Extensive |
            | Cat 3 | 96-112 | Devastating |
            | Cat 4 | 113-136 | Catastrophic |
            | Cat 5 | > 137 | Total |
            """)
        else:
            st.info("Click **Run Risk Assessment** to query this location.")


# ══════════════════════════════════════════════════════════════════
# PAGE: FLOOD RISK
# ══════════════════════════════════════════════════════════════════

def render_flood_page(inputs, ee_ready):
    st.markdown("# 🌊 Flood Risk Assessment")
    st.markdown("*Based on JRC/Copernicus GloFAS Flood Hazard v2.1*")

    with st.expander("ℹ️ What is this page? How to use it?", expanded=False):
        st.markdown("""
        **What:** A detailed flood inundation risk analysis for your selected location, based on modeled flood depth from the European Commission's Global Flood Awareness System (GloFAS).

        **Why:** Flood damage is the most frequent natural catastrophe peril in India, affecting basements, ground floors, and properties near rivers. This page shows how deep floodwater could get at your exact location for different statistical return periods.

        **How to use:**
        - The **left map** shows the classified flood depth layer — green is shallow (<0.5m), red is severe (>4m).
        - The **right panel** shows the exact depth in meters and the risk level at the queried point.
        - The **gauge chart** visualizes where the depth falls on the 0–6m scale.
        - Click **"Run All Return Periods"** to compare flood depths across all 7 scenarios (10yr to 500yr) — this helps assess how the risk escalates for rarer events.
        - The **Return Period** (set in sidebar) represents the statistical probability: e.g., "100-Year" means a 1% chance of occurring in any given year, NOT that it happens once every 100 years.
        """)

    if not ee_ready:
        st.error("Earth Engine not authenticated.")
        return

    with st.expander("📚 Methodology Details"):
        st.markdown(f"""
        - **Data Source:** JRC CEMS GloFAS Flood Hazard Maps v2.1
        - **Selected Return Period:** {inputs['flood_rp']}
        - **Variable:** Flood inundation depth (meters)
        - **Classification:** 4-tier (Low <0.5m / Moderate 0.5–2m / High 2–4m / Severe >4m)
        - **Resolution:** ~90m (3 arc-seconds)
        """)

    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("### Flood Risk Map")
        m = create_base_map(inputs["lat"], inputs["lon"], zoom=8)

        try:
            classified_flood, _ = build_flood_risk_image(inputs["flood_band"])
            add_ee_layer_to_map(m, classified_flood,
                                {"min": 2, "max": 8,
                                 "palette": ["#2ECC71", "#F1C40F", "#E67E22", "#E74C3C"]},
                                f"Flood Risk ({inputs['flood_rp']})")
        except Exception as e:
            st.warning(f"Map layer error: {e}")

        add_point_marker(m, inputs["lat"], inputs["lon"])
        folium.LayerControl().add_to(m)
        st_folium(m, width=None, height=550, returned_objects=[])

        legend_html = """
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:8px">
            <span class="risk-badge risk-low">Low (&lt;0.5m)</span>
            <span class="risk-badge risk-moderate">Moderate (0.5-2m)</span>
            <span class="risk-badge risk-high">High (2-4m)</span>
            <span class="risk-badge risk-extreme">Severe (&gt;4m)</span>
        </div>"""
        st.markdown(legend_html, unsafe_allow_html=True)

    with col2:
        st.markdown("### Point Query")
        if inputs["run"] or "assessment" in st.session_state:
            cached = st.session_state.get("assessment", {})
            cached_band = (cached.get("inputs") or {}).get("flood_band")
            current_band = inputs["flood_band"]

            # Use cached value only if it was computed for the SAME return period.
            # Otherwise re-query so the dropdown change is reflected immediately.
            if cached and cached_band == current_band and not inputs["run"]:
                flood = cached["flood"]
            else:
                with st.spinner(f"Querying flood risk for {inputs['flood_rp']}..."):
                    flood = get_flood_risk_at_point(
                        inputs["lat"],
                        inputs["lon"],
                        current_band,
                        buffer_radius_m=inputs["buffer_radius_m"],
                    )
                st.caption(
                    f"📊 Live query for **{inputs['flood_rp']}** "
                    f"(band: `{current_band}`)"
                )

            st.markdown(f"**Risk Level:** {risk_badge(flood['risk_level'])}", unsafe_allow_html=True)
            st.markdown(f"**Flood Depth:** {flood['depth_m']:.3f} m")
            st.markdown(f"**Premium Loading:** +{FLOOD_LOADING.get(flood['risk_level'], 0) * 100:.0f}%")

            # Depth gauge
            fig = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=flood["depth_m"],
                number={"suffix": " m"},
                title={"text": f"Flood Depth ({inputs['flood_rp']})"},
                gauge={
                    "axis": {"range": [0, 6]},
                    "bar": {"color": "#1565C0"},
                    "steps": [
                        {"range": [0, 0.5], "color": "#2ECC71"},
                        {"range": [0.5, 2], "color": "#F1C40F"},
                        {"range": [2, 4], "color": "#E67E22"},
                        {"range": [4, 6], "color": "#E74C3C"},
                    ],
                },
            ))
            fig.update_layout(height=300, margin=dict(t=40, b=20, l=30, r=30))
            st.plotly_chart(fig, use_container_width=True)

            # Multi-return period comparison
            st.markdown("### Multi-Return Period Analysis")
            if st.button("🔄 Run All Return Periods"):
                rp_results = []
                progress = st.progress(0)
                for i, (rp_name, rp_band) in enumerate(RETURN_PERIODS.items()):
                    result = get_flood_risk_at_point(
                        inputs["lat"],
                        inputs["lon"],
                        rp_band,
                        buffer_radius_m=inputs["buffer_radius_m"],
                    )
                    rp_results.append({
                        "Return Period": rp_name,
                        "Depth (m)": result["depth_m"],
                        "Risk Level": result["risk_level"],
                    })
                    progress.progress((i + 1) / len(RETURN_PERIODS))

                rp_df = pd.DataFrame(rp_results)
                st.dataframe(rp_df, hide_index=True, use_container_width=True)

                fig2 = px.bar(
                    rp_df, x="Return Period", y="Depth (m)",
                    color="Risk Level",
                    color_discrete_map={
                        "No Risk": "#95a5a6", "Low": "#2ecc71",
                        "Moderate": "#f1c40f", "High": "#e67e22", "Severe": "#e74c3c",
                    },
                    title="Flood Depth by Return Period",
                )
                fig2.update_layout(height=350)
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Click **Run Risk Assessment** to query this location.")


# ══════════════════════════════════════════════════════════════════
# PAGE: REPORT
# ══════════════════════════════════════════════════════════════════

def render_report_page(inputs, ee_ready):
    st.markdown("# 📄 Underwriting Report")

    with st.expander("ℹ️ What is this page? How to use it?", expanded=False):
        st.markdown("""
        **What:** A printable/downloadable underwriting report summarizing the entire risk assessment, decision, conditions, and premium indication in a professional format.

        **Why:** Underwriting files require formal documentation for audit trails, regulatory compliance, and communication with brokers/reinsurers. This report captures all data points and the decision rationale in one place.

        **How to use:**
        - The **report preview** shows the full text report — review it for accuracy.
        - **Download buttons:** Choose your preferred format:
          - **TXT** — Plain text for email or printing.
          - **CSV** — Structured data for spreadsheets and analysis.
          - **JSON** — Machine-readable format for API integration or database storage.
        - **Batch Assessment** (below) — Upload a CSV file with `latitude` and `longitude` columns to score multiple locations at once. Great for portfolio-level risk assessment.
        """)

    if "assessment" not in st.session_state:
        st.warning("⚠️ No assessment data. Please run a risk assessment first.")
        return

    data = st.session_state["assessment"]
    cyclone = data["cyclone"]
    flood = data["flood"]
    dem = data.get("dem", {"elevation_m": 0, "risk_level": "Unknown", "risk_score": 0})
    combined = data["combined_score"]
    decision = data["decision"]
    inp = data["inputs"]
    ts = data["timestamp"]

    # ── Report preview ──
    loc_label = inp["city"] if inp["city"] else "Custom"

    map_api_key = inputs.get("places_api_key") or get_places_api_key()
    data = enrich_assessment_for_report(data, map_api_key, ee_ready)
    report_loc = data.get("report_location", {})
    loc_meta = {
        "district": report_loc.get("district", "Unknown"),
        "state": report_loc.get("state", "Unknown"),
    }
    static_map_url = report_loc.get("google_static_map_url", "")
    flood_score = float(((report_loc.get("perils", {}).get("flood", {}) or {}).get("score", 0.0)))

    report_text = f"""
╔══════════════════════════════════════════════════════════════╗
║           NATURAL CATASTROPHE UNDERWRITING REPORT           ║
╚══════════════════════════════════════════════════════════════╝

Report Generated: {ts}
Reference No: UW-NATCAT-{datetime.now().strftime('%Y%m%d%H%M%S')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. RISK LOCATION
   Location: {loc_label}
   Coordinates: {inp['lat']:.4f}°N, {inp['lon']:.4f}°E
    District: {loc_meta.get('district', 'Unknown')}
    State: {loc_meta.get('state', 'Unknown')}

2. RISK LEVEL
    Combined Score: {combined} / 100
    Risk Level: {decision['decision']}

3. INDIVIDUAL PERIL RISK
    Cyclone Score: {cyclone.get('risk_score', 0.0):.1f} / 100 | Category: {cyclone.get('risk_level', 'Unknown')}
    Flood Score: {flood_score:.1f} / 100 | Category: {flood.get('risk_level', 'Unknown')}
    DEM Score: {dem.get('risk_score', 0.0):.1f} / 100 | Category: {dem.get('risk_level', 'Unknown')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

    st.code(report_text, language=None)

    # Download buttons
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            "📥 Download Report (TXT)",
            data=report_text,
            file_name=f"UW_NatCat_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain",
            use_container_width=True,
        )

    with col2:
        # CSV export of key data
        csv_data = pd.DataFrame([{
            "Timestamp": ts,
            "Location": loc_label,
            "Latitude": inp["lat"],
            "Longitude": inp["lon"],
            "District": loc_meta.get("district", "Unknown"),
            "State": loc_meta.get("state", "Unknown"),
            "Combined_Score": combined,
            "Risk_Level": decision["decision"],
        }])
        st.download_button(
            "📥 Download Data (CSV)",
            data=csv_data.to_csv(index=False),
            file_name=f"UW_NatCat_Data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with col3:
        # JSON export
        json_export = {
            "report_id": f"UW-NATCAT-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "timestamp": ts,
            "location": {
                "name": loc_label,
                "lat": inp["lat"],
                "lon": inp["lon"],
                "district": loc_meta.get("district", "Unknown"),
                "state": loc_meta.get("state", "Unknown"),
                "google_static_map_url": static_map_url,
            },
            "risk_assessment": {
                "combined_score": combined,
                "risk_level": decision["decision"],
            },
        }
        st.download_button(
            "📥 Download JSON",
            data=json.dumps(json_export, indent=2, default=str),
            file_name=f"UW_NatCat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True,
        )

    # ── PDF report ──
    st.markdown("")
    pdf_col, _ = st.columns([1, 2])
    with pdf_col:
        try:
            pdf_bytes = build_assessment_pdf(data)
            st.download_button(
                "📕 Download Report (PDF)",
                data=pdf_bytes,
                file_name=f"UW_NatCat_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
        except Exception as _pdf_err:
            st.error(f"PDF generation failed: {_pdf_err}")

    # ── Batch Assessment ──
    st.markdown("---")
    st.markdown("### 📊 Batch Location Assessment")
    with st.expander("ℹ️ How does batch assessment work?"):
        st.markdown("""
        **What:** Score multiple property locations in one go.

        **Why:** Useful for portfolio underwriting, renewal assessments, or comparing risk across a client's multiple sites.

        **How to use:**
        1. Prepare a CSV file with at least two columns: `latitude` and `longitude` (decimal degrees).
        2. Upload the file below — the engine will query Earth Engine for each location.
        3. Results will show a table with cyclone score, flood depth, combined score, and decision for each row.
        4. Download the results as CSV for further analysis.

        **Example CSV format:**
        ```
        latitude,longitude
        19.076,72.878
        13.083,80.271
        22.573,88.364
        ```

        ⚠️ Each location takes a few seconds to query. Large files (50+ rows) may take several minutes.
        """)
    st.markdown("Upload a CSV or Excel file with latitude/longitude columns for batch risk scoring.")

    uploaded = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"])
    if uploaded is not None:
        try:
            file_name = uploaded.name.lower()

            if file_name.endswith(".csv"):
                raw_df = pd.read_csv(uploaded)
            else:
                excel_book = pd.ExcelFile(uploaded)
                sheet_name = (
                    st.selectbox("Select Excel Sheet", excel_book.sheet_names, key="batch_sheet_select")
                    if len(excel_book.sheet_names) > 1
                    else excel_book.sheet_names[0]
                )
                raw_df = pd.read_excel(excel_book, sheet_name=sheet_name)

            if raw_df.empty:
                st.error("Uploaded file is empty.")
                return

            normalized_cols = {str(c).strip().lower(): c for c in raw_df.columns}
            lat_col = next((normalized_cols[k] for k in ["latitude", "lat"] if k in normalized_cols), None)
            lon_col = next((normalized_cols[k] for k in ["longitude", "lon", "lng"] if k in normalized_cols), None)
            name_col = next(
                (
                    normalized_cols[k]
                    for k in ["location", "location_name", "site", "name", "city"]
                    if k in normalized_cols
                ),
                None,
            )

            if lat_col is None or lon_col is None:
                st.error("File must contain latitude/longitude columns. Accepted headers: latitude/lat and longitude/lon/lng.")
                return

            work_df = raw_df.copy()
            work_df["_lat"] = pd.to_numeric(work_df[lat_col], errors="coerce")
            work_df["_lon"] = pd.to_numeric(work_df[lon_col], errors="coerce")

            invalid_mask = (
                work_df["_lat"].isna()
                | work_df["_lon"].isna()
                | (work_df["_lat"] < -90)
                | (work_df["_lat"] > 90)
                | (work_df["_lon"] < -180)
                | (work_df["_lon"] > 180)
            )

            invalid_count = int(invalid_mask.sum())
            valid_df = work_df.loc[~invalid_mask].copy()

            if invalid_count > 0:
                st.warning(f"Skipping {invalid_count} rows with invalid or missing coordinates.")
                preview_cols = [c for c in [name_col, lat_col, lon_col] if c is not None]
                st.dataframe(work_df.loc[invalid_mask, preview_cols].head(10), use_container_width=True)

            if valid_df.empty:
                st.error("No valid coordinate rows found after validation.")
                return

            st.info(f"Processing {len(valid_df)} valid locations...")
            progress = st.progress(0)
            results = []

            for idx, row in valid_df.iterrows():
                lat_val = float(row["_lat"])
                lon_val = float(row["_lon"])
                loc_name = str(row[name_col]).strip() if name_col and pd.notna(row[name_col]) else f"Row {idx + 1}"

                cyc = get_cyclone_risk_at_point(
                    lat_val,
                    lon_val,
                    buffer_radius_m=inp["buffer_radius_m"],
                )
                fld = get_flood_risk_at_point(
                    lat_val,
                    lon_val,
                    inp["flood_band"],
                    buffer_radius_m=inp["buffer_radius_m"],
                )
                dem_risk = get_dem_risk_at_point(
                    lat_val,
                    lon_val,
                    buffer_radius_m=inp["buffer_radius_m"],
                )
                comb = compute_combined_risk_score(cyc["risk_score"], fld["risk_level"], dem_risk["risk_score"])
                dec = make_decision(comb)

                results.append({
                    "Location": loc_name,
                    "Latitude": lat_val,
                    "Longitude": lon_val,
                    "Buffer_Radius_m": inp["buffer_radius_m"],
                    "Flood_Return_Period": inp["flood_rp"],
                    "Elevation_m": dem_risk["elevation_m"],
                    "Cyclone_Score": cyc["risk_score"],
                    "Cyclone_Level": cyc["risk_level"],
                    "Flood_Depth_m": fld["depth_m"],
                    "Flood_Level": fld["risk_level"],
                    "DEM_Risk_Level": dem_risk["risk_level"],
                    "DEM_Risk_Score": dem_risk["risk_score"],
                    "Combined_Score": comb,
                    "Decision": dec["decision"],
                })
                progress.progress(len(results) / len(valid_df))

            result_df = pd.DataFrame(results)

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Processed", len(result_df))
            with c2:
                st.metric("Skipped", invalid_count)
            with c3:
                st.metric("Avg Combined Score", f"{result_df['Combined_Score'].mean():.1f}")

            st.dataframe(result_df, use_container_width=True)

            st.download_button(
                "📥 Download Batch Results (CSV)",
                data=result_df.to_csv(index=False),
                file_name="batch_natcat_results.csv",
                mime="text/csv",
                use_container_width=True,
            )

            excel_output = BytesIO()
            with pd.ExcelWriter(excel_output) as writer:
                result_df.to_excel(writer, index=False, sheet_name="Batch_Results")
            excel_output.seek(0)

            st.download_button(
                "📥 Download Batch Results (Excel)",
                data=excel_output,
                file_name="batch_natcat_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        except Exception as e:
            st.error(f"Error processing file: {e}")


# ══════════════════════════════════════════════════════════════════
# PAGE: HAZARD PROXIMITY (Google Places API)
# ══════════════════════════════════════════════════════════════════

def render_poi_page(inputs, ee_ready):
    st.markdown("# 🏭 Hazard Proximity Risk (Google Places)")
    st.markdown(
        "*Detects high-risk neighbouring assets — refineries, chemical plants, "
        "fuel depots, factories, gas stations, godowns — that contribute "
        "fire, explosion and pollution spillover risk to the insured property.*"
    )

    with st.expander("ℹ️ How does this work?", expanded=False):
        st.markdown("""
        - We query the **Google Places API (Text Search v1)** for each
          selected hazard category, biased to a circle of the chosen
          radius around the property (default **500 m**).
        - Every detected POI is placed into a **proximity band** based on
          its distance from the insured asset:

            | Band | Distance | Weight Multiplier |
            |---|---|---|
            | 🔴 **Very Near** | ≤ 100 m | **× 1.00** (full risk) |
            | 🟠 **Near**      | ≤ 250 m | × 0.70 |
            | 🟡 **Mid-range** | ≤ 400 m | × 0.40 |
            | 🟢 **Far**       | ≤ 500 m | × 0.15 |

        - Each POI contributes `category_weight × multiplier` to a
          cumulative **Hazard Score (0 – 100)**, which maps to a
          **Premium Loading**:
            *None* → 0% &nbsp;·&nbsp; *Low* → 5% &nbsp;·&nbsp;
            *Moderate* → 15% &nbsp;·&nbsp; *High* → 30% &nbsp;·&nbsp;
            *Severe* → 50%
        - Concentric **100 / 250 / 400 / 500 m rings** are drawn around
          the property so you can see at a glance which zone each POI
          falls into.
        """)

    lat = inputs["lat"]
    lon = inputs["lon"]
    radius_m = inputs.get("poi_radius_m", 500)
    api_key = get_places_api_key()

    if not api_key:
        st.error(
            "🔑 **Google Places API key missing.** Paste it in the sidebar "
            "(*Hazard Proximity* section), or set "
            "`GOOGLE_PLACES_API_KEY` in `.streamlit/secrets.toml`."
        )
        st.info(
            "Enable the **Places API (New)** in your Google Cloud project "
            "and create an API key with that API restricted."
        )
        return

    # ── In-page location search ──
    st.markdown("### 📍 Search Asset Location")
    sc1, sc2 = st.columns([3, 1])
    with sc1:
        loc_query = st.text_input(
            "Place name, full address, or `lat, lon`",
            value=st.session_state.get("poi_loc_query", ""),
            placeholder="e.g.  Jamnagar Refinery   |   Andheri East, Mumbai   |   19.119, 72.847",
            key="poi_loc_query_input",
            help="Search any place name / address (Google Geocoding API), "
                 "or paste coordinates as 'lat, lon'.",
        )
    with sc2:
        st.write("")
        st.write("")
        do_search = st.button("🔎 Find", use_container_width=True)

    import re as _re_loc
    _ll_match = _re_loc.match(
        r"^\s*(-?\d+(?:\.\d+)?)\s*[,\s]+\s*(-?\d+(?:\.\d+)?)\s*$",
        loc_query or "",
    )

    if do_search and loc_query:
        st.session_state["poi_loc_query"] = loc_query
        if _ll_match:
            _plat, _plon = float(_ll_match.group(1)), float(_ll_match.group(2))
            if -90 <= _plat <= 90 and -180 <= _plon <= 180:
                st.session_state["poi_lat"] = _plat
                st.session_state["poi_lon"] = _plon
                st.session_state["poi_address"] = f"Coordinates: {_plat:.6f}, {_plon:.6f}"
                st.success(f"📌 Coordinates set: {_plat:.6f}, {_plon:.6f}")
            else:
                st.error("Invalid coordinates.")
        else:
            with st.spinner("Geocoding place name…"):
                hits = geocode_place(loc_query, api_key)
            if not hits:
                st.error("No match found. Try a more specific address.")
            else:
                st.session_state["poi_geocode_hits"] = hits

    hits = st.session_state.get("poi_geocode_hits")
    if hits and not _ll_match:
        labels = [f'{h["address"]}  ({h["lat"]:.5f}, {h["lon"]:.5f})' for h in hits]
        choice = st.selectbox(
            "Matching Locations", labels, key="poi_geocode_choice"
        )
        idx = labels.index(choice)
        st.session_state["poi_lat"] = hits[idx]["lat"]
        st.session_state["poi_lon"] = hits[idx]["lon"]
        st.session_state["poi_address"] = hits[idx]["address"]

    # Effective lat/lon (page override → sidebar fallback)
    lat = st.session_state.get("poi_lat", lat)
    lon = st.session_state.get("poi_lon", lon)

    info1, info2, info3 = st.columns(3)
    with info1:
        st.metric("Latitude", f"{lat:.6f}")
    with info2:
        st.metric("Longitude", f"{lon:.6f}")
    with info3:
        st.metric("Scan Radius", f"{radius_m} m")
    if st.session_state.get("poi_address"):
        st.caption(f"📌 **Selected:** {st.session_state['poi_address']}")

    st.markdown("---")

    # Category multi-select
    cols = st.columns([3, 1])
    with cols[0]:
        selected = st.multiselect(
            "Hazard Categories to Scan",
            options=list(HAZARDOUS_POI_CATEGORIES.keys()),
            default=list(HAZARDOUS_POI_CATEGORIES.keys()),
            help="Each category triggers a separate Places API text search.",
        )
    with cols[1]:
        st.metric("Categories", f"{len(selected)} / {len(HAZARDOUS_POI_CATEGORIES)}")

    scan_btn = st.button("🔍 Scan Nearby Hazards", type="primary", use_container_width=True)

    cache_key = f"poi_results_{lat:.5f}_{lon:.5f}_{radius_m}_{','.join(selected)}"
    if scan_btn:
        if not selected:
            st.warning("Select at least one hazard category.")
            return
        with st.spinner("Querying Google Places API…"):
            pois = search_hazardous_pois(lat, lon, radius_m, api_key, tuple(selected))
        st.session_state[cache_key] = pois

    pois = st.session_state.get(cache_key)
    if pois is None:
        st.info("Click **Scan Nearby Hazards** to query the Google Places API.")
        return

    hazard = compute_poi_hazard_score(pois, radius_m)

    # ── Top metric strip ──
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(
            metric_card("POIs Detected", f"{len(pois)}", "metric-blue"),
            unsafe_allow_html=True,
        )
    with m2:
        st.markdown(
            metric_card("Hazard Score", f"{hazard['score']:.1f} / 100",
                        "metric-orange" if hazard["score"] >= 35 else "metric-yellow"
                        if hazard["score"] >= 15 else "metric-green"),
            unsafe_allow_html=True,
        )
    with m3:
        st.markdown(
            f"<div style='padding-top:1.5rem;text-align:center'>"
            f"<div style='font-size:0.85rem;color:#666'>Risk Level</div>"
            f"{risk_badge(hazard['level'])}</div>",
            unsafe_allow_html=True,
        )
    with m4:
        st.markdown(
            metric_card("Premium Loading",
                        f"+{hazard['loading'] * 100:.0f}%",
                        "metric-red" if hazard["loading"] >= 0.30 else "metric-orange"
                        if hazard["loading"] >= 0.15 else "metric-green"),
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Map ──
    st.markdown("### 🗺️ Hazard Proximity Map")
    fmap = create_base_map(lat=lat, lon=lon, zoom=16)
    add_point_marker(fmap, lat, lon, label="Insured Property")

    # Concentric proximity rings (Very Near → Far) scaled to user radius
    scale = radius_m / 500.0
    for max_d, label, mult, color, _marker in PROXIMITY_BANDS:
        ring_r = max_d * scale
        if ring_r > radius_m:
            continue
        folium.Circle(
            location=[lat, lon],
            radius=ring_r,
            color=color,
            weight=2,
            dash_array="6,6",
            fill=True,
            fill_opacity=0.04,
            popup=f"{label}: ≤ {ring_r:.0f} m  (weight × {mult:.2f})",
        ).add_to(fmap)

    # POI markers, colour-coded by proximity band
    for p in pois:
        folium.Marker(
            location=[p["lat"], p["lon"]],
            icon=folium.Icon(color=p["color"], icon=p["icon"], prefix="fa"),
            popup=folium.Popup(
                f"<b>{p['name']}</b><br>"
                f"<i>{p['category']}</i><br>"
                f"Distance: <b>{p['distance_m']:.0f} m</b><br>"
                f"Proximity Band: <b style='color:{p['band_color']}'>"
                f"{p['band']}</b> (× {p['proximity_multiplier']:.2f})<br>"
                f"Base Weight: {p['weight']} → "
                f"Risk Contribution: "
                f"<b>{p['weight'] * p['proximity_multiplier']:.2f}</b><br>"
                f"<small>{p['address']}</small>",
                max_width=320,
            ),
        ).add_to(fmap)

    folium.LayerControl().add_to(fmap)
    st_folium(fmap, width=None, height=550, returned_objects=[])

    if not pois:
        st.success(
            "✅ No high-risk POIs detected within the scan radius. "
            "The property has no neighbouring hazard exposure from the "
            "selected categories."
        )
        return

    # ── Proximity-band breakdown ──
    st.markdown("### 📍 Hazards by Proximity Band")
    band_order = [b[1] for b in PROXIMITY_BANDS]
    band_rows = []
    for label in band_order:
        info = hazard["by_band"].get(label, {"count": 0, "score": 0.0})
        band_rows.append({
            "Proximity Band": label,
            "Count": info["count"],
            "Risk Contribution": round(info["score"], 2),
        })
    band_df = pd.DataFrame(band_rows)
    bcols = st.columns(len(band_order))
    band_palette = {b[1]: b[3] for b in PROXIMITY_BANDS}
    for i, row in enumerate(band_rows):
        with bcols[i]:
            color = band_palette[row["Proximity Band"]]
            st.markdown(
                f"<div style='background:{color};padding:0.8rem;"
                f"border-radius:10px;color:white;text-align:center'>"
                f"<div style='font-size:0.8rem;opacity:0.9'>"
                f"{row['Proximity Band']}</div>"
                f"<div style='font-size:1.6rem;font-weight:700'>"
                f"{row['Count']}</div>"
                f"<div style='font-size:0.75rem;opacity:0.85'>"
                f"contrib {row['Risk Contribution']:.1f}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("")  # spacer

    # ── Category breakdown ──
    st.markdown("### 📊 Hazard Score by Category")
    cat_df = pd.DataFrame([
        {
            "Category": c,
            "Count": v["count"],
            "Score Contribution": round(v["score"], 2),
        }
        for c, v in hazard["by_category"].items()
    ]).sort_values("Score Contribution", ascending=False)

    bar = px.bar(
        cat_df, x="Score Contribution", y="Category", orientation="h",
        color="Score Contribution", color_continuous_scale="OrRd",
        text="Count",
    )
    bar.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(bar, use_container_width=True)

    # ── Detailed list ──
    st.markdown("### 📋 Detected Hazardous POIs")
    df = pd.DataFrame([{
        "Category": p["category"],
        "Name": p["name"],
        "Address": p["address"],
        "Distance (m)": p["distance_m"],
        "Proximity Band": p["band"],
        "Multiplier": p["proximity_multiplier"],
        "Base Weight": p["weight"],
        "Risk Contribution": round(p["weight"] * p["proximity_multiplier"], 2),
    } for p in pois]).sort_values("Risk Contribution", ascending=False)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Download
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 Download POI list (CSV)",
        data=csv,
        file_name=f"hazard_pois_{lat:.4f}_{lon:.4f}.csv",
        mime="text/csv",
    )


# ══════════════════════════════════════════════════════════════════
# PAGE: SEARCH HISTORY
# ══════════════════════════════════════════════════════════════════

def render_history_page(inputs, ee_ready):
    st.markdown("# 📜 Search History")
    st.markdown(
        "*Every risk assessment you run is automatically saved to a local "
        "SQLite database. Browse, filter, reload, export or delete past "
        "searches below.*"
    )

    history_db.init_db()
    df = history_db.fetch_history()

    if df.empty:
        st.info(
            "No history yet. Run a risk assessment from the **Dashboard** "
            "to start populating your search history."
        )
        return

    # ── Top metrics ──
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Searches", len(df))
    with m2:
        st.metric("Unique Locations",
                  df[["latitude", "longitude"]].drop_duplicates().shape[0])
    with m3:
        st.metric("Avg Combined Score",
                  f"{df['combined_score'].mean():.1f}" if len(df) else "—")
    with m4:
        st.metric("Avg Premium",
                  format_inr(df["total_premium"].mean()) if len(df) else "—")

    st.markdown("---")

    # ── Filters ──
    st.markdown("### 🔎 Filters")
    f1, f2, f3 = st.columns([2, 2, 1])
    with f1:
        loc_filter = st.text_input(
            "Location contains",
            placeholder="e.g. Mumbai, Custom, Chennai…",
            key="hist_loc_filter",
        )
    with f2:
        decisions = sorted(d for d in df["decision"].dropna().unique())
        dec_filter = st.multiselect(
            "Decision",
            options=decisions,
            default=[],
            key="hist_dec_filter",
        )
    with f3:
        limit = st.number_input(
            "Max rows", min_value=10, max_value=10000, value=200, step=10,
            key="hist_limit",
        )

    fdf = df.copy()
    if loc_filter:
        fdf = fdf[fdf["location"].astype(str).str.contains(loc_filter,
                                                           case=False, na=False)]
    if dec_filter:
        fdf = fdf[fdf["decision"].isin(dec_filter)]
    fdf = fdf.head(int(limit))

    # ── Table ──
    st.markdown(f"### 📋 Records ({len(fdf)} shown)")
    display_df = fdf.copy()
    if "timestamp" in display_df.columns:
        display_df["timestamp"] = display_df["timestamp"].astype(str).str.replace(
            "T", " ", regex=False).str.slice(0, 19)
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.NumberColumn("ID", width="small"),
            "tsi": st.column_config.NumberColumn("TSI", format="₹%d"),
            "net_premium": st.column_config.NumberColumn("Net Premium",
                                                        format="₹%d"),
            "total_premium": st.column_config.NumberColumn("Total Premium",
                                                          format="₹%d"),
            "cyclone_score": st.column_config.NumberColumn("Cyc",
                                                          format="%.1f"),
            "combined_score": st.column_config.NumberColumn("Combined",
                                                           format="%.1f"),
            "flood_depth_m": st.column_config.NumberColumn("Flood (m)",
                                                          format="%.2f"),
            "dem_elevation_m": st.column_config.NumberColumn("Elev (m)",
                                                            format="%.1f"),
        },
    )

    st.markdown("---")

    # ── Row actions ──
    st.markdown("### 🛠️ Row Actions")
    id_options = fdf["id"].tolist() if not fdf.empty else []
    if id_options:
        a1, a2, a3 = st.columns([2, 1, 1])
        with a1:
            sel_id = st.selectbox(
                "Select a record",
                options=id_options,
                format_func=lambda i: (
                    f"#{i} — "
                    f"{fdf.loc[fdf['id'] == i, 'location'].iloc[0]} "
                    f"({str(fdf.loc[fdf['id'] == i, 'timestamp'].iloc[0])[:19]})"
                ),
                key="hist_row_select",
            )
        with a2:
            if st.button("🔁 Reload", use_container_width=True,
                         help="Restore this assessment as the active one."):
                payload = history_db.fetch_payload(int(sel_id))
                if payload:
                    st.session_state["assessment"] = payload
                    st.success(
                        f"Loaded record #{sel_id}. "
                        "Open **Dashboard** or **Report** to view it."
                    )
                else:
                    st.error("Could not load that record.")
        with a3:
            if st.button("🗑️ Delete", use_container_width=True,
                         help="Permanently delete this record."):
                history_db.delete_row(int(sel_id))
                st.success(f"Deleted record #{sel_id}.")
                st.rerun()

        # Per-row PDF
        payload = history_db.fetch_payload(int(sel_id))
        if payload:
            try:
                payload = enrich_assessment_for_report(
                    payload,
                    get_places_api_key(),
                    ee_ready,
                )
                pdf_bytes = build_assessment_pdf(payload)
                st.download_button(
                    "📕 Download PDF for this Record",
                    data=pdf_bytes,
                    file_name=f"UW_NatCat_Record_{sel_id}.pdf",
                    mime="application/pdf",
                )
            except Exception as _e:
                st.warning(f"PDF generation failed: {_e}")

    st.markdown("---")

    # ── Bulk export ──
    st.markdown("### 📥 Export Filtered History")
    e1, e2, e3 = st.columns(3)
    with e1:
        st.download_button(
            "Download CSV",
            data=fdf.to_csv(index=False).encode("utf-8"),
            file_name="natcat_search_history.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with e2:
        excel_buf = BytesIO()
        with pd.ExcelWriter(excel_buf) as writer:
            fdf.to_excel(writer, sheet_name="History", index=False)
        excel_buf.seek(0)
        st.download_button(
            "Download Excel",
            data=excel_buf,
            file_name="natcat_search_history.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with e3:
        try:
            hist_pdf = build_history_pdf(fdf)
            st.download_button(
                "Download PDF",
                data=hist_pdf,
                file_name="natcat_search_history.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as _e:
            st.error(f"History PDF failed: {_e}")

    st.markdown("---")
    with st.expander("⚠️ Danger Zone — Clear all history"):
        st.warning("This permanently deletes every record from the local "
                   "history database. This cannot be undone.")
        confirm = st.text_input(
            "Type **DELETE ALL** to confirm",
            key="hist_clear_confirm",
        )
        if st.button("Clear All History", type="secondary"):
            if confirm.strip() == "DELETE ALL":
                history_db.clear_all()
                st.success("All history cleared.")
                st.rerun()
            else:
                st.error("Confirmation text did not match. Nothing deleted.")


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def main():
    ee_ready, ee_error = init_earth_engine()
    inputs = render_sidebar()

    page = inputs["page"]

    if page == "📊 Dashboard":
        render_dashboard(inputs, ee_ready, ee_error)
    elif page == "🌀 Cyclone Risk":
        render_cyclone_page(inputs, ee_ready)
    elif page == "🌊 Flood Risk":
        render_flood_page(inputs, ee_ready)
    elif page == "🗻 DEM Low-Lying Risk":
        render_dem_page(inputs, ee_ready)
    elif page == "💧 Water Body Proximity":
        render_water_page(inputs, ee_ready)
    elif page == "🏭 Hazard Proximity (POI)":
        render_poi_page(inputs, ee_ready)
    elif page == "📄 Report":
        render_report_page(inputs, ee_ready)
    elif page == "📜 History":
        render_history_page(inputs, ee_ready)


if __name__ == "__main__":
    main()
