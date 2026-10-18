"""Notes section: unit test for gen.notes_by_project + browser test with a fixture status.json.
Usage: python3 tests/test_notes.py [BASE_URL]   (BASE serves this repo, e.g. python3 -m http.server 8790)"""
import json, os, sys, urllib.parse
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import gen
res = []
def ok(name, cond, info=""):
    res.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, info)

# ---- unit: filtering / ordering / reply ----
now = gen.from_iso("2026-10-18T10:00:00Z")
lab = lambda *n: {"nodes": [{"name": x} for x in n]}
raw = {"viewer": "sfxhewitt", "issues": [
    {"number": 1, "title": "old open", "body": "a", "state": "OPEN", "createdAt": "2026-10-01T10:00:00Z", "closedAt": None, "url": "u1", "labels": lab("mc:kinetic"),
     "comments": {"nodes": [{"author": {"login": "sfxhewitt"}, "body": "first", "createdAt": "2026-10-02T10:00:00Z", "url": "c1"},
                            {"author": {"login": "someone"}, "body": "x", "createdAt": "2026-10-03T10:00:00Z", "url": "c2"},
                            {"author": {"login": "sfxhewitt"}, "body": "latest  mine", "createdAt": "2026-10-04T10:00:00Z", "url": "c3"}]}},
    {"number": 2, "title": "done recently", "body": "", "state": "CLOSED", "createdAt": "2026-10-17T10:00:00Z", "closedAt": "2026-10-17T12:00:00Z", "url": "u2", "labels": lab("mc:kinetic", "bug"), "comments": {"nodes": []}},
    {"number": 3, "title": "new open", "body": "b " * 300, "state": "OPEN", "createdAt": "2026-10-16T10:00:00Z", "closedAt": None, "url": "u3", "labels": lab("mc:kinetic"), "comments": {"nodes": []}},
    {"number": 4, "title": "closed long ago", "body": "", "state": "CLOSED", "createdAt": "2026-08-01T10:00:00Z", "closedAt": "2026-08-02T10:00:00Z", "url": "u4", "labels": lab("mc:kinetic"), "comments": {"nodes": []}},
    {"number": 5, "title": "unlabelled", "body": "", "state": "OPEN", "createdAt": "2026-10-16T10:00:00Z", "closedAt": None, "url": "u5", "labels": lab("bug"), "comments": {"nodes": []}},
]}
nb = gen.notes_by_project(raw, now)
k = nb.get("kinetic", [])
ok("unit: only mc: labels, old closed dropped", [n["number"] for n in k] == [3, 1, 2] and list(nb) == ["kinetic"], str([n["number"] for n in k]))
ok("unit: latest reply from me", k[1].get("reply", {}).get("body") == "latest mine", str(k[1].get("reply")))
ok("unit: body snipped", len(k[0]["body"]) <= 220)
ok("unit: no reply key when none", "reply" not in k[0])
ok("unit: unavailable -> {}", gen.notes_by_project(None, now) == {})

# ---- browser ----
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8790/"
from playwright.sync_api import sync_playwright
d = json.load(open(os.path.join(HERE, "status.json")))
d["updated"] = __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")
for p in d["projects"]:
    p["comments"] = []
d["projects"][0]["comments"] = [
    {"number": 3, "title": "Scrub <b>jank</b>", "body": "On iPhone", "state": "open", "created_at": "2026-10-18T09:00:00+01:00", "html_url": "https://github.com/sfxhewitt/alight-status/issues/3"},
    {"number": 2, "title": "Old one", "body": "", "state": "closed", "created_at": "2026-10-17T09:00:00+01:00", "html_url": "https://github.com/sfxhewitt/alight-status/issues/2",
     "reply": {"body": "Fixed in abc123", "created_at": "2026-10-17T10:00:00+01:00", "html_url": "x"}}]
body = json.dumps(d)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 440, "height": 956}, is_mobile=True, has_touch=True, device_scale_factor=3)
    ctx.route("https://raw.githubusercontent.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
    pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE, wait_until="networkidle"); pg.wait_for_selector(".card")
    ok("ui: Notes section on every card", pg.locator(".card details.notes").count() == 5)
    ok("ui: collapsed by default", pg.locator("details.notes[open]").count() == 0)
    sm = pg.text_content("#p-kinetic .notes summary")
    ok("ui: summary counts", "1 open" in sm and "1 done" in sm, sm)
    pg.locator("#p-kinetic .notes summary").tap(); pg.wait_for_timeout(200)
    li = pg.locator("#p-kinetic .note")
    ok("ui: open note first, then done", li.count() == 2 and "open" in li.nth(0).get_attribute("class") and "closed" in li.nth(1).get_attribute("class"))
    ok("ui: title escaped", "<b>jank</b>" in li.nth(0).inner_text())
    ok("ui: reply shown", "Fixed in abc123" in li.nth(1).inner_text())
    href = pg.get_attribute("#p-kinetic .note-add", "href")
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query, keep_blank_values=True)
    ok("ui: Add note URL", href.startswith("https://github.com/sfxhewitt/alight-status/issues/new?") and q.get("labels") == ["mc:kinetic"]
       and q.get("title") == ["KINETIC // motion: "] and q.get("body") == [""], href)
    ok("ui: Add note opens new tab", pg.get_attribute("#p-kinetic .note-add", "target") == "_blank")
    ok("ui: empty state", "No notes yet" in (pg.text_content("#p-pepper .notes") or ""))
    h = pg.evaluate("document.querySelector('#p-kinetic .note-add').getBoundingClientRect().height")
    ok("ui: Add note tap target >=44px", h >= 44, str(h))
    pg.evaluate("load()"); pg.wait_for_timeout(1500)
    ok("ui: stays open across refresh", pg.locator("#p-kinetic details.notes[open]").count() == 1)
    ok("ui: no JS errors", not errs, "; ".join(errs))
    ok("ui: no horizontal overflow", pg.evaluate("document.documentElement.scrollWidth <= innerWidth"))
    pg.locator("#p-kinetic").screenshot(path=os.path.join(HERE, "screenshots", "notes-iphone.png"))
    b.close()
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
