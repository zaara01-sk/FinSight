"""Concise FinSight executive financial and MSME advisory PDF."""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from services import report_service


NAVY = colors.HexColor("#173B57")
BABY_BLUE = colors.HexColor("#DFF3FF")
ACCENT = colors.HexColor("#4EA5D9")
BORDER = colors.HexColor("#D7E9F4")
MUTED = colors.HexColor("#66788A")
POSITIVE = colors.HexColor("#2F9E72")
WARNING = colors.HexColor("#E5A93D")
WHITE = colors.white

DEFAULT_SECTIONS = {
    "executive_summary",
    "business_profile",
    "financial_performance",
    "cash_flow",
    "income_analysis",
    "expense_analysis",
    "payment_mode",
    "business_health",
    "anomalies",
    "recommendations",
    "government_schemes",
    "methodology",
    "disclaimer",
}

DEFAULT_LABELS = {
    "total_income": "Total Income",
    "total_expenses": "Total Expenses",
    "net_cash_flow": "Net Cash Flow",
}


def _money(minor: Any, currency: str) -> str:
    if minor is None:
        return "N/A"
    try:
        major = Decimal(str(minor)) / Decimal(100)
    except Exception:
        return "N/A"
    return f"{currency} {major:,.2f}"


def _text(value: Any, default: str = "N/A") -> str:
    if value is None or value == "":
        return default
    return str(value)


def _percent(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{value}%"


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "FS_CoverBrand", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=29, leading=33, textColor=NAVY, alignment=TA_CENTER, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "FS_CoverTitle", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=15, leading=20, textColor=ACCENT, alignment=TA_CENTER, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "FS_H1", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=16, leading=20, textColor=NAVY, spaceBefore=4, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "FS_H2", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=10.5, leading=14, textColor=NAVY, spaceBefore=5, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "FS_Body", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9.1, leading=13, textColor=colors.HexColor("#263B4D"), spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        "FS_Small", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=7.8, leading=10.5, textColor=MUTED, spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        "FS_MetricLabel", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=7.5, leading=9, textColor=MUTED, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "FS_MetricValue", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=13.5, leading=17, textColor=NAVY, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "FS_CalloutTitle", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=8.5, leading=11, textColor=NAVY, spaceAfter=2,
    ))
    return styles


def _footer(canvas, doc, *, business_name: str, period: str):
    canvas.saveState()
    width, _height = A4
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(17 * mm, 14 * mm, width - 17 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(17 * mm, 9 * mm, f"FinSight · {business_name}")
    canvas.drawCentredString(width / 2, 9 * mm, period)
    canvas.drawRightString(width - 17 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _section_title(number: int, title: str, styles) -> Paragraph:
    return Paragraph(f"{number}. {title}", styles["FS_H1"])


def _metric_cards(metrics: list[tuple[str, str]], styles) -> Table:
    data = []
    for label, value in metrics:
        data.append([
            Paragraph(label, styles["FS_MetricLabel"]),
            Paragraph(value, styles["FS_MetricValue"]),
        ])
    cards = [
        Table(
            [[label], [value]],
            colWidths=[39 * mm],
            rowHeights=[9 * mm, 13 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]),
        )
        for label, value in data
    ]
    return Table([cards], colWidths=[40 * mm] * len(cards), hAlign="CENTER")


def _callout(title: str, body: str, styles, *, shade=WHITE) -> Table:
    return Table(
        [[Paragraph(title, styles["FS_CalloutTitle"])],
         [Paragraph(body, styles["FS_Body"])]],
        colWidths=[160 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), shade),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]),
    )


def _table(headers: list[str], rows: list[list[Any]], widths) -> Table:
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    cell_style = ParagraphStyle(
        "FS_TableCell",
        fontName="Helvetica",
        fontSize=7.2,
        leading=9.2,
        textColor=colors.HexColor("#263B4D"),
    )
    header_style = ParagraphStyle(
        "FS_TableHeader",
        fontName="Helvetica-Bold",
        fontSize=7.3,
        leading=9.5,
        textColor=WHITE,
    )
    formatted_headers = [Paragraph(h, header_style) for h in headers]
    formatted_rows = [
        [Paragraph(_text(v, ""), cell_style) if isinstance(v, str) and len(str(v)) > 15 else _text(v, "")
         for v in row]
        for row in rows
    ]
    table = Table(
        [formatted_headers] + formatted_rows,
        colWidths=widths,
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.3),
        ("LEADING", (0, 0), (-1, -1), 9.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BABY_BLUE]),
        ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _bar_chart(title: str, categories: list[str], values: list[float]) -> Drawing | None:
    if not categories or not values or not any(value != 0 for value in values):
        return None
    categories = categories[:6]
    values = values[:6]
    drawing = Drawing(465, 175)
    drawing.add(String(8, 160, title, fontName="Helvetica-Bold", fontSize=9, fillColor=NAVY))
    chart = VerticalBarChart()
    chart.x = 42
    chart.y = 35
    chart.height = 105
    chart.width = 390
    chart.data = [values]
    chart.categoryAxis.categoryNames = categories
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.angle = 20
    chart.valueAxis.labels.fontSize = 6.5
    chart.valueAxis.valueMin = 0
    chart.bars[0].fillColor = ACCENT
    chart.barWidth = 12
    drawing.add(chart)
    return drawing


def _income_expense_chart(monthly: list[dict[str, Any]]) -> Drawing | None:
    if len(monthly) < 2:
        return None
    data = monthly[-12:]
    num_months = len(data)
    drawing = Drawing(465, 180)
    drawing.add(String(
        8, 164, "Income vs Expense Trend",
        fontName="Helvetica-Bold", fontSize=9, fillColor=NAVY,
    ))
    chart = VerticalBarChart()
    chart.x = 42
    chart.y = 38
    chart.height = 105
    chart.width = 390
    chart.data = [
        [float(Decimal(str(row.get("income_minor", 0))) / 100) for row in data],
        [float(Decimal(str(row.get("expense_minor", 0))) / 100) for row in data],
    ]
    chart.categoryAxis.categoryNames = [str(row.get("period")) for row in data]
    chart.categoryAxis.labels.fontSize = 5.5 if num_months > 8 else 6.5
    chart.categoryAxis.labels.angle = 25 if num_months > 8 else 0
    chart.valueAxis.labels.fontSize = 6.5
    chart.valueAxis.valueMin = 0
    chart.bars[0].fillColor = ACCENT
    chart.bars[1].fillColor = WARNING
    chart.barWidth = 5 if num_months > 8 else 8
    chart.groupSpacing = 3 if num_months > 8 else 5
    drawing.add(chart)
    drawing.add(String(48, 15, "Income", fontSize=7, fillColor=ACCENT))
    drawing.add(String(105, 15, "Expenses", fontSize=7, fillColor=WARNING))
    return drawing


def safe_report_filename(business_name: str, report_date: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", business_name.strip()).strip("_")
    base = base[:80] or "Business"
    return f"FinSight_{base}_{report_date}.pdf"


def _snapshot_text(advisory: dict[str, Any], currency: str) -> str:
    snapshot = advisory["performance_snapshot"]
    count = int(snapshot.get("transaction_count", 0) or 0)
    if count == 0:
        return (
            "No accepted transactions were available in the selected period. "
            "Financial interpretation is therefore limited until transaction data is imported."
        )
    net = snapshot.get("net_cash_flow_minor", 0)
    direction = "positive" if Decimal(str(net)) >= 0 else "negative"
    return (
        f"FinSight reviewed {count} accepted transaction(s). Recorded income was "
        f"{_money(snapshot.get('total_income_minor', 0), currency)}, recorded expenses were "
        f"{_money(snapshot.get('total_expense_minor', 0), currency)}, and net cash flow was "
        f"{_money(net, currency)} ({direction}). The analysis reflects transaction-level "
        "management records rather than audited accrual financial statements."
    )


def generate_business_report(
    *,
    business: dict[str, Any],
    report: dict[str, Any],
    decision_support: dict[str, Any] | None = None,
    scheme_results: list[dict[str, Any]] | None = None,
    report_title: str = "Executive Financial & MSME Advisory Report",
    included_sections: set[str] | None = None,
    labels: dict[str, str] | None = None,
) -> io.BytesIO:
    """Render a concise executive advisory report from service-layer outputs."""
    included = set(included_sections or DEFAULT_SECTIONS)
    display_labels = {**DEFAULT_LABELS, **(labels or {})}
    recommendations = (
        decision_support.get("recommendations", [])
        if isinstance(decision_support, dict)
        else []
    )
    advisory = report_service.build_advisory_model(report, recommendations)

    sections = report.get("sections", {}) if isinstance(report, dict) else {}
    summary = sections.get("financial_summary", {}) if isinstance(sections, dict) else {}
    categories = sections.get("category_report", []) if isinstance(sections, dict) else []
    payment_modes = sections.get("payment_mode_report", []) if isinstance(sections, dict) else []
    health = advisory.get("health", {})
    schemes = scheme_results if isinstance(scheme_results, list) else []

    currency = _text(report.get("currency"), "INR")
    date_range = report.get("date_range", {}) if isinstance(report, dict) else {}
    start_date = _text(date_range.get("start_date"))
    end_date = _text(date_range.get("end_date"))
    period = f"{start_date} to {end_date}"
    generated = _text(
        report.get("generated_at"),
        datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    business_name = _text(
        business.get("business_name"),
        _text(report.get("business", {}).get("name"), "Business"),
    )
    business_type = _text(business.get("business_type"), "Not specified")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=16 * mm,
        bottomMargin=19 * mm,
        title=f"FinSight — {business_name}",
        author="FinSight",
        pageCompression=0,
    )
    styles = _styles()
    story = []

    # COVER / CONTEXT & METRICS PROFILE
    story.extend([
        Spacer(1, 25 * mm),
        Paragraph("FinSight", styles["FS_CoverBrand"]),
        Paragraph(report_title, styles["FS_CoverTitle"]),
        Spacer(1, 9 * mm),
        _table(
            ["Report Context", "Details"],
            [
                ["Company Name", business_name],
                ["Reporting Period", period],
                ["Industry / Vertical", business_type],
                ["Accounting / Data Basis",
                 "Transaction-level cash-flow analysis based on imported management records."],
                ["Generated Date", generated[:10]],
            ],
            [48 * mm, 112 * mm],
        ),
        Spacer(1, 10 * mm),
        _metric_cards([
            (display_labels["total_income"], _money(summary.get("total_income_minor", 0), currency)),
            (display_labels["total_expenses"], _money(summary.get("total_expense_minor", 0), currency)),
            (display_labels["net_cash_flow"], _money(summary.get("net_cash_flow_minor", 0), currency)),
            ("Transactions", str(summary.get("transaction_count", 0) or 0)),
        ], styles),
        Spacer(1, 18 * mm),
        Paragraph(
            "Prepared by FinSight · Management decision-support report",
            styles["FS_CoverTitle"],
        ),
        PageBreak(),
    ])

    # SECTION 1 — EXECUTIVE BRIEFING
    if "executive_summary" in included:
        story.append(_section_title(1, "Executive Briefing", styles))
        story.append(Paragraph("<b>Performance Snapshot</b>", styles["FS_H2"]))
        story.append(Paragraph(_snapshot_text(advisory, currency), styles["FS_Body"]))

        positives = advisory.get("positives", [])
        story.append(Paragraph("<b>Top Financial Positives</b>", styles["FS_H2"]))
        if positives:
            for item in positives[:2]:
                story.append(Paragraph(f"• {item}", styles["FS_Body"]))
        else:
            story.append(Paragraph(
                "No material positive conclusion is stated because the supplied data is insufficient.",
                styles["FS_Body"],
            ))

        risk = advisory.get("primary_risk", {})
        story.append(Spacer(1, 2 * mm))
        story.append(_callout(
            "Primary Risk / Bottleneck",
            f"{_text(risk.get('title'))}: {_text(risk.get('detail'))}",
            styles,
            shade=colors.HexColor("#FFF8E8"),
        ))
        story.append(Spacer(1, 4 * mm))

        priority = advisory.get("management_priority", {})
        story.append(_callout(
            "Management Priority",
            f"{_text(priority.get('title'))}: {_text(priority.get('action'))}",
            styles,
            shade=BABY_BLUE,
        ))

        health_score = health.get("health_score") or health.get("overall_financial_health_score")
        if health_score is not None:
            story.append(Spacer(1, 5 * mm))
            story.append(Paragraph(
                f"<b>FinSight health context:</b> score {_text(health_score)}; "
                f"level {_text(health.get('health_level'))}. "
                "This is a deterministic management indicator, not a credit rating.",
                styles["FS_Small"],
            ))
    else:
        story.append(_section_title(1, "Executive Briefing", styles))
        story.append(Paragraph("Executive briefing excluded by report configuration.", styles["FS_Body"]))

    story.append(PageBreak())

    # SECTION 2 — ADVISORY PERFORMANCE DEEP-DIVE
    story.append(_section_title(2, "Advisory Performance Deep-Dive", styles))

    if "income_analysis" in included or "financial_performance" in included:
        story.append(Paragraph("2.1 Recorded Income Pattern & Margin Availability", styles["FS_H2"]))
        income_categories = advisory.get("income_categories", [])
        if income_categories:
            income_rows = [
                [
                    row.get("category") or "Uncategorized",
                    _money(row.get("income_minor", 0), currency),
                    row.get("income_count", row.get("count", 0)),
                ]
                for row in income_categories[:5]
            ]
            story.append(_table(
                ["Income Category", "Recorded Income", "Transactions"],
                income_rows,
                [72 * mm, 52 * mm, 36 * mm],
            ))
        else:
            story.append(Paragraph("No categorized income was available.", styles["FS_Body"]))

        monthly = advisory.get("monthly_trends", [])
        if len(monthly) >= 2:
            story.append(Paragraph(
                "Multiple monthly periods are available, so the trend chart below can be interpreted directionally.",
                styles["FS_Small"],
            ))
            chart = _income_expense_chart(monthly)
            if chart:
                story.append(chart)
        else:
            story.append(Paragraph(
                "Growth rate is not stated because the supplied data does not contain enough comparable monthly periods.",
                styles["FS_Small"],
            ))
        story.append(Paragraph(
            "<b>Gross margin:</b> Not available from supplied data. Gross margin cannot be "
            "reliably calculated without sufficient cost-of-goods / direct-cost information.",
            styles["FS_Small"],
        ))

    if "expense_analysis" in included or "financial_performance" in included:
        story.append(Paragraph("2.2 Expense Efficiency & Cash-Flow Quality", styles["FS_H2"]))
        expense_categories = advisory.get("expense_categories", [])
        if expense_categories:
            expense_rows = [
                [
                    row.get("category") or "Uncategorized",
                    _money(row.get("expense_minor", 0), currency),
                    row.get("expense_count", row.get("count", 0)),
                ]
                for row in expense_categories[:5]
            ]
            story.append(_table(
                ["Expense Category", "Recorded Expense", "Transactions"],
                expense_rows,
                [72 * mm, 52 * mm, 36 * mm],
            ))
            chart = _bar_chart(
                "Largest Expense Categories",
                [str(row.get("category") or "Uncategorized") for row in expense_categories],
                [float(Decimal(str(row.get("expense_minor", 0))) / 100) for row in expense_categories],
            )
            if chart:
                story.append(chart)
        else:
            story.append(Paragraph("No categorized expenses were available.", styles["FS_Body"]))

        story.append(Paragraph(
            f"Expense-to-income ratio: {_text(health.get('expense_to_income_ratio'))}. "
            f"Savings rate: {_percent(summary.get('savings_rate'))}. "
            f"Recurring expense burden: {_percent(health.get('recurring_expense_burden'))}. "
            "These figures are transaction-based cash-flow indicators; net cash flow is not presented as net profit.",
            styles["FS_Body"],
        ))

    if "cash_flow" in included or "payment_mode" in included:
        story.append(Paragraph("2.3 Cash Flow & Capital Preservation", styles["FS_H2"]))
        inc_exp_val = summary.get('income_expense_ratio')
        try:
            inc_exp_str = f"{float(Decimal(str(inc_exp_val))):.2f}" if inc_exp_val is not None else "N/A"
        except Exception:
            inc_exp_str = _text(inc_exp_val)

        story.append(Paragraph(
            f"Observed net cash flow is {_money(summary.get('net_cash_flow_minor', 0), currency)}. "
            f"Cash-flow stability score: {_text(health.get('cash_flow_stability'))}. "
            f"Income-to-expense ratio: {inc_exp_str}.",
            styles["FS_Body"],
        ))
        if "payment_mode" in included and payment_modes:
            mode_rows = [
                [
                    row.get("payment_mode") or "Other",
                    _money(row.get("income_minor", 0), currency),
                    _money(row.get("expense_minor", 0), currency),
                    row.get("count", 0),
                ]
                for row in payment_modes[:5]
            ]
            story.append(_table(
                ["Payment Mode", "Recorded Income", "Recorded Expenses", "Transactions"],
                mode_rows,
                [48 * mm, 42 * mm, 42 * mm, 28 * mm],
            ))
        story.append(Paragraph(
            "<b>Working capital, receivable days, payable days, inventory turnover and cash runway:</b> "
            "Not available from supplied data. FinSight does not estimate these metrics without the required source fields.",
            styles["FS_Small"],
        ))

    story.append(PageBreak())

    # SECTION 3 — MSME DUAL-LENS FRAMEWORK
    story.append(_section_title(3, "MSME Dual-Lens Framework", styles))
    story.append(Paragraph("Internal Management View — Operational Action Plan", styles["FS_H2"]))
    actions = advisory.get("internal_actions", [])
    if actions:
        for item in actions[:5]:
            story.append(Paragraph(
                f"• <b>{_text(item.get('action'))}</b> {_text(item.get('why'), '')}",
                styles["FS_Body"],
            ))
    else:
        story.append(Paragraph(
            "No specific operational action was generated from the available transaction evidence.",
            styles["FS_Body"],
        ))

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("External Partner / Lender View — Investor / Credit Readiness", styles["FS_H2"]))
    for observation in advisory.get("lender_observations", [])[:5]:
        story.append(Paragraph(f"• {observation}", styles["FS_Body"]))
    story.append(Paragraph(
        "FinSight does not state that the business is loan-approved, investor-ready or creditworthy. "
        "Those conclusions require additional evidence and an appropriate underwriting framework.",
        styles["FS_Small"],
    ))

    if "anomalies" in included:
        anomaly_summary = advisory.get("anomaly_summary", {})
        if isinstance(anomaly_summary, dict):
            severity_counts = anomaly_summary.get("severity_counts", {})
            severity_counts = (
                severity_counts if isinstance(severity_counts, dict) else {}
            )
            total_findings = int(anomaly_summary.get("total", 0) or 0)
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph("Risk / Anomaly Summary", styles["FS_H2"]))
            story.append(_table(
                ["Total", "Critical", "High", "Medium", "Low"],
                [[
                    total_findings,
                    severity_counts.get("CRITICAL", 0),
                    severity_counts.get("HIGH", 0),
                    severity_counts.get("MEDIUM", 0),
                    severity_counts.get("LOW", 0),
                ]],
                [28 * mm, 30 * mm, 30 * mm, 36 * mm, 36 * mm],
            ))

            type_counts = anomaly_summary.get("type_counts", {})
            type_counts = type_counts if isinstance(type_counts, dict) else {}
            ranked_types = sorted(
                type_counts.items(),
                key=lambda item: (-int(item[1]), str(item[0])),
            )
            if ranked_types:
                story.append(Spacer(1, 2 * mm))
                type_rows = [
                    [str(name).replace("_", " ").title(), count]
                    for name, count in ranked_types[:6]
                ]
                story.append(_table(
                    ["Finding Type", "Count"],
                    type_rows,
                    [125 * mm, 35 * mm],
                ))
                if len(ranked_types) > 6:
                    story.append(Paragraph(
                        f"{len(ranked_types) - 6} additional finding type(s) are summarized in FinSight.",
                        styles["FS_Small"],
                    ))

            examples = anomaly_summary.get("material_examples", [])
            examples = examples if isinstance(examples, list) else []
            for item in examples[:3]:
                if not isinstance(item, dict):
                    continue
                anomaly_type = str(item.get("type") or "Risk observation")
                title = anomaly_type.replace("_", " ").title()
                if anomaly_type == "negative_cash_flow_period":
                    title = "Negative Daily Cash Flow"
                elif anomaly_type == "repeated_identical_transactions":
                    title = "Repeated Transaction Pattern"
                period_text = _text(item.get("affected_period"), "")
                context = item.get("detection_context")
                context = context if isinstance(context, dict) else {}
                category = _text(context.get("category"), "")
                qualifiers = [value for value in (category, period_text) if value]
                qualifier_text = f" ({' · '.join(qualifiers)})" if qualifiers else ""
                story.append(Paragraph(
                    f"• <b>{title}</b> [{_text(item.get('severity'), 'N/A')}]"
                    f"{qualifier_text}: {_text(item.get('explanation'), 'Review required.')}",
                    styles["FS_Body"],
                ))
            additional = int(anomaly_summary.get("additional_count", 0) or 0)
            if additional > 0:
                story.append(Paragraph(
                    f"{additional} additional finding(s) are available in FinSight's "
                    "Anomalies page; the executive report shows only the most material examples.",
                    styles["FS_Small"],
                ))

    # SECTION 4 — PRIORITY ACTIONS
    story.append(Spacer(1, 4 * mm))
    story.append(_section_title(4, "Priority Actions", styles))
    priority_rows = [
        [
            item.get("priority"),
            item.get("action"),
            item.get("rationale"),
            item.get("time_horizon"),
        ]
        for item in advisory.get("priority_actions", [])[:5]
    ]
    if priority_rows:
        story.append(_table(
            ["Priority", "Action", "Financial Rationale", "Time Horizon"],
            priority_rows,
            [23 * mm, 50 * mm, 62 * mm, 25 * mm],
        ))
    else:
        story.append(Paragraph(
            "No priority action was generated from the selected-period evidence.",
            styles["FS_Body"],
        ))

    if "government_schemes" in included and schemes:
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("Government Scheme Opportunities", styles["FS_H2"]))
        
        # Sort so eligible and potentially relevant schemes come first
        order = {
            "Likely relevant based on supplied information": 0,
            "Potentially relevant": 1,
            "Not matched based on supplied information": 2,
        }
        sorted_schemes = sorted(
            schemes,
            key=lambda item: (order.get(item.get("relevance"), 9), str(item.get("scheme_name", "")))
        )
        
        # Prioritize actionable schemes (Likely or Potentially relevant)
        actionable_schemes = [s for s in sorted_schemes if s.get("relevance") != "Not matched based on supplied information"]
        schemes_to_display = actionable_schemes if actionable_schemes else sorted_schemes

        seen_schemes = set()
        deduped_schemes = []
        for s in schemes_to_display:
            name = s.get("scheme_name")
            if name not in seen_schemes:
                seen_schemes.add(name)
                deduped_schemes.append(s)

        scheme_rows = [
            [
                item.get("scheme_name"),
                item.get("relevance", "Potentially relevant"),
                item.get("information_required", "") or (", ".join(item.get("missing_information", [])) if isinstance(item.get("missing_information"), list) else "None"),
            ]
            for item in deduped_schemes[:5]
        ]
        story.append(_table(
            ["Scheme", "Screening Status", "Information Still Required"],
            scheme_rows,
            [58 * mm, 48 * mm, 54 * mm],
        ))
        story.append(Paragraph(
            "Scheme screening is indicative only. Official eligibility and current scheme rules must be verified before applying.",
            styles["FS_Small"],
        ))

    # SECTION 5 — METHODOLOGY & LIMITATIONS
    if "methodology" in included or "disclaimer" in included:
        story.append(Spacer(1, 5 * mm))
        story.append(_section_title(5, "Methodology & Limitations", styles))
        story.append(Paragraph(
            f"Analysis is based on {summary.get('transaction_count', 0) or 0} accepted transaction(s) "
            f"for {period}. Duplicate detection is applied during ingestion. Figures reflect imported "
            "management transaction records and are not audited financial statements. Unsupported accounting, "
            "working-capital, unit-economics and valuation metrics are not estimated. FinSight provides management "
            "decision support and does not replace professional accounting, tax, audit, legal, lending or investment advice.",
            styles["FS_Body"],
        ))

    footer = lambda canvas, document: _footer(
        canvas, document, business_name=business_name, period=period
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return buffer


generate_report = generate_business_report


__all__ = [
    "DEFAULT_LABELS",
    "DEFAULT_SECTIONS",
    "generate_business_report",
    "generate_report",
    "safe_report_filename",
]
