"""
PDF report generator for the NatCat Underwriting Engine.

Produces a multi-page A4 report that mirrors the on-screen text report
but in a properly formatted, branded layout.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any
import requests

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _fmt_inr(amount: float) -> str:
    try:
        amount = float(amount or 0)
    except (TypeError, ValueError):
        return "₹0"
    s = f"{amount:,.0f}"
    return f"Rs. {s}"


def _decision_color(decision: str | None) -> colors.Color:
    d = (decision or "").lower()
    if "accept" in d:
        return colors.HexColor("#11998e")
    if "decline" in d or "reject" in d:
        return colors.HexColor("#C33764")
    return colors.HexColor("#F09819")


def _kv_table(rows: list[tuple[str, Any]], col_widths=(60 * mm, 110 * mm)) -> Table:
    data = [[Paragraph(f"<b>{k}</b>", _LABEL_STYLE), Paragraph(str(v), _VALUE_STYLE)]
            for k, v in rows]
    t = Table(data, colWidths=col_widths)
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F2F4F8")),
                ("ROWBACKGROUNDS", (1, 0), (1, -1),
                 [colors.white, colors.HexColor("#FAFBFD")]),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


_styles = getSampleStyleSheet()
_TITLE_STYLE = ParagraphStyle(
    "Title", parent=_styles["Title"], fontSize=18, leading=22,
    alignment=TA_CENTER, textColor=colors.HexColor("#1D2671"),
    spaceAfter=4,
)
_SUBTITLE_STYLE = ParagraphStyle(
    "Subtitle", parent=_styles["Normal"], fontSize=10, leading=14,
    alignment=TA_CENTER, textColor=colors.HexColor("#475569"),
    spaceAfter=10,
)
_H2_STYLE = ParagraphStyle(
    "H2", parent=_styles["Heading2"], fontSize=12, leading=16,
    textColor=colors.HexColor("#1565C0"), spaceBefore=8, spaceAfter=4,
)
_LABEL_STYLE = ParagraphStyle(
    "Label", parent=_styles["Normal"], fontSize=9, leading=12,
    textColor=colors.HexColor("#1E293B"),
)
_VALUE_STYLE = ParagraphStyle(
    "Value", parent=_styles["Normal"], fontSize=9, leading=12,
    textColor=colors.HexColor("#0F172A"),
)
_BODY_STYLE = ParagraphStyle(
    "Body", parent=_styles["Normal"], fontSize=9, leading=12,
    alignment=TA_LEFT, textColor=colors.HexColor("#0F172A"),
)
_DISCLAIMER_STYLE = ParagraphStyle(
    "Disclaimer", parent=_styles["Normal"], fontSize=7.5, leading=10,
    textColor=colors.HexColor("#64748B"), alignment=TA_LEFT,
)


def build_assessment_pdf(assessment: dict) -> bytes:
    """Build a single-assessment PDF report. Returns raw PDF bytes."""
    inp = assessment.get("inputs", {}) or {}
    loc = assessment.get("report_location", {}) or {}
    combined = assessment.get("combined_score", 0)
    cyc = assessment.get("cyclone", {}) or {}
    fld = assessment.get("flood", {}) or {}
    dem = assessment.get("dem", {}) or {}
    ts = assessment.get("timestamp") or datetime.now().isoformat()

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="NatCat Report",
        author="NatCat Underwriting Engine",
    )

    story: list = []
    story.append(Paragraph("NatCat Report", _TITLE_STYLE))
    story.append(Paragraph(
        f"Cyclone &amp; Flood Multi-Peril Risk Assessment<br/>Generated: {ts}",
        _SUBTITLE_STYLE,
    ))

    risk_level = loc.get("risk_level") or "Unknown"
    perils = loc.get("perils", {}) or {}
    flood_score_map = {"No Risk": 0.0, "Low": 20.0, "Moderate": 50.0, "High": 75.0, "Severe": 95.0}

    cyclone_score = float((perils.get("cyclone") or {}).get("score", cyc.get("risk_score", 0.0)))
    cyclone_cat = (perils.get("cyclone") or {}).get("category", cyc.get("risk_level", "Unknown"))
    flood_score = float((perils.get("flood") or {}).get("score", flood_score_map.get(fld.get("risk_level", "No Risk"), 0.0)))
    flood_cat = (perils.get("flood") or {}).get("category", fld.get("risk_level", "Unknown"))
    dem_score = float((perils.get("dem") or {}).get("score", dem.get("risk_score", 0.0)))
    dem_cat = (perils.get("dem") or {}).get("category", dem.get("risk_level", "Unknown"))

    # 1. Location
    story.append(Paragraph("1. Risk Location", _H2_STYLE))
    story.append(_kv_table([
        ("Location", inp.get("city") or "Custom"),
        ("Coordinates", f"{inp.get('lat', 0):.4f}° N, {inp.get('lon', 0):.4f}° E"),
        ("District", loc.get("district", "Unknown")),
        ("State", loc.get("state", "Unknown")),
        ("Combined Score", f"{combined} / 100"),
    ]))

    # 2. Individual peril scores
    story.append(Spacer(1, 6))
    story.append(Paragraph("2. Individual Peril Risk", _H2_STYLE))
    story.append(_kv_table([
        ("Cyclone", f"Score: {cyclone_score:.1f} / 100 | Category: {cyclone_cat}"),
        ("Flood", f"Score: {flood_score:.1f} / 100 | Category: {flood_cat}"),
        ("DEM", f"Score: {dem_score:.1f} / 100 | Category: {dem_cat}"),
    ]))

    # 3. Water body proximity risk
    story.append(Spacer(1, 6))
    story.append(Paragraph("3. Water Body Proximity Risk", _H2_STYLE))
    water = (loc.get("water_proximity") or {})
    water_dist = water.get("distance_m")
    water_dist_text = f"{float(water_dist):.1f} m" if water_dist is not None else "Unknown"
    water_name = water.get("water_name") or "Nearest mapped water body"
    story.append(_kv_table([
        ("Nearest Water Body", water_name),
        ("Water Class", water.get("water_class", "Unknown")),
        ("Distance", water_dist_text),
        ("Risk Level", water.get("risk_level", "Unknown")),
    ]))

    # 4. Satellite map snapshot with location marker
    story.append(Spacer(1, 6))
    story.append(Paragraph("4. Google Satellite Location Snapshot", _H2_STYLE))
    map_url = loc.get("google_static_map_url", "")
    if map_url:
        try:
            r = requests.get(map_url, timeout=20)
            if r.status_code == 200 and r.content:
                img = Image(BytesIO(r.content), width=170 * mm, height=95 * mm)
                story.append(img)
            else:
                story.append(Paragraph("Map image unavailable.", _BODY_STYLE))
        except Exception:
            story.append(Paragraph("Map image unavailable.", _BODY_STYLE))
    else:
        story.append(Paragraph("Map image unavailable (missing API key).", _BODY_STYLE))

    # Disclaimer
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<b>Disclaimer:</b> This is a system-generated indicative location risk summary.",
        _DISCLAIMER_STYLE,
    ))

    doc.build(story)
    return buf.getvalue()


def build_history_pdf(history_df, payloads: list[dict] | None = None) -> bytes:
    """Build a PDF summary of search history (table of all rows).

    `history_df` is the DataFrame returned by `history_db.fetch_history()`.
    `payloads` is optional and currently unused (kept for future per-row detail).
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title="NatCat Underwriting — Search History",
    )
    story: list = []
    story.append(Paragraph("NatCat Underwriting — Search History", _TITLE_STYLE))
    story.append(Paragraph(
        f"Generated: {datetime.now().isoformat(timespec='seconds')} "
        f"&nbsp;|&nbsp; Total Records: <b>{len(history_df)}</b>",
        _SUBTITLE_STYLE,
    ))

    if history_df is None or len(history_df) == 0:
        story.append(Paragraph("<i>No history records.</i>", _BODY_STYLE))
        doc.build(story)
        return buf.getvalue()

    cols = [
        ("id", "ID", 10),
        ("timestamp", "Timestamp", 32),
        ("location", "Location", 30),
        ("latitude", "Lat", 15),
        ("longitude", "Lon", 15),
        ("cyclone_score", "Cyc", 12),
        ("flood_depth_m", "Flood (m)", 16),
        ("dem_elevation_m", "Elev (m)", 16),
        ("combined_score", "Comb", 12),
        ("decision", "Decision", 28),
        ("total_premium", "Premium", 22),
    ]
    header = [c[1] for c in cols]
    widths = [c[2] * mm for c in cols]
    rows = [header]

    def _fmt(v, key):
        if v is None or (isinstance(v, float) and v != v):  # NaN check
            return "—"
        if key in ("latitude", "longitude"):
            return f"{float(v):.4f}"
        if key in ("cyclone_score", "combined_score", "dem_elevation_m"):
            return f"{float(v):.1f}"
        if key == "flood_depth_m":
            return f"{float(v):.2f}"
        if key == "total_premium":
            return _fmt_inr(v)
        if key == "timestamp":
            return str(v)[:19].replace("T", " ")
        return str(v)

    for _, r in history_df.iterrows():
        rows.append([_fmt(r.get(k), k) for k, _, _ in cols])

    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1565C0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)

    doc.build(story)
    return buf.getvalue()
