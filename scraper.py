#!/usr/bin/env python3
"""
UniLodge Queensland — Daily Room Availability Report
Covers 4 properties: Brisbane City, Park Central, South Bank, Toowong
Scrapes ALL stay periods (租期) from the booking site and matches them to a
student's check-in date via a dropdown filter.
Run: python3 scraper.py
"""

import json
import re
import subprocess
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

# ===== Config =====
OUTPUT_DIR = Path(__file__).parent
OUTPUT_FILE = OUTPUT_DIR / "index.html"
HISTORY_FILE = OUTPUT_DIR / "previous_data.json"

BASE_URL = "https://www.reserve.unilodge.com.au"
# Initial search date used on the "select stay period" page (any valid date works)
SEARCH_DATE = "2026-07-15"

# Property definitions
PROPERTIES = {
    "Brisbane City": {
        "slug": "brisbane-city",
        "subdomain": "www.brisbanecity.reserve.unilodge.com.au",
        "address": "15 Adelaide Street, Brisbane City, Queensland 4000",
        "phone": "+61 7 3137 1500",
        "url": "https://www.unilodge.com.au/student-accommodation-brisbane/brisbane-city",
    },
    "Park Central": {
        "slug": "park-central",
        "subdomain": "www.parkcentral.reserve.unilodge.com.au",
        "address": "20 Gillingham Street, Woolloongabba, Queensland 4102",
        "phone": "+61 7 3444 8100",
        "url": "https://www.unilodge.com.au/student-accommodation-brisbane/park-central",
    },
    "South Bank": {
        "slug": "south-bank",
        "subdomain": "www.southbank.reserve.unilodge.com.au",
        "address": "125 Colchester Street, South Brisbane, Queensland 4101",
        "phone": "+61 7 3505 5700",
        "url": "https://www.unilodge.com.au/student-accommodation-brisbane/south-bank",
    },
    "Toowong": {
        "slug": "toowong",
        "subdomain": "www.toowong.reserve.unilodge.com.au",
        "address": "66 High Street, Toowong, Queensland 4066",
        "phone": "+61 7 3377 9000",
        "url": "https://www.unilodge.com.au/student-accommodation-brisbane/toowong",
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
    try:
        next_day = (datetime.strptime(from_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:
        next_day = to_date
    url = (f"{booking_url}?"
           f"id=123x8816752334648537&"
           f"initialQueryString=searchType%3DProperty%26searchId%3D{subdomain}%26siteType%3Dunilodge%26fromDate%3D{from_date}%26toDate%3D{next_day}&"
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


def parse_stay_periods(html):
    """Extract all stay periods (租期/contracts) from the booking choices page.

    Each `.choicesRate` div carries a name (data-stayperiod) and a radio
    `fixedStayId` value, plus a `.choicesDatepicker` whose data attributes
    describe the check-in window (data-min → data-maxstart) and checkout
    window (data-minend → data-max).

    Returns a list of dicts:
      {name, stay_id, checkin_min, checkin_max, checkout_min, checkout_max}
    """
    periods = []
    for m in re.finditer(r'<div class="choicesRate choicesRateType\d+"[^>]*data-stayperiod="([^"]*)"', html):
        name = m.group(1).strip()
        block = html[m.start():m.start() + 4500]
        stay_m = re.search(r'name="fixedStayId"[^>]*value="(\d+)"', block)
        dp_m = re.search(r'class="choicesDatepicker"[^>]*>', block)
        if not stay_m or not dp_m:
            continue
        dp = dp_m.group(0)

        def _g(attr):
            mm = re.search(attr + r'="(\d{4}-\d{2}-\d{2})"', dp)
            return mm.group(1) if mm else ""

        cin_min = _g('data-min')
        cin_max = _g('data-maxstart')
        cout_min = _g('data-minend')
        cout_max = _g('data-max')
        if not cin_min or not cin_max:
            continue
        periods.append({
            "name": name,
            "stay_id": stay_m.group(1),
            "checkin_min": cin_min,
            "checkin_max": cin_max,
            "checkout_min": cout_min,
            "checkout_max": cout_max,
        })
    return periods


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
    Returns dict: room_id -> int (count)
    """
    results = {}

    room_positions = []
    for m in re.finditer(r'value="(\d+)_(\d+)"', html):
        room_id = m.group(1)
        if room_id not in results:
            room_positions.append((m.start(), room_id))
            results[room_id] = 0

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

    badge_idx = 0
    for room_pos, room_id in room_positions:
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


def category_key(category):
    """Map a room category to a simplified filter key."""
    if "Studio" in category:
        return "studio"
    if "1 Bedroom" in category:
        return "one"
    if "2 Bedroom" in category:
        return "two"
    if "Multi-Share" in category:
        return "multi"
    return "other"


def safe_attr(s):
    """Strip characters that would break an HTML data-* attribute."""
    return re.sub(r'["<>]', ' ', str(s))


def contract_slug(name):
    """Stable slug for a stay-period name (used as JS/data-attr key)."""
    return re.sub(r'[^a-zA-Z0-9]+', '-', str(name)).strip('-').lower()


def fmt_cn_date(iso):
    """'2026-08-19' -> '8月19日'"""
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{d.month}月{d.day}日"
    except Exception:
        return iso


CAT_ORDER = [
    "Studio", "Studio Twin Share",
    "1 Bedroom", "2 Bedroom",
    "3 Bedroom Multi-Share", "4 Bedroom Multi-Share",
    "5 Bedroom Multi-Share", "6 Bedroom Multi-Share",
    "Other",
]


# ===== Main Fetcher =====

def fetch_property_data(prop_name, prop_config):
    """Fetch all stay periods (租期) and their rooms for one property."""
    print(f"  [{prop_name}] Fetching stay periods...")
    subdomain = prop_config["subdomain"]
    choices_url = (f"{BASE_URL}/bookingChoicesProperties.html?"
                   f"searchType=Property&searchId={subdomain}&siteType=unilodge&"
                   f"fromDate={SEARCH_DATE}&toDate=2026-07-16&promoCode=AUHOME")
    choices_html = fetch_url(choices_url)
    periods = parse_stay_periods(choices_html)
    print(f"    Found {len(periods)} stay periods")

    stay_data = {}
    for p in periods:
        name = p["name"]
        stay_id = p["stay_id"]
        cin = p["checkin_min"]
        cout = p["checkout_min"] or p["checkin_min"]
        print(f"    - {name} (stay {stay_id}, 起租 {cin}~{p['checkin_max']})")
        try:
            html = fetch_room_details(subdomain, stay_id, cin, cout)
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
                    "category": get_category(room_name),
                })

        rooms.sort(key=lambda r: r["weekly_price"])
        stay_data[name] = {
            "checkin_min": p["checkin_min"],
            "checkin_max": p["checkin_max"],
            "checkout_min": p["checkout_min"],
            "checkout_max": p["checkout_max"],
            "rooms": rooms,
        }

    return stay_data


# ===== Persistence (new / price-drop tracking) =====

def load_previous_data():
    """Load previous scrape data. Returns {room_key: {weekly_price, is_waitlist, first_seen}}."""
    if not HISTORY_FILE.exists():
        return {}
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('rooms', {})
    except (json.JSONDecodeError, KeyError, IOError):
        return {}


def save_previous_data(all_data):
    """Save current rooms as previous data for next comparison."""
    rooms = {}
    for prop_name, contracts in all_data.items():
        slug = PROPERTIES[prop_name]["slug"]
        for cname, stay in contracts.items():
            cslug = contract_slug(cname)
            for r in stay["rooms"]:
                key = f"{slug}:{cslug}:{r['id']}"
                rooms[key] = {
                    "weekly_price": r.get("weekly_price", 0),
                    "is_waitlist": r.get("is_waitlist", False),
                    "first_seen": r.get("_first_seen", datetime.now().strftime('%Y-%m-%d')),
                }
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump({"rooms": rooms, "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M')}, f, ensure_ascii=False)


# ===== HTML Generator =====

def generate_html(all_data):
    """Generate Iglu-style self-contained HTML for all properties."""
    now = datetime.now()
    update_time_display = now.strftime("%Y年%m月%d日 %H:%M")
    update_time_iso = now.strftime("%Y-%m-%d %H:%M")

    prop_order = ["Brisbane City", "Park Central", "South Bank", "Toowong"]
    prop_slugs = {p: PROPERTIES[p]["slug"] for p in prop_order}

    # ---- Build the global check-in date dropdown (union of all windows) ----
    all_dates = set()
    for prop_name in prop_order:
        if prop_name not in all_data:
            continue
        for stay in all_data[prop_name].values():
            try:
                d1 = datetime.strptime(stay["checkin_min"], "%Y-%m-%d")
                d2 = datetime.strptime(stay["checkin_max"], "%Y-%m-%d")
                cur = d1
                while cur <= d2:
                    all_dates.add(cur)
                    cur += timedelta(days=1)
            except Exception:
                pass
    date_options = "".join(
        f'<option value="{d.strftime("%Y-%m-%d")}">{fmt_cn_date(d.strftime("%Y-%m-%d"))}</option>'
        for d in sorted(all_dates)
    )

    # ---- Build property tabs ----
    prop_tabs_html = ""
    for i, prop_name in enumerate(prop_order):
        if prop_name not in all_data:
            continue
        slug = prop_slugs[prop_name]
        active = " active" if i == 0 else ""
        stay_count = len(all_data[prop_name])
        prop_tabs_html += f"""<button class="prop-btn{active}" data-slug="{slug}" onclick="switchProp('{slug}')">{prop_name}<span class="count">{stay_count} 租期</span></button>
        """

    # ---- Build property panels ----
    panels_html = ""
    for i, prop_name in enumerate(prop_order):
        if prop_name not in all_data:
            continue
        slug = prop_slugs[prop_name]
        active = " active" if i == 0 else ""
        contract_data = all_data[prop_name]

        # Contract sub-tabs
        sub_tabs_html = ""
        for j, (cname, stay) in enumerate(contract_data.items()):
            c_active = " active" if j == 0 else ""
            cslug = contract_slug(cname)
            cin_min = stay["checkin_min"]
            cin_max = stay["checkin_max"]
            nrooms = len(stay["rooms"])
            sub_tabs_html += f"""<button class="sub-tab{c_active}" data-contract="{cslug}" data-prop="{slug}" data-window-min="{cin_min}" data-window-max="{cin_max}" title="{safe_attr(cname)} · 起租 {fmt_cn_date(cin_min)}~{fmt_cn_date(cin_max)}" onclick="switchContract('{slug}','{cslug}')">{safe_attr(cname)}<span class="count">{nrooms}</span></button>
            """

        # Contract panels
        contract_panels_html = ""
        for j, (cname, stay) in enumerate(contract_data.items()):
            c_active = " active" if j == 0 else ""
            cslug = contract_slug(cname)
            cin_min = stay["checkin_min"]
            cin_max = stay["checkin_max"]
            cout_min = stay["checkout_min"]
            rooms = stay["rooms"]
            avail = sum(1 for r in rooms if not r["is_waitlist"])
            wl = sum(1 for r in rooms if r["is_waitlist"])

            key = f"{slug}-{cslug}"

            # Group by category
            cats = {}
            for r in rooms:
                cat = r["category"]
                cats.setdefault(cat, []).append(r)

            rows_html = ""
            for cat in CAT_ORDER:
                if cat not in cats:
                    continue
                rows_html += f"""<tr class="cat-divider"><td colspan="6"><span class="cat-label">{cat}</span></td></tr>"""
                for room in cats[cat]:
                    wl_room = room["is_waitlist"]
                    rc = "row-ok" if not wl_room else "row-warn"
                    tc = "tag-ok" if not wl_room else "tag-warn"
                    tt = "有房" if not wl_room else "等位"
                    count_val = room.get("room_count", 0)
                    if wl_room:
                        inventory_cell = f'<span class="tag {tc}">{tt}</span>'
                    else:
                        count_str = f"{count_val}+" if count_val >= 10 else str(count_val)
                        inventory_cell = f'<span class="count-num">{count_str}</span> <span class="tag {tc}">{tt}</span>'

                    price_badges = ""
                    if room.get("is_new"):
                        price_badges += ' <span class="badge badge-new">🆕 新上</span>'
                    if room.get("price_drop"):
                        price_badges += f' <span class="badge badge-drop">🔻 -${room["price_drop"]}</span>'

                    search_text = safe_attr(f"{room['name']} {room['short_title']} {room['category']} {room['occupancy']}人").lower()
                    cat_key = category_key(room["category"])
                    avail_key = "1" if not wl_room else "0"

                    rows_html += f"""<tr class="{rc}" data-search="{search_text}" data-cat="{cat_key}" data-avail="{avail_key}" data-price="{room['weekly_price']}" data-bed="{room['occupancy']}" data-days="{room['days']}" data-total="{room['total_price']}" data-name="{safe_attr(room['name'])}"><td><span class="room-name">{room['name']}</span></td><td>{room['occupancy']}人</td><td><span class="price">${room['weekly_price']:,}</span>{price_badges}</td><td><span class="price">${room['total_price']:,.2f}</span></td><td>{room['days']}天</td><td>{inventory_cell}</td></tr>"""

            filter_bar = f"""
                <div class="filter-bar" data-key="{key}">
                    <input class="f-input f-search" type="text" placeholder="🔍 搜索房型 / 户型..." oninput="filterTable('{key}')">
                    <div class="f-group">
                        <button class="f-btn active" data-v="all" onclick="setFilter('{key}','cat','all',this)">全部</button>
                        <button class="f-btn" data-v="studio" onclick="setFilter('{key}','cat','studio',this)">Studio</button>
                        <button class="f-btn" data-v="one" onclick="setFilter('{key}','cat','one',this)">1房</button>
                        <button class="f-btn" data-v="two" onclick="setFilter('{key}','cat','two',this)">2房</button>
                        <button class="f-btn" data-v="multi" onclick="setFilter('{key}','cat','multi',this)">多人间</button>
                        <button class="f-btn" data-v="other" onclick="setFilter('{key}','cat','other',this)">其他</button>
                    </div>
                    <div class="f-group">
                        <button class="f-btn active" data-v="all" onclick="setFilter('{key}','avail','all',this)">全部状态</button>
                        <button class="f-btn" data-v="1" onclick="setFilter('{key}','avail','1',this)">有房</button>
                        <button class="f-btn" data-v="0" onclick="setFilter('{key}','avail','0',this)">等位</button>
                    </div>
                    <div class="f-group f-price">
                        <input class="f-input f-price-min" type="number" min="0" placeholder="周租$最低" oninput="filterTable('{key}')">
                        <span class="f-sep">—</span>
                        <input class="f-input f-price-max" type="number" min="0" placeholder="最高" oninput="filterTable('{key}')">
                    </div>
                    <button class="f-clear" onclick="clearFilters('{key}')">✕ 清除</button>
                    <span class="f-count" id="count-{key}"></span>
                </div>"""

            cin_disp = f"{fmt_cn_date(cin_min)} ~ {fmt_cn_date(cin_max)}"
            cout_disp = fmt_cn_date(cout_min) if cout_min else "—"

            contract_panels_html += f"""
                <div class="sub-panel{c_active}" data-contract="{cslug}" data-prop="{slug}" data-key="{key}" data-window-min="{cin_min}" data-window-max="{cin_max}">
                    {filter_bar}
                    <div class="table-wrap fade-in">
                        <table>
                            <thead><tr><th class="sortable" data-sort="name" onclick="sortTable('{key}','name','text')">房型 <span class="sort-arrow"></span></th><th class="sortable" data-sort="bed" onclick="sortTable('{key}','bed','num')">入住 <span class="sort-arrow"></span></th><th class="sortable" data-sort="price" onclick="sortTable('{key}','price','num')">周租金 <span class="sort-arrow"></span></th><th class="sortable" data-sort="total" onclick="sortTable('{key}','total','num')">总租金 (含GST) <span class="sort-arrow"></span></th><th class="sortable" data-sort="days" onclick="sortTable('{key}','days','num')">合同期 <span class="sort-arrow"></span></th><th>库存</th></tr></thead>
                            <tbody>{rows_html}</tbody>
                        </table>
                    </div>
                    <div class="panel-summary">📅 起租 <b>{cin_disp}</b> · 退租 {cout_disp} &ensp;|&ensp; 共 {len(rooms)} 种房型 &ensp;|&ensp; <span class="stat-ok">可预订 {avail}</span> &ensp;|&ensp; <span class="stat-warn">等位 {wl}</span></div>
                </div>"""

        panels_html += f"""
    <div class="prop-panel{active}" id="prop-{slug}">
        <div class="sub-tabs">{sub_tabs_html}</div>
        {contract_panels_html}
    </div>"""

    # ---- Summary stats ----
    total_stays = 0
    total_entries = 0
    total_avail = 0
    total_wl = 0
    prop_count = 0
    for prop_name in prop_order:
        if prop_name not in all_data:
            continue
        prop_count += 1
        for stay in all_data[prop_name].values():
            total_stays += 1
            rooms = stay["rooms"]
            total_entries += len(rooms)
            total_avail += sum(1 for r in rooms if not r["is_waitlist"])
            total_wl += sum(1 for r in rooms if r["is_waitlist"])

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

    /* Check-in date picker */
    .date-picker {{ display: flex; align-items: center; gap: 12px; margin-top: 16px; flex-wrap: wrap; background: var(--card-bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; }}
    .date-picker label {{ font-size: 0.9rem; font-weight: 700; color: var(--text); }}
    .date-picker .hint {{ font-size: 0.78rem; color: var(--text-muted); }}
    .date-picker select {{ padding: 9px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-family: var(--font); font-size: 0.9rem; font-weight: 600; outline: none; cursor: pointer; min-width: 150px; }}
    .date-picker select:focus {{ border-color: var(--text-muted); }}
    #date-match {{ font-size: 0.82rem; color: var(--green); font-weight: 700; }}

    /* Property nav */
    .prop-nav {{ display: flex; gap: 6px; margin-bottom: 22px; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; }}
    .prop-nav::-webkit-scrollbar {{ display: none; }}
    .prop-btn {{ flex-shrink: 0; padding: 9px 18px; border-radius: 8px; cursor: pointer; font-size: 0.84rem; font-weight: 600; color: var(--text-muted); border: 1px solid var(--border); background: var(--card-bg); font-family: var(--font); transition: all 200ms cubic-bezier(0.32,0.72,0,1); white-space: nowrap; letter-spacing: -0.01em; }}
    .prop-btn:hover {{ color: var(--text); border-color: var(--text-muted); }}
    .prop-btn.active {{ background: var(--text); color: var(--bg); border-color: var(--text); }}
    .prop-btn .count {{ font-size: 0.68rem; opacity: 0.5; margin-left: 3px; font-weight: 400; }}

    /* Sub tabs */
    .sub-tabs {{ display: flex; gap: 4px; margin-bottom: 16px; background: var(--card-bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 4px; width: fit-content; max-width: 100%; overflow-x: auto; scrollbar-width: none; }}
    .sub-tabs::-webkit-scrollbar {{ display: none; }}
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

    /* Filter bar */
    .filter-bar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 14px; padding: 10px 12px; background: var(--card-bg); border: 1px solid var(--border); border-radius: var(--radius); }}
    .f-input {{ padding: 7px 12px; border-radius: 7px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-size: 0.82rem; font-family: var(--font); outline: none; min-width: 0; }}
    .f-input:focus {{ border-color: var(--text-muted); }}
    .f-search {{ min-width: 180px; flex: 1 1 160px; }}
    .f-group {{ display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }}
    .f-btn {{ padding: 6px 11px; border-radius: 99px; cursor: pointer; font-size: 0.76rem; font-weight: 600; color: var(--text-muted); border: 1px solid var(--border); background: transparent; font-family: var(--font); transition: all 150ms ease; white-space: nowrap; }}
    .f-btn:hover {{ color: var(--text); border-color: var(--text-muted); }}
    .f-btn.active {{ background: var(--text); color: var(--bg); border-color: var(--text); }}
    .f-price-min, .f-price-max {{ width: 90px; }}
    .f-sep {{ color: var(--text-muted); font-size: 0.8rem; }}
    .f-clear {{ padding: 6px 11px; border-radius: 7px; cursor: pointer; font-size: 0.76rem; font-weight: 600; color: var(--text-muted); border: 1px solid var(--border); background: transparent; font-family: var(--font); }}
    .f-clear:hover {{ color: var(--red); border-color: var(--red); }}
    .f-count {{ margin-left: auto; font-size: 0.76rem; color: var(--text-muted); white-space: nowrap; }}

    /* Sort */
    .sortable {{ cursor: pointer; user-select: none; }}
    .sortable:hover {{ color: var(--text); }}
    .sort-arrow {{ font-size: 0.62rem; margin-left: 2px; }}

    /* Badges */
    .badge {{ display: inline-flex; align-items: center; gap: 3px; padding: 2px 7px; border-radius: 99px; font-size: 0.68rem; font-weight: 700; margin-left: 6px; white-space: nowrap; vertical-align: middle; }}
    .badge-new {{ background: var(--green-bg); color: var(--green); }}
    .badge-drop {{ background: var(--red-bg); color: var(--red); }}

    /* Empty state */
    .empty-state {{ display: none; padding: 32px 16px; text-align: center; color: var(--text-muted); font-size: 0.86rem; }}

    .prop-panel {{ display: none; }}
    .prop-panel.active {{ display: block; }}
    .sub-panel {{ display: none; }}
    .sub-panel.active {{ display: block; }}
    .date-hidden {{ display: none !important; }}

    .panel-summary {{ margin-top: 12px; font-size: 0.8rem; color: var(--text-muted); }}
    .panel-summary b {{ color: var(--text); }}
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
    <p class="meta">📍 Brisbane, Queensland — {prop_count} 所公寓 &ensp;|&ensp; 更新于 {update_time_display} &ensp;|&ensp; 每日 10:00 / 15:00 自动刷新</p>
    <div class="date-picker">
        <label for="checkin-date">🎯 学生起租日</label>
        <select id="checkin-date" onchange="filterByDate(this.value)">
            <option value="all" selected>全部租期（不限日期）</option>
            {date_options}
        </select>
        <span class="hint">选择起租日期，自动匹配所有适合该日起租的租约</span>
        <span id="date-match"></span>
    </div>
</div>

<nav class="prop-nav fade-in" style="animation-delay:60ms" id="prop-nav">{prop_tabs_html}</nav>

{panels_html}

<div class="footer fade-in" style="animation-delay:300ms">
    <div class="footer-grid">
        <div class="footer-card">
            <h3>房源概况</h3>
            <ul>
                <li>{prop_count} 所 UniLodge Queensland 公寓</li>
                <li>共 {total_stays} 个租期（Full Year / Half Year / 学期合同等）</li>
                <li>共 {total_entries} 个房型×租期组合</li>
                <li>可预订 {total_avail} · 等位 {total_wl}</li>
            </ul>
        </div>
        <div class="footer-card">
            <h3>注意事项</h3>
            <ul>
                <li>价格均为澳元 (AUD)，已含 GST</li>
                <li>候补（等位）= 当前无房，可排队等待</li>
                <li>上方选择起租日后，自动匹配可入住的租约</li>
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
        var firstSub = panel.querySelector('.sub-tab:not(.date-hidden)');
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

function filterByDate(date) {{
    document.querySelectorAll('.sub-tab').forEach(function(t) {{
        var mn = t.getAttribute('data-window-min'), mx = t.getAttribute('data-window-max');
        var show = (date === 'all') || (date >= mn && date <= mx);
        t.classList.toggle('date-hidden', !show);
    }});
    document.querySelectorAll('.sub-panel').forEach(function(p) {{
        var mn = p.getAttribute('data-window-min'), mx = p.getAttribute('data-window-max');
        var show = (date === 'all') || (date >= mn && date <= mx);
        p.classList.toggle('date-hidden', !show);
    }});
    document.querySelectorAll('.prop-panel').forEach(function(pp) {{
        var vis = pp.querySelectorAll('.sub-panel:not(.date-hidden)').length;
        pp.classList.toggle('date-hidden', vis === 0);
        var btn = document.querySelector('.prop-btn[data-slug="' + pp.id.replace('prop-', '') + '"]');
        if (btn) btn.classList.toggle('date-hidden', vis === 0);
        var active = pp.querySelector('.sub-tab.active');
        if (!active || active.classList.contains('date-hidden')) {{
            var first = pp.querySelector('.sub-tab:not(.date-hidden)');
            if (first) first.click();
        }}
    }});
    var total = document.querySelectorAll('.sub-panel:not(.date-hidden)').length;
    var c = document.getElementById('date-match');
    if (c) c.textContent = (date === 'all') ? '' : ('匹配 ' + total + ' 个租约');
}}

var __fs = {{}};
var __sort = {{}};

function getFilterState(key) {{
    if (!__fs[key]) __fs[key] = {{cat: 'all', avail: 'all'}};
    return __fs[key];
}}

function setFilter(key, f, v, btn) {{
    var st = getFilterState(key);
    st[f] = v;
    var panel = document.querySelector('.sub-panel[data-key="' + key + '"]');
    if (panel && btn) {{
        var group = btn.parentElement;
        if (group) group.querySelectorAll('.f-btn').forEach(function(b) {{ b.classList.remove('active'); }});
        btn.classList.add('active');
    }}
    filterTable(key);
}}

function clearFilters(key) {{
    var st = getFilterState(key);
    st.cat = 'all'; st.avail = 'all';
    var panel = document.querySelector('.sub-panel[data-key="' + key + '"]');
    if (panel) {{
        var s = panel.querySelector('.f-search'); if (s) s.value = '';
        var mn = panel.querySelector('.f-price-min'); if (mn) mn.value = '';
        var mx = panel.querySelector('.f-price-max'); if (mx) mx.value = '';
        panel.querySelectorAll('.f-btn').forEach(function(b) {{ b.classList.toggle('active', b.dataset.v === 'all'); }});
    }}
    filterTable(key);
}}

function filterTable(key) {{
    var panel = document.querySelector('.sub-panel[data-key="' + key + '"]');
    if (!panel) return;
    var st = getFilterState(key);
    var searchEl = panel.querySelector('.f-search');
    var search = searchEl ? (searchEl.value || '').trim().toLowerCase() : '';
    var min = parseFloat(panel.querySelector('.f-price-min').value) || 0;
    var max = parseFloat(panel.querySelector('.f-price-max').value);
    if (isNaN(max)) max = Infinity;
    var tbody = panel.querySelector('tbody');
    if (!tbody) return;
    var visible = 0;
    Array.from(tbody.children).forEach(function(el) {{
        if (el.classList.contains('cat-divider')) return;
        var show = true;
        if (st.cat !== 'all' && el.dataset.cat !== st.cat) show = false;
        if (st.avail !== 'all' && el.dataset.avail !== st.avail) show = false;
        if (search && (el.dataset.search || '').indexOf(search) === -1) show = false;
        var price = parseInt(el.dataset.price, 10) || 0;
        if (price < min || price > max) show = false;
        el.style.display = show ? '' : 'none';
        if (show) visible++;
    }});
    updateDividers(tbody);
    var countEl = document.getElementById('count-' + key);
    if (countEl) countEl.textContent = '找到 ' + visible + ' 套';
    var empty = panel.querySelector('.empty-state');
    if (!empty) {{
        empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = '没有匹配的房源';
        var tw = panel.querySelector('.table-wrap');
        if (tw) tw.appendChild(empty);
    }}
    empty.style.display = visible === 0 ? 'block' : 'none';
}}

function updateDividers(tbody) {{
    var pending = [];
    Array.from(tbody.children).forEach(function(el) {{
        if (el.classList.contains('cat-divider')) {{
            if (pending.length) pending[pending.length - 1].divider.style.display = pending[pending.length - 1].any ? '' : 'none';
            pending.push({{divider: el, any: false}});
        }} else {{
            if (pending.length && el.style.display !== 'none') pending[pending.length - 1].any = true;
        }}
    }});
    if (pending.length) pending[pending.length - 1].divider.style.display = pending[pending.length - 1].any ? '' : 'none';
}}

function sortTable(key, col, dataType) {{
    var panel = document.querySelector('.sub-panel[data-key="' + key + '"]');
    if (!panel) return;
    var tbody = panel.querySelector('tbody');
    if (!tbody) return;
    var st = __sort[key] || {{col: '', dir: 0}};
    var dir = st.col === col ? st.dir * -1 : 1;
    __sort[key] = {{col: col, dir: dir}};
    panel.querySelectorAll('th.sortable').forEach(function(th) {{
        var arrow = th.querySelector('.sort-arrow');
        if (arrow) arrow.textContent = th.dataset.sort === col ? (dir > 0 ? '▲' : '▼') : '';
    }});
    var groups = [], cur = null;
    Array.from(tbody.children).forEach(function(el) {{
        if (el.classList.contains('cat-divider')) {{ cur = {{divider: el, rows: []}}; groups.push(cur); }}
        else if (cur) cur.rows.push(el);
    }});
    groups.forEach(function(g) {{
        g.rows.sort(function(a, b) {{
            var av = a.dataset[col], bv = b.dataset[col];
            if (dataType === 'num') {{ av = parseFloat(av) || 0; bv = parseFloat(bv) || 0; return (av - bv) * dir; }}
            return String(av).localeCompare(String(bv)) * dir;
        }});
        g.rows.forEach(function(r) {{ tbody.removeChild(r); }});
        var anchor = g.divider.nextElementSibling;
        g.rows.forEach(function(r) {{ tbody.insertBefore(r, anchor); }});
    }});
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
    expected_properties = ["Brisbane City", "Park Central", "South Bank", "Toowong"]

    for prop_name in expected_properties:
        prop_config = PROPERTIES[prop_name]
        try:
            data = fetch_property_data(prop_name, prop_config)
            if data:
                all_data[prop_name] = data
                stays = len(data)
                first_stay = list(data.values())[0] if data else {"rooms": []}
                room_count = len(first_stay["rooms"])
                print(f"  ✓ {prop_name}: {stays} stay periods, {room_count} types in first period")
            else:
                print(f"  ✗ {prop_name}: No data")
        except Exception as e:
            print(f"  ✗ {prop_name}: ERROR - {e}")

    missing = [p for p in expected_properties if p not in all_data]
    if missing:
        if len(missing) == len(expected_properties):
            print("\n❌ ERROR: No data fetched for any property! Refusing to write empty report.")
            print("   (GitHub runner IP likely blocked by UniLodge. Run locally instead.)")
        else:
            print(f"\n❌ ERROR: {len(missing)}/{len(expected_properties)} properties failed: {', '.join(missing)}")
            print("   Refusing to overwrite last complete report with partial data.")
        sys.exit(1)

    # ---- Compare with previous data for new / price-drop badges ----
    previous = load_previous_data()
    today_str = datetime.now().strftime('%Y-%m-%d')
    new_count = 0
    drop_count = 0
    for prop_name in all_data:
        slug = PROPERTIES[prop_name]["slug"]
        for cname, stay in all_data[prop_name].items():
            cslug = contract_slug(cname)
            for r in stay["rooms"]:
                key = f"{slug}:{cslug}:{r['id']}"
                price = r.get("weekly_price", 0)
                if key in previous:
                    prev = previous[key]
                    prev_price = prev.get("weekly_price", 0)
                    if price > 0 and prev_price > 0 and price < prev_price:
                        r["price_drop"] = prev_price - price
                        drop_count += 1
                    r["_first_seen"] = prev.get("first_seen", today_str)
                else:
                    r["is_new"] = True
                    r["_first_seen"] = today_str
                    new_count += 1
    print(f"    New rooms: {new_count}, Price drops: {drop_count}")

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Generating HTML report...")
    html = generate_html(all_data)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    save_previous_data(all_data)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Report saved to: {OUTPUT_FILE}")
    print(f"\n✅ Done! Open {OUTPUT_FILE} in your browser.")


if __name__ == "__main__":
    main()
