#!/usr/bin/env python3
"""
GPS Jamming & Spoofing Watch - Bahrain
=======================================

Runs on GitHub Actions every 5 minutes. No paid services, no extra packages.

  python monitor.py detect    fetch live aircraft, find confirmed incidents, build the website
  python monitor.py send      email any new confirmed incident (alarm), mark it as sent
  python monitor.py monthly   build + email last month's report of confirmed incidents

Data source: free public ADS-B (adsb.lol, with airplanes.live as a fallback).
Aircraft broadcast their own GPS quality figures (NIC / NACp). When GPS is jammed
those figures drop; when GPS is spoofed, the GPS position/altitude stop agreeing
with physics and with the barometric altimeter.
"""

import json
import math
import os
import shutil
import smtplib
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

# ----------------------------------------------------------------- settings --
CENTER_LAT, CENTER_LON = 26.07, 50.55       # Bahrain
RADIUS_NM = 250                              # full horizon around Bahrain
BAHRAIN_TZ = timezone(timedelta(hours=3), "Bahrain")

# Jamming: an aircraft counts as "degraded" when its GPS quality drops this low
NACP_DEGRADED = 7          # NACp 7 or less  (normal is 8-11)
NIC_DEGRADED = 6           # NIC 6 or less   (normal is 7-11)
JAM_MIN_AIRCRAFT = 3       # confirmed = at least this many degraded aircraft ...
JAM_CLUSTER_NM = 60        # ... within this distance of each other ...
JAM_WINDOW_MIN = 15        # ... within this many minutes

# Spoofing signs
GEOM_BARO_GAP_FT = 3500    # GPS altitude and pressure altitude disagree by this much
SPOOF_CLUSTER_NM = 100     # 2+ aircraft with spoofing signs within this distance = confirmed
SPOOF_WINDOW_MIN = 30
STACK_NM = 1.0             # 3+ cruising aircraft "sitting" at the same spot = spoofed position
STACK_MIN_ALT_FT = 10000

# Incident handling
MERGE_NM = 100             # new signs this close to an open incident belong to it
CLOSE_AFTER_MIN = 60       # incident closes after this long with no new signs
MEMORY_KEEP_MIN = 90
ALARM_MAX_AGE_HOURS = 6    # older than this is sent as a LATE ALARM

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
INCIDENTS_FILE = DATA / "incidents.json"
MEMORY_FILE = ROOT / "state" / "memory.json"
SITE_SRC = ROOT / "site"
SITE_OUT = ROOT / "_site"
REPORTS = ROOT / "reports"

SOURCES = [
    "https://api.adsb.lol/v2/point/{lat}/{lon}/{r}",
    "https://api.airplanes.live/v2/point/{lat}/{lon}/{r}",
]


# ------------------------------------------------------------------ helpers --
def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def bh(dt_or_iso, fmt="%d %b %Y, %H:%M", label=True):
    dt = parse_iso(dt_or_iso) if isinstance(dt_or_iso, str) else dt_or_iso
    return dt.astimezone(BAHRAIN_TZ).strftime(fmt) + (" (Bahrain time)" if label else "")


def dist_nm(lat1, lon1, lat2, lon2):
    r = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1, math.sqrt(a)))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    deg = (math.degrees(math.atan2(x, y)) + 360) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((deg + 22.5) // 45) % 8]


def where_text(lat, lon):
    d = dist_nm(CENTER_LAT, CENTER_LON, lat, lon)
    if d < 15:
        return f"over Bahrain ({lat:.2f}, {lon:.2f})"
    return f"{d:.0f} nm {bearing(CENTER_LAT, CENTER_LON, lat, lon)} of Bahrain ({lat:.2f}, {lon:.2f})"


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# -------------------------------------------------------------------- fetch --
def fetch_aircraft():
    """Return (list_of_aircraft, source_name). Tries each free source in turn."""
    test_file = os.environ.get("TEST_SNAPSHOT")
    if test_file:
        return load_json(test_file, {}).get("ac", []), "test data"
    last_err = None
    for tmpl in SOURCES:
        url = tmpl.format(lat=CENTER_LAT, lon=CENTER_LON, r=RADIUS_NM)
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "gps-interference-watch-bahrain (GitHub Actions)"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                ac = body.get("ac") or body.get("aircraft") or []
                return ac, url.split("/")[2]
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(3)
    raise RuntimeError(f"No ADS-B source reachable: {last_err}")


# ------------------------------------------------------------------ analyse --
def observe(ac_list, t, memory):
    """Turn raw aircraft into observations with jamming/spoofing signs."""
    last_pos = memory.setdefault("last_pos", {})
    obs = []
    for a in ac_list:
        lat, lon = num(a.get("lat")), num(a.get("lon"))
        if lat is None or lon is None:
            continue
        src = str(a.get("type", "adsb_icao"))
        if not (src.startswith("adsb") or src.startswith("adsr")):
            continue                       # skip MLAT/TIS-B: they carry no GPS figures
        if a.get("alt_baro") == "ground":
            continue                       # only airborne aircraft
        if (num(a.get("seen_pos")) or 0) > 60:
            continue                       # stale position
        hexid = str(a.get("hex", "")).lower().strip("~")
        if not hexid:
            continue

        alt_baro, alt_geom = num(a.get("alt_baro")), num(a.get("alt_geom"))
        gs = num(a.get("gs"))
        nic, nacp = num(a.get("nic")), num(a.get("nac_p"))
        version = num(a.get("version"))
        figures_valid = version is None or version >= 1   # ADS-B v0 doesn't report these properly

        jam_signs = []
        if figures_valid and nacp is not None and nacp <= NACP_DEGRADED:
            jam_signs.append(f"GPS accuracy low (NACp {int(nacp)})")
        if figures_valid and nic is not None and nic <= NIC_DEGRADED:
            jam_signs.append(f"GPS integrity low (NIC {int(nic)})")
        if "gpsOkBefore" in a:
            jam_signs.append("aircraft reported GPS lost")

        spoof_signs = []
        if alt_baro is not None and alt_geom is not None and abs(alt_geom - alt_baro) >= GEOM_BARO_GAP_FT:
            spoof_signs.append(f"GPS altitude {int(alt_geom):,} ft vs pressure altitude {int(alt_baro):,} ft")
        prev = last_pos.get(hexid)
        if prev:
            dt_h = (t - parse_iso(prev["t"])).total_seconds() / 3600
            if 60 / 3600 <= dt_h <= 0.5:
                d = dist_nm(prev["lat"], prev["lon"], lat, lon)
                implied = d / dt_h
                limit = max(800, 1.5 * max(gs or 0, prev.get("gs") or 0) + 150)
                if implied > limit and d > 20:
                    spoof_signs.append(f"position jumped {d:.0f} nm in {dt_h*60:.0f} min")
        last_pos[hexid] = {"t": iso(t), "lat": lat, "lon": lon, "gs": gs}

        obs.append({
            "t": iso(t), "hex": hexid,
            "flight": (a.get("flight") or "").strip(), "reg": a.get("r") or "",
            "actype": a.get("t") or "", "lat": round(lat, 4), "lon": round(lon, 4),
            "alt": alt_baro, "alt_geom": alt_geom, "gs": gs, "nic": nic, "nacp": nacp,
            "jam": jam_signs, "spoof": spoof_signs,
        })

    # Several cruising aircraft reporting the same spot = spoofed positions
    high = [o for o in obs if (o["alt"] or 0) >= STACK_MIN_ALT_FT]
    for o in high:
        near = [p for p in high if dist_nm(o["lat"], o["lon"], p["lat"], p["lon"]) <= STACK_NM]
        if len(near) >= 3:
            sign = f"{len(near)} aircraft reporting the same position"
            if sign not in o["spoof"]:
                o["spoof"].append(sign)

    # forget old positions
    cutoff = t - timedelta(minutes=MEMORY_KEEP_MIN)
    memory["last_pos"] = {k: v for k, v in last_pos.items() if parse_iso(v["t"]) >= cutoff}
    return obs


def clusters(points, radius_nm, min_count):
    """Greedy grouping: biggest group of points within radius of one point first."""
    pts = list(points)
    out = []
    while pts:
        best = max(pts, key=lambda p: sum(dist_nm(p["lat"], p["lon"], q["lat"], q["lon"]) <= radius_nm for q in pts))
        group = [q for q in pts if dist_nm(best["lat"], best["lon"], q["lat"], q["lon"]) <= radius_nm]
        if len(group) < min_count:
            break
        out.append(group)
        ids = {id(q) for q in group}
        pts = [q for q in pts if id(q) not in ids]
    return out


def find_confirmed(memory, t):
    """Return list of (kind, [observations]) for confirmed jamming/spoofing right now."""
    recent = memory["obs"]
    found = []

    # Jamming: several different aircraft with degraded GPS, close together, recently
    win = t - timedelta(minutes=JAM_WINDOW_MIN)
    latest = {}
    for o in recent:
        if o["jam"] and parse_iso(o["t"]) >= win:
            latest[o["hex"]] = o
    for g in clusters(latest.values(), JAM_CLUSTER_NM, JAM_MIN_AIRCRAFT):
        found.append(("jamming", g))

    # Spoofing: signs shared by 2+ aircraft, or repeated on one aircraft in separate checks
    win = t - timedelta(minutes=SPOOF_WINDOW_MIN)
    spoofed = [o for o in recent if o["spoof"] and parse_iso(o["t"]) >= win]
    latest = {}
    times = {}
    for o in spoofed:
        latest[o["hex"]] = o
        times.setdefault(o["hex"], set()).add(o["t"])
    used = set()
    for g in clusters(latest.values(), SPOOF_CLUSTER_NM, 2):
        found.append(("spoofing", g))
        used |= {o["hex"] for o in g}
    for h, o in latest.items():
        if h not in used and len(times[h]) >= 2:
            found.append(("spoofing", [o]))
    return found


def centroid(group):
    return (sum(o["lat"] for o in group) / len(group), sum(o["lon"] for o in group) / len(group))


def update_incidents(incidents, confirmed, memory, t):
    """Merge confirmed findings into the incident log. Returns list of new incident ids."""
    new_ids = []
    for kind, group in confirmed:
        clat, clon = centroid(group)
        match = None
        for inc in incidents:
            if inc["type"] == kind and inc["status"] == "open" and \
               dist_nm(inc["lat"], inc["lon"], clat, clon) <= MERGE_NM:
                match = inc
                break
        if match is None:
            stamp = t.astimezone(BAHRAIN_TZ).strftime("%Y%m%d-%H%M")
            prefix = "JAM" if kind == "jamming" else "SPF"
            n = sum(1 for i in incidents if i["id"].startswith(f"{prefix}-{stamp}"))
            match = {
                "id": f"{prefix}-{stamp}" + (f"-{n+1}" if n else ""),
                "type": kind, "status": "open",
                "first_seen": iso(t), "last_seen": iso(t),
                "lat": round(clat, 3), "lon": round(clon, 3),
                "where": where_text(clat, clon),
                "aircraft": {}, "emailed": False,
            }
            incidents.append(match)
            new_ids.append(match["id"])
        match["last_seen"] = iso(t)
        # bring in every observation of these aircraft that showed signs (full history in window)
        hexes = {o["hex"] for o in group}
        signs_key = "jam" if kind == "jamming" else "spoof"
        for o in memory["obs"]:
            if o["hex"] in hexes and o[signs_key]:
                rec = match["aircraft"].setdefault(o["hex"], {
                    "hex": o["hex"], "flight": o["flight"], "reg": o["reg"], "actype": o["actype"],
                    "first_seen": o["t"], "signs": []})
                if o["t"] < rec["first_seen"]:
                    rec["first_seen"] = o["t"]
                if o["t"] >= rec.get("last_seen", ""):
                    rec.update({"last_seen": o["t"], "lat": o["lat"], "lon": o["lon"],
                                "alt": o["alt"], "alt_geom": o["alt_geom"], "gs": o["gs"],
                                "nic": o["nic"], "nacp": o["nacp"]})
                    rec["flight"] = o["flight"] or rec["flight"]
                for s in o[signs_key]:
                    if s not in rec["signs"]:
                        rec["signs"].append(s)
        pts = list(match["aircraft"].values())
        match["lat"], match["lon"] = (round(v, 3) for v in centroid(pts))
        match["where"] = where_text(match["lat"], match["lon"])
        match["aircraft_count"] = len(pts)

    for inc in incidents:
        if inc["status"] == "open" and t - parse_iso(inc["last_seen"]) > timedelta(minutes=CLOSE_AFTER_MIN):
            inc["status"] = "closed"
    return new_ids


# ------------------------------------------------------------------- website --
def build_site(incidents, status):
    if SITE_OUT.exists():
        shutil.rmtree(SITE_OUT)
    shutil.copytree(SITE_SRC, SITE_OUT)
    (SITE_OUT / "data").mkdir(exist_ok=True)
    save_json(SITE_OUT / "data" / "incidents.json", incidents)
    save_json(SITE_OUT / "data" / "status.json", status)
    reports = sorted([p.name for p in REPORTS.glob("*.html")], reverse=True) if REPORTS.exists() else []
    if reports:
        shutil.copytree(REPORTS, SITE_OUT / "reports")
    save_json(SITE_OUT / "data" / "reports.json", reports)
    (SITE_OUT / ".nojekyll").write_text("")


# --------------------------------------------------------------------- email --
STYLE_TD = "padding:6px 8px;border-bottom:1px solid #e3e6ea;font-size:13px;vertical-align:top"
STYLE_TH = ("padding:6px 8px;border-bottom:2px solid #c9ced6;font-size:12px;text-align:left;"
            "color:#5b6573;text-transform:uppercase;letter-spacing:.04em")


def aircraft_rows(inc):
    rows = []
    for a in sorted(inc["aircraft"].values(), key=lambda x: x["first_seen"]):
        alt = f"{int(a['alt']):,} ft" if num(a.get("alt")) is not None else "-"
        ident = escape(a["flight"] or a["reg"] or a["hex"].upper())
        sub = " · ".join(escape(x) for x in [a["reg"], a["actype"], a["hex"].upper()] if x)
        rows.append(
            f"<tr><td style='{STYLE_TD}'><b>{ident}</b><br><span style='color:#5b6573'>{sub}</span></td>"
            f"<td style='{STYLE_TD}'>{escape(bh(a['first_seen'], '%d %b %H:%M', False))}</td>"
            f"<td style='{STYLE_TD}'>{alt}</td>"
            f"<td style='{STYLE_TD}'>{a['lat']:.3f}, {a['lon']:.3f}</td>"
            f"<td style='{STYLE_TD}'>{'<br>'.join(escape(s) for s in a['signs'])}</td></tr>")
    return "".join(rows)


def alarm_html(inc, map_url):
    colour = "#c0392b" if inc["type"] == "jamming" else "#8e44ad"
    title = "GPS JAMMING" if inc["type"] == "jamming" else "GPS SPOOFING"
    return f"""<!doctype html><html><body style="margin:0;background:#f3f5f7;font-family:Segoe UI,Arial,sans-serif;color:#1d2530">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f5f7;padding:20px 0"><tr><td align="center">
<table width="680" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #dde1e6;border-radius:8px;overflow:hidden">
<tr><td style="background:{colour};color:#fff;padding:16px 22px">
 <div style="font-size:12px;letter-spacing:.08em;opacity:.85">CONFIRMED INCIDENT · {escape(inc['id'])}</div>
 <div style="font-size:22px;font-weight:700;margin-top:4px">{title} near Bahrain</div></td></tr>
<tr><td style="padding:18px 22px;font-size:14px;line-height:1.55">
 <b>First detected:</b> {escape(bh(inc['first_seen']))}<br>
 <b>Location:</b> {escape(inc['where'])}<br>
 <b>Aircraft affected:</b> {inc['aircraft_count']}
 <div style="margin:18px 0"><a href="{escape(map_url)}" style="background:{colour};color:#fff;text-decoration:none;padding:11px 20px;border-radius:5px;font-weight:600;display:inline-block">Open satellite map of affected aircraft</a></div>
 <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
 <tr><th style="{STYLE_TH}">Aircraft</th><th style="{STYLE_TH}">Time (Bahrain)</th><th style="{STYLE_TH}">Altitude</th><th style="{STYLE_TH}">Position</th><th style="{STYLE_TH}">Signs</th></tr>
 {aircraft_rows(inc)}</table>
 <p style="font-size:12px;color:#6b7480;margin-top:18px">Detected automatically from public ADS-B data (aircraft-reported GPS quality, NIC/NACp, and position/altitude consistency).
 One alarm is sent per new incident; further aircraft in the same incident appear on the map.</p>
</td></tr></table></td></tr></table></body></html>"""


def send_email(subject, html, recipients):
    user, pw = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASS", "")
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or 587)
    if not (user and pw and recipients):
        raise RuntimeError("Email not configured (SMTP_USER / SMTP_PASS / ALARM_TO missing)")
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, f"GPS Interference Watch <{user}>", ", ".join(recipients)
    msg.attach(MIMEText("This message is in HTML. Please view it in an HTML-capable mail app.", "plain"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    body = msg.as_string()
    # Try port 587 (STARTTLS) first, then 465 (SSL) - Gmail sometimes drops one of them.
    ports = [port] + [p for p in (587, 465) if p != port]
    errors = []
    for p in ports:
        ctx = ssl.create_default_context()
        try:
            if p == 465:
                with smtplib.SMTP_SSL(host, p, context=ctx, timeout=30) as s:
                    s.login(user, pw)
                    s.sendmail(user, recipients, body)
            else:
                with smtplib.SMTP(host, p, timeout=30) as s:
                    s.ehlo()
                    s.starttls(context=ctx)
                    s.ehlo()
                    s.login(user, pw)
                    s.sendmail(user, recipients, body)
            return
        except Exception as e:  # noqa: BLE001
            errors.append(f"port {p}: {e}")
    raise RuntimeError("; ".join(errors))


def recipients():
    return [r.strip() for r in os.environ.get("ALARM_TO", "").replace(";", ",").split(",") if r.strip()]


def site_url():
    u = os.environ.get("SITE_URL", "").strip()
    return u if u.endswith("/") else u + "/"


# ------------------------------------------------------------------ commands --
def cmd_detect():
    t = now_utc()
    memory = load_json(MEMORY_FILE, {"obs": [], "last_pos": {}})
    incidents = load_json(INCIDENTS_FILE, [])
    ac, source = fetch_aircraft()
    obs = observe(ac, t, memory)
    cutoff = t - timedelta(minutes=MEMORY_KEEP_MIN)
    memory["obs"] = [o for o in memory["obs"] if parse_iso(o["t"]) >= cutoff] + \
                    [o for o in obs if o["jam"] or o["spoof"]]
    confirmed = find_confirmed(memory, t)
    new_ids = update_incidents(incidents, confirmed, memory, t)

    status = {
        "checked": iso(t), "source": source, "aircraft_seen": len(obs),
        "degraded_now": [o for o in obs if o["jam"]],
        "spoof_signs_now": [o for o in obs if o["spoof"]],
        "open_incidents": [i["id"] for i in incidents if i["status"] == "open"],
        "center": [CENTER_LAT, CENTER_LON], "radius_nm": RADIUS_NM,
    }
    save_json(MEMORY_FILE, memory)
    save_json(INCIDENTS_FILE, incidents)
    build_site(incidents, status)
    print(f"[{bh(t)}] {source}: {len(obs)} aircraft, {len(status['degraded_now'])} degraded, "
          f"{len(status['spoof_signs_now'])} with spoofing signs, new incidents: {new_ids or 'none'}")


def cmd_send():
    incidents = load_json(INCIDENTS_FILE, [])
    t = now_utc()
    to = recipients()
    changed = False
    failed = []
    for inc in incidents:
        if inc.get("emailed"):
            continue
        if not to:
            print("ALARM_TO is empty - alarm emails are switched off.")
            break
        late = t - parse_iso(inc["first_seen"]) > timedelta(hours=ALARM_MAX_AGE_HOURS)
        map_url = f"{site_url()}map.html?id={inc['id']}"
        kind = "GPS jamming" if inc["type"] == "jamming" else "GPS spoofing"
        prefix = "LATE ALARM" if late else "ALARM"
        subject = f"{prefix}: {kind} near Bahrain - {inc['aircraft_count']} aircraft - {bh(inc['first_seen'], '%d %b %H:%M')}"
        try:
            send_email(subject, alarm_html(inc, map_url), to)
            inc["emailed"] = iso(t)
            changed = True
            print(f"{prefix} sent for {inc['id']} to {', '.join(to)}")
        except Exception as e:  # noqa: BLE001  - retried on the next run
            failed.append(inc["id"])
            print(f"::error::Could not send alarm for {inc['id']}: {e}")
    if changed:
        save_json(INCIDENTS_FILE, incidents)
    if failed:
        # Make the GitHub check fail (red) so the failure is noticed; it is retried on the next run.
        sys.exit(1)


def monthly_html(month_label, incs):
    jam = [i for i in incs if i["type"] == "jamming"]
    spo = [i for i in incs if i["type"] == "spoofing"]
    ac = {h for i in incs for h in i["aircraft"]}
    rows = "".join(
        f"<tr><td style='{STYLE_TD}'><a href='{escape(site_url())}map.html?id={escape(i['id'])}'>{escape(i['id'])}</a></td>"
        f"<td style='{STYLE_TD}'>{'Jamming' if i['type']=='jamming' else 'Spoofing'}</td>"
        f"<td style='{STYLE_TD}'>{escape(bh(i['first_seen'], '%d %b %H:%M', False))}</td>"
        f"<td style='{STYLE_TD}'>{escape(bh(i['last_seen'], '%d %b %H:%M', False))}</td>"
        f"<td style='{STYLE_TD}'>{escape(i['where'])}</td>"
        f"<td style='{STYLE_TD}'>{i['aircraft_count']}</td></tr>" for i in incs)
    if not rows:
        rows = f"<tr><td colspan='6' style='{STYLE_TD}'>No confirmed jamming or spoofing incidents this month.</td></tr>"
    card = ("display:inline-block;width:128px;margin:0 8px 10px 0;padding:12px 14px;border:1px solid #dde1e6;"
            "border-radius:6px;background:#fafbfc")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>GPS interference report {escape(month_label)}</title></head>
<body style="margin:0;background:#f3f5f7;font-family:Segoe UI,Arial,sans-serif;color:#1d2530">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:20px 0"><tr><td align="center">
<table width="760" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #dde1e6;border-radius:8px">
<tr><td style="background:#1f3b57;color:#fff;padding:18px 22px"><div style="font-size:12px;letter-spacing:.08em;opacity:.8">MONTHLY REPORT</div>
<div style="font-size:22px;font-weight:700">GPS jamming &amp; spoofing around Bahrain - {escape(month_label)}</div>
<div style="font-size:13px;opacity:.85">Confirmed incidents within {RADIUS_NM} nm of Bahrain</div></td></tr>
<tr><td style="padding:18px 22px">
<div style="{card}"><div style="font-size:26px;font-weight:700">{len(incs)}</div><div style="font-size:12px;color:#5b6573">Confirmed incidents</div></div>
<div style="{card}"><div style="font-size:26px;font-weight:700;color:#c0392b">{len(jam)}</div><div style="font-size:12px;color:#5b6573">Jamming</div></div>
<div style="{card}"><div style="font-size:26px;font-weight:700;color:#8e44ad">{len(spo)}</div><div style="font-size:12px;color:#5b6573">Spoofing</div></div>
<div style="{card}"><div style="font-size:26px;font-weight:700">{len(ac)}</div><div style="font-size:12px;color:#5b6573">Aircraft affected</div></div>
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:10px">
<tr><th style="{STYLE_TH}">Incident</th><th style="{STYLE_TH}">Type</th><th style="{STYLE_TH}">Started</th><th style="{STYLE_TH}">Last seen</th><th style="{STYLE_TH}">Location</th><th style="{STYLE_TH}">Aircraft</th></tr>
{rows}</table>
<p style="font-size:12px;color:#6b7480;margin-top:18px">Times are Bahrain time. "Confirmed" means corroborated signs: several aircraft affected,
or spoofing signs shared by several aircraft or repeated on one aircraft. Source: public ADS-B data.</p>
</td></tr></table></td></tr></table></body></html>"""


def cmd_monthly():
    t = now_utc().astimezone(BAHRAIN_TZ)
    month = os.environ.get("REPORT_MONTH")  # optional "2026-10" to rerun a month
    if month:
        y, m = map(int, month.split("-"))
    else:
        first = t.replace(day=1)
        last_month = first - timedelta(days=1)
        y, m = last_month.year, last_month.month
    label = datetime(y, m, 1).strftime("%B %Y")
    incs = [i for i in load_json(INCIDENTS_FILE, [])
            if (lambda d: (d.year, d.month) == (y, m))(parse_iso(i["first_seen"]).astimezone(BAHRAIN_TZ))]
    incs.sort(key=lambda i: i["first_seen"])
    html = monthly_html(label, incs)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{y:04d}-{m:02d}.html").write_text(html, encoding="utf-8")
    print(f"Report for {label}: {len(incs)} incidents")
    to = recipients()
    if to:
        send_email(f"Monthly GPS jamming & spoofing report - {label}", html, to)
        print("Monthly report emailed to " + ", ".join(to))
    else:
        print("ALARM_TO is empty - report saved but not emailed.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "detect"
    {"detect": cmd_detect, "send": cmd_send, "monthly": cmd_monthly}[cmd]()
