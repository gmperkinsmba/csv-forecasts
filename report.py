from datetime import datetime, timedelta, timezone
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def make_report(payload):
    out = BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=letter,
        rightMargin=0.62 * inch,
        leftMargin=0.62 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title="CSV Forecasts report",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Sub", parent=styles["Normal"], textColor=colors.HexColor("#556577"), fontSize=9, leading=13))
    styles.add(ParagraphStyle(name="Kicker", parent=styles["Normal"], textColor=colors.HexColor("#1F5C8B"), fontSize=8, leading=11, spaceAfter=5))
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=12.75, leading=16, wordWrap="CJK"))
    styles["Title"].fontSize = 24
    styles["Heading2"].fontSize = 16

    story = [
        Paragraph("CSV FORECASTS / ANALYSIS", styles["Kicker"]),
        Paragraph("Forecast and backtest report", styles["Title"]),
        Paragraph("Prepared " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), styles["Sub"]),
        Spacer(1, 12),
        Paragraph("Run summary", styles["Heading2"]),
        Paragraph(f"Forecast comparison by series · Horizon: {payload['horizon']} steps · Series: {len(payload['series'])}", styles["Normal"]),
        Spacer(1, 8),
    ]

    for series in payload["series"]:
        name = escape(series["name"])
        active = series.get("timesfm") or {}
        shown = active.get("forecast", series["forecast"])
        block = [
            Paragraph(name, styles["Heading2"]),
            Paragraph(
                f"{series['rows']} rows · {escape(series['start'])} to {escape(series['end'])} · "
                f"cadence {escape(series.get('cadence_label', 'unknown'))} · "
                f"unit: {escape(series.get('unit', 'unspecified'))}",
                styles["Small"],
            ),
            Spacer(1, 5),
        ]
        quality = series["quality"]
        block.append(Paragraph(
            f"Data checks: {quality['duplicates']} duplicate timestamps, {quality['gaps']} cadence gaps, "
            f"{quality['missing']} missing values. Repair: {escape(series.get('repair', 'none'))}.",
            styles["Small"],
        ))
        rows = [
            ["Method", "MAE", "MASE", "Test points"],
            ["Last value", f"{series['methods']['Last value']['mae']:.4g}", _num(series['methods']['Last value']['mase']), series['methods']['Last value']['observations']],
            ["Seasonal naive", f"{series['methods']['Seasonal naive']['mae']:.4g}", _num(series['methods']['Seasonal naive']['mase']), series['methods']['Seasonal naive']['observations']],
        ]
        if active:
            rows.append(["TimesFM 2.5", f"{active['mae']:.4g}", _num(active['mase']), active['observations']])
        block.append(Spacer(1, 7))
        block.append(Table(rows, colWidths=[1.6 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17243A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D7DEE8")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6F8")]),
            ("FONTSIZE", (0, 0), (-1, -1), 11.5),
            ("PADDING", (0, 0), (-1, -1), 7),
        ])))
        block.append(Spacer(1, 7))
        title = "TimesFM 2.5 forecast values: " if active else "Baseline forecast values: "
        block.append(Paragraph(title + ", ".join(f"{v:.4g}" for v in shown), styles["Small"]))
        if active:
            block.append(Paragraph(
                "TimesFM quantile levels " + escape(str(active.get("quantile_levels", []))) +
                " · output by step: " + escape(str(active.get("quantiles", []))), styles["Small"]
            ))

        history = [value for value in series.get("history", []) if value is not None]
        combined = history + shown
        if combined:
            low, high = min(combined), max(combined)
            span = high - low or 1
            chart = Drawing(440, 112)
            chart.add(Line(26, 20, 425, 20, strokeColor=colors.HexColor("#CBD5E1")))
            chart.add(String(27, 98, "Recent history · value (" + escape(series.get("unit", "unspecified"))[:32] + ")", fontSize=8, fillColor=colors.HexColor("#556577")))
            chart.add(String(355, 98, "Forecast", fontSize=8, fillColor=colors.HexColor("#B45309")))
            chart.add(String(1, 86, f"{high:.4g}", fontSize=7, fillColor=colors.HexColor("#556577")))
            chart.add(String(1, 23, f"{low:.4g}", fontSize=7, fillColor=colors.HexColor("#556577")))
            chart.add(String(27, 7, escape(series.get("history_start", series.get("start", ""))), fontSize=7, fillColor=colors.HexColor("#556577")))
            try:
                end = datetime.fromisoformat(series["end"])
                forecast_end = end + timedelta(seconds=series["cadence_seconds"] * len(shown))
                end_label = forecast_end.isoformat()
            except (KeyError, TypeError, ValueError):
                end_label = "forecast end unavailable"
            chart.add(String(270, 7, escape(end_label), fontSize=7, fillColor=colors.HexColor("#556577")))

            def point(index, value):
                return (28 + index * 395 / max(1, len(combined) - 1), 24 + (value - low) * 64 / span)

            if len(history) > 1:
                chart.add(PolyLine([coord for index, value in enumerate(history) for coord in point(index, value)], strokeColor=colors.HexColor("#315E84"), strokeWidth=1.8))
            forecast_points = [coord for index, value in enumerate(shown, start=len(history)) for coord in point(index, value)]
            if len(forecast_points) >= 4:
                chart.add(PolyLine(forecast_points, strokeColor=colors.HexColor("#D97706"), strokeWidth=2, strokeDashArray=[4, 2]))
            block.append(chart)

        if active:
            diagnostic = (
                f"TimesFM package {active['package_version']} · checkpoint {escape(active['checkpoint_id'])} · "
                f"weights SHA-256 {active['checkpoint_sha256']} · load and fold runtime "
                f"{active['load_runtime_ms'] + active['runtime_ms']:.1f} ms. Observed coverage uses held-out "
                "targets within the model's 0.1 to 0.9 quantiles."
            )
        else:
            diagnostic = f"Prediction interval and coverage: unavailable in baseline-only mode. Runtime {series['runtime_ms']:.1f} ms."
        diagnostic += f" Fold bounds (training start, test start, test end row offsets): {escape(str(series['fold_bounds']))}."
        block.append(Paragraph(diagnostic, styles["Small"]))
        block.append(Spacer(1, 12))
        story.append(KeepTogether(block))

    mode_note = (
        "TimesFM 2.5 forecasts and rolling-origin scores use the same expanding time windows as the baselines."
        if payload.get("mode") == "timesfm" else
        "TimesFM weights were not loaded; forecasts use the selected baseline."
    )
    story.extend([
        Paragraph("Method and limits", styles["Heading2"]),
        Paragraph(
            "Backtests use expanding time-ordered training windows. Each test window begins after its training origin. "
            "Missing training values use the selected repair method within that fold's training prefix. Missing test "
            "targets are excluded. MASE is pooled MAE divided by the mean training-only seasonal-naive scale and is "
            "unavailable when that scale is zero. " + mode_note,
            styles["Small"],
        ),
        Spacer(1, 6),
        Paragraph(
            f"Reproducibility: {escape(payload.get('engine_version', 'forecast-studio-baseline-v1'))} · input SHA-256 "
            f"{escape(payload.get('input_sha256', 'unavailable'))}. Source data is not embedded.",
            styles["Small"],
        ),
    ])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D7DEE8"))
        canvas.line(0.62 * inch, 0.45 * inch, 7.88 * inch, 0.45 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#556577"))
        canvas.drawString(0.62 * inch, 0.29 * inch, "CSV Forecasts · forecast comparison")
        canvas.drawRightString(7.88 * inch, 0.29 * inch, f"{document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()


def _num(value):
    return f"{value:.4g}" if value is not None else "n/a (zero scale)"
