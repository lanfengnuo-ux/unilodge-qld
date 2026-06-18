#!/usr/bin/env python3
"""
UniLodge Queensland — Daily Room Availability Report
Covers 4 properties: Brisbane City, Park Central, South Bank, Toowong
Generates a self-contained Iglu-style HTML report.
Run: python3 update_report.py
"""

import json
import re
import subprocess
from datetime import datetime, date
from pathlib import Path

# ===== Config =====
OUTPUT_DIR = Path(__file__).parent
OUTPUT_FILE = OUTPUT_DIR / "index.html"

BASE_URL = "https://www.reserve.unilodge.com.au"
CHECKIN_DATE = "2026-07-15"

# Property definitions
PROPERTIES = {
    "Brisbane City": {
        "slug": "brisbane-city",
        "subdomain": "www.brisbanecity.reserve.unilodge.com.au",
        "address": "15 Adelaide Street, Brisbane City, Queensland 4000",
        "phone": "+61 7 3137 1500",
        "url": "https://www.unilodge.com.au/student-accommodation-brisbane/brisbane-city",
        "contracts": {
            "Full Year": {"stay_id": "2081", "from": "2026-07-15", "to": "2027-07-09"},
            "Half Year": {"stay_id": "2080", "from": "2026-07-15", "to": "2027-02-08"},
        },
    },
    "Park Central": {
        "slug": "park-central",
        "subdomain": "www.parkcentral.reserve.unilodge.com.au",
        "address": "20 Gillingham Street, Woolloongabba, Queensland 4102",
        "phone": "+61 7 3444 8100",
        "url": "https://www.unilodge.com.au/student-accommodation-brisbane/park-central",
        "contracts": {
            "Full Year": {"stay_id": "1040", "from": "2026-07-15", "to": "2027-06-28"},
            "Half Year": {"stay_id": "1044", "from": "2026-07-15", "to": "2027-01-25"},
        },
    },
    "South Bank": {
        "slug": "south-bank",
        "subdomain": "www.southbank.reserve.unilodge.com.au",
        "address": "125 Colchester Street, South Brisbane, Queensland 4101",
        "phone": "+61 7 3505 5700",
        "url": "https://www.unilodge.com.au/student-accommodation-brisbane/south-bank",
        "contracts": {
            "Full Year": {"stay_id": "2069", "from": "2026-07-15", "to": "2027-07-09"},
            "Half Year": {"stay_id": "2070", "from": "2026-07-15", "to": "2027-02-08"},
        },
    },
    "Toowong": {
        "slug": "toowong",
        "subdomain": "www.toowong.reserve.unilodge.com.au",
        "address": "66 High Street, Toowong, Queensland 4066",
        "phone": "+61 7 3377 9000",
        "url": "https://www.unilodge.com.au/student-accommodation-brisbane/toowong",
        "contracts": {
            "Full Year": {"stay_id": "957", "from": "2026-07-15", "to": "2027-07-05"},
            "Half Year": {"stay_id": "1748", "from": "2026-07-15", "to": "2027-01-22"},
        },
    },
}

# ===== HTTP Fetch =====

def fetch_url(url, timeout=30):
    """Fetch URL using curl."""
    result = subprocess.run(
        ["curl", "-sL", "--max-time", str(timeout),
         "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
         "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
         "-H", "Accept-Language: en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
         url],
        capture_output=True,
        timeout=timeout + 5,
    )
    if result.returncode != 0:
        raise Exception(f"curl failed: {result.stderr.decode()}")
    return result.stdout.decode("utf-8", errors="replace")


def fetch_room_details(subdomain, stay_id, from_date, to_date):
    """Fetch the room selection page for a specific property + stay period."""
    booking_url = f"https://{subdomain}/bookingSearch.html"
    url = (f"{booking_url}?"
           f"id=123x8816752334648537&"
           f"initialQueryString=searchType%3DProperty%26searchId%3D{subdomain}%26siteType%3Dunilodge%26fromDate%3D{CHECKIN_DATE}%26toDate%3D2026-07-16&"
           f"initialSearchType=Property&"
           f"initialSearchId={subdomain}&"
           f"fixedStayId={stay_id}&"
           f"fromDateCustom={from_date}&"
           f"toDateCustom={to_date}&"
           f"category=0&"
           f"noID=noID&"
           f"promoCode=AUHOME&"
           f"agentEmail=AUHOME&"
           f"usePromoCode=AUHOME&"
           f"initialPromoCode=AUHOME")
    return fetch_url(url)


# ===== Parsers =====

def parse_jsonld(html):
    """Extract JSON-LD structured data from HTML."""
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    return None


def check_august_availability(subdomain):
    """Check if this property supports August 2026 start date.
    Looks at the booking choices page to find the maximum selectable date (data-maxstart)
    across ALL stay periods. If ANY stay period allows selecting dates >= 2026-08-01,
    then August start is supported.

    Returns True if August is selectable in the website date picker UI, False otherwise.
    """
    try:
        url = (f"{BASE_URL}/bookingChoicesProperties.html?"
               f"searchType=Property&"
               f"searchId={subdomain}&"
               f"siteType=unilodge&"
               f"fromDate=2026-07-15&"
               f"toDate=2026-07-16&"
               f"promoCode=AUHOME")
        html = fetch_url(url)

        # Find ALL data-maxstart values across all stay periods
        maxstart_dates = re.findall(r'data-maxstart="([^"]*)"', html)

        for ms in maxstart_dates:
            if ms >= "2026-08-01":
                return True
    except Exception as e:
        print(f"      August check error: {e}")

    return False


def parse_grid(html):
    """Extract room availability grid data. Returns dict: room_id -> info."""
    results = {}
    pattern = re.compile(
        r'<div class="choicesRate choicesRateType\d+"\s*'
        r'data-current="[^"]*"\s+'
        r'data-price="([^"]*)"\s+'
        r'data-maxguests="([^"]*)"\s+'
        r'data-waitlist="(true|false)"\s+'
        r'data-search="([^"]*)"',
        re.DOTALL
    )
    for match in pattern.finditer(html):
        price = match.group(1)
        waitlist = match.group(3) == "true"
        search_cat = match.group(4)
        start = match.start()
        context = html[max(0, start - 200):start + 600]
        id_match = re.search(r'value="(\d+)_(\d+)"', context)
        room_id = id_match.group(1) if id_match else None
        title_match = re.search(r'data-val="room_\d+_shortTitle"[^>]*>\s*([^<]+)', context)
        short_title = title_match.group(1).strip() if title_match else ""
        if room_id:
            results[room_id] = {
                "waitlist": waitlist,
                "price": float(price) if price else 0,
                "short_title": short_title,
                "search_category": search_cat,
            }
    return results


def parse_availability_counts(html):
    """Extract room availability counts from the agent-view badges.
    Badges look like: <b style=...>10+&nbsp;Available</b> or <b...>Waitlist Only</b>
    Strategy: find each room by its radio input value (ROOMID_RATEID), then
    look ahead for the nearest availability badge.
    Returns dict: room_id -> int (count)
    """
    results = {}

    # Find all room identifiers: value="ROOMID_RATEID"
    room_positions = []
    for m in re.finditer(r'value="(\d+)_(\d+)"', html):
        room_id = m.group(1)
        if room_id not in results:  # first occurrence per room
            room_positions.append((m.start(), room_id))
            results[room_id] = 0  # default

    # Find all availability badges with their positions
    badge_pattern = re.compile(r'<b[^>]*style="[^"]*"[^>]*>([^<]+)</b>')
    badge_positions = []
    for m in badge_pattern.finditer(html):
        text = m.group(1).strip()
        if 'Available' in text:
            num_match = re.search(r'(\d+)', text)
            count = int(num_match.group(1)) if num_match else 0
            badge_positions.append((m.start(), count))
        elif 'Waitlist' in text:
            badge_positions.append((m.start(), 0))

    # Match each badge to the nearest preceding room_id
    # Badges appear AFTER the room radio input in the HTML
    badge_idx = 0
    for room_pos, room_id in room_positions:
        # Find the first badge after this room position but before the next room
        next_room_pos = room_positions[room_positions.index((room_pos, room_id)) + 1][0] if (room_pos, room_id) != room_positions[-1] else len(html)

        for badge_pos, count in badge_positions[badge_idx:]:
            if room_pos < badge_pos < next_room_pos:
                results[room_id] = count
                badge_idx += 1
                break

    return results


def get_category(room_name):
    """Categorize room by name."""
    if "Twin" in room_name:
        return "Studio Twin Share"
    if "Studio" in room_name:
        return "Studio"
    if "6 Bedroom" in room_name:
        return "6 Bedroom Multi-Share"
    if "5 Bedroom" in room_name:
        return "5 Bedroom Multi-Share"
    if "4 Bedroom" in room_name:
        return "4 Bedroom Multi-Share"
    if "3 Bedroom" in room_name:
        return "3 Bedroom Multi-Share"
    if "2 Bedroom" in room_name:
        return "2 Bedroom"
    if "1 Bedroom" in room_name:
        return "1 Bedroom"
    return "Other"


CAT_ORDER = [
    "Studio", "Studio Twin Share",
    "1 Bedroom", "2 Bedroom",
    "3 Bedroom Multi-Share", "4 Bedroom Multi-Share",
    "5 Bedroom Multi-Share", "6 Bedroom Multi-Share",
    "Other",
]


# ===== Main Fetcher =====

def fetch_property_data(prop_name, prop_config):
    """Fetch all room data for one property."""
    print(f"  [{prop_name}] Fetching...")
    subdomain = prop_config["subdomain"]
    all_contracts = {}

    # Check August availability based on website date picker UI (data-maxstart)
    aug_supported = check_august_availability(subdomain)
    print(f"    August start: {'YES' if aug_supported else 'NO'}")

    for contract_name, contract_info in prop_config["contracts"].items():
        stay_id = contract_info["stay_id"]
        from_date = contract_info["from"]
        to_date = contract_info["to"]

        print(f"    - {contract_name} (stay {stay_id})...")
        try:
            html = fetch_room_details(subdomain, stay_id, from_date, to_date)
        except Exception as e:
            print(f"      ERROR: {e}")
            continue

        jsonld = parse_jsonld(html)
        grid = parse_grid(html)
        counts = parse_availability_counts(html)

        if not jsonld:
            print(f"      WARNING: No JSON-LD data")
            continue

        rooms = []
        for room in jsonld.get("containsPlace", []):
            room_id = room.get("identifier", "")
            room_name = room.get("name", "")
            description = room.get("description", "")
            occupancy = room.get("occupancy", {}).get("value", 1)

            for offer in room.get("offers", []):
                checkin = offer.get("checkinTime", "")
                checkout = offer.get("checkoutTime", "")
                total_price = offer.get("price", 0)

                base_rate, gst = 0, 0
                for comp in offer.get("priceSpecification", {}).get("priceComponent", []):
                    if comp["name"] == "Base rate":
                        base_rate = comp["price"]
                    elif comp["name"] == "GST":
                        gst = comp["price"]

                try:
                    d1 = datetime.strptime(checkin.split("T")[0], "%Y-%m-%d")
                    d2 = datetime.strptime(checkout.split("T")[0], "%Y-%m-%d")
                    days = (d2 - d1).days
                    weeks = days / 7
                    weekly_price = total_price / weeks if weeks > 0 else 0
                except Exception:
                    days, weeks, weekly_price = 0, 0, 0

                grid_info = grid.get(room_id, {})
                is_waitlist = grid_info.get("waitlist", False)
                short_title = grid_info.get("short_title", room_name)
                grid_price = grid_info.get("price", 0)
                room_count = counts.get(room_id, 0)
                august_ok = aug_supported

                rooms.append({
                    "id": room_id,
                    "name": room_name,
                    "short_title": short_title,
                    "description": description,
                    "occupancy": occupancy,
                    "checkin": checkin,
                    "checkout": checkout,
                    "days": days,
                    "weeks": round(weeks, 1),
                    "total_price": total_price,
                    "weekly_price": int(round(weekly_price)),
                    "base_rate": base_rate,
                    "gst": gst,
                    "is_waitlist": is_waitlist,
                    "grid_price": grid_price,
                    "room_count": room_count,
                    "august_available": august_ok,
                    "category": get_category(room_name),
                })

        rooms.sort(key=lambda r: r["weekly_price"])
        all_contracts[contract_name] = rooms

    return all_contracts


# ===== HTML Generator =====

def generate_html(all_data):
    """Generate Iglu-style self-contained HTML for all properties."""
    now = datetime.now()
    update_time_display = now.strftime("%Y年%m月%d日 %H:%M")
    update_time_iso = now.strftime("%Y-%m-%d %H:%M")

    prop_order = ["Brisbane City", "Park Central", "South Bank", "Toowong"]
    prop_slugs = {p: PROPERTIES[p]["slug"] for p in prop_order}

    # ---- Build property tabs ----
    prop_tabs_html = ""
    for i, prop_name in enumerate(prop_order):
        if prop_name not in all_data:
            continue
        slug = prop_slugs[prop_name]
        active = " active" if i == 0 else ""
        total_rooms = sum(
            len(contract_rooms)
            for contract_rooms in all_data[prop_name].values()
        ) // max(1, len(all_data[prop_name]))
        prop_tabs_html += f"""<button class="prop-btn{active}" data-slug="{slug}" onclick="switchProp('{slug}')">{prop_name}<span class="count">{total_rooms}</span></button>
        """

    # ---- Build property panels ----
    panels_html = ""
    for i, prop_name in enumerate(prop_order):
        if prop_name not in all_data:
            continue
        slug = prop_slugs[prop_name]
        prop_config = PROPERTIES[prop_name]
        active = " active" if i == 0 else ""
        contract_data = all_data[prop_name]

        # Contract sub-tabs
        contract_names = list(contract_data.keys())
        sub_tabs_html = ""
        for j, cname in enumerate(contract_names):
            c_active = " active" if j == 0 else ""
            sub_tabs_html += f"""<button class="sub-tab{c_active}" data-contract="{cname}" data-prop="{slug}" onclick="switchContract('{slug}','{cname}')">{cname}<span class="count">{len(contract_data[cname])}</span></button>
            """

        # Contract panels
        contract_panels_html = ""
        for j, cname in enumerate(contract_names):
            c_active = " active" if j == 0 else ""
            rooms = contract_data[cname]
            avail = sum(1 for r in rooms if not r["is_waitlist"])
            wl = sum(1 for r in rooms if r["is_waitlist"])

            # Group by category
            cats = {}
            for r in rooms:
                cat = r["category"]
                if cat not in cats:
                    cats[cat] = []
                cats[cat].append(r)

            # Find contract dates from config
            contract_info = prop_config["contracts"].get(cname, {})
            c_from = contract_info.get("from", CHECKIN_DATE)
            c_to = contract_info.get("to", "")

            rows_html = ""
            for cat in CAT_ORDER:
                if cat not in cats:
                    continue
                rows_html += f"""<tr class="cat-divider"><td colspan="8"><span class="cat-label">{cat}</span></td></tr>"""
                for room in cats[cat]:
                    wl = room["is_waitlist"]
                    rc = "row-ok" if not wl else "row-warn"
                    tc = "tag-ok" if not wl else "tag-warn"
                    tt = "有房" if not wl else "等位"
                    count_val = room.get("room_count", 0)
                    if wl:
                        inventory_cell = f'<span class="tag {tc}">{tt}</span>'
                    else:
                        if count_val >= 10:
                            count_str = f"{count_val}+"
                        else:
                            count_str = str(count_val)
                        inventory_cell = f'<span class="count-num">{count_str}</span> <span class="tag {tc}">{tt}</span>'
                    aug_ok = room.get("august_available", False)
                    aug_display = '<span style="color:var(--green);font-weight:600">是</span>' if aug_ok else '<span style="color:var(--text-muted)">否</span>'
                    rows_html += f"""<tr class="{rc}"><td><span class="room-name">{room['name']}</span></td><td>{room['occupancy']}人</td><td><span class="price">${room['weekly_price']:,}</span></td><td><span class="price">${room['total_price']:,.2f}</span></td><td>{room['days']}天</td><td>{inventory_cell}</td><td>{aug_display}</td><td>{c_from}</td></tr>"""

            contract_panels_html += f"""
                <div class="sub-panel{c_active}" data-contract="{cname}" data-prop="{slug}">
                    <div class="table-wrap fade-in">
                        <table>
                            <thead><tr><th>房型</th><th>入住</th><th>周租金</th><th>总租金 (含GST)</th><th>合同期</th><th>库存</th><th>8月份</th><th>起租日期</th></tr></thead>
                            <tbody>{rows_html}</tbody>
                        </table>
                    </div>
                    <div class="panel-summary">📅 {c_from} → {c_to} &ensp;|&ensp; 共 {len(rooms)} 种房型 &ensp;|&ensp; <span class="stat-ok">可预订 {avail}</span> &ensp;|&ensp; <span class="stat-warn">等位 {wl}</span></div>
                </div>"""

        panels_html += f"""
    <div class="prop-panel{active}" id="prop-{slug}">
        <div class="sub-tabs">{sub_tabs_html}</div>
        {contract_panels_html}
    </div>"""

    # ---- Summary stats ----
    total_avail = 0
    total_wl = 0
    total_types = 0
    prop_count = 0
    for prop_name in prop_order:
        if prop_name not in all_data:
            continue
        prop_count += 1
        first_contract = list(all_data[prop_name].values())[0] if all_data[prop_name] else []
        total_avail += sum(1 for r in first_contract if not r["is_waitlist"])
        total_wl += sum(1 for r in first_contract if r["is_waitlist"])
        total_types += len(first_contract)

    # ---- Full HTML ----
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>UniLodge Queensland — 空房日报</title>
<link href="https://api.fontshare.com/v2/css?f[]=satoshi@400,500,600,700&display=swap" rel="stylesheet">
<style>
    :root {{
        --bg: #fafaf9;
        --card-bg: #fff;
        --text: #1a1a1a;
        --text-muted: #6b7280;
        --border: #e5e4e1;
        --green: #059669; --green-bg: #ecfdf5;
        --amber: #d97706; --amber-bg: #fffbeb;
        --red: #dc2626; --red-bg: #fef2f2;
        --radius: 10px;
        --font: 'Satoshi', system-ui, -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
    }}
    @media (prefers-color-scheme: dark) {{
        :root {{
            --bg: #0c0c0c;
            --card-bg: #161616;
            --text: #e5e5e5;
            --text-muted: #8b8b8b;
            --border: #262626;
        }}
        .cat-divider td {{ background: #1a1a1a !important; }}
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ font-family: var(--font); -webkit-font-smoothing: antialiased; background: var(--bg); color: var(--text); }}
    body {{ max-width: 1050px; margin: 0 auto; padding: 32px 20px 60px; line-height: 1.6; }}

    /* Header */
    .header {{ margin-bottom: 24px; }}
    .header-top {{ display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 4px; }}
    .header h1 {{ font-size: clamp(1.2rem, 3vw, 1.5rem); font-weight: 700; letter-spacing: -0.025em; display: flex; align-items: center; gap: 8px; }}
    .header h1 .dot {{ width: 10px; height: 10px; border-radius: 50%; background: #E21836; flex-shrink: 0; }}
    .header .meta {{ color: var(--text-muted); font-size: 0.8rem; line-height: 1.7; }}

    /* Property nav */
    .prop-nav {{ display: flex; gap: 6px; margin-bottom: 22px; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; }}
    .prop-nav::-webkit-scrollbar {{ display: none; }}
    .prop-btn {{ flex-shrink: 0; padding: 9px 18px; border-radius: 8px; cursor: pointer; font-size: 0.84rem; font-weight: 600; color: var(--text-muted); border: 1px solid var(--border); background: var(--card-bg); font-family: var(--font); transition: all 200ms cubic-bezier(0.32,0.72,0,1); white-space: nowrap; letter-spacing: -0.01em; }}
    .prop-btn:hover {{ color: var(--text); border-color: var(--text-muted); }}
    .prop-btn.active {{ background: var(--text); color: var(--bg); border-color: var(--text); }}
    .prop-btn .count {{ font-size: 0.68rem; opacity: 0.5; margin-left: 3px; font-weight: 400; }}

    /* Sub tabs */
    .sub-tabs {{ display: flex; gap: 4px; margin-bottom: 16px; background: var(--card-bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 4px; width: fit-content; }}
    .sub-tab {{ padding: 7px 16px; border-radius: 7px; cursor: pointer; font-size: 0.83rem; font-weight: 500; color: var(--text-muted); border: none; background: none; font-family: var(--font); transition: all 200ms cubic-bezier(0.32,0.72,0,1); white-space: nowrap; }}
    .sub-tab:hover {{ color: var(--text); }}
    .sub-tab.active {{ background: var(--bg); color: var(--text); box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
    .sub-tab .count {{ font-size: 0.66rem; opacity: 0.45; margin-left: 4px; font-weight: 400; }}

    /* Table */
    .table-wrap {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }}
    .table-wrap table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
    .table-wrap th {{ text-align: left; padding: 12px 16px; font-weight: 600; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-muted); background: var(--bg); border-bottom: 1px solid var(--border); white-space: nowrap; }}
    .table-wrap td {{ padding: 12px 16px; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }}
    .table-wrap tr:last-child td {{ border-bottom: none; }}
    .table-wrap tbody tr {{ transition: background 200ms cubic-bezier(0.32,0.72,0,1); }}
    .table-wrap tbody tr:hover {{ background: var(--bg); }}

    .cat-divider td {{ padding: 8px 16px !important; background: var(--bg); font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-muted); border-bottom: 1px solid var(--border); }}

    .row-ok  {{ box-shadow: inset 3px 0 0 var(--green); }}
    .row-warn {{ box-shadow: inset 3px 0 0 var(--amber); }}

    .tag {{ display: inline-flex; align-items: center; gap: 5px; padding: 4px 12px; border-radius: 99px; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }}
    .tag::before {{ content: ''; width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }}
    .tag-ok   {{ background: var(--green-bg); color: var(--green); }}
    .tag-ok::before   {{ background: var(--green); }}
    .tag-warn {{ background: var(--amber-bg); color: var(--amber); }}
    .tag-warn::before {{ background: var(--amber); }}

    .price {{ font-weight: 600; }}
    .room-name {{ font-weight: 600; }}
    .count-num {{ font-weight: 700; font-size: 0.9rem; color: var(--text); font-variant-numeric: tabular-nums; }}

    .prop-panel {{ display: none; }}
    .prop-panel.active {{ display: block; }}
    .sub-panel {{ display: none; }}
    .sub-panel.active {{ display: block; }}

    .panel-summary {{ margin-top: 12px; font-size: 0.8rem; color: var(--text-muted); }}
    .stat-ok {{ color: var(--green); font-weight: 600; }}
    .stat-warn {{ color: var(--amber); font-weight: 600; }}

    .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border); }}
    .footer-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr)); gap: 14px; }}
    .footer-card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 18px; }}
    .footer-card h3 {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-muted); margin-bottom: 8px; font-weight: 600; }}
    .footer-card p, .footer-card li {{ font-size: 0.82rem; line-height: 1.7; }}
    .footer-card ul {{ list-style: none; padding: 0; }}
    .footer-card li::before {{ content: "— "; color: var(--text-muted); }}

    .fade-in {{ opacity: 0; transform: translateY(8px); animation: fadeIn 500ms cubic-bezier(0.32,0.72,0,1) forwards; }}
    @keyframes fadeIn {{ to {{ opacity: 1; transform: translateY(0); }} }}

    @media (max-width: 768px) {{
        body {{ padding: 20px 12px 50px; }}
        .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
        .table-wrap table {{ min-width: 620px; }}
        .header-top {{ flex-direction: column; }}
        .prop-nav, .sub-tabs {{ overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; width: 100%; }}
        .prop-nav::-webkit-scrollbar, .sub-tabs::-webkit-scrollbar {{ display: none; }}
    }}
</style>
</head>
<body>

<div class="header fade-in" style="animation-delay:0ms">
    <div class="header-top">
        <h1><span class="dot"></span>UniLodge Queensland 空房日报</h1>
    </div>
    <p class="meta">📍 Brisbane, Queensland — {prop_count} 所公寓 &ensp;|&ensp; 更新于 {update_time_display} &ensp;|&ensp; 🎯 起租: {CHECKIN_DATE} &ensp;|&ensp; 每日 10:00 / 15:00 自动刷新</p>
</div>

<nav class="prop-nav fade-in" style="animation-delay:60ms" id="prop-nav">{prop_tabs_html}</nav>

{panels_html}

<div class="footer fade-in" style="animation-delay:300ms">
    <div class="footer-grid">
        <div class="footer-card">
            <h3>房源概况</h3>
            <ul>
                <li>{prop_count} 所 UniLodge Queensland 公寓</li>
                <li>共 {total_types} 种房型 (Full Year)</li>
                <li>可预订 {total_avail} · 等位 {total_wl}</li>
                <li>起租日期统一为 {CHECKIN_DATE}</li>
            </ul>
        </div>
        <div class="footer-card">
            <h3>注意事项</h3>
            <ul>
                <li>价格均为澳元 (AUD)，已含 GST</li>
                <li>候补（等位）= 当前无房，可排队等待</li>
                <li>Full Year 和 Half Year 为固定学期合同</li>
                <li>周租金为总价÷合同天数×7估算</li>
            </ul>
        </div>
        <div class="footer-card">
            <h3>数据来源</h3>
            <ul>
                <li>UniLodge 官方预订系统</li>
                <li>reserve.unilodge.com.au</li>
                <li>macOS launchd 每日自动抓取</li>
                <li>生成时间: {update_time_iso}</li>
            </ul>
        </div>
    </div>
    <p style="color:var(--text-muted);font-size:0.74rem;margin-top:20px;text-align:center">UniLodge Queensland · 仅供内部参考 · {update_time_display}</p>
</div>

<script>
function switchProp(slug) {{
    document.querySelectorAll('.prop-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.prop-panel').forEach(p => p.classList.remove('active'));
    var btn = document.querySelector('.prop-btn[data-slug="' + slug + '"]');
    if (btn) btn.classList.add('active');
    var panel = document.getElementById('prop-' + slug);
    if (panel) {{
        panel.classList.add('active');
        // Activate first sub-tab
        var firstSub = panel.querySelector('.sub-tab');
        if (firstSub) firstSub.click();
    }}
}}

function switchContract(propSlug, contractName) {{
    var panel = document.getElementById('prop-' + propSlug);
    if (!panel) return;
    panel.querySelectorAll('.sub-tab').forEach(t => t.classList.remove('active'));
    panel.querySelectorAll('.sub-panel').forEach(p => p.classList.remove('active'));
    var subBtn = panel.querySelector('.sub-tab[data-contract="' + contractName + '"]');
    if (subBtn) subBtn.classList.add('active');
    var subPanel = panel.querySelector('.sub-panel[data-contract="' + contractName + '"]');
    if (subPanel) subPanel.classList.add('active');
}}
</script>

</body>
</html>"""
    return html


# ===== Main =====

def main():
    print("=" * 60)
    print("UniLodge Queensland — Daily Room Report Generator")
    print(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    all_data = {}

    for prop_name in ["Brisbane City", "Park Central", "South Bank", "Toowong"]:
        prop_config = PROPERTIES[prop_name]
        try:
            data = fetch_property_data(prop_name, prop_config)
            if data:
                all_data[prop_name] = data
                first_contract = list(data.keys())[0] if data else ""
                room_count = len(data[first_contract]) if first_contract else 0
                avail = sum(1 for r in data[first_contract] if not r["is_waitlist"])
                wl = sum(1 for r in data[first_contract] if r["is_waitlist"])
                print(f"  ✓ {prop_name}: {room_count} types, {avail} avail, {wl} waitlist")
            else:
                print(f"  ✗ {prop_name}: No data")
        except Exception as e:
            print(f"  ✗ {prop_name}: ERROR - {e}")

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Generating HTML report...")
    html = generate_html(all_data)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Report saved to: {OUTPUT_FILE}")
    print(f"\n✅ Done! Open {OUTPUT_FILE} in your browser.")


if __name__ == "__main__":
    main()
