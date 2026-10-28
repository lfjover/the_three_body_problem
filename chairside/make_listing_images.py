#!/usr/bin/env python3
"""
Renders the 5 listing images for a trade (2400x1800, Etsy's 4:3).

  python3 make_listing_images.py trades/barber.json

Output: out/images/<slug>/01_hero.png ... 05_included.png
The screens are drawn from the same config the builder uses, so what the
images show matches what buyers get.
"""

import html
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACCENTS = {"barber": ("#B4532A", "#F6E3D8"), "nail_tech": ("#A8395E", "#F7E1E8")}

HERO_WEEK = {
    "barber": [
        (0, "10:00", "Marcus — Haircut", "Confirmed"), (0, "13:30", "Luis — Skin Fade", "Booked"),
        (1, "11:00", "Diego — Cut + Beard", "Confirmed"), (1, "16:00", "Sam — Kids Cut", "Booked"),
        (2, "09:30", "Chris — Haircut", "Booked"), (3, "12:00", "Andre — Skin Fade", "Booked"),
        (3, "17:00", "Jay — Lineup", "Confirmed"), (4, "10:00", "Rob — Beard Trim", "Booked"),
        (4, "14:00", "Malik — Cut + Beard", "Confirmed"), (5, "11:00", "Tony — Haircut", "Booked"),
    ],
    "nail_tech": [
        (0, "10:00", "Jasmine — Acrylic Fill", "Confirmed"), (0, "14:00", "Ana — Gel Manicure", "Booked"),
        (1, "11:30", "Brianna — Gel-X Full Set", "Confirmed"), (2, "10:00", "Taylor — Gel Manicure", "Booked"),
        (2, "15:00", "Mia — Pedicure", "Booked"), (3, "12:00", "Sofia — Gel Manicure", "Confirmed"),
        (4, "10:30", "Kayla — Acrylic Full Set", "Booked"), (4, "15:30", "Dani — Acrylic Fill", "Confirmed"),
        (5, "11:00", "Rosa — Nail Art", "Booked"),
    ],
}
COPY = {
    "barber": {"who": "barbers", "due": "Know who's due back in the chair",
               "due_sub": "Every client's cut notes, visits and spend in one place. "
                          "The Reach out list shows who's past their usual 3 weeks and hasn't booked."},
    "nail_tech": {"who": "nail techs", "due": "Know who's due for a fill",
                  "due_sub": "Shape, length, colors and history for every client. "
                             "The Reach out list shows who's past their 2-week fill and hasn't booked."},
}
STATUS_COL = {"Booked": ("#2F5E9E", "#E3ECF8"), "Confirmed": ("#2F7A4D", "#E1F1E7"),
              "Completed": ("#5F5A54", "#ECE9E5"), "No-show": ("#A33A2C", "#F7E0DC")}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1200px;height:900px;background:#FAF6F0;font-family:Inter,sans-serif;color:#1F1B16;
     overflow:hidden;position:relative}
.kicker{font-size:13px;letter-spacing:.14em;font-weight:700;color:var(--a);text-transform:uppercase}
h1{font-family:Lora,serif;font-weight:700;font-size:58px;line-height:1.05;letter-spacing:-.01em}
h2{font-family:Lora,serif;font-weight:700;font-size:46px;line-height:1.08;letter-spacing:-.01em}
.sub{font-size:19px;line-height:1.5;color:#5E554C}
.win{background:#fff;border-radius:14px;box-shadow:0 30px 60px -20px rgba(60,40,20,.28),0 0 0 1px rgba(60,40,20,.08);
     overflow:hidden}
.bar{height:34px;background:#F3EFEA;display:flex;align-items:center;gap:7px;padding:0 14px;border-bottom:1px solid #E8E1D8}
.bar i{width:11px;height:11px;border-radius:50%;background:#DDD3C7;display:block}
.pg{padding:22px 28px}
.ptitle{font-size:26px;font-weight:700;display:flex;gap:10px;align-items:center;margin-bottom:6px}
.sec{font-size:17px;font-weight:700;margin:16px 0 8px;display:flex;gap:8px;align-items:center}
.tabs{display:flex;gap:16px;font-size:13px;color:#8A8178;border-bottom:1px solid #EEE8E1;margin-bottom:8px}
.tabs span{padding:6px 0}.tabs .on{color:#1F1B16;font-weight:600;border-bottom:2px solid #1F1B16}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;font-weight:500;color:#8A8178;padding:7px 8px;border-bottom:1px solid #EEE8E1;white-space:nowrap}
td{padding:9px 8px;border-bottom:1px solid #F3EEE8;white-space:nowrap}
.chip{display:inline-block;padding:2px 8px;border-radius:5px;font-size:12.5px;font-weight:500}
.muted{color:#8A8178}
.callout{background:#FBF3DD;border-radius:8px;padding:10px 14px;font-size:14px;display:flex;gap:10px}
.week{display:grid;grid-template-columns:repeat(7,1fr);border:1px solid #EEE8E1;border-radius:8px;overflow:hidden}
.day{border-right:1px solid #EEE8E1;min-height:270px;padding:8px 6px}
.day:last-child{border-right:none}
.dh{font-size:12px;color:#8A8178;margin-bottom:8px;display:flex;justify-content:space-between}
.dh b{color:#1F1B16}
.ev{border-radius:6px;padding:6px 7px;font-size:11.5px;line-height:1.3;margin-bottom:6px}
.ev small{display:block;opacity:.75;font-size:10.5px}
.badge{position:absolute;border-radius:999px;background:var(--a);color:#fff;font-weight:700}
.foot{position:absolute;bottom:26px;left:56px;font-size:13px;color:#8A8178;letter-spacing:.04em}
"""


def esc(s):
    return html.escape(str(s))


def chip(status):
    fg, bg = STATUS_COL[status]
    return f'<span class="chip" style="color:{fg};background:{bg}">{esc(status)}</span>'


def money(x):
    return f"${x:,.0f}"


def simulate(cfg, today):
    """Same math as the Notion formulas, run on the sample data."""
    weeks = cfg["rebook_weeks"]
    svc = {s["name"]: s["price"] for s in cfg["services"]}
    appts = []
    for a in cfg["sample_appointments"]:
        dt = (today + timedelta(days=a["days"])).replace(hour=a["hour"], minute=0)
        price, tip, dep = svc[a["service"]], a.get("tip", 0), a.get("deposit", 0)
        dep_paid = bool(dep) and a["status"] != "Booked"
        if a["status"] == "Completed":
            total = price + tip
        elif a["status"] == "No-show" and dep_paid:
            total = dep
        else:
            total = 0
        bal = price - (dep if dep_paid else 0) if a["status"] in ("Booked", "Confirmed") else 0
        name = cfg["sample_clients"][a["client"]]["name"].replace(" (sample)", "")
        appts.append(dict(a, dt=dt, price=price, tip=tip, dep=dep, dep_paid=dep_paid, total=total,
                          bal=bal, client_name=name, title=f"{name.split()[0]} — {a['service']}"))
    clients = []
    for i, c in enumerate(cfg["sample_clients"]):
        mine = [a for a in appts if a["client"] == i]
        done = [a["dt"] for a in mine if a["status"] == "Completed"]
        nxt = sorted(a["dt"] for a in mine if a["dt"] >= today and a["status"] in ("Booked", "Confirmed"))
        last = max(done) if done else None
        due = last + timedelta(weeks=weeks) if last else None
        status = "📅 Booked" if nxt else ("—" if not due else ("🔔 Reach out" if due <= today else "✅ Not yet"))
        clients.append(dict(name=c["name"].replace(" (sample)", ""), phone=c["phone"], notes=c["notes"],
                            visits=len(done), spent=sum(a["total"] for a in mine), last=last,
                            next=nxt[0] if nxt else None, due=due, status=status))
    return appts, clients


def d(dt, fmt="%b %-d"):
    return dt.strftime(fmt) if dt else ""


def page(cfg, body):
    a, soft = ACCENTS[cfg["slug"]]
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>:root{{--a:{a};--s:{soft}}}{CSS}</style>'
            f'</head><body>{body}<div class="foot">CHAIRSIDE STUDIO · NOTION TEMPLATE</div></body></html>')


def win(inner, w, h, x, y, rot=0):
    return (f'<div class="win" style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px;'
            f'transform:rotate({rot}deg)"><div class="bar"><i></i><i></i><i></i></div>'
            f'<div class="pg">{inner}</div></div>')


def img_hero(cfg, appts, clients, today):
    slug = cfg["slug"]
    monday = today - timedelta(days=today.weekday())
    days = ""
    for i in range(7):
        dt = monday + timedelta(days=i)
        evs = "".join(
            f'<div class="ev" style="background:{STATUS_COL[s][1]};color:{STATUS_COL[s][0]}">'
            f'<small>{t}</small>{esc(n)}</div>'
            for (di, t, n, s) in HERO_WEEK[slug] if di == i)
        days += f'<div class="day"><div class="dh">{dt.strftime("%a")}<b>{dt.day}</b></div>{evs}</div>'
    inner = (f'<div class="ptitle">{cfg["emoji"]} {esc(cfg["product_name"])}</div>'
             f'<div class="callout">👋 <span>{esc(cfg["tagline"])}</span></div>'
             f'<div class="sec">📅 Your week</div>'
             f'<div class="tabs"><span class="on">This week</span><span>Upcoming</span><span>Month</span><span>By status</span></div>'
             f'<div class="week">{days}</div>')
    body = (f'<div style="position:absolute;left:56px;top:60px;width:520px">'
            f'<div class="kicker">Notion template for {COPY[slug]["who"]}</div>'
            f'<h1 style="margin-top:16px">{esc(cfg["product_name"])}</h1>'
            f'<p class="sub" style="margin-top:18px">Bookings, deposits, rebooks and income. '
            f'One page you can run from your phone.</p></div>'
            + win(inner, 1000, 530, 150, 290)
            + '<div class="badge" style="right:60px;top:70px;width:150px;height:150px;display:flex;'
              'flex-direction:column;align-items:center;justify-content:center;font-size:15px;text-align:center;'
              'transform:rotate(8deg)"><span style="font-size:13px;font-weight:600;opacity:.85">Works on</span>'
              'Notion free plan</div>')
    return page(cfg, body)


def img_clients(cfg, appts, clients, today):
    rows = ""
    for c in clients:
        hi = ' style="background:#FFF8E8"' if "Reach" in c["status"] else ""
        rows += (f'<tr{hi}><td><b>{esc(c["name"])}</b></td><td>{c["status"]}</td>'
                 f'<td class="muted">{d(c["last"])}</td><td class="muted">{d(c["next"])}</td>'
                 f'<td>{c["visits"]}</td><td>{money(c["spent"])}</td>'
                 f'<td class="muted" style="max-width:250px;overflow:hidden;text-overflow:ellipsis">{esc(c["notes"])}</td></tr>')
    inner = (f'<div class="sec" style="margin-top:0">👤 Clients</div>'
             f'<div class="tabs"><span>Reach out</span><span class="on">All clients</span><span>VIPs</span></div>'
             f'<table><tr><th>Client</th><th>Rebook Status</th><th>Last Visit</th><th>Next</th><th>Visits</th>'
             f'<th>Total Spent</th><th>{esc(cfg["notes_label"])}</th></tr>{rows}</table>')
    due = next((c for c in clients if "Reach" in c["status"]), None)
    note = ""
    if due:
        late = (today - due["due"]).days
        note = (f'<div class="win" style="position:absolute;right:70px;top:640px;width:430px;padding:18px 22px;'
                f'font-size:16px;line-height:1.45">🔔 <b>{esc(due["name"].split()[0])}</b> is {late} days past his '
                f'usual {cfg["rebook_weeks"]} weeks and has nothing booked.'
                f'<div class="muted" style="font-size:13px;margin-top:6px">Updates on its own from his visits.</div></div>')
        if cfg["slug"] == "nail_tech":
            note = note.replace(" his ", " her ").replace("from his", "from her")
    body = (f'<div style="position:absolute;left:56px;top:56px;width:900px">'
            f'<div class="kicker">Client book</div><h2 style="margin-top:14px">{esc(COPY[cfg["slug"]]["due"])}</h2>'
            f'<p class="sub" style="margin-top:14px;max-width:760px">{esc(COPY[cfg["slug"]]["due_sub"])}</p></div>'
            + win(inner, 1090, 360, 56, 280) + note)
    return page(cfg, body)


def img_money(cfg, appts, clients, today):
    due = [a for a in appts if a["status"] in ("Booked", "Confirmed") and a["dep"] and not a["dep_paid"]]
    drows = "".join(f'<tr><td><b>{esc(a["title"])}</b></td><td class="muted">{d(a["dt"], "%a %b %-d")}</td>'
                    f'<td>{money(a["dep"])}</td><td>☐</td></tr>' for a in due)
    up = [a for a in appts if a["status"] in ("Booked", "Confirmed")]
    urows = "".join(f'<tr><td><b>{esc(a["title"])}</b></td><td>{chip(a["status"])}</td>'
                    f'<td>{money(a["dep"]) if a["dep"] else "—"}</td><td>{"☑" if a["dep_paid"] else "☐"}</td>'
                    f'<td><b>{money(a["bal"])}</b></td></tr>' for a in up)
    left = (f'<div class="sec" style="margin-top:0">💵 Deposits to collect</div>'
            f'<table><tr><th>Appointment</th><th>Date</th><th>Deposit</th><th>Paid</th></tr>{drows}</table>'
            f'<div class="sec">Upcoming</div>'
            f'<table><tr><th>Appointment</th><th>Status</th><th>Deposit</th><th>Paid</th><th>Balance Due</th></tr>{urows}</table>')
    paid = [a for a in appts if a["status"] in ("Completed", "No-show")]
    earned = sum(a["total"] for a in paid)
    prow = "".join(f'<tr><td>{esc(a["title"])}</td><td>{chip(a["status"])}</td><td><b>{money(a["total"])}</b></td></tr>'
                   for a in sorted(paid, key=lambda a: a["dt"], reverse=True))
    right = (f'<div class="sec" style="margin-top:0">📈 Income</div>'
             f'<div class="tabs"><span>By month</span><span class="on">Earned this month</span></div>'
             f'<div style="font-family:Lora,serif;font-size:64px;font-weight:700;margin:10px 0 2px">{money(earned)}</div>'
             f'<div class="muted" style="font-size:13px;margin-bottom:14px">Completed visits + tips + kept no-show deposits</div>'
             f'<table><tr><th>Appointment</th><th>Status</th><th>Total Paid</th></tr>{prow}</table>')
    body = (f'<div style="position:absolute;left:56px;top:56px;width:1000px">'
            f'<div class="kicker">Money</div><h2 style="margin-top:14px">Deposits and income, worked out for you</h2>'
            f'<p class="sub" style="margin-top:14px;max-width:820px">Tick the deposit when it lands. Balance due, '
            f'totals and monthly income update on their own. No-shows keep their deposit in your numbers.</p></div>'
            + win(left, 600, 520, 56, 290) + win(right, 470, 520, 676, 290))
    return page(cfg, body)


def img_messages(cfg, appts, clients, today):
    msgs = list(cfg["messages"].items())
    blocks = "".join(f'<div style="font-weight:700;font-size:15px;margin:14px 0 6px">{esc(t)}</div>'
                     f'<div style="border-left:3px solid #1F1B16;padding:2px 0 2px 14px;font-size:14.5px;line-height:1.5">'
                     f'{esc(m)}</div>' for t, m in msgs[:4])
    inner = (f'<div class="ptitle">💬 Message Templates</div>'
             f'<div class="callout">✍️ <span>Copy, paste, and swap the {{brackets}} for real details.</span></div>{blocks}')
    phone_msg = msgs[1][1].replace("{name}", "Marcus" if cfg["slug"] == "barber" else "Jasmine") \
        .replace("{date}", "Friday").replace("{deposit}", "10" if cfg["slug"] == "barber" else "20") \
        .replace("{method}", "Cash App").replace("${", "$")
    phone = (f'<div style="position:absolute;right:70px;top:250px;width:330px;height:600px;background:#1F1B16;'
             f'border-radius:44px;padding:14px;box-shadow:0 30px 60px -20px rgba(60,40,20,.4)">'
             f'<div style="background:#F2F2F4;border-radius:32px;height:100%;padding:60px 16px 16px">'
             f'<div style="text-align:center;font-size:12px;color:#888;margin-bottom:16px">Today 9:41 AM</div>'
             f'<div style="margin-left:auto;max-width:85%;background:#2F7AF5;color:#fff;border-radius:18px;'
             f'padding:10px 13px;font-size:14px;line-height:1.4">{esc(phone_msg)}</div>'
             f'<div style="max-width:60%;background:#E3E3E8;border-radius:18px;padding:10px 13px;font-size:14px;'
             f'margin-top:10px">Sent! See you Friday 🙌</div></div></div>')
    body = (f'<div style="position:absolute;left:56px;top:56px;width:720px">'
            f'<div class="kicker">Bonus</div><h2 style="margin-top:14px">Text clients in seconds</h2>'
            f'<p class="sub" style="margin-top:14px">{len(msgs)} ready-to-send messages for bookings, deposits, '
            f'reminders and no-shows. Written for {COPY[cfg["slug"]]["who"]}.</p></div>'
            + win(inner, 690, 560, 56, 280) + phone)
    return page(cfg, body)


def img_included(cfg, appts, clients, today):
    items = [
        ("📅", "Booking calendar", "Week and month views, upcoming list and a status board"),
        ("💵", "Deposits", "See who still owes a deposit and the balance due"),
        ("👤", "Client profiles", f"{cfg['notes_label']}, visits, total spent, no-shows"),
        ("🔔", "Rebook list", f"Who's past {cfg['rebook_weeks']} weeks with nothing booked"),
        ("📈", "Income", "Grouped by month, tips and kept deposits included"),
        ("💬", "Message templates", "Confirmations, deposits, reminders, policies"),
        ("🚀", "Start Here guide", "Set up in about 10 minutes, sample data included"),
    ]
    li = "".join(f'<div style="display:flex;gap:16px;align-items:flex-start;margin-bottom:20px">'
                 f'<div style="font-size:26px;width:40px">{e}</div><div><div style="font-weight:700;font-size:19px">{esc(t)}</div>'
                 f'<div class="muted" style="font-size:15.5px;margin-top:2px">{esc(s)}</div></div></div>' for e, t, s in items)
    steps = [("1", "Buy", "Instant download, no waiting"), ("2", "Open the PDF", "Click the template link inside"),
             ("3", "Duplicate", "Copy it into your free Notion account")]
    st = "".join(f'<div style="display:flex;gap:16px;align-items:center;margin-bottom:26px">'
                 f'<div style="width:48px;height:48px;border-radius:50%;background:var(--a);color:#fff;font-weight:700;'
                 f'font-size:20px;display:flex;align-items:center;justify-content:center">{n}</div>'
                 f'<div><div style="font-weight:700;font-size:19px">{t}</div><div class="muted" style="font-size:15px">{s}</div></div></div>'
                 for n, t, s in steps)
    body = (f'<div style="position:absolute;left:56px;top:56px">'
            f'<div class="kicker">{esc(cfg["product_name"])}</div><h2 style="margin-top:14px">What you get</h2></div>'
            f'<div style="position:absolute;left:56px;top:200px;width:600px">{li}</div>'
            f'<div style="position:absolute;left:720px;top:200px;width:424px;background:var(--s);border-radius:18px;padding:34px 30px">'
            f'<div style="font-family:Lora,serif;font-weight:700;font-size:28px;margin-bottom:26px">How it works</div>{st}'
            f'<div style="font-size:14px;color:#5E554C;line-height:1.5;border-top:1px solid rgba(0,0,0,.1);padding-top:16px">'
            f'Works on phone and computer. Notion doesn\'t send texts by itself; the message templates make it quick to copy and send.</div></div>')
    return page(cfg, body)


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text())
    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    appts, clients = simulate(cfg, today)
    out = HERE / "out" / "images" / cfg["slug"]
    out.mkdir(parents=True, exist_ok=True)
    pages = [("01_hero", img_hero), ("02_clients", img_clients), ("03_money", img_money),
             ("04_messages", img_messages), ("05_included", img_included)]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1200, "height": 900}, device_scale_factor=2)
        for name, fn in pages:
            html_text = fn(cfg, appts, clients, today)
            (out / f"{name}.html").write_text(html_text)
            pg.set_content(html_text)
            pg.wait_for_timeout(150)
            pg.screenshot(path=str(out / f"{name}.png"))
            print("✓", out / f"{name}.png")
        b.close()


if __name__ == "__main__":
    main()
