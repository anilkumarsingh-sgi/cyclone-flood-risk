"""
PDF report generator for the NatCat Underwriting Engine.

Produces a multi-page A4 report that mirrors the on-screen text report
but in a properly formatted, branded layout.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
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
    cyc = assessment.get("cyclone", {}) or {}
    fld = assessment.get("flood", {}) or {}
    dem = assessment.get("dem", {}) or {"elevation_m": 0, "risk_level": "—", "risk_score": 0}
    dec = assessment.get("decision", {}) or {}
    prem = assessment.get("premium", {}) or {}
    combined = assessment.get("combined_score", 0)
    ts = assessment.get("timestamp") or datetime.now().isoformat()
    ref_no = f"UW-NATCAT-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="NatCat Underwriting Report",
        author="NatCat Underwriting Engine",
    )

    story: list = []
    story.append(Paragraph("Natural Catastrophe Underwriting Report", _TITLE_STYLE))
    story.append(Paragraph(
        f"Cyclone &amp; Flood Multi-Peril Risk Assessment<br/>"
        f"Reference No: <b>{ref_no}</b> &nbsp;|&nbsp; Generated: {ts}",
        _SUBTITLE_STYLE,
    ))

    # Decision banner
    dec_color = _decision_color(dec.get("decision"))
    banner = Table(
        [[Paragraph(
            f"<b>DECISION: {dec.get('decision', '—')}</b><br/>"
            f"<font size=8>Authority: {dec.get('authority', '—')} &nbsp;|&nbsp; "
            f"Combined Score: {combined} / 100</font>",
            ParagraphStyle("banner", parent=_BODY_STYLE,
                           textColor=colors.white, fontSize=12, leading=16,
                           alignment=TA_CENTER),
        )]],
        colWidths=[174 * mm],
    )
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), dec_color),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]))
    story.append(banner)
    story.append(Spacer(1, 8))

    # 1. Location
    story.append(Paragraph("1. Risk Location", _H2_STYLE))
    story.append(_kv_table([
        ("Location", inp.get("city") or "Custom"),
        ("Coordinates", f"{inp.get('lat', 0):.4f}° N, {inp.get('lon', 0):.4f}° E"),
        ("Buffer Radius", f"{inp.get('buffer_radius_m', 0)} m"),
        ("Coast Proximity", inp.get("coast_proximity", "—")),
    ]))

    # 2. Property
    story.append(Paragraph("2. Property Details", _H2_STYLE))
    story.append(_kv_table([
        ("Total Sum Insured", _fmt_inr(inp.get("tsi", 0))),
        ("Construction", inp.get("construction", "—")),
        ("Occupancy", inp.get("occupancy", "—")),
        ("Building Age", inp.get("age", "—")),
        ("Floor Level", inp.get("floor_level", "—")),
    ]))

    # 3. Hazards summary table
    story.append(Paragraph("3. Hazard Assessment", _H2_STYLE))
    haz_data = [
        ["Peril", "Metric", "Value", "Risk Level", "Loading"],
        ["Cyclone", "Score", f"{cyc.get('risk_score', 0):.1f} / 100",
         cyc.get("risk_level", "—"),
         f"+{prem.get('cyclone_loading_pct', 0):.0f}%"],
        ["Flood", f"Depth ({inp.get('flood_rp', '')})",
         f"{fld.get('depth_m', 0):.3f} m",
         fld.get("risk_level", "—"),
         f"+{prem.get('flood_loading_pct', 0):.0f}%"],
        ["Elevation (DEM)", "Elevation",
         f"{dem.get('elevation_m', 0):.2f} m",
         dem.get("risk_level", "—"),
         f"+{prem.get('dem_loading_pct', 0):.0f}%"],
    ]
    haz_t = Table(haz_data, colWidths=[30 * mm, 38 * mm, 38 * mm, 38 * mm, 30 * mm])
    haz_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1565C0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(haz_t)

    # 4. Combined
    story.append(Paragraph("4. Combined Risk Score", _H2_STYLE))
    story.append(_kv_table([
        ("Composite Score", f"{combined} / 100"),
        ("Methodology", "Weighted (Cyclone 45%, Flood 35%, DEM 20%)"),
    ]))

    # 5. Decision & conditions
    story.append(Paragraph("5. Underwriting Decision &amp; Conditions", _H2_STYLE))
    story.append(_kv_table([
        ("Decision", dec.get("decision", "—")),
        ("Authority Level", dec.get("authority", "—")),
        ("Rationale", dec.get("detail", "—")),
    ]))
    conds = dec.get("conditions") or []
    if conds:
        story.append(Spacer(1, 4))
        story.append(Paragraph("<b>Special Conditions:</b>", _BODY_STYLE))
        for c in conds:
            story.append(Paragraph(f"&bull; {c}", _BODY_STYLE))

    # Page break before premium
    story.append(PageBreak())

    # 6. Premium breakdown
    story.append(Paragraph("6. Premium Indication", _H2_STYLE))
    story.append(_kv_table([
        ("Base Rate", f"{prem.get('base_rate_pct', 0):.2f}%"),
        ("Cyclone Loading", f"+{prem.get('cyclone_loading_pct', 0):.0f}%"),
        ("Flood Loading", f"+{prem.get('flood_loading_pct', 0):.0f}%"),
        ("DEM Loading", f"+{prem.get('dem_loading_pct', 0):.0f}%"),
        ("Peril Loading Factor", f"x{prem.get('peril_loading', 1):.2f}"),
        ("Property Factor", f"x{prem.get('property_factor', 1):.2f}"),
        ("Effective Rate", f"{prem.get('effective_rate_pct', 0):.4f}%"),
        ("Net Premium", _fmt_inr(prem.get("net_premium", 0))),
        ("GST (18%)", _fmt_inr(prem.get("gst_18_pct", 0))),
        ("TOTAL PREMIUM", f"<b>{_fmt_inr(prem.get('total_premium', 0))}</b>"),
        ("NatCat Deductible", f"{inp.get('deductible', 0)}%"),
    ]))

    # 7. Data sources
    story.append(Paragraph("7. Data Sources &amp; Methodology", _H2_STYLE))
    story.append(Paragraph(
        "<b>Cyclone:</b> NOAA IBTrACS v4 (International Best Track Archive — "
        "North Indian Basin).<br/>"
        "<b>Flood:</b> JRC / Copernicus CEMS GloFAS Flood Hazard Maps v2.1.<br/>"
        "<b>Elevation:</b> USGS SRTMGL1_003 (30 m global resolution).<br/>"
        "<b>Engine:</b> Google Earth Engine.",
        _BODY_STYLE,
    ))

    # Disclaimer
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<b>Disclaimer:</b> This is a system-generated indicative assessment based "
        "on satellite-derived hazard data. Final underwriting decisions must comply "
        "with company policy, regulatory requirements, and may require additional "
        "survey / inspection reports. All currency figures are in Indian Rupees (INR). "
        "GST is shown at 18% as an illustrative rate.",
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
