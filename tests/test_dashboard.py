import json, sys
from playwright.sync_api import sync_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8790/"
OUT = "/workspace/alight-status/screenshots/"
res = []
def ok(name, cond, info=""):
    res.append((name, bool(cond), info)); print(("PASS " if cond else "FAIL ") + name, info)
with sync_playwright() as p:
    for eng in ["chromium", "webkit"]:
        try: b = getattr(p, eng).launch()
        except Exception as e: print(f"SKIP {eng}: not runnable on this host"); continue
        for label, vp, mob in [("iphone", {"width": 440, "height": 956}, True), ("desktop", {"width": 1440, "height": 900}, False)]:
            if eng == "webkit" and not mob: continue
            ctx = b.new_context(viewport=vp, device_scale_factor=3 if mob else 1, is_mobile=mob and eng == "chromium", has_touch=mob)
            pg = ctx.new_page(); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
            pg.goto(BASE, wait_until="networkidle")
            pg.wait_for_selector(".card")
            t = f"[{eng}/{label}]"
            ok(t + " 5 project cards", pg.locator(".card").count() == 5, str(pg.locator(".card").count()))
            ok(t + " no JS errors", not errs, "; ".join(errs))
            ok(t + " no horizontal overflow", pg.evaluate("document.documentElement.scrollWidth <= innerWidth"))
            ok(t + " summary populated", "/" in pg.inner_text("#sUp"), pg.inner_text("#sUp"))
            ok(t + " KINETIC steps", pg.locator("#p-kinetic .steps li").count() >= 6)
            ok(t + " Reel Pick progress bar", pg.locator("#p-reelpick .steps .bar").count() >= 1)
            ok(t + " TCG has no live link", pg.locator("#p-tcg a.btn").count() == 1)
            ok(t + " London times", "BST" in pg.inner_text("#p-kinetic") or "GMT" in pg.inner_text("#p-kinetic"))
            small = pg.evaluate("[...document.querySelectorAll('a.btn,button,summary')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height<44}).length")
            ok(t + " tap targets >=44px", small == 0, str(small))
            meta = pg.evaluate("document.querySelector('meta[name=apple-mobile-web-app-status-bar-style]').content")
            ok(t + " status-bar style default", meta == "default", meta)
            ok(t + " manifest + apple-touch-icon", pg.evaluate("!!document.querySelector('link[rel=manifest]') && !!document.querySelector('link[rel=apple-touch-icon]')"))
            for u in ["manifest.webmanifest", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "sw.js"]:
                r = pg.request.get(BASE + u); ok(f"{t} GET {u}", r.status == 200, str(r.status))
            pg.click("#reposPanel summary"); pg.wait_for_timeout(300)
            ok(t + " repo list", pg.locator(".repo").count() >= 20, str(pg.locator(".repo").count()))
            # auto refresh: count status.json requests over ~16s (only once to save time)
            if eng == "chromium" and mob:
                n = []
                pg.on("request", lambda r: "status.json" in r.url and n.append(1))
                pg.wait_for_timeout(16000)
                ok(t + " auto-refresh 15s", len(n) >= 1, f"{len(n)} refetches in 16s")
            pg.evaluate("document.querySelector('#reposPanel').open=false"); pg.evaluate("scrollTo(0,0)")
            pg.screenshot(path=f"{OUT}{eng}-{label}.png")
            pg.screenshot(path=f"{OUT}{eng}-{label}-full.png", full_page=True)
            ctx.close()
        b.close()
fails = [r for r in res if not r[1]]
print(f"\n{len(res)-len(fails)}/{len(res)} passed")
sys.exit(1 if fails else 0)
