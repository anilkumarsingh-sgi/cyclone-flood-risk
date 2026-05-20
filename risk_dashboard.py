"""
╔══════════════════════════════════════════════════════════════════╗
║      MULTI-HAZARD NATURAL CATASTROPHE RISK ANALYSIS PLATFORM   ║
║      Cyclone · Flood · Elevation   |  India Risk Intelligence  ║
║      Powered by Google Earth Engine + Streamlit                 ║
╚══════════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import ee
import folium
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import re as _re
from streamlit_folium import st_folium
from datetime import datetime

# ──────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NatCat Risk Intelligence",
    page_icon="🌪️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────
# THEME & CUSTOM CSS
# ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main .block-container { padding-top: 0.8rem; max-width: 1500px; }
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }

    /* ── Score cards ── */
    .score-card {
        background: #1e1e2e;
        border: 1px solid #313244;
        border-radius: 14px;
        padding: 1.1rem 1rem;
        text-align: center;
        transition: transform .15s;
    }
    .score-card:hover { transform: translateY(-3px); }
    .score-card .label { font-size: 0.72rem; color: #a6adc8; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px; }
    .score-card .value { font-size: 2rem; font-weight: 800; margin: 0; }
    .score-card .sub   { font-size: 0.78rem; color: #cdd6f4; margin-top: 2px; }

    .card-cyclone  { border-top: 3px solid #cba6f7; }
    .card-flood    { border-top: 3px solid #89dceb; }
    .card-dem      { border-top: 3px solid #a6e3a1; }
    .card-combined { border-top: 3px solid #fab387; }
    .card-rank     { border-top: 3px solid #f38ba8; }

    /* ── Risk pills ── */
    .pill {
        display: inline-block; padding: 3px 14px; border-radius: 20px;
        font-weight: 700; font-size: 0.82rem; letter-spacing: 0.4px;
    }
    .pill-low      { background: #a6e3a1; color: #1e1e2e; }
    .pill-moderate { background: #f9e2af; color: #1e1e2e; }
    .pill-high     { background: #fab387; color: #1e1e2e; }
    .pill-veryhigh { background: #f38ba8; color: #1e1e2e; }
    .pill-extreme  { background: #cba6f7; color: #1e1e2e; }
    .pill-norisk   { background: #585b70; color: #cdd6f4; }

    /* ── Section header bar ── */
    .sec-head {
        display: flex; align-items: center; gap: 10px;
        border-left: 4px solid #89b4fa; padding-left: 12px;
        margin: 1.4rem 0 0.8rem 0;
    }
    .sec-head h3 { margin: 0; font-size: 1.1rem; color: #cdd6f4; }

    /* ── Hazard band bar ── */
    .hazard-bar-wrap { background: #313244; border-radius: 8px; height: 14px; overflow: hidden; margin: 4px 0 10px 0; }
    .hazard-bar      { height: 100%; border-radius: 8px; transition: width .5s; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════

CYCLONE_THRESHOLDS = {
    "Low":       (0,  20),
    "Moderate":  (20, 40),
    "High":      (40, 60),
    "Very High": (60, 80),
    "Extreme":   (80, 100),
}

FLOOD_THRESHOLDS = {
    "No Risk":  (None, 0),
    "Low":      (0,   0.5),
    "Moderate": (0.5, 2.0),
    "High":     (2.0, 4.0),
    "Severe":   (4.0, float("inf")),
}

DEM_THRESHOLDS = {
    "Very High Risk": (None, 10),
    "High Risk":      (10,  25),
    "Moderate Risk":  (25,  50),
    "Low Risk":       (50, 100),
    "Very Low Risk":  (100, float("inf")),
}

DEM_8CLASS = [
    (None, 5,            "< 5 m"),
    (5,    10,           "5–10 m"),
    (10,   20,           "10–20 m"),
    (20,   35,           "20–35 m"),
    (35,   50,           "35–50 m"),
    (50,   100,          "50–100 m"),
    (100,  200,          "100–200 m"),
    (200,  float("inf"), "> 200 m"),
]

RETURN_PERIODS = {
    "10-Year  (10% annual)":   "RP10_depth",
    "20-Year  (5% annual)":    "RP20_depth",
    "50-Year  (2% annual)":    "RP50_depth",
    "75-Year  (1.3% annual)":  "RP75_depth",
    "100-Year (1% annual)":    "RP100_depth",
    "200-Year (0.5% annual)":  "RP200_depth",
    "500-Year (0.2% annual)":  "RP500_depth",
}

REFERENCE_LOCATIONS = {
    "Mumbai":               (19.0760, 72.8777),
    "Chennai":              (13.0827, 80.2707),
    "Kolkata":              (22.5726, 88.3639),
    "Visakhapatnam":        (17.6868, 83.2185),
    "Bhubaneswar":          (20.2961, 85.8245),
    "Puri":                 (19.8135, 85.8312),
    "Surat":                (21.1702, 72.8311),
    "Mangalore":            (12.9141, 74.8560),
    "Kochi":                (9.9312,  76.2673),
    "Thiruvananthapuram":   (8.5241,  76.9366),
    "Goa (Panaji)":         (15.4909, 73.8278),
    "Puducherry":           (11.9416, 79.8083),
    "Ratnagiri":            (16.9902, 73.3120),
    "Machilipatnam":        (16.1875, 81.1389),
    "Paradip":              (20.3165, 86.6114),
    "New Delhi":            (28.6139, 77.2090),
    "Bengaluru":            (12.9716, 77.5946),
    "Hyderabad":            (17.3850, 78.4867),
    "Ahmedabad":            (23.0225, 72.5714),
    "Jaipur":               (26.9124, 75.7873),
    "Nagpur":               (21.1458, 79.0882),
    "Patna":                (25.5941, 85.1376),
    "Lucknow":              (26.8467, 80.9462),
    "Bhopal":               (23.2599, 77.4126),
    "Indore":               (22.7196, 75.8577),
    "Ranchi":               (23.3441, 85.3096),
    "Raipur":               (21.2514, 81.6296),
}

# Flood score mapping for composite
FLOOD_SCORE_MAP = {"No Risk": 0, "Low": 15, "Moderate": 40, "High": 70, "Severe": 95}

# DEM risk score mapping
DEM_SCORE_MAP = {
    "Very High Risk": 85, "High Risk": 65,
    "Moderate Risk": 35, "Low Risk": 12, "Very Low Risk": 2,
}

# ══════════════════════════════════════════════════════════════════
# EARTH ENGINE INIT
# ══════════════════════════════════════════════════════════════════

@st.cache_resource
def init_earth_engine():
    try:
        ee.Initialize(project="ee-singhanil854")
        return True
    except Exception:
        try:
            ee.Authenticate()
            ee.Initialize(project="ee-singhanil854")
            return True
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════
# EE — CYCLONE ENGINE
# ══════════════════════════════════════════════════════════════════

def _build_cyclone_hazard():
    region = ee.Geometry.Rectangle([40, -5, 110, 35])
    proj   = ee.Projection("EPSG:4326").atScale(20000)
    storms = ee.FeatureCollection("NOAA/IBTrACS/v4")
    cyc    = storms.filter(ee.Filter.eq("BASIN", "NI")).filterBounds(region)
    cyc    = cyc.map(lambda f: f.set("constant", 1))
    freq   = cyc.reduceToImage(["constant"], ee.Reducer.sum()).reproject(crs=proj)
    intns  = cyc.reduceToImage(["USA_WIND"],  ee.Reducer.mean()).reproject(crs=proj)
    freq   = freq.focal_mean(radius=90000, units="meters").reproject(crs=proj)
    intns  = intns.focal_mean(radius=90000, units="meters").reproject(crs=proj)
    hazard = intns.multiply(freq).rename("hazard").clip(region).updateMask(
        intns.multiply(freq).gt(0)
    )
    return hazard, region, proj


def build_cyclone_risk_image():
    hazard, region, _ = _build_cyclone_hazard()
    stats = hazard.reduceRegion(
        reducer=ee.Reducer.percentile([10, 90]),
        geometry=region, scale=20000, bestEffort=True, maxPixels=int(1e13),
    )
    p10  = ee.Number(stats.get("hazard_p10"))
    p90  = ee.Number(stats.get("hazard_p90"))
    risk = hazard.subtract(p10).divide(p90.subtract(p10)).clamp(0, 1).multiply(100)
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
def get_cyclone_risk(lat, lon, buffer_m=500):
    hazard, region, _ = _build_cyclone_hazard()
    stats = hazard.reduceRegion(
        reducer=ee.Reducer.percentile([10, 90]),
        geometry=region, scale=20000, bestEffort=True, maxPixels=int(1e13),
    )
    p10  = ee.Number(stats.get("hazard_p10"))
    p90  = ee.Number(stats.get("hazard_p90"))
    risk = hazard.subtract(p10).divide(p90.subtract(p10)).clamp(0, 1).multiply(100).rename("risk")

    pt   = ee.Geometry.Point([lon, lat])
    geom = pt if buffer_m <= 0 else pt.buffer(buffer_m)
    val  = risk.reduceRegion(ee.Reducer.mean(), geom, scale=20000, bestEffort=True).getInfo().get("risk")

    if val is None:
        return {"score": 0.0, "level": "Low", "percentile": 0.0}

    score = round(float(val), 2)
    level = next((l for l, (lo, hi) in CYCLONE_THRESHOLDS.items() if lo <= score < hi), "Extreme")
    return {"score": score, "level": level}


# ══════════════════════════════════════════════════════════════════
# EE — FLOOD ENGINE
# ══════════════════════════════════════════════════════════════════

def build_flood_risk_image(band="RP100_depth"):
    fc   = ee.ImageCollection("JRC/CEMS_GLOFAS/FloodHazard/v2_1").mosaic()
    dep  = fc.select(band).updateMask(fc.select(band).gt(0))
    cls  = dep.expression(
        "(b(0)>0 && b(0)<0.5)?2:(b(0)<2)?4:(b(0)<4)?6:8"
    ).updateMask(dep)
    return cls, dep


@st.cache_data(ttl=3600, show_spinner=False)
def get_flood_risk(lat, lon, band="RP100_depth", buffer_m=500):
    pt   = ee.Geometry.Point([lon, lat])
    geom = pt if buffer_m <= 0 else pt.buffer(buffer_m)
    fc   = ee.ImageCollection("JRC/CEMS_GLOFAS/FloodHazard/v2_1").mosaic()
    val  = fc.select(band).reduceRegion(ee.Reducer.mean(), geom, scale=90, bestEffort=True).getInfo().get(band)

    if val is None or val <= 0:
        return {"depth_m": 0.0, "level": "No Risk", "score": 0}

    depth = round(float(val), 3)
    level = ("Low" if depth < 0.5 else "Moderate" if depth < 2.0 else "High" if depth < 4.0 else "Severe")
    return {"depth_m": depth, "level": level, "score": FLOOD_SCORE_MAP[level]}


@st.cache_data(ttl=3600, show_spinner=False)
def get_flood_all_rp(lat, lon, buffer_m=500):
    """Query all 7 return periods at once."""
    results = []
    for label, band in RETURN_PERIODS.items():
        r = get_flood_risk(lat, lon, band, buffer_m)
        results.append({"Return Period": label, "Depth (m)": r["depth_m"],
                        "Risk Level": r["level"], "Score": r["score"]})
    return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════════
# EE — DEM ENGINE
# ══════════════════════════════════════════════════════════════════

def build_dem_image():
    dem = ee.Image("USGS/SRTMGL1_003").select("elevation")
    classified = (
        ee.Image(0)
        .where(dem.lt(5), 1)
        .where(dem.gte(5).And(dem.lt(10)), 2)
        .where(dem.gte(10).And(dem.lt(20)), 3)
        .where(dem.gte(20).And(dem.lt(35)), 4)
        .where(dem.gte(35).And(dem.lt(50)), 5)
        .where(dem.gte(50).And(dem.lt(100)), 6)
        .where(dem.gte(100).And(dem.lt(200)), 7)
        .where(dem.gte(200), 8)
        .selfMask()
    )
    return classified, dem


@st.cache_data(ttl=3600, show_spinner=False)
def get_dem_risk(lat, lon, buffer_m=500):
    pt   = ee.Geometry.Point([lon, lat])
    geom = pt if buffer_m <= 0 else pt.buffer(buffer_m)
    dem  = ee.Image("USGS/SRTMGL1_003")
    val  = dem.reduceRegion(ee.Reducer.mean(), geom, scale=30, bestEffort=True).getInfo().get("elevation")

    if val is None:
        return {"elevation_m": 0.0, "level": "Unknown", "score": 20, "class_label": "N/A"}

    elev = round(float(val), 2)
    level = next(
        (l for l, (lo, hi) in DEM_THRESHOLDS.items()
         if (lo is None and elev < hi) or (lo is not None and (hi == float("inf") and elev >= lo) or (lo is not None and lo <= elev < hi))),
        "Very Low Risk",
    )
    score = DEM_SCORE_MAP.get(level, 20)
    cls   = next((lbl for lo, hi, lbl in DEM_8CLASS
                  if (lo is None and elev < hi) or (lo is not None and elev >= lo and (hi == float("inf") or elev < hi))), "> 200 m")
    return {"elevation_m": elev, "level": level, "score": score, "class_label": cls}


# ══════════════════════════════════════════════════════════════════
# COMPOSITE RISK
# ══════════════════════════════════════════════════════════════════

def composite_risk(cyclone_score, flood_level, dem_score,
                   w_cyclone=0.45, w_flood=0.35, w_dem=0.20):
    """Weighted composite hazard index (0–100)."""
    flood_numeric = FLOOD_SCORE_MAP.get(flood_level, 0)
    raw = w_cyclone * cyclone_score + w_flood * flood_numeric + w_dem * dem_score
    return round(min(raw, 100), 2)


def composite_level(score):
    if score < 20:  return "Low"
    if score < 40:  return "Moderate"
    if score < 60:  return "High"
    if score < 80:  return "Very High"
    return "Extreme"


def score_color(score):
    if score < 20:  return "#a6e3a1"
    if score < 40:  return "#f9e2af"
    if score < 60:  return "#fab387"
    if score < 80:  return "#f38ba8"
    return "#cba6f7"


def level_pill(level):
    css = {
        "Low": "pill-low", "No Risk": "pill-norisk",
        "Very Low Risk": "pill-low",
        "Moderate": "pill-moderate", "Moderate Risk": "pill-moderate",
        "High": "pill-high", "High Risk": "pill-high",
        "Very High": "pill-veryhigh", "Very High Risk": "pill-veryhigh",
        "Extreme": "pill-extreme", "Severe": "pill-extreme",
    }.get(level, "pill-norisk")
    return f'<span class="pill {css}">{level}</span>'


# ══════════════════════════════════════════════════════════════════
# MAP UTILITIES
# ══════════════════════════════════════════════════════════════════

def base_map(lat=20.0, lon=78.0, zoom=5):
    m = folium.Map(location=[lat, lon], zoom_start=zoom,
                   tiles="CartoDB dark_matter", control_scale=True)
    folium.TileLayer("CartoDB positron", name="Light").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite",
    ).add_to(m)
    return m


def add_ee_layer(fmap, image, vis, name, opacity=0.75):
    try:
        url = image.getMapId(vis)["tile_fetcher"].url_format
        folium.TileLayer(tiles=url, attr="GEE", name=name,
                         overlay=True, control=True, opacity=opacity).add_to(fmap)
    except Exception as exc:
        st.caption(f"⚠️ {name} layer unavailable: {exc}")


def add_point(fmap, lat, lon, label="", color="red"):
    folium.Marker(
        [lat, lon],
        tooltip=f"<b>{label}</b><br>{lat:.5f}, {lon:.5f}",
        popup=folium.Popup(f"<b>{label}</b><br>Lat: {lat:.5f}<br>Lon: {lon:.5f}", max_width=220),
        icon=folium.Icon(color=color, icon="crosshairs", prefix="fa"),
    ).add_to(fmap)


def add_buffer(fmap, lat, lon, radius_m):
    if radius_m > 0:
        folium.Circle(
            [lat, lon], radius=radius_m,
            color="#89b4fa", fill=True, fill_opacity=0.10,
            weight=2, popup=f"Buffer: {radius_m} m",
        ).add_to(fmap)


# ══════════════════════════════════════════════════════════════════
# CHART HELPERS
# ══════════════════════════════════════════════════════════════════

GAUGE_STEPS = [
    {"range": [0,  20],  "color": "#1e3a2f"},
    {"range": [20, 40],  "color": "#3d3515"},
    {"range": [40, 60],  "color": "#3d2510"},
    {"range": [60, 80],  "color": "#3d1015"},
    {"range": [80, 100], "color": "#2e1040"},
]


def gauge_chart(value, title, max_val=100, suffix=""):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": suffix, "font": {"size": 28, "color": "#cdd6f4"}},
        title={"text": title, "font": {"size": 13, "color": "#a6adc8"}},
        gauge={
            "axis": {"range": [0, max_val], "tickcolor": "#585b70",
                     "tickfont": {"color": "#a6adc8"}},
            "bar":  {"color": score_color(value if max_val == 100 else value * 100 / max_val),
                     "thickness": 0.25},
            "bgcolor": "#1e1e2e",
            "borderwidth": 0,
            "steps": GAUGE_STEPS,
            "threshold": {
                "line": {"color": "#cdd6f4", "width": 3},
                "thickness": 0.8,
                "value": value,
            },
        },
    ))
    fig.update_layout(
        height=240,
        paper_bgcolor="#1e1e2e",
        plot_bgcolor="#1e1e2e",
        margin=dict(t=55, b=10, l=20, r=20),
        font={"color": "#cdd6f4"},
    )
    return fig


def radar_chart(cyclone_score, flood_score, dem_score, label="Location"):
    categories = ["Cyclone\nHazard", "Flood\nHazard", "Elevation\nRisk",
                  "Combined\nIndex", "Coast\nExposure"]
    coast_proxy = min(cyclone_score * 1.1, 100)
    combined    = composite_risk(cyclone_score,
                                 next(l for l, s in FLOOD_SCORE_MAP.items() if s == flood_score or True),
                                 dem_score)
    values = [cyclone_score, flood_score, dem_score, combined, coast_proxy]
    values_closed = values + [values[0]]
    cats_closed   = categories + [categories[0]]

    fig = go.Figure(go.Scatterpolar(
        r=values_closed, theta=cats_closed,
        fill="toself",
        fillcolor="rgba(203,166,247,0.2)",
        line=dict(color="#cba6f7", width=2),
        name=label,
    ))
    fig.update_layout(
        polar=dict(
            bgcolor="#181825",
            radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(color="#585b70"),
                            gridcolor="#313244", linecolor="#313244"),
            angularaxis=dict(tickfont=dict(color="#a6adc8"), gridcolor="#313244"),
        ),
        showlegend=False,
        paper_bgcolor="#1e1e2e",
        height=320,
        margin=dict(t=30, b=30, l=50, r=50),
        font={"color": "#cdd6f4"},
    )
    return fig


def risk_matrix_heatmap(w_cyclone=0.45, w_flood=0.35, w_dem=0.20, dem_fixed=20):
    c_levels = list(CYCLONE_THRESHOLDS.keys())
    f_levels  = [k for k in FLOOD_SCORE_MAP if k != "No Risk"]
    z = []
    for fl in f_levels:
        row = []
        for cl in c_levels:
            lo, hi = CYCLONE_THRESHOLDS[cl]
            c_mid  = (lo + hi) / 2
            score  = composite_risk(c_mid, fl, dem_fixed, w_cyclone, w_flood, w_dem)
            row.append(round(score, 1))
        z.append(row)

    fig = go.Figure(go.Heatmap(
        z=z, x=c_levels, y=f_levels,
        colorscale=[
            [0.00, "#1e3a2f"], [0.25, "#f9e2af"],
            [0.55, "#fab387"], [0.80, "#f38ba8"], [1.00, "#cba6f7"],
        ],
        text=[[f"{v}" for v in row] for row in z],
        texttemplate="%{text}",
        textfont={"size": 13, "color": "#1e1e2e"},
        hovertemplate="Cyclone: %{x}<br>Flood: %{y}<br>Composite: %{z}<extra></extra>",
        showscale=True,
        zmin=0, zmax=100,
    ))
    fig.update_layout(
        paper_bgcolor="#1e1e2e", plot_bgcolor="#1e1e2e",
        height=340,
        font={"color": "#cdd6f4"},
        xaxis=dict(title="Cyclone Risk Level", tickfont=dict(color="#a6adc8"),
                   gridcolor="#313244"),
        yaxis=dict(title="Flood Risk Level", tickfont=dict(color="#a6adc8"),
                   gridcolor="#313244"),
        margin=dict(t=20, b=50, l=90, r=20),
    )
    return fig


def flood_rp_chart(df: pd.DataFrame):
    color_map = {"No Risk": "#585b70", "Low": "#a6e3a1",
                 "Moderate": "#f9e2af", "High": "#fab387", "Severe": "#f38ba8"}
    fig = px.bar(
        df, x="Return Period", y="Depth (m)", color="Risk Level",
        color_discrete_map=color_map,
        text="Depth (m)",
    )
    fig.update_traces(texttemplate="%{text:.2f}m", textposition="outside",
                      textfont_color="#cdd6f4")
    fig.update_layout(
        paper_bgcolor="#1e1e2e", plot_bgcolor="#181825",
        height=380, showlegend=True,
        font={"color": "#cdd6f4"},
        xaxis=dict(tickangle=-30, tickfont=dict(size=10), gridcolor="#313244"),
        yaxis=dict(gridcolor="#313244", title="Flood Depth (m)"),
        legend=dict(bgcolor="#1e1e2e", bordercolor="#313244", borderwidth=1),
        margin=dict(t=20, b=80, l=60, r=20),
    )
    return fig


def score_decomposition_chart(cyclone_score, flood_score, dem_score,
                               w_c=0.45, w_f=0.35, w_d=0.20):
    contributions = {
        "🌀 Cyclone": round(w_c * cyclone_score, 1),
        "🌊 Flood":   round(w_f * flood_score,   1),
        "⛰️ Elevation": round(w_d * dem_score,  1),
    }
    colors = ["#cba6f7", "#89dceb", "#a6e3a1"]
    fig = go.Figure(go.Bar(
        x=list(contributions.values()),
        y=list(contributions.keys()),
        orientation="h",
        marker_color=colors,
        text=[f"{v:.1f}" for v in contributions.values()],
        textposition="outside",
        textfont=dict(color="#cdd6f4"),
    ))
    fig.update_layout(
        paper_bgcolor="#1e1e2e", plot_bgcolor="#181825",
        height=200,
        font={"color": "#cdd6f4"},
        xaxis=dict(range=[0, 60], gridcolor="#313244", title="Contribution to Composite (pts)"),
        yaxis=dict(gridcolor="#313244"),
        margin=dict(t=10, b=30, l=120, r=60),
        showlegend=False,
    )
    return fig


def multi_location_comparison(locations_data: list):
    """Bar chart comparing composite scores across saved locations."""
    if not locations_data:
        return None
    names  = [d["name"] for d in locations_data]
    cyc    = [d["cyclone_score"] for d in locations_data]
    fld    = [d["flood_score"] for d in locations_data]
    dem    = [d["dem_score"] for d in locations_data]
    comp   = [d["composite"] for d in locations_data]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="🌀 Cyclone",  x=names, y=cyc, marker_color="#cba6f7"))
    fig.add_trace(go.Bar(name="🌊 Flood",    x=names, y=fld, marker_color="#89dceb"))
    fig.add_trace(go.Bar(name="⛰️ Elevation",x=names, y=dem, marker_color="#a6e3a1"))
    fig.add_trace(go.Scatter(name="◆ Composite", x=names, y=comp,
                             mode="markers+lines",
                             marker=dict(color="#fab387", size=12, symbol="diamond"),
                             line=dict(color="#fab387", width=2, dash="dot")))
    fig.update_layout(
        barmode="group",
        paper_bgcolor="#1e1e2e", plot_bgcolor="#181825",
        height=380,
        font={"color": "#cdd6f4"},
        xaxis=dict(tickfont=dict(color="#a6adc8"), gridcolor="#313244"),
        yaxis=dict(range=[0, 105], title="Risk Score (0–100)", gridcolor="#313244"),
        legend=dict(bgcolor="#1e1e2e", bordercolor="#313244", borderwidth=1),
        margin=dict(t=20, b=60, l=60, r=20),
    )
    return fig


# ══════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════

def render_sidebar():
    with st.sidebar:
        st.markdown("## 🌪️ Risk Intelligence")
        st.markdown("<small style='color:#a6adc8'>Multi-Hazard NatCat Analysis · India</small>",
                    unsafe_allow_html=True)
        st.markdown("---")

        page = st.radio("Navigation", [
            "🗺️  Hazard Map",
            "🌀  Cyclone Analysis",
            "🌊  Flood Analysis",
            "⛰️  Elevation Risk",
            "📊  Composite Score",
            "📍  Multi-Location",
        ], label_visibility="collapsed")

        st.markdown("---")
        st.markdown("### 📍 Location")

        # Session state defaults
        for k, v in [("lat_s", 19.076), ("lon_s", 72.878), ("loc_name", "Mumbai")]:
            if k not in st.session_state:
                st.session_state[k] = v

        query = st.text_input(
            "Search or paste lat, lon",
            placeholder="e.g. Chennai  or  13.08, 80.27",
            label_visibility="visible",
        )

        # Detect pasted coordinates
        _pat   = _re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,\s]+\s*(-?\d+(?:\.\d+)?)\s*$")
        _match = _pat.match(query) if query else None

        if _match:
            _plat, _plon = float(_match.group(1)), float(_match.group(2))
            if -90 <= _plat <= 90 and -180 <= _plon <= 180:
                st.session_state["lat_s"] = _plat
                st.session_state["lon_s"] = _plon
                st.session_state["loc_name"] = f"{_plat:.4f}, {_plon:.4f}"
            st.success(f"📌 {_plat:.5f}, {_plon:.5f}")
            loc_name = st.session_state["loc_name"]
        else:
            hits = [n for n in REFERENCE_LOCATIONS if not query or query.lower() in n.lower()]
            if hits:
                sel = st.selectbox("Matching locations", hits)
                if sel != st.session_state.get("loc_name"):
                    st.session_state["lat_s"]    = REFERENCE_LOCATIONS[sel][0]
                    st.session_state["lon_s"]    = REFERENCE_LOCATIONS[sel][1]
                    st.session_state["loc_name"] = sel
                loc_name = sel
            else:
                st.info("No match — type coordinates manually above.")
                loc_name = st.session_state.get("loc_name", "Custom")

        lat = st.session_state["lat_s"]
        lon = st.session_state["lon_s"]

        # Show coords as read-only info
        st.caption(f"📌 Lat: `{lat:.5f}`  |  Lon: `{lon:.5f}`")

        st.markdown("---")
        st.markdown("### ⚙️ Query Settings")

        buffer_m = st.slider("Buffer Radius (m)", 0, 5000, 500, 50,
                              help="Spatial averaging radius around the selected point.")

        flood_rp_label = st.selectbox("Flood Return Period", list(RETURN_PERIODS.keys()), index=4)
        flood_band     = RETURN_PERIODS[flood_rp_label]

        st.markdown("---")
        st.markdown("### ⚖️ Composite Weights")
        w_c = st.slider("Cyclone Weight %",   0, 100, 45, 5) / 100
        w_f = st.slider("Flood Weight %",     0, 100, 35, 5) / 100
        w_d = st.slider("Elevation Weight %", 0, 100, 20, 5) / 100
        total_w = w_c + w_f + w_d
        if abs(total_w - 1.0) > 0.01:
            st.warning(f"Weights sum to {total_w*100:.0f}%. Normalising automatically.")
            if total_w > 0:
                w_c /= total_w; w_f /= total_w; w_d /= total_w

        st.markdown("---")
        run = st.button("🔍 Run Risk Analysis", use_container_width=True, type="primary")

        st.markdown("---")
        st.caption("© 2026 NatCat Risk Intelligence Platform")

    return {
        "page": page, "lat": lat, "lon": lon, "loc_name": loc_name,
        "buffer_m": buffer_m, "flood_rp_label": flood_rp_label,
        "flood_band": flood_band,
        "w_c": w_c, "w_f": w_f, "w_d": w_d,
        "run": run,
    }


# ══════════════════════════════════════════════════════════════════
# PAGE: HAZARD MAP  (default landing)
# ══════════════════════════════════════════════════════════════════

def page_hazard_map(cfg, ee_ok):
    st.markdown("# 🗺️ Multi-Hazard Risk Map")
    st.caption("Cyclone intensity × frequency · Flood inundation depth · DEM elevation — all in one interactive view.")

    if not ee_ok:
        st.error("Earth Engine not authenticated. Run `earthengine authenticate` and restart.")
        return

    col_ctrl, col_map = st.columns([1, 3])

    with col_ctrl:
        st.markdown("**Map Layers**")
        show_cyc   = st.checkbox("🌀 Cyclone Risk",    value=True)
        show_flood = st.checkbox("🌊 Flood Hazard",    value=True)
        show_dem   = st.checkbox("⛰️ Elevation (DEM)", value=False)
        opacity    = st.slider("Layer Opacity", 0.1, 1.0, 0.70, 0.05)
        zoom       = st.slider("Zoom Level", 3, 14, 5, 1)

        st.markdown("---")
        st.markdown("**Legend — Cyclone**")
        st.markdown("""
        <div style='font-size:0.78rem; line-height:2'>
        🟢 Low &nbsp;&nbsp; 🟡 Moderate &nbsp;&nbsp; 🟠 High<br>
        🔴 Very High &nbsp;&nbsp; 🟣 Extreme
        </div>""", unsafe_allow_html=True)

        st.markdown("**Legend — Flood**")
        st.markdown("""
        <div style='font-size:0.78rem; line-height:2'>
        🟢 &lt;0.5m &nbsp; 🟡 0.5–2m<br>
        🟠 2–4m &nbsp;&nbsp; 🔴 &gt;4m
        </div>""", unsafe_allow_html=True)

        st.markdown("**Legend — DEM**")
        st.markdown("""
        <div style='font-size:0.78rem; line-height:2'>
        🔴 &lt;5m &nbsp; 🟠 5–20m &nbsp; 🟡 20–50m<br>
        🟢 50–200m &nbsp; 💚 &gt;200m
        </div>""", unsafe_allow_html=True)

    with col_map:
        m = base_map(cfg["lat"], cfg["lon"], zoom)

        if show_cyc:
            try:
                cls_cyc, _ = build_cyclone_risk_image()
                add_ee_layer(m, cls_cyc,
                             {"min": 1, "max": 5,
                              "palette": ["#2ecc71","#f1c40f","#e67e22","#e74c3c","#6c3483"]},
                             "Cyclone Risk", opacity)
            except Exception as e:
                st.warning(f"Cyclone layer: {e}")

        if show_flood:
            try:
                cls_fl, _ = build_flood_risk_image(cfg["flood_band"])
                add_ee_layer(m, cls_fl,
                             {"min": 2, "max": 8,
                              "palette": ["#2ECC71","#F1C40F","#E67E22","#E74C3C"]},
                             f"Flood ({cfg['flood_rp_label']})", opacity)
            except Exception as e:
                st.warning(f"Flood layer: {e}")

        if show_dem:
            try:
                cls_dem, _ = build_dem_image()
                add_ee_layer(m, cls_dem,
                             {"min": 1, "max": 8,
                              "palette": ["#7f0000","#b30000","#d7301f","#ef6548",
                                          "#fc8d59","#fdbb84","#c7e9b4","#41ab5d"]},
                             "DEM (Elevation)", opacity)
            except Exception as e:
                st.warning(f"DEM layer: {e}")

        add_point(m, cfg["lat"], cfg["lon"], cfg["loc_name"])
        add_buffer(m, cfg["lat"], cfg["lon"], cfg["buffer_m"])
        folium.LayerControl(collapsed=False).add_to(m)
        st_folium(m, width=None, height=620, returned_objects=[])


# ══════════════════════════════════════════════════════════════════
# PAGE: CYCLONE ANALYSIS
# ══════════════════════════════════════════════════════════════════

def page_cyclone(cfg, ee_ok):
    st.markdown("# 🌀 Cyclone Risk Analysis")
    st.caption("NOAA IBTrACS v4 — North Indian Basin (Arabian Sea + Bay of Bengal)")

    if not ee_ok:
        st.error("Earth Engine not authenticated.")
        return

    col_map, col_right = st.columns([3, 2])

    with col_map:
        m = base_map(cfg["lat"], cfg["lon"], 5)
        try:
            cls, _ = build_cyclone_risk_image()
            add_ee_layer(m, cls, {"min":1,"max":5,
                "palette":["#2ecc71","#f1c40f","#e67e22","#e74c3c","#6c3483"]},
                "Cyclone Risk")
        except Exception as e:
            st.warning(str(e))
        add_point(m, cfg["lat"], cfg["lon"], cfg["loc_name"])
        add_buffer(m, cfg["lat"], cfg["lon"], cfg["buffer_m"])
        folium.LayerControl().add_to(m)
        st_folium(m, width=None, height=500, returned_objects=[])

    with col_right:
        if cfg["run"] or "risk_result" in st.session_state:
            if cfg["run"]:
                with st.spinner("Querying IBTrACS..."):
                    cyc = get_cyclone_risk(cfg["lat"], cfg["lon"], cfg["buffer_m"])
                st.session_state["cyc_result"] = cyc
            else:
                cyc = st.session_state.get("cyc_result",
                      st.session_state.get("risk_result", {}).get("cyclone", {}))

            if cyc:
                st.markdown(f"**Risk Level:** {level_pill(cyc['level'])}", unsafe_allow_html=True)
                st.markdown(f"**Score:** `{cyc['score']:.1f}` / 100")

                st.plotly_chart(gauge_chart(cyc["score"], "Cyclone Risk Score"),
                                use_container_width=True)

                st.markdown("---")
                st.markdown("**Saffir-Simpson Reference**")
                ss_df = pd.DataFrame([
                    ("Tropical Depression", "< 34 kt",  "Minimal"),
                    ("Tropical Storm",      "34–63 kt", "Moderate"),
                    ("Cat 1",               "64–82 kt", "Some structural"),
                    ("Cat 2",               "83–95 kt", "Extensive"),
                    ("Cat 3 (Major)",       "96–112 kt","Devastating"),
                    ("Cat 4",               "113–136 kt","Catastrophic"),
                    ("Cat 5",               "> 137 kt", "Total destruction"),
                ], columns=["Category", "Wind Speed", "Damage"])
                st.dataframe(ss_df, hide_index=True, use_container_width=True)
        else:
            st.info("Click **Run Risk Analysis** in the sidebar to query this location.")


# ══════════════════════════════════════════════════════════════════
# PAGE: FLOOD ANALYSIS
# ══════════════════════════════════════════════════════════════════

def page_flood(cfg, ee_ok):
    st.markdown("# 🌊 Flood Risk Analysis")
    st.caption("JRC/Copernicus GloFAS Flood Hazard Maps v2.1 — modeled inundation depth")

    if not ee_ok:
        st.error("Earth Engine not authenticated.")
        return

    col_map, col_right = st.columns([3, 2])

    with col_map:
        m = base_map(cfg["lat"], cfg["lon"], 7)
        try:
            cls, _ = build_flood_risk_image(cfg["flood_band"])
            add_ee_layer(m, cls, {"min":2,"max":8,
                "palette":["#2ECC71","#F1C40F","#E67E22","#E74C3C"]},
                f"Flood ({cfg['flood_rp_label']})")
        except Exception as e:
            st.warning(str(e))
        add_point(m, cfg["lat"], cfg["lon"], cfg["loc_name"])
        add_buffer(m, cfg["lat"], cfg["lon"], cfg["buffer_m"])
        folium.LayerControl().add_to(m)
        st_folium(m, width=None, height=500, returned_objects=[])

    with col_right:
        if cfg["run"] or "fld_result" in st.session_state:
            if cfg["run"]:
                with st.spinner("Querying GloFAS..."):
                    fld = get_flood_risk(cfg["lat"], cfg["lon"],
                                        cfg["flood_band"], cfg["buffer_m"])
                st.session_state["fld_result"] = fld
            else:
                fld = st.session_state.get("fld_result",
                      st.session_state.get("risk_result", {}).get("flood", {}))

            if fld:
                st.markdown(f"**Risk Level:** {level_pill(fld['level'])}", unsafe_allow_html=True)
                st.markdown(f"**Inundation Depth:** `{fld['depth_m']:.3f} m`")

                depth_gauge = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=fld["depth_m"],
                    number={"suffix": " m", "font": {"size": 28, "color": "#cdd6f4"}},
                    title={"text": f"Flood Depth ({cfg['flood_rp_label']})", "font": {"size": 12, "color": "#a6adc8"}},
                    gauge={
                        "axis": {"range": [0, 6], "tickcolor": "#585b70"},
                        "bar":  {"color": "#89dceb", "thickness": 0.25},
                        "bgcolor": "#1e1e2e", "borderwidth": 0,
                        "steps": [
                            {"range": [0, 0.5], "color": "#1e3a2f"},
                            {"range": [0.5, 2],  "color": "#3d3515"},
                            {"range": [2,   4],  "color": "#3d2510"},
                            {"range": [4,   6],  "color": "#3d1015"},
                        ],
                    },
                ))
                depth_gauge.update_layout(
                    height=240, paper_bgcolor="#1e1e2e",
                    font={"color": "#cdd6f4"},
                    margin=dict(t=55, b=10, l=20, r=20),
                )
                st.plotly_chart(depth_gauge, use_container_width=True)
        else:
            st.info("Click **Run Risk Analysis** in the sidebar.")

    # ── Multi-return period panel ──
    st.markdown("---")
    st.markdown('<div class="sec-head"><h3>Multi Return-Period Curve</h3></div>', unsafe_allow_html=True)
    if st.button("📈 Run All 7 Return Periods", use_container_width=False):
        with st.spinner("Querying all return periods..."):
            rp_df = get_flood_all_rp(cfg["lat"], cfg["lon"], cfg["buffer_m"])
        st.session_state["rp_df"] = rp_df

    if "rp_df" in st.session_state:
        df = st.session_state["rp_df"]
        c1, c2 = st.columns([3, 2])
        with c1:
            st.plotly_chart(flood_rp_chart(df), use_container_width=True)
        with c2:
            st.dataframe(df.style.format({"Depth (m)": "{:.3f}", "Score": "{:.0f}"}),
                         hide_index=True, use_container_width=True)

            # Exceedance probability note
            st.markdown("""
            **Exceedance Probabilities**
            | Return Period | Annual Probability |
            |---|---|
            | 10-Year  | 10.0% |
            | 20-Year  | 5.0%  |
            | 50-Year  | 2.0%  |
            | 100-Year | 1.0%  |
            | 200-Year | 0.5%  |
            | 500-Year | 0.2%  |
            """)


# ══════════════════════════════════════════════════════════════════
# PAGE: ELEVATION RISK
# ══════════════════════════════════════════════════════════════════

def page_elevation(cfg, ee_ok):
    st.markdown("# ⛰️ Elevation & Terrain Risk")
    st.caption("USGS SRTMGL1_003 DEM — 30m resolution · 8-class topographic vulnerability")

    if not ee_ok:
        st.error("Earth Engine not authenticated.")
        return

    col_map, col_right = st.columns([3, 2])

    with col_map:
        m = base_map(cfg["lat"], cfg["lon"], 8)
        try:
            cls, _ = build_dem_image()
            add_ee_layer(m, cls,
                         {"min":1,"max":8,
                          "palette":["#7f0000","#b30000","#d7301f","#ef6548",
                                     "#fc8d59","#fdbb84","#c7e9b4","#41ab5d"]},
                         "DEM (8 Classes)")
        except Exception as e:
            st.warning(str(e))
        add_point(m, cfg["lat"], cfg["lon"], cfg["loc_name"])
        add_buffer(m, cfg["lat"], cfg["lon"], cfg["buffer_m"])
        folium.LayerControl().add_to(m)
        st_folium(m, width=None, height=500, returned_objects=[])

        # Color band legend
        classes = ["<5m","5–10m","10–20m","20–35m","35–50m","50–100m","100–200m",">200m"]
        colors  = ["#7f0000","#b30000","#d7301f","#ef6548","#fc8d59","#fdbb84","#c7e9b4","#41ab5d"]
        leg = " ".join(
            f'<span style="background:{c};color:#1e1e2e;padding:2px 10px;'
            f'border-radius:12px;font-size:0.72rem;font-weight:700">{lbl}</span>'
            for c, lbl in zip(colors, classes)
        )
        st.markdown(leg, unsafe_allow_html=True)

    with col_right:
        if cfg["run"] or "dem_result" in st.session_state:
            if cfg["run"]:
                with st.spinner("Querying SRTM DEM..."):
                    dem = get_dem_risk(cfg["lat"], cfg["lon"], cfg["buffer_m"])
                st.session_state["dem_result"] = dem
            else:
                dem = st.session_state.get("dem_result",
                      st.session_state.get("risk_result", {}).get("dem", {}))

            if dem:
                st.markdown(f"**Elevation:** `{dem['elevation_m']:.1f} m` above MSL")
                st.markdown(f"**Terrain Class:** `{dem['class_label']}`")
                st.markdown(f"**Vulnerability:** {level_pill(dem['level'])}", unsafe_allow_html=True)
                st.markdown(f"**Risk Score:** `{dem['score']}` / 100")

                st.plotly_chart(gauge_chart(dem["score"], "Elevation Risk Score"),
                                use_container_width=True)

                st.markdown("---")
                st.markdown("**Class Vulnerability Guide**")
                guide_df = pd.DataFrame([
                    ("<5 m",      "Class 1", "🔴 Extreme", "Storm surge, tidal flooding"),
                    ("5–10 m",    "Class 2", "🔴 Very High","Cyclone inundation"),
                    ("10–20 m",   "Class 3", "🟠 High",    "Riverine flood risk"),
                    ("20–35 m",   "Class 4", "🟠 Moderate","Flash flood susceptible"),
                    ("35–50 m",   "Class 5", "🟡 Moderate","Low pluvial risk"),
                    ("50–100 m",  "Class 6", "🟢 Low",     "Elevated, low exposure"),
                    ("100–200 m", "Class 7", "🟢 Very Low","Negligible flood risk"),
                    (">200 m",    "Class 8", "🟢 Minimal", "Near-zero inundation"),
                ], columns=["Elevation", "Class", "Risk", "Exposure Type"])
                st.dataframe(guide_df, hide_index=True, use_container_width=True)
        else:
            st.info("Click **Run Risk Analysis** to query this location.")


# ══════════════════════════════════════════════════════════════════
# PAGE: COMPOSITE SCORE
# ══════════════════════════════════════════════════════════════════

def page_composite(cfg, ee_ok):
    st.markdown("# 📊 Composite Risk Score")
    st.caption(f"Weighted multi-hazard index — Cyclone {cfg['w_c']*100:.0f}% · Flood {cfg['w_f']*100:.0f}% · Elevation {cfg['w_d']*100:.0f}%")

    if not ee_ok:
        st.error("Earth Engine not authenticated.")
        return

    need_run = cfg["run"] or "risk_result" not in st.session_state

    if need_run and not cfg["run"]:
        st.info("Click **Run Risk Analysis** to compute the composite hazard score.")
        # Still show matrix
        st.markdown("---")
        st.markdown('<div class="sec-head"><h3>Risk Scoring Matrix</h3></div>', unsafe_allow_html=True)
        st.caption("Composite scores for all cyclone × flood combinations (elevation fixed at 20/100).")
        st.plotly_chart(risk_matrix_heatmap(cfg["w_c"], cfg["w_f"], cfg["w_d"]), use_container_width=True)
        return

    if cfg["run"]:
        with st.spinner("🌀 Cyclone..."):
            cyc = get_cyclone_risk(cfg["lat"], cfg["lon"], cfg["buffer_m"])
        with st.spinner("🌊 Flood..."):
            fld = get_flood_risk(cfg["lat"], cfg["lon"], cfg["flood_band"], cfg["buffer_m"])
        with st.spinner("⛰️ DEM..."):
            dem = get_dem_risk(cfg["lat"], cfg["lon"], cfg["buffer_m"])

        comp = composite_risk(cyc["score"], fld["level"], dem["score"],
                              cfg["w_c"], cfg["w_f"], cfg["w_d"])
        result = {
            "cyclone": cyc, "flood": fld, "dem": dem,
            "composite": comp, "level": composite_level(comp),
            "timestamp": datetime.now().isoformat(),
            "cfg": cfg,
        }
        st.session_state["risk_result"] = result

        # Push individual caches too
        st.session_state["cyc_result"] = cyc
        st.session_state["fld_result"] = fld
        st.session_state["dem_result"] = dem

    data = st.session_state["risk_result"]
    cyc  = data["cyclone"]
    fld  = data["flood"]
    dem  = data["dem"]
    comp = data["composite"]
    clvl = data["level"]
    ts   = data["timestamp"]

    # ── Score cards ──
    c1, c2, c3, c4, c5 = st.columns(5)
    cards = [
        (c1, "card-cyclone",  "🌀 Cyclone Score",  f"{cyc['score']:.1f}",  cyc["level"]),
        (c2, "card-flood",    "🌊 Flood Depth",     f"{fld['depth_m']:.2f}m", fld["level"]),
        (c3, "card-dem",      "⛰️ Elevation",       f"{dem['elevation_m']:.0f}m", dem["level"]),
        (c4, "card-combined", "📊 Composite Index", f"{comp:.1f}",          clvl),
        (c5, "card-rank",     "🏷️ Hazard Tier",    clvl,                   f"Score {comp:.0f}/100"),
    ]
    for col, cls, label, val, sub in cards:
        with col:
            st.markdown(
                f'<div class="score-card {cls}">'
                f'<div class="label">{label}</div>'
                f'<div class="value" style="color:{score_color(comp)}">{val}</div>'
                f'<div class="sub">{sub}</div>'
                f'</div>', unsafe_allow_html=True,
            )

    st.markdown("---")
    col_gauge, col_radar, col_decomp = st.columns([2, 2, 2])

    with col_gauge:
        st.markdown('<div class="sec-head"><h3>Composite Gauge</h3></div>', unsafe_allow_html=True)
        st.plotly_chart(gauge_chart(comp, "Multi-Hazard Index"), use_container_width=True)
        st.markdown(f"""
        <div style='font-size:0.82rem;color:#a6adc8;line-height:1.8'>
        <b>Location:</b> {cfg['loc_name']}<br>
        <b>Coords:</b> {cfg['lat']:.5f}°N, {cfg['lon']:.5f}°E<br>
        <b>Buffer:</b> {cfg['buffer_m']} m<br>
        <b>Assessed:</b> {ts[:16].replace('T',' ')}<br>
        <b>Weights:</b> C:{cfg['w_c']*100:.0f}% · F:{cfg['w_f']*100:.0f}% · D:{cfg['w_d']*100:.0f}%
        </div>
        """, unsafe_allow_html=True)

    with col_radar:
        st.markdown('<div class="sec-head"><h3>Hazard Radar</h3></div>', unsafe_allow_html=True)
        st.plotly_chart(
            radar_chart(cyc["score"], fld["score"], dem["score"], cfg["loc_name"]),
            use_container_width=True,
        )

    with col_decomp:
        st.markdown('<div class="sec-head"><h3>Score Decomposition</h3></div>', unsafe_allow_html=True)
        st.plotly_chart(
            score_decomposition_chart(cyc["score"], fld["score"], dem["score"],
                                      cfg["w_c"], cfg["w_f"], cfg["w_d"]),
            use_container_width=True,
        )
        # Contribution table
        total = cfg["w_c"]*cyc["score"] + cfg["w_f"]*fld["score"] + cfg["w_d"]*dem["score"]
        decomp_df = pd.DataFrame([
            {"Hazard": "🌀 Cyclone",   "Raw Score": f"{cyc['score']:.1f}",
             "Weight": f"{cfg['w_c']*100:.0f}%",
             "Contribution": f"{cfg['w_c']*cyc['score']:.1f}",
             "Share %": f"{cfg['w_c']*cyc['score']/max(total,0.01)*100:.1f}%"},
            {"Hazard": "🌊 Flood",     "Raw Score": f"{fld['score']:.0f}",
             "Weight": f"{cfg['w_f']*100:.0f}%",
             "Contribution": f"{cfg['w_f']*fld['score']:.1f}",
             "Share %": f"{cfg['w_f']*fld['score']/max(total,0.01)*100:.1f}%"},
            {"Hazard": "⛰️ Elevation","Raw Score": f"{dem['score']:.0f}",
             "Weight": f"{cfg['w_d']*100:.0f}%",
             "Contribution": f"{cfg['w_d']*dem['score']:.1f}",
             "Share %": f"{cfg['w_d']*dem['score']/max(total,0.01)*100:.1f}%"},
            {"Hazard": "📊 Composite","Raw Score": "—",
             "Weight": "100%",
             "Contribution": f"{comp:.1f}",
             "Share %": "100%"},
        ])
        st.dataframe(decomp_df, hide_index=True, use_container_width=True)

    # ── Risk matrix ──
    st.markdown("---")
    st.markdown('<div class="sec-head"><h3>Full Risk Scoring Matrix</h3></div>', unsafe_allow_html=True)
    st.caption("Every cyclone × flood combination at current weights. Your location's composite plotted on gauges above.")
    st.plotly_chart(risk_matrix_heatmap(cfg["w_c"], cfg["w_f"], cfg["w_d"], dem["score"]),
                    use_container_width=True)

    # ── Hazard detail table ──
    st.markdown("---")
    st.markdown('<div class="sec-head"><h3>Hazard Detail</h3></div>', unsafe_allow_html=True)
    detail_df = pd.DataFrame([
        {"Hazard": "🌀 Cyclone",    "Data Source": "NOAA IBTrACS v4 (NI Basin)",
         "Raw Score": f"{cyc['score']:.2f}/100", "Level": cyc["level"],
         "Method": "Frequency × Intensity, P10–P90 norm."},
        {"Hazard": "🌊 Flood",      "Data Source": "JRC GloFAS FHM v2.1",
         "Raw Score": f"{fld['depth_m']:.3f} m", "Level": fld["level"],
         "Method": f"Inundation depth at {cfg['flood_rp_label']}"},
        {"Hazard": "⛰️ Elevation",  "Data Source": "USGS SRTMGL1_003 (30m)",
         "Raw Score": f"{dem['elevation_m']:.1f} m", "Level": dem["level"],
         "Method": "Mean elevation in buffer, 8-class DEM"},
        {"Hazard": "📊 Composite",  "Data Source": "Multi-hazard weighted index",
         "Raw Score": f"{comp:.2f}/100", "Level": clvl,
         "Method": f"C×{cfg['w_c']:.2f} + F×{cfg['w_f']:.2f} + D×{cfg['w_d']:.2f}"},
    ])
    st.dataframe(detail_df, hide_index=True, use_container_width=True)

    # ── Export ──
    st.markdown("---")
    st.markdown('<div class="sec-head"><h3>Export</h3></div>', unsafe_allow_html=True)
    export_dict = {
        "location": cfg["loc_name"],
        "latitude": cfg["lat"], "longitude": cfg["lon"],
        "buffer_m": cfg["buffer_m"],
        "timestamp": ts,
        "cyclone": {"score": cyc["score"], "level": cyc["level"]},
        "flood":   {"depth_m": fld["depth_m"], "level": fld["level"],
                    "return_period": cfg["flood_rp_label"]},
        "dem":     {"elevation_m": dem["elevation_m"], "level": dem["level"],
                    "class": dem["class_label"]},
        "composite": {"score": comp, "level": clvl},
        "weights": {"cyclone": cfg["w_c"], "flood": cfg["w_f"], "dem": cfg["w_d"]},
    }
    import json
    col_j, col_c = st.columns(2)
    with col_j:
        st.download_button(
            "⬇️ Download JSON",
            data=json.dumps(export_dict, indent=2),
            file_name=f"risk_{cfg['loc_name'].replace(' ','_')}_{ts[:10]}.json",
            mime="application/json",
            use_container_width=True,
        )
    with col_c:
        csv_rows = [
            f"Location,{cfg['loc_name']}",
            f"Latitude,{cfg['lat']}",
            f"Longitude,{cfg['lon']}",
            f"Buffer_m,{cfg['buffer_m']}",
            f"Timestamp,{ts}",
            f"Cyclone_Score,{cyc['score']}",
            f"Cyclone_Level,{cyc['level']}",
            f"Flood_Depth_m,{fld['depth_m']}",
            f"Flood_Level,{fld['level']}",
            f"Flood_ReturnPeriod,{cfg['flood_rp_label']}",
            f"DEM_Elevation_m,{dem['elevation_m']}",
            f"DEM_Level,{dem['level']}",
            f"DEM_Class,{dem['class_label']}",
            f"Composite_Score,{comp}",
            f"Composite_Level,{clvl}",
            f"Weight_Cyclone,{cfg['w_c']}",
            f"Weight_Flood,{cfg['w_f']}",
            f"Weight_DEM,{cfg['w_d']}",
        ]
        st.download_button(
            "⬇️ Download CSV",
            data="\n".join(csv_rows),
            file_name=f"risk_{cfg['loc_name'].replace(' ','_')}_{ts[:10]}.csv",
            mime="text/csv",
            use_container_width=True,
        )


# ══════════════════════════════════════════════════════════════════
# PAGE: MULTI-LOCATION COMPARISON
# ══════════════════════════════════════════════════════════════════

def _analyse_location(name, lat, lon, cfg):
    """Run all three hazard queries and return a result dict."""
    cyc  = get_cyclone_risk(lat, lon, cfg["buffer_m"])
    fld  = get_flood_risk(lat, lon, cfg["flood_band"], cfg["buffer_m"])
    dem  = get_dem_risk(lat, lon, cfg["buffer_m"])
    comp = composite_risk(cyc["score"], fld["level"], dem["score"],
                          cfg["w_c"], cfg["w_f"], cfg["w_d"])
    return {
        "name": name, "lat": lat, "lon": lon,
        "cyclone_score": cyc["score"], "cyclone_level": cyc["level"],
        "flood_score": fld["score"], "flood_depth_m": fld["depth_m"], "flood_level": fld["level"],
        "dem_score": dem["score"], "elevation_m": dem["elevation_m"], "dem_level": dem["level"],
        "composite": comp, "composite_level": composite_level(comp),
        "flood_return_period": cfg["flood_rp_label"],
    }


def _render_results_section(cfg):
    """Shared charts + map + downloads for saved_locations."""
    locs = st.session_state["saved_locations"]
    if not locs:
        return

    # ── Summary table ──
    tbl = pd.DataFrame([{
        "Site": d["name"],
        "Lat": f"{d['lat']:.4f}",
        "Lon": f"{d['lon']:.4f}",
        "🌀 Cyclone": f"{d['cyclone_score']:.1f}",
        "Cyc Level": d["cyclone_level"],
        "🌊 Depth (m)": f"{d['flood_depth_m']:.3f}",
        "Flood Level": d["flood_level"],
        "⛰️ Elev (m)": f"{d['elevation_m']:.0f}",
        "Elev Risk": d["dem_level"],
        "📊 Composite": d["composite"],
        "Hazard Tier": d["composite_level"],
    } for d in locs])

    st.markdown("---")
    # KPI strip
    k1, k2, k3, k4 = st.columns(4)
    avg = sum(d["composite"] for d in locs) / len(locs)
    highest = max(locs, key=lambda x: x["composite"])
    lowest  = min(locs, key=lambda x: x["composite"])
    with k1:
        st.metric("Sites Analysed", len(locs))
    with k2:
        st.metric("Avg Composite Score", f"{avg:.1f}")
    with k3:
        st.metric("Highest Risk", f"{highest['name']} ({highest['composite']:.0f})")
    with k4:
        st.metric("Lowest Risk",  f"{lowest['name']} ({lowest['composite']:.0f})")

    st.markdown("---")
    st.markdown("### 📋 Results Table")
    st.dataframe(tbl, hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("### 📊 Comparison Charts")
    fig_comp = multi_location_comparison(locs)
    if fig_comp:
        st.plotly_chart(fig_comp, use_container_width=True)

    # ── Site map ──
    st.markdown("### 🗺️ Site Map")
    all_lats   = [d["lat"] for d in locs]
    all_lons   = [d["lon"] for d in locs]
    center_lat = sum(all_lats) / len(all_lats)
    center_lon = sum(all_lons) / len(all_lons)
    m = base_map(center_lat, center_lon, 5)
    color_map_comp = {"Low": "green", "Moderate": "blue", "High": "orange",
                      "Very High": "red", "Extreme": "purple"}
    for d in locs:
        c = color_map_comp.get(d["composite_level"], "gray")
        folium.Marker(
            [d["lat"], d["lon"]],
            tooltip=f"<b>{d['name']}</b><br>Composite: {d['composite']:.1f} ({d['composite_level']})",
            popup=folium.Popup(
                f"<b>{d['name']}</b><br>"
                f"Cyclone: {d['cyclone_score']:.1f} ({d['cyclone_level']})<br>"
                f"Flood: {d['flood_depth_m']:.3f} m ({d['flood_level']})<br>"
                f"Elevation: {d['elevation_m']:.0f} m ({d['dem_level']})<br>"
                f"<b>Composite: {d['composite']:.1f} — {d['composite_level']}</b>",
                max_width=240,
            ),
            icon=folium.Icon(color=c, icon="map-marker", prefix="fa"),
        ).add_to(m)
    folium.LayerControl().add_to(m)
    st_folium(m, width=None, height=480, returned_objects=[])

    # ── Downloads ──
    st.markdown("---")
    st.markdown("### ⬇️ Download Results")
    from io import BytesIO
    dl1, dl2 = st.columns(2)
    with dl1:
        csv_data = pd.DataFrame(locs).to_csv(index=False)
        st.download_button("📄 Download CSV", csv_data,
                           file_name="multi_location_risk.csv",
                           mime="text/csv", use_container_width=True)
    with dl2:
        xls_buf = BytesIO()
        with pd.ExcelWriter(xls_buf, engine="openpyxl") as writer:
            pd.DataFrame(locs).to_excel(writer, index=False, sheet_name="Risk_Results")
        xls_buf.seek(0)
        st.download_button("📊 Download Excel", xls_buf.read(),
                           file_name="multi_location_risk.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)


def page_multi_location(cfg, ee_ok):
    st.markdown("# 📍 Multi-Location Risk Comparison")
    st.caption("Add sites manually one-by-one, or upload a CSV/Excel file with many lat/lon rows at once.")

    if not ee_ok:
        st.error("Earth Engine not authenticated.")
        return

    if "saved_locations" not in st.session_state:
        st.session_state["saved_locations"] = []

    tab_manual, tab_upload = st.tabs(["➕ Manual Add", "📂 Bulk Upload (CSV / Excel)"])

    # ──────────────────────────────────────────────────────────────
    # TAB 1 — MANUAL ADD
    # ──────────────────────────────────────────────────────────────
    with tab_manual:
        col_add, col_list = st.columns([2, 3])

        with col_add:
            st.markdown("#### Add a Single Location")
            new_name = st.text_input("Site Name", value=cfg["loc_name"], key="ml_name")
            new_lat  = st.number_input("Latitude",  value=cfg["lat"],  format="%.5f", key="ml_lat")
            new_lon  = st.number_input("Longitude", value=cfg["lon"],  format="%.5f", key="ml_lon")

            if st.button("➕ Add & Analyse", use_container_width=True, key="ml_add_btn"):
                existing = [d["name"] for d in st.session_state["saved_locations"]]
                lbl = new_name if new_name not in existing else f"{new_name} ({new_lat:.2f})"
                with st.spinner(f"Analysing {lbl}..."):
                    result = _analyse_location(lbl, new_lat, new_lon, cfg)
                st.session_state["saved_locations"].append(result)
                st.success(f"✅ {lbl} added — Composite: **{result['composite']:.1f}** ({result['composite_level']})")

            if st.button("🗑️ Clear All Sites", use_container_width=True, key="ml_clear_btn"):
                st.session_state["saved_locations"] = []
                st.rerun()

        with col_list:
            locs = st.session_state["saved_locations"]
            if not locs:
                st.info("Add at least one location to begin comparison.")
            else:
                tbl = pd.DataFrame([{
                    "Site": d["name"],
                    "🌀 Cyc": f"{d['cyclone_score']:.1f}",
                    "🌊 Flood (m)": f"{d['flood_depth_m']:.3f}",
                    "⛰️ Elev (m)": f"{d['elevation_m']:.0f}",
                    "📊 Composite": d["composite"],
                    "Tier": d["composite_level"],
                } for d in locs])
                st.dataframe(tbl, hide_index=True, use_container_width=True)

    # ──────────────────────────────────────────────────────────────
    # TAB 2 — BULK UPLOAD
    # ──────────────────────────────────────────────────────────────
    with tab_upload:
        st.markdown("#### Upload CSV or Excel with Lat/Long Columns")

        # Template download
        sample_csv = (
            "location,latitude,longitude\n"
            "Mumbai,19.076,72.878\n"
            "Chennai,13.083,80.271\n"
            "Kolkata,22.573,88.364\n"
            "Visakhapatnam,17.687,83.219\n"
            "Bhubaneswar,20.296,85.825\n"
        )
        st.download_button(
            "⬇️ Download Sample Template",
            data=sample_csv,
            file_name="batch_template.csv",
            mime="text/csv",
        )

        st.markdown("""
        **Accepted column names:**
        - Latitude: `latitude` or `lat`
        - Longitude: `longitude` or `lon` or `lng`
        - Location name *(optional)*: `location`, `name`, `site`, or `city`

        Any extra columns in your file are preserved in the output.
        """)

        uploaded = st.file_uploader(
            "Upload CSV or Excel",
            type=["csv", "xlsx", "xls"],
            key="bulk_uploader",
        )

        if uploaded is not None:
            # ── Parse file ──
            try:
                fname = uploaded.name.lower()
                if fname.endswith(".csv"):
                    raw_df = pd.read_csv(uploaded)
                else:
                    book = pd.ExcelFile(uploaded)
                    sheet = (
                        st.selectbox("Select Sheet", book.sheet_names, key="bulk_sheet")
                        if len(book.sheet_names) > 1
                        else book.sheet_names[0]
                    )
                    raw_df = pd.read_excel(book, sheet_name=sheet)
            except Exception as e:
                st.error(f"Could not read file: {e}")
                return

            if raw_df.empty:
                st.error("Uploaded file has no rows.")
                return

            # ── Detect columns ──
            norm = {str(c).strip().lower(): c for c in raw_df.columns}
            lat_col  = next((norm[k] for k in ["latitude",  "lat"]           if k in norm), None)
            lon_col  = next((norm[k] for k in ["longitude", "lon", "lng"]    if k in norm), None)
            name_col = next((norm[k] for k in ["location",  "name", "site", "city", "location_name"] if k in norm), None)

            if lat_col is None or lon_col is None:
                st.error("Could not find latitude/longitude columns. Use headers: `latitude`/`lat` and `longitude`/`lon`.")
                st.dataframe(raw_df.head(3), use_container_width=True)
                return

            # ── Validate rows ──
            work = raw_df.copy()
            work["_lat"] = pd.to_numeric(work[lat_col], errors="coerce")
            work["_lon"] = pd.to_numeric(work[lon_col], errors="coerce")
            bad = work["_lat"].isna() | work["_lon"].isna() | \
                  (work["_lat"] < -90) | (work["_lat"] > 90) | \
                  (work["_lon"] < -180) | (work["_lon"] > 180)
            valid_df   = work.loc[~bad].copy().reset_index(drop=True)
            invalid_ct = int(bad.sum())

            col_v, col_i = st.columns(2)
            col_v.metric("✅ Valid Rows",   len(valid_df))
            col_i.metric("⚠️ Skipped Rows", invalid_ct)

            if invalid_ct > 0:
                with st.expander(f"Show {invalid_ct} invalid row(s)"):
                    st.dataframe(work.loc[bad, [c for c in [name_col, lat_col, lon_col] if c]],
                                 use_container_width=True)

            if valid_df.empty:
                st.error("No valid coordinate rows after validation.")
                return

            if st.button(f"🚀 Run Analysis for {len(valid_df)} Locations", use_container_width=True,
                         key="bulk_run_btn"):

                progress_bar  = st.progress(0, text="Starting…")
                status_text   = st.empty()
                results       = []

                for i, row in valid_df.iterrows():
                    lat_v = float(row["_lat"])
                    lon_v = float(row["_lon"])
                    loc_n = (
                        str(row[name_col]).strip()
                        if name_col and pd.notna(row.get(name_col))
                        else f"Row {i + 1}"
                    )
                    status_text.caption(f"Analysing {i + 1}/{len(valid_df)}: **{loc_n}**")
                    try:
                        res = _analyse_location(loc_n, lat_v, lon_v, cfg)
                        # Carry through any extra columns from the upload
                        for c in raw_df.columns:
                            if c not in (lat_col, lon_col, name_col):
                                res[f"input_{c}"] = row.get(c, "")
                        results.append(res)
                    except Exception as exc:
                        results.append({
                            "name": loc_n, "lat": lat_v, "lon": lon_v,
                            "cyclone_score": None, "cyclone_level": "Error",
                            "flood_score": None, "flood_depth_m": None, "flood_level": "Error",
                            "dem_score": None, "elevation_m": None, "dem_level": "Error",
                            "composite": None, "composite_level": "Error",
                            "error": str(exc),
                        })
                    progress_bar.progress((i + 1) / len(valid_df),
                                          text=f"{i + 1}/{len(valid_df)} locations done")

                status_text.empty()
                progress_bar.empty()

                # Merge batch results into session state (append, don't overwrite manual entries)
                existing_names = {d["name"] for d in st.session_state["saved_locations"]}
                added = 0
                for r in results:
                    if r["name"] not in existing_names:
                        st.session_state["saved_locations"].append(r)
                        added += 1
                st.success(f"✅ Bulk analysis complete — {added} location(s) added to comparison.")

                # Also show a standalone table of this batch
                batch_df = pd.DataFrame(results)
                st.markdown("#### Batch Results Preview")
                display_cols = ["name", "lat", "lon",
                                "cyclone_score", "cyclone_level",
                                "flood_depth_m", "flood_level",
                                "elevation_m", "dem_level",
                                "composite", "composite_level"]
                display_cols = [c for c in display_cols if c in batch_df.columns]
                st.dataframe(batch_df[display_cols], hide_index=True, use_container_width=True)

                # Immediate downloads of this batch
                from io import BytesIO as _BytesIO
                dl1, dl2 = st.columns(2)
                with dl1:
                    st.download_button("📄 Download Batch CSV",
                                       batch_df.to_csv(index=False),
                                       file_name="batch_risk_results.csv",
                                       mime="text/csv",
                                       use_container_width=True)
                with dl2:
                    xbuf = _BytesIO()
                    with pd.ExcelWriter(xbuf, engine="openpyxl") as _w:
                        batch_df.to_excel(_w, index=False, sheet_name="Batch_Risk")
                    xbuf.seek(0)
                    st.download_button("📊 Download Batch Excel",
                                       xbuf.read(),
                                       file_name="batch_risk_results.xlsx",
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                       use_container_width=True)

    # ──────────────────────────────────────────────────────────────
    # COMBINED RESULTS (both tabs feed here)
    # ──────────────────────────────────────────────────────────────
    _render_results_section(cfg)


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def main():
    ee_ok = init_earth_engine()
    cfg   = render_sidebar()

    page = cfg["page"]

    if page == "🗺️  Hazard Map":
        page_hazard_map(cfg, ee_ok)
    elif page == "🌀  Cyclone Analysis":
        page_cyclone(cfg, ee_ok)
    elif page == "🌊  Flood Analysis":
        page_flood(cfg, ee_ok)
    elif page == "⛰️  Elevation Risk":
        page_elevation(cfg, ee_ok)
    elif page == "📊  Composite Score":
        page_composite(cfg, ee_ok)
    elif page == "📍  Multi-Location":
        page_multi_location(cfg, ee_ok)


if __name__ == "__main__" or True:
    main()
