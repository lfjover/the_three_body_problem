# Chairside Studio — product kit

Run these on your Mac (Python 3). Install once: `pip3 install requests reportlab playwright && python3 -m playwright install chromium`

1. Build a template in your Notion:
   export NOTION_TOKEN=ntn_...
   python3 build_template.py trades/barber.json --parent <PAGE_ID>
   (try `--dry-run` first: no Notion calls, just checks)
2. In Notion: Share -> Publish -> turn on "Allow duplicate as template" -> copy link.
3. Buyer PDF: python3 make_delivery_pdf.py trades/barber.json --link <link>
4. Listing images: python3 make_listing_images.py trades/barber.json

New trade = copy a file in trades/, edit services, notes, messages. Everything else follows.
Outputs land in out/.
