#!/usr/bin/env python3
"""Knowles Family Sports independent collector.

Runs off-host (GitHub Actions) because the tournament provider limits requests
from the website's hosting server. Reads only public tournament pages and posts
the raw official rows to the website's authenticated ingest endpoint.
A failed fetch posts nothing for that team; the website keeps its saved data.

Cadence: every 5 minutes. Only teams with events near "today" are fetched, and
event/team discovery runs once per day (the provider throttles heavy polling).
"""
import json, os, re, sys, time, urllib.request, urllib.parse, http.cookiejar
from datetime import datetime, timedelta, timezone

SITE = "https://joshuaknowles.com/family-sports/ingest.php"
TOKEN = os.environ.get("COLLECTOR_TOKEN", "")
DISCOVERY = os.environ.get("DISCOVERY", "") == "1"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

def fetch(url, opener, data=None, referer=None, xhr=False):
    headers = {**UA}
    if referer: headers["Referer"] = referer
    if xhr: headers["X-Requested-With"] = "XMLHttpRequest"
    req = urllib.request.Request(url, data=data, headers=headers)
    with opener.open(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

def api(route, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{SITE}?route={route}", data=data,
        headers={"X-KFS-Collector": TOKEN, "Content-Type": "application/json",
                 "Accept": "application/json, */*;q=0.8", "Accept-Language": "en-US,en;q=0.9", **UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

def norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())

def active_team_urls(registry, today):
    out = []
    for url, player in registry["teams"].items():
        w = (registry.get("teamWindows") or {}).get(url)
        if not w or not w.get("start"):
            continue
        start = datetime.strptime(w["start"], "%Y-%m-%d").date()
        end = datetime.strptime(w["end"] or w["start"], "%Y-%m-%d").date()
        if start - timedelta(days=10) <= today <= end + timedelta(days=2):
            out.append((url, player))
    return out

def teamgames(team_url, opener):
    last = None
    for attempt in (1, 2):
        try:
            html = fetch(team_url, opener)
            m = re.search(r'scheduleUrl\s*:\s*"([^"]+)"', html)
            if not m:
                raise RuntimeError("scheduleUrl missing")
            endpoint = "https://basketball.exposureevents.com" + m.group(1).replace("&amp;", "&")
            time.sleep(1)
            body = fetch(endpoint, opener, data=b"page=1&pageSize=200", referer=team_url, xhr=True)
            groups = json.loads(body)
            return [g for grp in groups for g in (grp.get("Games") or [])]
        except Exception as e:
            last = e
            time.sleep(3)
    raise last

def discover(registry, opener, today):
    found = []
    html = fetch(registry["discoveryListUrl"], opener)
    bases = sorted(set(re.findall(r"https://basketball\.exposureevents\.com/(\d+/maine-hoops-[a-z0-9-]+)", html)))
    for base in bases[:24]:
        event_url = f"https://basketball.exposureevents.com/{base}"
        try:
            time.sleep(2)
            page = fetch(event_url + "/teams", opener)
            md = re.search(r'itemprop="startDate" content="([0-9-]+)T', page)
            me = re.search(r'itemprop="endDate" content="([0-9-]+)T', page)
            if not md:
                continue
            start_s, end_s = md.group(1), (me.group(1) if me else md.group(1))
            start = datetime.strptime(start_s, "%Y-%m-%d").date()
            end = datetime.strptime(end_s, "%Y-%m-%d").date()
            if end < today or start > today + timedelta(days=45):
                continue
            if start_s > registry["season"]["end"]:
                continue
            for m in re.finditer(r'href="(/[^"]*/teams/[^"]*\?divisionteamid=\d+)"[^>]*>([^<]+)', page):
                url = "https://basketball.exposureevents.com" + m.group(1).replace("&amp;", "&")
                if url in registry["teams"]:
                    continue
                nl = norm(m.group(2).strip())
                for player, aliases in registry["aliases"].items():
                    if any(norm(a) == nl for a in aliases):
                        found.append({"url": url, "player": player, "eventDate": start_s, "eventEnd": end_s})
        except Exception as e:
            print(f"discover skip {base}: {e}", file=sys.stderr)
    return found

def main():
    if not TOKEN:
        sys.exit("COLLECTOR_TOKEN is not set")
    today = datetime.now(timezone.utc).date() - timedelta(hours=5)  # approx ET
    registry = api("registry")
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    if DISCOVERY:
        discovered = discover(registry, opener, today)
        if discovered:
            r = api("ingest", {"teams": discovered})
            print("registered:", json.dumps(r))
            registry = api("registry")

    changed = 0
    teams = active_team_urls(registry, today)
    print(f"{len(teams)} active team feeds")
    for url, player in sorted(teams):
        try:
            time.sleep(2)
            rows = teamgames(url, opener)
            if not rows:
                print(f"{player}: no rows published"); continue
            r = api("ingest", {"games": [{"url": url, "player": player, "rows": rows}]})
            changed += r.get("changed", 0)
            if r.get("errors"):
                print(f"{player} errors: {r['errors']}", file=sys.stderr)
            else:
                print(f"{player}: {len(rows)} rows, changed {r.get('changed',0)}")
        except Exception as e:
            code = getattr(e, "code", None)
            if code in (404, 410):
                print(f"{player}: event no longer published ({code})")
            else:
                u = getattr(e, "url", "?")
                print(f"{player} fetch failed (saved data retained): {e} :: {u}", file=sys.stderr)
    print(f"done, total changed {changed}")

if __name__ == "__main__":
    main()
