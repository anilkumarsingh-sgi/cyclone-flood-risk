# NatCat Insurance Underwriting Decision Engine

Multi-peril Natural Catastrophe risk assessment platform for insurance underwriting, combining **Cyclone** and **Flood** hazard analysis powered by Google Earth Engine.

## Features

- **Cyclone Risk Assessment** — IBTrACS v4 North Indian Basin frequency × intensity model
- **Flood Risk Assessment** — JRC GloFAS v2.1 multi-return-period depth analysis
- **Combined Risk Scoring** — Weighted composite (55% cyclone, 45% flood)
- **Automated Underwriting Decision** — Accept / Refer / Decline with authority levels
- **Premium Calculation** — Full factor breakdown (peril, construction, occupancy, age, coast, deductible)
- **Interactive Maps** — EE tile layers on folium with layer control
- **Batch Processing** — CSV upload for multi-location assessment
- **Report Generation** — TXT, CSV, JSON export

## Prerequisites

1. **Python 3.9+**
2. **Google Earth Engine account** — [Sign up here](https://earthengine.google.com/)
3. Authenticate Earth Engine:
   ```bash
   earthengine authenticate
   ```

## Setup

```bash
cd underwriting_app
pip install -r requirements.txt
streamlit run app.py
```

## Pages

| Page | Description |
|------|-------------|
| 📊 Dashboard | Overview: metrics, map, risk summary, premium, decision |
| 🌀 Cyclone Risk | Detailed cyclone hazard map + point query + wind context |
| 🌊 Flood Risk | Flood depth map + multi-return-period comparison |
| 📋 Underwriting Decision | Decision matrix, conditions, premium indication |
| 📄 Report | Downloadable report (TXT/CSV/JSON) + batch upload |

## Data Sources

- **Cyclone:** NOAA IBTrACS v4 (`NOAA/IBTrACS/v4`)
- **Flood:** JRC/Copernicus CEMS GloFAS Flood Hazard v2.1 (`JRC/CEMS_GLOFAS/FloodHazard/v2_1`)
