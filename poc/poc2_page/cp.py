"""PoC-2 共通: Edge のヘッドレスで Copilot を開き、必要なら「Sign in」で再ログインする。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "poc1_login"))
from common_browser import URL, launch  # noqa: E402
from probe_state import SIGNIN  # noqa: E402

INPUT = "span[role=textbox][contenteditable=true]"
ZW = "\u200b\u200c\u200d\ufeff"

# DOM の構造を JS で要約する。テキストは記録しない（aria-label、placeholder、ボタンの名前だけ）
# サイドバー（nav, aside, 会話の一覧）は除外する
SKELETON_JS = r"""
(root) => {
  const SKIP = el => el.closest('nav, aside, [role=navigation], [role=complementary]');
  const out = [];
  const attrs = el => {
    const a = {};
    for (const at of el.attributes) {
      if (/^(data-|aria-|role$|type$|contenteditable$|id$|name$|placeholder$|title$)/.test(at.name)) {
        let v = at.value;
        if (at.name === 'aria-label' || at.name === 'placeholder' || at.name === 'title') v = v.slice(0, 40);
        else v = v.slice(0, 30);
        a[at.name] = v;
      }
    }
    return a;
  };
  const walk = (el, depth) => {
    if (depth > 40 || out.length > 1500) return;
    if (SKIP(el)) return;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') return;
    const a = attrs(el);
    const interesting = Object.keys(a).length || ['BUTTON','TEXTAREA','INPUT','PRE','CODE','MAIN','FORM','ARTICLE','SECTION'].includes(el.tagName);
    if (interesting) out.push({d: depth, t: el.tagName.toLowerCase(), a, n: el.children.length,
                               cls: (el.className && typeof el.className === 'string') ? el.className.split(/\s+/).slice(0,3).join('.').slice(0,60) : ''});
    for (const c of el.children) walk(c, depth + 1);
  };
  walk(root || document.body, 0);
  return out;
}
"""


def open_copilot(pw, variant: str = "msedge-headless", relogin_wait: float = 150, init_script: str | None = None):
    ctx = launch(pw, variant)
    if init_script:
        ctx.add_init_script(init_script)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(URL, timeout=60000)
    t0 = time.time()
    info = {"relogin": False}
    # 入力欄が出るまで少し待つ
    for _ in range(20):
        if page.locator(INPUT).count() > 0:
            break
        page.wait_for_timeout(500)
    if page.locator(INPUT).count() == 0:
        page.get_by_role("button", name=SIGNIN).first.click(timeout=15000)
        info["relogin"] = True
        while time.time() - t0 < relogin_wait:
            # 同期 API では time.sleep の間はイベントが処理されず page.url が古いままになる。
            # ページに問い合わせ、待つときは wait_for_timeout を使う
            try:
                host = page.evaluate("location.hostname") or ""
                if not host.startswith("login.") and page.locator(INPUT).count() > 0:
                    break
            except Exception:  # noqa: BLE001  遷移中は問い合わせが失敗する
                pass
            page.wait_for_timeout(500)
    info["ready"] = page.locator(INPUT).count() > 0
    try:
        info["host"] = page.evaluate("location.hostname")
    except Exception:  # noqa: BLE001
        info["host"] = None
    info["seconds"] = round(time.time() - t0, 1)
    return ctx, page, info


def print_skeleton(nodes, max_lines=400):
    import json
    for n in nodes[:max_lines]:
        print("  " * min(n["d"], 30) + n["t"], (("." + n["cls"]) if n["cls"] else ""), json.dumps(n["a"], ensure_ascii=False), f"[{n['n']}]")


# クリップボードへの書き込みを横取りする（OS のクリップボードには書かない）。spec-browser-driver 7.1
CLIP_HOOK = r"""
(() => {
  if (window.__llmc) return;
  const st = window.__llmc = {armed: false, got: []};
  const save = (kind, v) => { st.got.push({kind, v}); };
  const c = navigator.clipboard;
  if (c) {
    const ow = c.writeText && c.writeText.bind(c), ox = c.write && c.write.bind(c);
    c.writeText = async (t) => { if (st.armed) { save('writeText', String(t)); return; } return ow(t); };
    c.write = async (items) => {
      if (!st.armed) return ox(items);
      for (const it of items) for (const ty of it.types) {
        const b = await it.getType(ty); save('write:' + ty, await b.text());
      }
    };
  }
  const oexec = document.execCommand.bind(document);
  document.execCommand = (cmd, ...a) => {
    if (st.armed && String(cmd).toLowerCase() === 'copy') {
      const dt = new DataTransfer();
      const ev = new ClipboardEvent('copy', {clipboardData: dt, bubbles: true, cancelable: true});
      (document.activeElement || document.body).dispatchEvent(ev);
      for (const ty of dt.types) save('execCommand:' + ty, dt.getData(ty));
      return true;
    }
    return oexec(cmd, ...a);
  };
  const osd = DataTransfer.prototype.setData;
  DataTransfer.prototype.setData = function (ty, v) { if (st.armed) save('setData:' + ty, v); return osd.call(this, ty, v); };
  document.addEventListener('copy', (e) => { if (st.armed) e.preventDefault(); }, true);
})();
"""
