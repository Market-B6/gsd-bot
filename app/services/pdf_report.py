"""PDF report for doctor with charts (matplotlib -> embedded)."""
import io
from datetime import datetime, timedelta
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import (
    User, Meal, GlucoseReading, InsulinDose, WeightEntry, BPEntry,
    KickSession, GlucoseType,
)


def _register_fonts():
    """Try to register Cyrillic-capable font. Falls back to Helvetica if missing."""
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


async def generate_pdf_report(session: AsyncSession, user: User, days: int = 28) -> io.BytesIO:
    now = datetime.now()
    start = now - timedelta(days=days)

    glucose = (await session.execute(
        select(GlucoseReading).where(
            GlucoseReading.user_id == user.id,
            GlucoseReading.datetime >= start,
        ).order_by(GlucoseReading.datetime)
    )).scalars().all()

    meals = (await session.execute(
        select(Meal).where(Meal.user_id == user.id, Meal.datetime >= start)
        .order_by(Meal.datetime)
    )).scalars().all()

    insulin = (await session.execute(
        select(InsulinDose).where(InsulinDose.user_id == user.id, InsulinDose.datetime >= start)
        .order_by(InsulinDose.datetime)
    )).scalars().all()

    weights = (await session.execute(
        select(WeightEntry).where(WeightEntry.user_id == user.id, WeightEntry.datetime >= start)
        .order_by(WeightEntry.datetime)
    )).scalars().all()

    bps = (await session.execute(
        select(BPEntry).where(BPEntry.user_id == user.id, BPEntry.datetime >= start)
        .order_by(BPEntry.datetime)
    )).scalars().all()

    kicks = (await session.execute(
        select(KickSession).where(
            KickSession.user_id == user.id,
            KickSession.start_time >= start,
            KickSession.end_time.isnot(None),
        ).order_by(KickSession.start_time)
    )).scalars().all()

    font, font_bold = _register_fonts()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("t", parent=styles["Title"], fontName=font_bold, fontSize=18)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=font_bold, fontSize=13)
    normal = ParagraphStyle("n", parent=styles["Normal"], fontName=font, fontSize=10)

    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=1.5*cm, rightMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
    story = []

    story.append(Paragraph("Дневник ГСД — отчёт для врача", title_style))
    story.append(Spacer(1, 0.3*cm))
    patient = user.full_name or user.username or f"ID {user.tg_id}"
    story.append(Paragraph(f"Пациент: <b>{patient}</b>", normal))
    story.append(Paragraph(f"Период: {start.strftime('%d.%m.%Y')} — {now.strftime('%d.%m.%Y')}", normal))
    story.append(Paragraph(f"Отчёт сформирован: {now.strftime('%d.%m.%Y %H:%M')}", normal))
    story.append(Spacer(1, 0.6*cm))

    # Summary
    if glucose:
        values = [g.value for g in glucose]
        fasting = [g.value for g in glucose if g.type == GlucoseType.FASTING]
        postmeal = [g.value for g in glucose if g.type == GlucoseType.POSTMEAL]
        normal_count = sum(1 for g in glucose if g.is_normal)
        story.append(Paragraph("Сводка по гликемии", h2))
        rows = [
            ["Показатель", "Значение"],
            ["Всего замеров", str(len(glucose))],
            ["Средний уровень", f"{sum(values)/len(values):.2f} ммоль/л"],
            ["Минимум / Максимум", f"{min(values):.1f} / {max(values):.1f}"],
            ["Замеры в норме", f"{normal_count} ({normal_count/len(glucose)*100:.0f}%)"],
        ]
        if fasting:
            rows.append(["Средний натощак", f"{sum(fasting)/len(fasting):.2f} ммоль/л"])
        if postmeal:
            rows.append(["Средний после еды", f"{sum(postmeal)/len(postmeal):.2f} ммоль/л"])
        tbl = Table(rows, colWidths=[9*cm, 7*cm])
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), font),
            ("FONTNAME", (0,0), (-1,0), font_bold),
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.5*cm))

        # Chart 1: glucose over time
        chart_buf = io.BytesIO()
        fig, ax = plt.subplots(figsize=(7, 3))
        f_x = [g.datetime for g in glucose if g.type == GlucoseType.FASTING]
        f_y = [g.value for g in glucose if g.type == GlucoseType.FASTING]
        p_x = [g.datetime for g in glucose if g.type == GlucoseType.POSTMEAL]
        p_y = [g.value for g in glucose if g.type == GlucoseType.POSTMEAL]
        if f_x:
            ax.plot(f_x, f_y, "o-", label="Натощак", color="#2b6cb0")
        if p_x:
            ax.plot(p_x, p_y, "s-", label="После еды", color="#c05621")
        ax.axhline(5.1, ls="--", color="#2b6cb0", alpha=0.4, label="Норма натощак (<5.1)")
        ax.axhline(7.0, ls="--", color="#c05621", alpha=0.4, label="Норма ч/з 1ч (<7.0)")
        ax.set_ylabel("ммоль/л")
        ax.set_title("Динамика гликемии")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(chart_buf, format="png", dpi=140)
        plt.close(fig)
        chart_buf.seek(0)
        story.append(Image(chart_buf, width=17*cm, height=7.2*cm))
        story.append(Spacer(1, 0.4*cm))

    # Insulin
    if insulin:
        story.append(Paragraph("Инсулинотерапия", h2))
        by_day = defaultdict(lambda: {"short": 0.0, "long": 0.0})
        for d in insulin:
            by_day[d.datetime.date()][d.type.value] += d.units
        total_short = sum(v["short"] for v in by_day.values())
        total_long = sum(v["long"] for v in by_day.values())
        rows = [
            ["Показатель", "Значение"],
            ["Дней с инсулином", str(len(by_day))],
            ["Всего короткого", f"{total_short:.1f} Ед"],
            ["Всего длинного", f"{total_long:.1f} Ед"],
            ["Средняя суточная доза", f"{(total_short+total_long)/max(len(by_day),1):.1f} Ед"],
        ]
        tbl = Table(rows, colWidths=[9*cm, 7*cm])
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), font),
            ("FONTNAME", (0,0), (-1,0), font_bold),
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.5*cm))

    # Weight/BP
    if weights or bps:
        story.append(PageBreak())
        story.append(Paragraph("Вес и артериальное давление", h2))
        if weights:
            first_w = weights[0].weight_kg
            last_w = weights[-1].weight_kg
            story.append(Paragraph(
                f"Вес: {first_w:.1f} кг → {last_w:.1f} кг (Δ {last_w-first_w:+.1f} кг за период)",
                normal,
            ))
        if bps:
            alerts = [b for b in bps if b.is_alert]
            story.append(Paragraph(
                f"Замеров АД: {len(bps)}. Из них выше 140/90: <b>{len(alerts)}</b>",
                normal,
            ))
            if alerts:
                story.append(Paragraph(
                    "⚠ Рекомендуется наблюдение риска преэклампсии.", normal
                ))
        story.append(Spacer(1, 0.5*cm))

    if kicks:
        low = [k for k in kicks if k.is_alert]
        story.append(Paragraph("Шевеления плода", h2))
        story.append(Paragraph(
            f"Завершённых сессий подсчёта: {len(kicks)}. "
            f"Из них менее 10 шевелений за 2 часа: <b>{len(low)}</b>",
            normal,
        ))
        if low:
            dates = ", ".join(k.start_time.strftime("%d.%m") for k in low[:10])
            story.append(Paragraph(f"Даты со снижением активности: {dates}", normal))
            story.append(Paragraph("Требуется оценка состояния плода.", normal))
        story.append(Spacer(1, 0.5*cm))

    # Meals summary
    if meals:
        meal_days = len({m.datetime.date() for m in meals})
        per_active_day = len(meals) / max(meal_days, 1)
        story.append(Paragraph("Питание", h2))
        story.append(Paragraph(
            f"Записано приёмов пищи: <b>{len(meals)}</b>. "
            f"Записи велись {meal_days} дн. из {days}.",
            normal,
        ))
        story.append(Paragraph(
            f"В дни с записями — в среднем {per_active_day:.1f} приёма пищи в день.",
            normal,
        ))
        if meal_days < days / 2:
            story.append(Paragraph(
                "Дневник заполнен неполно — данные могут не отражать обычный рацион.",
                normal,
            ))

    doc.build(story)
    out.seek(0)
    return out
