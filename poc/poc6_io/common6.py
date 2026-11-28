"""PoC-6 の共通部品: 空行の代わりの行、クリップボード（除外の印つきの書き込み、テキストと HTML の同時の読み取り）、CF_HTML の厳密な読み方。"""
from __future__ import annotations

import ctypes
import msvcrt
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (ROOT, ROOT / "manual"):
    sys.path.insert(0, str(p))
import clip  # noqa: E402
from clip import CF_HTML, CF_UNICODETEXT, GMEM_MOVEABLE, _open, k32, u32  # noqa: E402
from common.report import OUT_DIR  # noqa: E402

OUT = OUT_DIR / "poc6"
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 空行の代わりの行（spec-file-protocol 9.6）


def choose_filler(texts) -> str:
    """どの文脈ファイルにも「その行そのもの」として現れない、最短の空白だけの行。"""
    for n in range(1, 17):
        f = " " * n
        if all(f not in t.replace("\r\n", "\n").split("\n") for t in texts):
            return f
    raise ValueError("代わりの行を選べない")


def apply_filler(text: str, filler: str) -> str:
    return "\n".join(filler if line == "" else line for line in text.split("\n"))


def restore_filler(lines: list[str], filler: str) -> list[str]:
    return ["" if line == filler else line for line in lines]


# ---------------------------------------------------------------- クリップボード

F_EXCLUDE = u32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")
F_HISTORY = u32.RegisterClipboardFormatW("CanIncludeInClipboardHistory")
F_CLOUD = u32.RegisterClipboardFormatW("CanUploadToCloudClipboard")
F_PWMGR = u32.RegisterClipboardFormatW("Clipboard Viewer Ignore")


def _global(data: bytes):
    h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    p = k32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    k32.GlobalUnlock(h)
    return h


def set_text_private(text: str, private: bool = True) -> int:
    """テキストを入れる。private なら履歴とクラウドへの同期から除外する印も入れる。書き込み後の更新番号を返す。"""
    handles = [(CF_UNICODETEXT, _global((text + "\0").encode("utf-16-le")))]
    if private:
        zero = (0).to_bytes(4, "little")
        handles += [(F_HISTORY, _global(zero)), (F_CLOUD, _global(zero)), (F_EXCLUDE, _global(b"\0"))]
    _open()
    try:
        u32.EmptyClipboard()
        for fmt, h in handles:
            if not u32.SetClipboardData(fmt, h):
                k32.GlobalFree(h)
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        u32.CloseClipboard()
    return clip.sequence()


def _read(fmt) -> bytes | None:
    h = u32.GetClipboardData(fmt)
    if not h:
        return None
    p = k32.GlobalLock(h)
    try:
        return ctypes.string_at(p, k32.GlobalSize(h))
    finally:
        k32.GlobalUnlock(h)


def read_both() -> dict | None:
    """1 回の OpenClipboard の中でテキストと HTML を読む。前後で更新番号が変われば None（読み直す）。"""
    seq = clip.sequence()
    _open()
    try:
        excluded = bool(u32.IsClipboardFormatAvailable(F_EXCLUDE) or u32.IsClipboardFormatAvailable(F_PWMGR))
        text = html = None
        if not excluded:
            t = _read(CF_UNICODETEXT)
            text = t.decode("utf-16-le", "replace").split("\0", 1)[0] if t else None
            html = _read(CF_HTML) if u32.IsClipboardFormatAvailable(CF_HTML) else None
    finally:
        u32.CloseClipboard()
    if clip.sequence() != seq:
        return None
    return {"seq": seq, "excluded": excluded, "text": text, "html": html.split(b"\0", 1)[0] if html else None}


def clear_if_ours(seq: int) -> bool:
    """更新番号が自分の書き込みのときのままなら、クリップボードを空にする。"""
    if clip.sequence() != seq:
        return False
    _open()
    try:
        u32.EmptyClipboard()
    finally:
        u32.CloseClipboard()
    return True


# ---------------------------------------------------------------- CF_HTML


def parse_cf_html(raw: bytes) -> dict:
    """ヘッダのバイト位置で断片を切り出し、UTF-8 として厳密に復号する。"""
    head = {}
    for m in re.finditer(rb"^(Version|StartHTML|EndHTML|StartFragment|EndFragment|SourceURL):(.*?)\r?$", raw[:600], re.M):
        head[m.group(1).decode()] = m.group(2).decode("ascii", "replace").strip()
    res = {"source_url_host": None, "by_offset": False, "strict_utf8": True, "fragment": None}
    if "SourceURL" in head:
        res["source_url_host"] = re.sub(r"^https?://([^/]+).*$", r"\1", head["SourceURL"])
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        res["strict_utf8"] = False
    if "StartFragment" not in head:  # 自動の方式で横取りした HTML（CF_HTML のヘッダが無い）
        res["by_offset"] = None
    try:
        sf, ef = int(head["StartFragment"]), int(head["EndFragment"])
        res["fragment"] = raw[sf:ef].decode("utf-8")
        res["by_offset"] = True
    except (KeyError, ValueError, UnicodeDecodeError):
        s = raw.decode("utf-8", "replace")
        m = re.search(r"<!--StartFragment-->(.*)<!--EndFragment-->", s, re.S)
        res["fragment"] = m.group(1) if m else s
    return res


# ---------------------------------------------------------------- 回答を待つ（spec-browser-driver 13.2）


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def wait_answer(tid: str, sent: str, timeout: float = 1800, want=("LLMC-DONE", "LLMC-PLAN"), keys: str = "") -> dict:
    """回答のコピーを待つ。keys に書いたキーが押されたら {"key": キー} を返す（失敗の報告など）。"""
    start_seq = clip.sequence()
    last = start_seq
    t0 = time.time()
    sent_n = norm(sent)
    while time.time() - t0 < timeout:
        time.sleep(0.4)
        while keys and msvcrt.kbhit():
            ch = msvcrt.getwch().lower()
            if ch in keys:
                return {"key": ch}
        s = clip.sequence()
        if s == last:
            continue
        last = s
        try:
            got = read_both()
        except OSError:
            continue
        if got is None:
            last = -1  # 読み直す
            continue
        t = got["text"] or ""
        if got["excluded"]:
            why = "除外の印があるので読まない"
        elif not got["html"]:
            why = "HTML が無い"
        elif tid not in t.upper():
            why = "このターンの ID が無い"
        elif want and not any(re.search(rf"{w}\b[^\n]*id={tid}", t, re.I) for w in want):
            why = "このターンの LLMC-DONE / LLMC-PLAN が無い"
        elif norm(t) == sent_n:
            why = "送った本文と同じ"
        else:
            got["seconds"] = round(time.time() - t0, 1)
            return got
        print(f"  （コピーを無視しました: {why}、{len(t)} 文字）", file=sys.stderr)
    return {"timeout": True}


HINTS = {  # 書式どおりでない回答の中身を、英数字のコードで示す（--short の要約でも読めるように）
    "DL": r"ダウンロード|download|添付|リンク|ファイルとして(作成|生成|用意|保存)",
    "LIMIT": r"上限|長すぎ|長い|制限|too long|limit",
    "REFUSE": r"申し訳|できません|お応えできません|cannot|can't|unable",
    "SPLIT": r"分割|複数回|続き|分けて",
    "CODE": r"Python|コードを実行|スクリプト|code interpreter",
    "ASK": r"[?？]\s*$|よろしいですか|しますか",
}


def response_hints(text: str, html_raw: bytes | None) -> dict:
    """回答が書式どおりでないときに、何が起きたかの手がかりを返す。"""
    t = text or ""
    frag = parse_cf_html(html_raw)["fragment"] if html_raw else ""
    # 手がかりは、コードブロックの外の文章だけから探す（ファイルの中身の語に反応しないため）
    prose = re.sub(r"<[^>]+>", " ", re.sub(r"<(pre|style|head)[^>]*>.*?</\1>", " ", frag, flags=re.S)) if frag else t
    found = [k for k, pat in HINTS.items() if re.search(pat, prose, re.I | re.M)]
    return {"hint": "+".join(found) or "none", "links": len(re.findall(r"<a\s", frag)), "pres": len(re.findall(r"<pre", frag)),
            "imgs": len(re.findall(r"<img", frag)), "buttons": len(re.findall(r"<button", frag)),
            "llmc_lines": sum(1 for x in t.split("\n") if x.strip().startswith("LLMC-"))}


def short_tid(tid: str) -> str:
    return tid[:2] + "****"


# ---------------------------------------------------------------- 送り方（人が送信する / 自動）

PRE_JS = r"""(tid) => Array.from(document.querySelectorAll('main pre')).filter(p => p.textContent.includes('id=' + tid))
  .map(p => ({textContent: p.textContent, innerText: p.innerText,
              tags: Array.from(new Set(Array.from(p.querySelectorAll('*')).map(e => e.tagName.toLowerCase()))).sort()}))"""


FACTS_JS = r"""() => {
  const qs = Array.from(document.querySelectorAll('[data-testid=chatQuestion]'));
  const q = qs[qs.length - 1];
  const after = el => !q || (q.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
  const main = document.querySelector('main') || document.body;
  const links = Array.from(main.querySelectorAll('a[href]')).filter(after);
  const kind = h => /sharepoint|onedrive|1drv/i.test(h) ? 'sp' : /blob:|download/i.test(h) ? 'dl' : 'other';
  const kinds = {};
  links.forEach(a => { const k = kind(a.href); kinds[k] = (kinds[k] || 0) + 1; });
  const btn = Array.from(main.querySelectorAll('button')).filter(after)
    .map(b => (b.getAttribute('aria-label') || b.textContent || '')).filter(t => /ダウンロード|Download|開く|Open|保存|Save/i.test(t));
  const files = Array.from(main.querySelectorAll('[data-testid*=file i], [class*=file i], [class*=attachment i]')).filter(after).length;
  return {dom_links: kinds, dom_dl_buttons: btn.length, dom_file_like: files};
}"""


class ManualSender:
    """人が送信する方式（個人版）。プロンプトをクリップボードに入れ、回答のコピーを待つ。"""
    auto = False

    def ask(self, tid: str, text: str, new_chat: bool, label: str, keys: str = "", want=("LLMC-DONE", "LLMC-PLAN")) -> dict:
        seq = set_text_private(text)
        where = "【新しいチャット】" if new_chat else "【同じチャット】"
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"[{label}] ID {short_tid(tid)}、{len(text):,} 文字。Copilot の{where}に貼り付けて（Ctrl+V）送信し、回答の下の「コピー」を押してください。",
              file=sys.stderr)
        if keys:
            print("  エラーで送れない・回答が止まったときは f、添付に変わったら a、飛ばすなら s を押してください。", file=sys.stderr)
        got = wait_answer(tid, text, want=want, keys=keys)
        clear_if_ours(seq)
        return got

    def dom_pres(self, tid: str):
        return None

    def response_facts(self) -> dict:
        return {}

    def close(self):
        pass


class AutoSender:
    """自動の方式（組織版、最小化した画面ありの Edge）。貼り付けイベントで入れて送信し、「応答のコピー」を横取りする。"""
    auto = True

    def __init__(self, url: str, variant: str = "msedge-headed", minimize: bool = True, timeout: float = 600):
        import os
        sys.path.insert(0, str(ROOT / "poc2_page"))
        sys.path.insert(0, str(ROOT / "poc3_auto"))
        os.environ["POC_URL"] = url
        from playwright.sync_api import sync_playwright

        from cp import CLIP_HOOK, open_copilot
        from roundtrip import Driver
        self.timeout = timeout
        self.pw = sync_playwright().start()
        self.ctx, self.page, self.info = open_copilot(self.pw, variant=variant, init_script=CLIP_HOOK)
        if not self.info["ready"]:
            raise RuntimeError(f"画面の準備ができない: {self.info}")
        if minimize and variant.endswith("headed"):
            cdp = self.ctx.new_cdp_session(self.page)
            wid = cdp.send("Browser.getWindowForTarget")["windowId"]
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}})
        self.drv = Driver(self.page, self.ctx, url)

    def ask(self, tid: str, text: str, new_chat: bool, label: str, keys: str = "", want=None) -> dict:
        print(f"[{label}] ID {short_tid(tid)}、{len(text):,} 文字を自動で送信します", file=sys.stderr)
        if new_chat:
            self.drv.new_chat()
        self.drv.put(text, "paste_text")  # 空行の代わりの行は、呼び出し元で入れてある
        t0 = time.time()
        w = self.drv.send_and_wait(timeout=self.timeout)
        if not w["ok"]:
            return {"error": w.get("error")}
        t, h = self.drv.copy_last()
        if not h:
            return {"error": "コピーの HTML を横取りできなかった"}
        return {"text": t or "", "html": h.encode("utf-8"), "seconds": round(time.time() - t0, 1)}

    def dom_pres(self, tid: str):
        return self.page.evaluate(PRE_JS, tid)

    def response_facts(self) -> dict:
        """最後の利用者のメッセージより後ろ（= 最後の回答）にある、リンク・ボタン・ファイルらしい要素を数える。
        リンク先のホスト名は記録しない（社内のテナント名を含み得るため）。種類だけを数える。"""
        try:
            return self.page.evaluate(FACTS_JS)
        except Exception as e:  # noqa: BLE001
            return {"facts_error": str(e)[:60]}

    def close(self):
        try:
            self.ctx.close()
        finally:
            self.pw.stop()


def make_sender(args):
    return AutoSender(args.url, args.variant) if args.auto else ManualSender()


def add_sender_args(ap):
    ap.add_argument("--auto", action="store_true", help="自動の方式（組織版）。--url が必要")
    ap.add_argument("--url", help="自動の方式で開く URL（例: https://m365.cloud.microsoft/chat）")
    ap.add_argument("--variant", default="msedge-headed")
