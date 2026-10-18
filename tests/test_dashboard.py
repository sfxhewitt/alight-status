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
            # ---- carousel ----
            pg.evaluate("document.querySelector('#reposPanel').open=false; scrollTo(0,0)"); pg.wait_for_timeout(200)
            rail = "#projects"
            ov = pg.evaluate(f"getComputedStyle(document.querySelector('{rail}')).overflowX")
            snap = pg.evaluate(f"getComputedStyle(document.querySelector('{rail}')).scrollSnapType")
            ok(t + " carousel horizontal + snap", ov == "auto" and "x" in snap and "mandatory" in snap, f"{ov} / {snap}")
            ok(t + " touch-action + overscroll", pg.evaluate(f"(s=>s.touchAction.includes('pan-x')&&s.overscrollBehaviorX=='contain')(getComputedStyle(document.querySelector('{rail}')))"))
            geo = pg.evaluate(f"""(()=>{{const r=document.querySelector('{rail}'),c=[...r.querySelectorAll('.card')];const rr=r.getBoundingClientRect();
                return {{rw:rr.width,cw:c[0].getBoundingClientRect().width,visible:c.filter(x=>{{const b=x.getBoundingClientRect();return b.left<rr.right-1&&b.right>rr.left+1}}).length}}}})()""")
            if mob:
                ok(t + " one card ~fills width, next peeks", 0.75 < geo["cw"] / geo["rw"] < 0.95 and geo["visible"] == 2, str(geo))
            else:
                ok(t + " several cards per row", geo["visible"] >= 3, str(geo))
            ok(t + " counter shows 1 / 5", pg.inner_text("#counter").strip() == "1 / 5", pg.inner_text("#counter"))
            ok(t + " 5 position dots", pg.locator("#dots button").count() == 5)
            box = pg.locator(rail).bounding_box()
            if mob and eng == "chromium":
                # real touch swipe (CDP touch events), then check it settles on a snap point
                cdp = ctx.new_cdp_session(pg); y = box["y"] + 200
                def drag(x0, y0, dx, dy, n=15):
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]})
                    for i in range(1, n + 1):
                        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x0 + dx * i / n, "y": y0 + dy * i / n}]}); pg.wait_for_timeout(16)
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                drag(380, y, -270, 0)
            else:
                pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + 200); pg.mouse.wheel(int(box["width"] * 0.3), 0)
            pg.wait_for_timeout(1200)
            sn = pg.evaluate(f"""(()=>{{const r=document.querySelector('{rail}'),pl=parseFloat(getComputedStyle(r).scrollPaddingLeft)||0,max=r.scrollWidth-r.clientWidth;
                const pts=[...r.querySelectorAll('.card')].map(c=>Math.min(max,c.offsetLeft-r.offsetLeft-pl));return {{x:r.scrollLeft,pts}}}})()""")
            near = min(abs(sn["x"] - p_) for p_ in sn["pts"])
            ok(t + " swipe scrolls + snaps to a card", sn["x"] > 10 and near <= 2, f"x={sn['x']:.0f} nearest snap off by {near:.1f}")
            ok(t + " counter follows scroll", pg.inner_text("#counter").strip() != "1 / 5", pg.inner_text("#counter"))
            vy = pg.evaluate("scrollY")
            ok(t + " page did not scroll vertically during swipe", vy < 5, str(vy))
            if mob and eng == "chromium":
                sl = pg.evaluate(f"document.querySelector('{rail}').scrollLeft")
                drag(220, 700, 0, -300); pg.wait_for_timeout(1000)
                ok(t + " vertical swipe over a card scrolls the page, not the carousel", pg.evaluate("scrollY") > 50 and pg.evaluate(f"document.querySelector('{rail}').scrollLeft") == sl, f"scrollY={pg.evaluate('scrollY')}")
                pg.evaluate("scrollTo(0,0)")
            pg.evaluate(f"document.querySelector('{rail}').scrollLeft=0"); pg.wait_for_timeout(300)
            # ---- archive ----
            pg.locator("#p-pepper").scroll_into_view_if_needed(); pg.wait_for_timeout(400)
            pg.locator("#p-pepper .archbtn").tap() if mob else pg.locator("#p-pepper .archbtn").click()
            pg.wait_for_timeout(200)
            ok(t + " archived card leaves carousel", pg.locator("#projects #p-pepper").count() == 0 and pg.locator(".rail .card").count() == 4)
            ok(t + " undo toast shown", pg.locator("#toast.show #undo").is_visible())
            ok(t + " Archived (1) section", pg.is_visible("#archPanel summary") and "(1)" in pg.inner_text("#archCount"))
            pg.click("#undo"); pg.wait_for_timeout(200)
            ok(t + " undo restores", pg.locator("#projects #p-pepper").count() == 1 and pg.is_hidden("#archPanel"))
            pg.locator("#p-pepper").scroll_into_view_if_needed(); pg.wait_for_timeout(400)
            pg.locator("#p-pepper .archbtn").click(); pg.wait_for_timeout(5600)
            ok(t + " toast auto-hides", not pg.locator("#toast.show").count())
            pg.reload(wait_until="networkidle"); pg.wait_for_selector(".card")
            ok(t + " archive persists across reload", pg.locator("#projects #p-pepper").count() == 0 and "(1)" in pg.inner_text("#archCount"), pg.evaluate("localStorage.getItem('mc-archived')"))
            pg.click("#archPanel summary"); pg.click("[data-unarchive=pepper]"); pg.wait_for_timeout(200)
            ok(t + " unarchive works", pg.locator("#projects #p-pepper").count() == 1 and pg.is_hidden("#archPanel"))
            pg.reload(wait_until="networkidle"); pg.wait_for_selector(".card")
            ok(t + " unarchive persists", pg.locator(".rail .card").count() == 5, pg.evaluate("localStorage.getItem('mc-archived')"))
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
