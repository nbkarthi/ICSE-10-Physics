"""Accessibility and phone-layout audit of every top-level HTML page (axe-core, 375px and 1280px, light and dark).

Run: uv run --no-project --with playwright --with axe-playwright-python python scripts/audit_a11y.py
If Playwright's browser is not installed, set CHROMIUM_PATH to a Chromium/headless-shell binary.
Expect no violations and no horizontal scroll. "small_targets" lists controls under 40px; hidden radio
inputs (opacity 0) whose visible labels are 44px are false positives.
"""
import json, sys, threading, http.server, functools, glob, os
from playwright.sync_api import sync_playwright
from axe_playwright_python.sync_playwright import Axe

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
H.log_message = lambda *a, **k: None
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
pages = sorted(os.path.basename(p) for p in glob.glob(ROOT + "/*.html"))
axe = Axe()
out = {}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or None)
    for name in pages:
        for scheme in ("light", "dark"):
            for label, (w, h) in {"phone": (375, 812), "desktop": (1280, 800)}.items():
                ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme)
                pg = ctx.new_page()
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)[:150]))
                pg.goto(f"http://127.0.0.1:8765/{name}", wait_until="load")
                pg.wait_for_timeout(600)
                res = axe.run(pg, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa", "best-practice"]}})
                viol = [(v["id"], v["impact"], len(v["nodes"]), v["nodes"][0]["target"][0][:60] if v["nodes"] else "") for v in res.response["violations"]]
                over = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                small = pg.evaluate("""() => [...document.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,[role=button],[tabindex]:not([tabindex="-1"])')]
                    .filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&(r.height<40||r.width<40)&&getComputedStyle(e).visibility!=='hidden'})
                    .map(e=>(e.id||e.className||e.tagName)+':'+Math.round(e.getBoundingClientRect().width)+'x'+Math.round(e.getBoundingClientRect().height)).slice(0,8)""")
                out[f"{name} {scheme} {label}"] = {"violations": viol, "hscroll_px": over, "small_targets": small, "js_errors": errs}
                ctx.close()
    b.close()
for k, v in out.items():
    print(k, json.dumps(v))
