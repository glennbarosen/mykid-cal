"""Serve a de-noised copy of a MyKid iCal feed.

Drops weekly routines (any title that shows up in RECURRING_WEEKS or more
distinct ISO weeks) and merges consecutive all-day events with the same title
(e.g. "Juleferie" on 6 weekdays -> one 21.-31. Dec event).
"""

import datetime as dt
import hmac
import os
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# /<any MyKid uid>.ics serves that uid's feed (unless ALLOW_ANY_UID=0), and
# /<ACCESS_TOKEN>.ics optionally serves MYKID_UID's feed behind a token of your own.
MYKID_UID = os.environ.get("MYKID_UID", "")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")
ALLOW_ANY_UID = os.environ.get("ALLOW_ANY_UID", "1") != "0"
UID_PATTERN = re.compile(r"[A-Za-z0-9]{40,100}")
MAX_CACHED_FEEDS = 200
RECURRING_WEEKS = int(os.environ.get("RECURRING_WEEKS", "3"))
# All-day runs separated by at most this many days (weekends, public holidays) merge.
MERGE_GAP_DAYS = int(os.environ.get("MERGE_GAP_DAYS", "4"))
CACHE_SECONDS = int(os.environ.get("CACHE_SECONDS", "900"))
# Optional regexes (case-insensitive) that override the recurrence rule.
ALWAYS_KEEP = os.environ.get("ALWAYS_KEEP", "")
ALWAYS_DROP = os.environ.get("ALWAYS_DROP", "")
FEED_URL = "https://mykid.no/calendar/mykid_calendar.php?uid={}"

_cache = {}  # uid -> {"at": fetched timestamp, "body": cleaned feed}


def unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).replace("\r\n", "\n").split("\n")


def split_feed(lines):
    head, events, tail, cur = [], [], [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = [line]
        elif line == "END:VEVENT":
            cur.append(line)
            events.append(cur)
            cur = None
        elif cur is not None:
            cur.append(line)
        elif events:
            tail.append(line)
        else:
            head.append(line)
    return head, events, tail


def prop(event, name):
    for line in event:
        key, _, value = line.partition(":")
        if key.split(";")[0] == name:
            return key, value
    return None, None


def normalize(summary):
    s = summary.lower().replace("\\,", ",")
    s = re.sub(r"\bgruppe\b", "gr.", s)
    return re.sub(r"\s+", " ", s).strip()


def start_date(event):
    _, value = prop(event, "DTSTART")
    return dt.datetime.strptime(value[:8], "%Y%m%d").date()


def is_all_day(event):
    key, _ = prop(event, "DTSTART")
    return "VALUE=DATE" in key


def drop_routines(events):
    weeks = defaultdict(set)
    for ev in events:
        weeks[normalize(prop(ev, "SUMMARY")[1] or "")].add(start_date(ev).isocalendar()[:2])

    def keep(ev):
        title = normalize(prop(ev, "SUMMARY")[1] or "")
        if ALWAYS_KEEP and re.search(ALWAYS_KEEP, title, re.I):
            return True
        if ALWAYS_DROP and re.search(ALWAYS_DROP, title, re.I):
            return False
        return len(weeks[title]) < RECURRING_WEEKS

    return [ev for ev in events if keep(ev)]


def merge_all_day_runs(events):
    out, runs = [], defaultdict(list)
    for ev in events:
        if is_all_day(ev):
            runs[normalize(prop(ev, "SUMMARY")[1] or "")].append(ev)
        else:
            out.append(ev)
    for run in runs.values():
        run.sort(key=start_date)
        group = [run[0]]
        for ev in run[1:]:
            _, prev_end = prop(group[-1], "DTEND")
            gap = start_date(ev) - dt.datetime.strptime(prev_end[:8], "%Y%m%d").date()
            if gap <= dt.timedelta(days=MERGE_GAP_DAYS):
                group.append(ev)
            else:
                out.append(merge(group))
                group = [ev]
        out.append(merge(group))
    return sorted(out, key=start_date)


def merge(group):
    if len(group) == 1:
        return group[0]
    _, last_end = prop(group[-1], "DTEND")
    return [
        f"DTEND;VALUE=DATE:{last_end}" if line.startswith("DTEND") else line
        for line in group[0]
    ]


def clean(raw):
    head, events, tail = split_feed(unfold(raw))
    head = [
        "X-WR-CALNAME:MyKid (viktig)" if line.startswith("X-WR-CALNAME") else line
        for line in head
    ]
    events = merge_all_day_runs(drop_routines(events))
    lines = head + [line for ev in events for line in ev] + tail
    return "\r\n".join(line for line in lines if line) + "\r\n"


class NotACalendar(Exception):
    pass


def feed(uid):
    entry = _cache.get(uid)
    if entry and time.time() - entry["at"] < CACHE_SECONDS:
        return entry["body"]
    req = urllib.request.Request(FEED_URL.format(uid), headers={"User-Agent": "mykid-cal"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")
    # MyKid answers unknown uids with an empty calendar.
    if "BEGIN:VEVENT" not in raw:
        raise NotACalendar()
    if len(_cache) >= MAX_CACHED_FEEDS and uid not in _cache:
        _cache.pop(min(_cache, key=lambda k: _cache[k]["at"]))
    _cache[uid] = {"at": time.time(), "body": clean(raw).encode("utf-8")}
    return _cache[uid]["body"]


def uid_for(path):
    # Pasted links often pick up trailing whitespace ("%20") or a webcal-style suffix.
    name = urllib.parse.unquote(path).strip().lstrip("/")
    name = name.removesuffix(".ics").strip()
    if ACCESS_TOKEN and MYKID_UID and hmac.compare_digest(name, ACCESS_TOKEN):
        return MYKID_UID
    if ALLOW_ANY_UID and UID_PATTERN.fullmatch(name):
        return name
    return None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":
            return self.reply(200, b"ok", "text/plain")
        uid = uid_for(path)
        if uid is None:
            return self.reply(404, b"not found", "text/plain")
        try:
            body = feed(uid)
        except NotACalendar:
            return self.reply(404, b"not found", "text/plain")
        except Exception as exc:  # serve stale data if MyKid is down
            self.log_error("upstream failed: %s", exc)
            if uid not in _cache:
                return self.reply(502, b"upstream error", "text/plain")
            body = _cache[uid]["body"]
        self.reply(200, body, "text/calendar; charset=utf-8")

    def reply(self, status, body, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Request lines contain the secret uid/token; log only status codes for those.
        line = fmt % args
        print(f"GET {args[1]}" if "GET /" in line else line, flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("", int(os.environ.get("PORT", "5000"))), Handler).serve_forever()
