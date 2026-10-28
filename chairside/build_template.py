#!/usr/bin/env python3
"""
Chairside Studio — template builder.

Builds a complete "Client Book" Notion template for one trade from a JSON
config in trades/. One command, no clicking:

  export NOTION_TOKEN=ntn_...            # internal integration token
  python3 build_template.py trades/barber.json --parent <PAGE_ID>

  python3 build_template.py trades/nail_tech.json --dry-run   # no API calls

What it builds under the parent page:
  <emoji> <Product name>          hub page with linked views
    ├─ Today & this week          calendar + upcoming + deposits due
    ├─ Clients                    rebook due, VIPs, all clients
    ├─ Income                     by month, earned this month
    ├─ Message Templates          copy-paste texts for the trade
    ├─ Start Here                 setup guide for buyers
    └─ Databases                  Appointments, Clients, Services (+ sample rows)

After it runs: open the hub page in Notion -> Share -> Publish -> turn on
"Allow duplicate as template", copy the link. That link is the product.

Notion API version 2026-03-11.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.notion.com/v1"
VERSION = "2026-03-11"
HERE = Path(__file__).resolve().parent

STATUSES = [
    ("Booked", "blue"), ("Confirmed", "green"), ("Completed", "gray"),
    ("No-show", "red"), ("Cancelled", "brown"),
]
PAY_METHODS = ["Cash", "Card", "Cash App", "Zelle", "Venmo", "Apple Pay", "Other"]
CLIENT_TAGS = [("New", "blue"), ("Regular", "green"), ("VIP", "yellow"), ("Late often", "orange")]


# ---------------------------------------------------------------------------
# Tiny Notion client (with a dry-run mode that records every request)
# ---------------------------------------------------------------------------

class Notion:
    def __init__(self, token, dry_run, log_path):
        self.dry = dry_run
        self.log = []
        self.log_path = log_path
        self.n = 0
        self.warnings = []
        if not dry_run:
            import requests
            self.s = requests.Session()
            self.s.headers.update({
                "Authorization": f"Bearer {token}",
                "Notion-Version": VERSION,
                "Content-Type": "application/json",
            })

    def _fake_id(self, kind):
        self.n += 1
        return f"dry-{kind}-{self.n:04d}"

    def call(self, method, path, body=None):
        self.log.append({"method": method, "path": path, "body": body})
        if self.dry:
            return self._fake_response(path, body)
        for attempt in range(6):
            r = self.s.request(method, API + path, json=body)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(float(r.headers.get("Retry-After", 1 + attempt)))
                continue
            time.sleep(0.34)  # stay under ~3 requests/second
            if r.status_code >= 400:
                raise NotionError(r.status_code, r.text, method, path)
            return r.json()
        raise NotionError(429, "gave up after retries", method, path)

    def _fake_response(self, path, body):
        if path == "/databases":
            props = (body.get("initial_data_source") or {}).get("properties", {})
            ds = self._fake_id("ds")
            self._fake_props = getattr(self, "_fake_props", {})
            self._fake_props[ds] = {k: f"p{i}" for i, k in enumerate(props)}
            return {"id": self._fake_id("db"), "data_sources": [{"id": ds}]}
        if path.startswith("/data_sources/"):
            ds = path.split("/")[2]
            props = dict(self._fake_props.get(ds, {}))
            for k in (body or {}).get("properties", {}) if body else {}:
                props.setdefault(k, f"p{len(props)}")
            self._fake_props[ds] = props
            return {"id": ds, "properties": {k: {"id": v, "name": k} for k, v in props.items()}}
        if path == "/views":
            return {"id": self._fake_id("view"), "parent": {"database_id": self._fake_id("ldb")}}
        if path == "/pages":
            return {"id": self._fake_id("page"), "url": "https://notion.so/dry-run"}
        return {"id": self._fake_id("obj"), "results": []}

    def save_log(self):
        self.log_path.write_text(json.dumps(self.log, indent=2, ensure_ascii=False))


class NotionError(Exception):
    def __init__(self, status, text, method, path):
        super().__init__(f"{method} {path} -> {status}: {text[:500]}")


# ---------------------------------------------------------------------------
# Block helpers
# ---------------------------------------------------------------------------

def rt(text, bold=False, color="default"):
    return [{"type": "text", "text": {"content": text},
             "annotations": {"bold": bold, "color": color}}]


def para(text, **kw):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(text, **kw)}}


def heading(text, level=2):
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rt(text)}}


def callout(text, emoji="💡", color="gray_background"):
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": rt(text), "icon": {"type": "emoji", "emoji": emoji}, "color": color}}


def bullet(text):
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rt(text)}}


def numbered(text):
    return {"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": rt(text)}}


def divider():
    return {"object": "block", "type": "divider", "divider": {}}


def quote(text):
    return {"object": "block", "type": "quote", "quote": {"rich_text": rt(text)}}


def title_prop(text):
    return {"title": [{"type": "text", "text": {"content": text}}]}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class Builder:
    def __init__(self, cfg, api, parent_id):
        self.c = cfg
        self.api = api
        self.parent = parent_id
        self.ds = {}       # name -> data source id
        self.db = {}       # name -> database id
        self.pid = {}      # (ds name, prop name) -> property id
        self.ok_props = set()

    # -- pages & blocks --------------------------------------------------
    def page(self, parent_page, title, emoji, children=None):
        body = {"parent": {"type": "page_id", "page_id": parent_page},
                "properties": {"title": title_prop(title)},
                "icon": {"type": "emoji", "emoji": emoji}}
        if children:
            body["children"] = children[:100]
        res = self.api.call("POST", "/pages", body)
        if children and len(children) > 100:
            self.append(res["id"], children[100:])
        return res["id"]

    def append(self, block_id, children):
        for i in range(0, len(children), 100):
            self.api.call("PATCH", f"/blocks/{block_id}/children", {"children": children[i:i + 100]})

    # -- databases ---------------------------------------------------------
    def database(self, parent_page, name, emoji, props):
        res = self.api.call("POST", "/databases", {
            "parent": {"type": "page_id", "page_id": parent_page},
            "title": rt(name),
            "icon": {"type": "emoji", "emoji": emoji},
            "is_inline": False,
            "initial_data_source": {"properties": props},
        })
        self.db[name] = res["id"]
        self.ds[name] = res["data_sources"][0]["id"]
        self.ok_props.update((name, p) for p in props)
        return res

    def add_props(self, name, props, optional=False):
        """Add properties one at a time so one bad formula can't sink the build."""
        for pname, pdef in props.items():
            try:
                self.api.call("PATCH", f"/data_sources/{self.ds[name]}", {"properties": {pname: pdef}})
                self.ok_props.add((name, pname))
            except NotionError as e:
                if not optional:
                    raise
                self.api.warnings.append(f"Skipped property '{pname}' on {name}: {e}")

    def load_prop_ids(self, name):
        res = self.api.call("GET", f"/data_sources/{self.ds[name]}")
        for pname, p in res.get("properties", {}).items():
            self.pid[(name, pname)] = p["id"]

    def has(self, name, prop):
        return (name, prop) in self.ok_props

    # -- views -------------------------------------------------------------
    def linked_view(self, page_id, ds_name, view_name, vtype, **extra):
        """First view creates a linked database block on the page."""
        body = {"create_database": {"parent": {"type": "page_id", "page_id": page_id},
                                    "show_data_source_title": False},
                "data_source_id": self.ds[ds_name], "name": view_name, "type": vtype}
        body.update({k: v for k, v in extra.items() if v is not None})
        res = self.api.call("POST", "/views", body)
        return res["parent"]["database_id"]

    def more_view(self, container_db, ds_name, view_name, vtype, **extra):
        body = {"database_id": container_db, "data_source_id": self.ds[ds_name],
                "name": view_name, "type": vtype}
        body.update({k: v for k, v in extra.items() if v is not None})
        try:
            self.api.call("POST", "/views", body)
        except NotionError as e:
            self.api.warnings.append(f"Skipped view '{view_name}': {e}")

    def props_cfg(self, ds_name, names):
        return [{"property_id": self.pid.get((ds_name, n), n), "visible": True}
                for n in names if self.has(ds_name, n)]

    # ---------------------------------------------------------------------
    def build(self):
        c = self.c
        weeks = c["rebook_weeks"]
        notes = c["notes_label"]

        hub = self.page(self.parent, f"{c['emoji']} {c['product_name']}", c["emoji"], [
            callout(f"{c['tagline']} New here? Open 'Start Here' first.", "👋", "yellow_background"),
        ])
        data_page = self.page(hub, "Databases", "🗂️", [
            para("The raw data lives here. You rarely need to open this page; "
                 "everything is linked from the main page. Don't delete these databases.")
        ])

        # 1. Services ------------------------------------------------------
        self.database(data_page, "Services", "🧾", {
            "Service": {"title": {}},
            "Price": {"number": {"format": "dollar"}},
            "Minutes": {"number": {"format": "number"}},
            "Category": {"select": {"options": [{"name": n} for n in c["service_categories"]]}},
            "Active": {"checkbox": {}},
        })

        # 2. Clients -------------------------------------------------------
        client_props = {
            "Client": {"title": {}},
            "Phone": {"phone_number": {}},
            "Email": {"email": {}},
            "Instagram": {"url": {}},
            notes: {"rich_text": {}, "description": c["notes_hint"][:280]},
            "Tags": {"multi_select": {"options": [{"name": n, "color": col} for n, col in CLIENT_TAGS]}},
            "Rebook Every (weeks)": {"number": {"format": "number"},
                                     "description": f"Leave empty to use the default of {weeks} weeks."},
            "Client Since": {"date": {}},
        }
        client_props.update(self.extras(c.get("client_extras", {})))
        self.database(data_page, "Clients", "👤", client_props)

        # 3. Appointments --------------------------------------------------
        appt_props = {
            "Appointment": {"title": {}},
            "Date": {"date": {}},
            "Client": {"relation": {"data_source_id": self.ds["Clients"], "type": "dual_property",
                                    "dual_property": {"synced_property_name": "Appointments"}}},
            "Service": {"relation": {"data_source_id": self.ds["Services"], "type": "single_property",
                                     "single_property": {}}},
            "Status": {"select": {"options": [{"name": n, "color": col} for n, col in STATUSES]}},
            "Price": {"number": {"format": "dollar"}},
            "Deposit": {"number": {"format": "dollar"}},
            "Deposit Paid": {"checkbox": {}},
            "Tip": {"number": {"format": "dollar"}},
            "Payment Method": {"select": {"options": [{"name": n} for n in PAY_METHODS]}},
            "Notes": {"rich_text": {}},
        }
        appt_props.update(self.extras(c.get("appointment_extras", {})))
        self.database(data_page, "Appointments", "📅", appt_props)
        self.ok_props.add(("Clients", "Appointments"))

        # 4. Formulas (added after the relation exists) --------------------
        num = lambda p: f'if(empty(prop("{p}")), 0, prop("{p}"))'
        self.add_props("Appointments", {
            "Total Paid": {"formula": {"expression":
                f'if(prop("Status") == "Completed", {num("Price")} + {num("Tip")}, '
                f'if(prop("Status") == "No-show" and prop("Deposit Paid"), {num("Deposit")}, 0))'}},
            "Balance Due": {"formula": {"expression":
                f'if(prop("Status") == "Booked" or prop("Status") == "Confirmed", '
                f'{num("Price")} - if(prop("Deposit Paid"), {num("Deposit")}, 0), 0)'}},
        }, optional=True)

        done = 'current.prop("Status") == "Completed"'
        self.add_props("Clients", {
            "Visits": {"formula": {"expression": f'prop("Appointments").filter({done}).length()'}},
            "Total Spent": {"formula": {"expression":
                'prop("Appointments").map(current.prop("Total Paid")).sum()'}},
            "No-shows": {"formula": {"expression":
                'prop("Appointments").filter(current.prop("Status") == "No-show").length()'}},
            "Last Visit": {"formula": {"expression":
                f'prop("Appointments").filter({done}).map(current.prop("Date")).sort().last()'}},
            "Next Appointment": {"formula": {"expression":
                'prop("Appointments").filter(current.prop("Date") >= today() and '
                '(current.prop("Status") == "Booked" or current.prop("Status") == "Confirmed"))'
                '.map(current.prop("Date")).sort().first()'}},
        }, optional=True)
        self.add_props("Clients", {
            "Rebook Due": {"formula": {"expression":
                f'if(empty(prop("Last Visit")), prop("Last Visit"), dateAdd(prop("Last Visit"), '
                f'if(empty(prop("Rebook Every (weeks)")), {weeks}, prop("Rebook Every (weeks)")), "weeks"))'}},
        }, optional=True)
        self.add_props("Clients", {
            "Rebook Status": {"formula": {"expression":
                'if(not empty(prop("Next Appointment")), "📅 Booked", '
                'if(empty(prop("Rebook Due")), "—", '
                'if(prop("Rebook Due") <= today(), "🔔 Reach out", "✅ Not yet")))'}},
        }, optional=True)

        for name in ("Services", "Clients", "Appointments"):
            self.load_prop_ids(name)

        # 5. Sample data -----------------------------------------------------
        self.sample_data()

        # 6. Hub page sections with linked views -----------------------------
        self.hub_views(hub)

        # 7. Message templates + Start Here ------------------------------------
        self.page(hub, "Message Templates", "💬", self.message_blocks())
        self.page(hub, "Start Here", "🚀", self.guide_blocks())
        return hub

    def extras(self, spec):
        out = {}
        for name, d in spec.items():
            if "select" in d:
                out[name] = {"select": {"options": [{"name": o} for o in d["select"]]}}
            elif "checkbox" in d:
                out[name] = {"checkbox": {}}
            elif "url" in d:
                out[name] = {"url": {}}
            else:
                out[name] = {"rich_text": {}}
        return out

    # -- sample rows ------------------------------------------------------
    def sample_data(self):
        c = self.c
        svc_ids, svc_price = {}, {}
        for s in c["services"]:
            res = self.api.call("POST", "/pages", {
                "parent": {"type": "data_source_id", "data_source_id": self.ds["Services"]},
                "properties": {
                    "Service": title_prop(s["name"]),
                    "Price": {"number": s["price"]},
                    "Minutes": {"number": s["minutes"]},
                    "Category": {"select": {"name": s["category"]}},
                    "Active": {"checkbox": True},
                }})
            svc_ids[s["name"]] = res["id"]
            svc_price[s["name"]] = s["price"]

        client_ids = []
        since = (datetime.now() - timedelta(days=60)).date().isoformat()
        for cl in c["sample_clients"]:
            props = {
                "Client": title_prop(cl["name"]),
                "Phone": {"phone_number": cl["phone"]},
                c["notes_label"]: {"rich_text": rt(cl["notes"])},
                "Tags": {"multi_select": [{"name": t} for t in cl.get("tags", [])]},
                "Client Since": {"date": {"start": since}},
            }
            for k, v in cl.get("extras", {}).items():
                props[k] = {"select": {"name": v}}
            res = self.api.call("POST", "/pages", {
                "parent": {"type": "data_source_id", "data_source_id": self.ds["Clients"]},
                "properties": props})
            client_ids.append(res["id"])

        now = datetime.now()
        for a in c["sample_appointments"]:
            when = (now + timedelta(days=a["days"])).replace(hour=a["hour"], minute=0, second=0, microsecond=0)
            first = c["sample_clients"][a["client"]]["name"].split(" ")[0]
            props = {
                "Appointment": title_prop(f"{first} — {a['service']}"),
                "Date": {"date": {"start": when.isoformat()}},
                "Client": {"relation": [{"id": client_ids[a["client"]]}]},
                "Service": {"relation": [{"id": svc_ids[a["service"]]}]},
                "Status": {"select": {"name": a["status"]}},
                "Price": {"number": svc_price[a["service"]]},
            }
            if a.get("deposit"):
                props["Deposit"] = {"number": a["deposit"]}
                props["Deposit Paid"] = {"checkbox": a["status"] != "Booked"}
            if a.get("tip"):
                props["Tip"] = {"number": a["tip"]}
                props["Payment Method"] = {"select": {"name": "Card"}}
            self.api.call("POST", "/pages", {
                "parent": {"type": "data_source_id", "data_source_id": self.ds["Appointments"]},
                "properties": props})

    # -- hub views --------------------------------------------------------
    def hub_views(self, hub):
        A, C = "Appointments", "Clients"
        date_id = self.pid.get((A, "Date"), "Date")
        status_id = self.pid.get((A, "Status"), "Status")
        active = {"or": [{"property": "Status", "select": {"equals": "Booked"}},
                         {"property": "Status", "select": {"equals": "Confirmed"}}]}

        self.append(hub, [heading("📅 Your week")])
        week = self.linked_view(hub, A, "This week", "calendar",
            configuration={"type": "calendar", "date_property_id": date_id, "view_range": "week",
                           "properties": self.props_cfg(A, ["Status", "Balance Due"])})
        self.more_view(week, A, "Upcoming", "table",
            filter={"and": [{"property": "Date", "date": {"next_month": {}}}, active]},
            sorts=[{"property": "Date", "direction": "ascending"}],
            configuration={"type": "table", "properties": self.props_cfg(
                A, ["Appointment", "Date", "Client", "Service", "Status", "Deposit", "Deposit Paid", "Balance Due"])})
        self.more_view(week, A, "Month", "calendar",
            configuration={"type": "calendar", "date_property_id": date_id, "view_range": "month"})
        self.more_view(week, A, "By status", "board",
            configuration={"type": "board", "group_by": {"type": "select", "property_id": status_id,
                                                         "sort": {"type": "manual"}}})

        self.append(hub, [heading("💵 Deposits to collect")])
        self.linked_view(hub, A, "Deposits to collect", "table",
            filter={"and": [active, {"property": "Deposit Paid", "checkbox": {"equals": False}},
                            {"property": "Deposit", "number": {"greater_than": 0}}]},
            sorts=[{"property": "Date", "direction": "ascending"}],
            configuration={"type": "table", "properties": self.props_cfg(
                A, ["Appointment", "Date", "Client", "Deposit", "Deposit Paid"])})

        self.append(hub, [heading("👤 Clients")])
        cview = self.props_cfg(C, ["Client", "Phone", "Rebook Status", "Last Visit", "Next Appointment",
                                   "Visits", "Total Spent", self.c["notes_label"]])
        clients = self.linked_view(hub, C, "Reach out", "table",
            filter={"property": "Rebook Status", "formula": {"string": {"equals": "🔔 Reach out"}}}
            if self.has(C, "Rebook Status") else None,
            sorts=[{"property": "Rebook Due", "direction": "ascending"}] if self.has(C, "Rebook Due") else None,
            configuration={"type": "table", "properties": cview})
        self.more_view(clients, C, "All clients", "table",
            sorts=[{"property": "Client", "direction": "ascending"}],
            configuration={"type": "table", "properties": cview})
        self.more_view(clients, C, "VIPs", "gallery",
            filter={"property": "Tags", "multi_select": {"contains": "VIP"}},
            configuration={"type": "gallery", "card_layout": "list",
                           "properties": self.props_cfg(C, ["Phone", "Visits", "Total Spent", self.c["notes_label"]])})

        self.append(hub, [heading("📈 Income")])
        paid = {"or": [{"property": "Status", "select": {"equals": "Completed"}},
                       {"property": "Status", "select": {"equals": "No-show"}}]}
        inc = self.linked_view(hub, A, "By month", "table",
            filter=paid,
            sorts=[{"property": "Date", "direction": "descending"}],
            configuration={"type": "table",
                           "group_by": {"type": "date", "property_id": date_id, "group_by": "month",
                                        "sort": {"type": "descending"}},
                           "properties": self.props_cfg(A, ["Appointment", "Date", "Status", "Total Paid",
                                                            "Tip", "Payment Method"])})
        if self.has(A, "Total Paid"):
            self.more_view(inc, A, "Earned this month", "chart",
                filter={"and": [paid, {"property": "Date", "date": {"this_month": {}}}]},
                configuration={"type": "chart", "chart_type": "number",
                               "value": {"aggregator": "sum",
                                         "property_id": self.pid.get((A, "Total Paid"), "Total Paid")}})
        self.append(hub, [divider(), para("Made by Chairside Studio. Questions? See 'Start Here'.", color="gray")])

    # -- text pages -------------------------------------------------------
    def message_blocks(self):
        b = [callout("Copy, paste, and swap the {brackets} for real details. "
                     "Edit them so they sound like you.", "✍️")]
        for title, text in self.c["messages"].items():
            b += [heading(title, 3), quote(text)]
        return b

    def guide_blocks(self):
        c = self.c
        return [
            callout("Welcome! This takes about 10 minutes to set up.", "🚀", "green_background"),
            heading("1. Set up your services"),
            numbered("Open Databases → Services."),
            numbered("Change the names, prices and minutes to match your menu. Untick 'Active' for anything you stopped offering."),
            heading("2. Add your clients"),
            numbered("Go to Clients on the main page and click New."),
            numbered(f"Fill in name and phone. Use '{c['notes_label']}' for anything you want to remember next time."),
            numbered(f"Rebook reminders default to every {c['rebook_weeks']} weeks. Set 'Rebook Every (weeks)' on a client to change it for them."),
            heading("3. Book appointments"),
            numbered("Click New in 'Your week'. Pick the client and service, set the date and time."),
            numbered("Type the price (copy it from the service), and a deposit if you take one."),
            numbered("When they pay the deposit, tick 'Deposit Paid'. After the visit, set Status to Completed and add the tip."),
            heading("4. What updates on its own"),
            bullet("Total Paid and Balance Due on each appointment."),
            bullet("Visits, Total Spent, No-shows, Last Visit and Next Appointment on each client."),
            bullet("'Reach out' lists clients who are due to rebook and don't have anything booked."),
            bullet("Income groups everything you earned by month. No-shows count their kept deposit."),
            heading("5. Delete the sample data"),
            para("Everything marked (sample) is there so you can see how it works. Delete those clients and appointments when you're ready."),
            heading("Good to know"),
            bullet("Works on Notion's free plan, on phone and computer."),
            bullet("Notion doesn't send texts by itself. Use the Message Templates page to copy and send them quickly."),
            bullet("Your copy is private to your Notion account."),
            divider(),
            para("Chairside Studio • One license per business. Please don't resell or share the template link.", color="gray"),
        ]


# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Build a Chairside Client Book template in Notion")
    p.add_argument("config", help="trade config, e.g. trades/barber.json")
    p.add_argument("--parent", help="ID of the Notion page to build under (shared with your integration)")
    p.add_argument("--dry-run", action="store_true", help="don't call Notion, just write the requests to out/")
    args = p.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    log_path = out / f"requests_{cfg['slug']}.json"

    import os
    token = os.environ.get("NOTION_TOKEN")
    if not args.dry_run and (not token or not args.parent):
        sys.exit("Set NOTION_TOKEN and pass --parent <page id>, or use --dry-run.")

    api = Notion(token, args.dry_run, log_path)
    b = Builder(cfg, api, args.parent or "dry-parent")
    try:
        hub = b.build()
    except NotionError as e:
        api.save_log()
        sys.exit(f"\nBuild stopped: {e}\nRequests so far saved to {log_path}")
    api.save_log()

    print(f"\n✓ Built '{cfg['product_name']}' ({len(api.log)} API calls). Hub page id: {hub}")
    for w in api.warnings:
        print("  ! " + w)
    if not args.dry_run:
        print("\nNext: open the page in Notion → Share → Publish → turn on 'Allow duplicate as template',"
              "\nthen copy the public link and run:"
              f"\n  python3 make_delivery_pdf.py {args.config} --link <public link>")


if __name__ == "__main__":
    main()
