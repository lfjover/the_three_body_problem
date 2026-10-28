#!/usr/bin/env python3
"""
Makes the PDF buyers download on Etsy (Gumroad can use the link directly).

  python3 make_delivery_pdf.py trades/barber.json --link https://<your>.notion.site/...

Output: out/<Product Name> - Chairside Studio.pdf
"""

import argparse
import json
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
INK = HexColor("#1F1B16")
MUTED = HexColor("#6B6259")
ACCENT = HexColor("#B4532A")
PAPER = HexColor("#FAF6F0")


def wrap(c, text, x, y, width, font="Helvetica", size=11, leading=16, color=INK):
    c.setFont(font, size)
    c.setFillColor(color)
    words, line = text.split(), ""
    for w in words:
        test = (line + " " + w).strip()
        if c.stringWidth(test, font, size) > width:
            c.drawString(x, y, line)
            y -= leading
            line = w
        else:
            line = test
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def main():
    p = argparse.ArgumentParser()
    p.add_argument("config")
    p.add_argument("--link", required=True, help="public 'duplicate as template' link from Notion")
    args = p.parse_args()
    cfg = json.loads(Path(args.config).read_text())

    out = HERE / "out" / f"{cfg['product_name']} - Chairside Studio.pdf"
    out.parent.mkdir(exist_ok=True)
    W, H = letter
    c = canvas.Canvas(str(out), pagesize=letter)
    c.setTitle(f"{cfg['product_name']} — Chairside Studio")

    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    m = 64

    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(m, H - 70, "CHAIRSIDE STUDIO")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 30)
    c.drawString(m, H - 112, cfg["product_name"])
    y = wrap(c, "Thank you for your purchase! Your Notion template is one click away.",
             m, H - 142, W - 2 * m, size=13, leading=18, color=MUTED)

    # Button
    by = y - 50
    c.setFillColor(ACCENT)
    c.roundRect(m, by, 300, 46, 10, stroke=0, fill=1)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(m + 150, by + 17, "Get your template  →")
    c.linkURL(args.link, (m, by, m + 300, by + 46), relative=0)
    y = wrap(c, f"Or paste this link in your browser: {args.link}", m, by - 22, W - 2 * m,
             size=9, leading=12, color=MUTED)

    y -= 22
    c.setFont("Helvetica-Bold", 15)
    c.setFillColor(INK)
    c.drawString(m, y, "How to get it into your Notion")
    y -= 26
    steps = [
        "Make a free Notion account at notion.com if you don't have one (the free plan works).",
        "Click the button above. The template opens in your browser.",
        "Click 'Duplicate' (top right). Pick your workspace. It's now yours to edit.",
        "Open the 'Start Here' page inside the template. Setup takes about 10 minutes.",
    ]
    for i, s in enumerate(steps, 1):
        c.setFillColor(ACCENT)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(m, y, f"{i}.")
        y = wrap(c, s, m + 22, y, W - 2 * m - 22, size=12, leading=17) - 8

    y -= 10
    c.setFont("Helvetica-Bold", 15)
    c.setFillColor(INK)
    c.drawString(m, y, "What's inside")
    y -= 24
    inside = [
        "Weekly and monthly booking calendar, plus an upcoming list",
        "Deposits to collect, with balance due worked out for you",
        f"Client profiles with {cfg['notes_label'].lower()}, visit count and total spent",
        f"Rebook list: who is due back (default every {cfg['rebook_weeks']} weeks) and has nothing booked",
        "Income grouped by month, including kept no-show deposits",
        "Copy-paste message templates for confirmations, deposits and reminders",
    ]
    for s in inside:
        c.setFillColor(ACCENT)
        c.circle(m + 4, y + 4, 2.5, stroke=0, fill=1)
        y = wrap(c, s, m + 16, y, W - 2 * m - 16, size=11, leading=15) - 4

    c.setStrokeColor(HexColor("#E3DACE"))
    c.line(m, 92, W - m, 92)
    wrap(c, "One license per business. Please don't resell or share the template link. "
            "Trouble with the link? Message us through the shop and we'll help.",
         m, 74, W - 2 * m, size=9, leading=12, color=MUTED)
    c.save()
    print(f"✓ {out}")


if __name__ == "__main__":
    main()
