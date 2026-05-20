"""
SQLite-backed persistence for NatCat Underwriting search history.

Each completed risk assessment is saved as a row containing:
- timestamp, location label, lat/lon, buffer
- cyclone / flood / DEM scores & levels
- combined score, decision
- premium summary
- full JSON payload of inputs + results (for reload / PDF)
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import pandas as pd

DB_PATH = os.environ.get(
    "NATCAT_DB_PATH",
    os.path.join(os.path.dirname(__file__), "history.db"),
)


# ──────────────────────────────────────────────────────────────────
# CONNECTION
# ──────────────────────────────────────────────────────────────────
@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    """Create the history table if it does not already exist."""
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS search_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT    NOT NULL,
                location        TEXT,
                latitude        REAL    NOT NULL,
                longitude       REAL    NOT NULL,
                buffer_radius_m INTEGER,
                tsi             REAL,
                construction    TEXT,
                occupancy       TEXT,
                cyclone_score   REAL,
                cyclone_level   TEXT,
                flood_depth_m   REAL,
                flood_level     TEXT,
                flood_rp        TEXT,
                dem_elevation_m REAL,
                dem_level       TEXT,
                dem_score       REAL,
                combined_score  REAL,
                decision        TEXT,
                net_premium     REAL,
                total_premium   REAL,
                payload_json    TEXT
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_search_history_ts "
            "ON search_history(timestamp DESC)"
        )


# ──────────────────────────────────────────────────────────────────
# WRITE
# ──────────────────────────────────────────────────────────────────
def save_assessment(assessment: dict[str, Any]) -> int:
    """Persist one assessment dict (as built in `app.py`). Returns row id."""
    init_db()
    inp = assessment.get("inputs", {}) or {}
    cyc = assessment.get("cyclone", {}) or {}
    fld = assessment.get("flood", {}) or {}
    dem = assessment.get("dem", {}) or {}
    dec = assessment.get("decision", {}) or {}
    prem = assessment.get("premium", {}) or {}

    row = (
        assessment.get("timestamp") or datetime.now().isoformat(),
        inp.get("city") or "Custom",
        float(inp.get("lat", 0.0)),
        float(inp.get("lon", 0.0)),
        int(inp.get("buffer_radius_m", 0) or 0),
        float(inp.get("tsi", 0) or 0),
        inp.get("construction"),
        inp.get("occupancy"),
        float(cyc.get("risk_score", 0) or 0),
        cyc.get("risk_level"),
        float(fld.get("depth_m", 0) or 0),
        fld.get("risk_level"),
        inp.get("flood_rp"),
        float(dem.get("elevation_m", 0) or 0),
        dem.get("risk_level"),
        float(dem.get("risk_score", 0) or 0),
        float(assessment.get("combined_score", 0) or 0),
        dec.get("decision"),
        float(prem.get("net_premium", 0) or 0),
        float(prem.get("total_premium", 0) or 0),
        json.dumps(assessment, default=str),
    )

    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO search_history (
                timestamp, location, latitude, longitude, buffer_radius_m,
                tsi, construction, occupancy,
                cyclone_score, cyclone_level,
                flood_depth_m, flood_level, flood_rp,
                dem_elevation_m, dem_level, dem_score,
                combined_score, decision,
                net_premium, total_premium, payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            row,
        )
        return int(cur.lastrowid)


# ──────────────────────────────────────────────────────────────────
# READ
# ──────────────────────────────────────────────────────────────────
_LIST_COLUMNS = (
    "id, timestamp, location, latitude, longitude, buffer_radius_m, "
    "tsi, construction, occupancy, "
    "cyclone_score, cyclone_level, flood_depth_m, flood_level, flood_rp, "
    "dem_elevation_m, dem_level, dem_score, "
    "combined_score, decision, net_premium, total_premium"
)


def fetch_history(limit: int | None = None) -> pd.DataFrame:
    """Return all search history as a DataFrame, newest first."""
    init_db()
    sql = f"SELECT {_LIST_COLUMNS} FROM search_history ORDER BY id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with _conn() as con:
        return pd.read_sql_query(sql, con)


def fetch_payload(row_id: int) -> dict | None:
    """Return the full assessment payload for a given history row id."""
    init_db()
    with _conn() as con:
        cur = con.execute(
            "SELECT payload_json FROM search_history WHERE id = ?",
            (int(row_id),),
        )
        r = cur.fetchone()
    if not r:
        return None
    try:
        return json.loads(r["payload_json"])
    except (TypeError, json.JSONDecodeError):
        return None


# ──────────────────────────────────────────────────────────────────
# DELETE
# ──────────────────────────────────────────────────────────────────
def delete_row(row_id: int) -> None:
    init_db()
    with _conn() as con:
        con.execute("DELETE FROM search_history WHERE id = ?", (int(row_id),))


def clear_all() -> None:
    init_db()
    with _conn() as con:
        con.execute("DELETE FROM search_history")


def count_rows() -> int:
    init_db()
    with _conn() as con:
        cur = con.execute("SELECT COUNT(*) AS n FROM search_history")
        return int(cur.fetchone()["n"])
