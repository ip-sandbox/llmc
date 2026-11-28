"""PoC-7 (a)〜(e): ループの模擬（同じチャットで 10 ラウンド）。

架空のベンチマーク（llmc が用意する bench.py。AI のコードは実行しない。AI が書くのは設定の YAML だけ）の
スループットを上げるよう、config/app.yaml の調整を 10 ラウンド依頼する。spec-loop の流れ（基準 → 依頼 → 解析 →
書き込み → 実行 → 評価 → 次の依頼）をそのまま小さく作ったもの。

記録すること
  - ターンごとの解析の分類・エラー・警告（形式違反の率、省略、base の誤り）
  - 読み取り要求（docs/hints.md は送らず、読み取りだけを許可する。AI が LLMC-READ で頼めば返す）
  - 続きの依頼・出し直しが通ったか
  - 指標の推移（改善するか、同じ失敗を繰り返すか）
  - 自動の方式だけ: 5 ラウンド目の後に会話の URL を開き直して続けられるか（--reopen-at）、回答までの秒数
規則は、1 ラウンド目と 5 ラウンドごとに長い版、それ以外は短い版（spec-agent 3.1）。

使い方:
  個人版（人が送信する）: .\\.venv\\Scripts\\python.exe poc7_loop\\loop_sim.py [--rounds 10]
  組織版（自動）:         .\\.venv\\Scripts\\python.exe poc7_loop\\loop_sim.py --auto --url https://m365.cloud.microsoft/chat
結果: out\\poc7-loop-report.md（自動は poc7-loop-auto-report.md）。最後に貼り付け用の要約を出す
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "poc6_io"))
sys.path.insert(0, str(HERE.parent))
from common6 import OUT, add_sender_args, apply_filler, choose_filler, make_sender, parse_cf_html, response_hints, restore_filler  # noqa: E402
import run as M  # noqa: E402
from common.report import Report  # noqa: E402
from htmlseg import segments  # noqa: E402
from protocol import content_sha, parse, path_key  # noqa: E402

CONFIG = """# 架空のサービスの設定（PoC 用）
server:
  # 同時に動かす作業者の数（1〜16）
  workers: 2
  # 待ち行列の長さ（10〜1000）
  queue: 50

  # 1 回にまとめて処理する件数（1〜64）
  batch: 4
cache:
  # キャッシュの大きさ（MB、0〜512）
  size_mb: 16
"""
BENCH = r'''"""架空のベンチマーク（PoC 用。llmc が用意する。決まった式でスループットを計算する）。"""
import re, sys
t = open(sys.argv[1], encoding="utf-8").read()
def get(k, lo, hi):
    m = re.search(rf"^\s*{k}:\s*(-?\d+)\s*$", t, re.M)
    if not m:
        print(f"ERROR: {k} が無い"); sys.exit(2)
    v = int(m.group(1))
    if not lo <= v <= hi:
        print(f"ERROR: {k}={v} は範囲 {lo}〜{hi} の外"); sys.exit(3)
    return v
w, q, b, c = get("workers", 1, 16), get("queue", 10, 1000), get("batch", 1, 64), get("size_mb", 0, 512)
if "#" not in t:
    print("ERROR: コメントが消えた"); sys.exit(4)
mem = w * 64 + c + b * 8
if mem > 900:
    print(f"ERROR: メモリ不足（推定 {mem} MB > 900 MB）"); sys.exit(5)
tp = min(w, 8) * 100 * (1 + min(b, 16) / 16) * (1 + min(c, 256) / 512) * min(1.0, q / (w * b * 2)) - max(0, w - 8) * 40
print(f"throughput={tp:.1f}")
print("RESULT: ok")
'''
HINTS = "# 架空の手引き（読み取り要求で返す）\n- workers は 8 を超えると切り替えの負荷で遅くなる\n- queue は workers × batch × 2 以上が必要\n"
CFG = "config/app.yaml"
GOAL = ("架空のサービスの設定 config/app.yaml を調整し、ベンチマーク bench.py の throughput をできるだけ上げてください。"
        "値の範囲はコメントのとおり。コメントは消さないでください。1 ラウンドで変える値は 1〜2 個にしてください。"
        "docs/hints.md に手引きがあります（送っていないので、必要なら読み取り要求で頼んでください）。")


def bench(ws: Path) -> dict:
    p = subprocess.run([sys.executable, str(ws / "bench.py"), str(ws / CFG)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    m = re.search(r"throughput=([0-9.]+)", p.stdout)
    return {"exit": p.returncode, "ok": p.returncode == 0 and "RESULT: ok" in p.stdout,
            "tp": float(m.group(1)) if m else None, "out": p.stdout.strip()[-200:]}


def build(tid, rnd, long_rules, last, history, ws, extra="") -> tuple[str, dict, dict]:
    t = (ws / CFG).read_text(encoding="utf-8")
    sha = {path_key(CFG): content_sha(t)}
    res = (f"終了コード {last['exit']}、成功 {'はい' if last['ok'] else 'いいえ'}、throughput={last['tp']}\n出力の末尾:\n"
           + "\n".join("> " + x for x in last["out"].split("\n")))
    hist = "\n".join(history[-8:]) or "（まだ無い）"
    body = [f"llmc プロトコル: llmc/1（規則の版 {M.REV}）\nこのターンの ID: {tid}\n", M.LONG if long_rules else M.SHORT, "",
            f"# 依頼（ラウンド {rnd}）", GOAL, extra, "", "# 書き込みを許可するパス", f"- {CFG}", "",
            "# 読み取りを許可するパス（読み取り要求で頼めるもの）", "- docs/hints.md", "", "# 前のラウンドの実行結果", res, "",
            "# 試行の履歴", hist, "", "# 現在のファイル（全文）", M.ctx_block(CFG, t), "",
            f"このターンの ID: {tid}（回答の LLMC- の行には、この ID を使ってください）"]
    return "\n".join(body), sha, {path_key(CFG): t}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--reopen-at", type=int, default=5, help="自動の方式で、このラウンドの後に会話の URL を開き直す（0 で行わない）")
    ap.add_argument("--read-at", type=int, default=3, help="このラウンドで、docs/hints.md を読み取り要求で読んでから提案するよう頼む（0 で頼まない）")
    add_sender_args(ap)
    a = ap.parse_args()
    if a.auto and not a.url:
        ap.error("--auto には --url が必要")
    rep = Report("poc7-loop-auto" if a.auto else "poc7-loop", "PoC-7: ループの模擬" + ("（自動）" if a.auto else ""))
    ws = OUT / (("poc7-ws-auto" if a.auto else "poc7-ws") + os.environ.get("LLMC_POC_REPORT_SUFFIX", ""))
    if ws.exists():
        shutil.rmtree(ws)
    (ws / "config").mkdir(parents=True)
    (ws / "docs").mkdir()
    (ws / CFG).write_bytes(CONFIG.encode("utf-8"))
    (ws / "bench.py").write_bytes(BENCH.encode("utf-8"))
    (ws / "docs/hints.md").write_bytes(HINTS.encode("utf-8"))
    last = bench(ws)
    best = last["tp"] if last["ok"] else None
    rep.add("基準", "ラウンド 0", "OK" if last["ok"] else "NG", {"tp": last["tp"]})
    history, stats = [], {"turns": 0, "kinds": {}, "errors": {}, "warnings": {}, "reads": 0, "conts": 0, "retries": 0}
    sender = make_sender(a)
    allowed_w = {path_key(CFG)}
    try:
        for rnd in range(1, a.rounds + 1):
            sec = f"ラウンド {rnd}"
            long_rules = rnd == 1 or rnd % 5 == 1
            tid = M.new_tid()
            # 1 回目の実行では、AI は読み取り要求を一度も使わなかった。読み取りの往復を確かめるため、このラウンドだけ明示的に頼む
            extra = ("このラウンドでは、提案の前に docs/hints.md を読み取り要求で読んでください。"
                     "このターンは読み取り要求だけを書き、ファイルは出力しないでください。読み取り要求の書き方: "
                     "計画のコードブロックに LLMC-PLAN id=<ID> read=\"docs/hints.md\"、別のコードブロックに "
                     "LLMC-READ id=<ID> path=\"docs/hints.md\"、最後に LLMC-DONE。llmc が中身を返すので、それを見てから提案してください。"
                     ) if rnd == a.read_at else ""
            text, sha, ctx = build(tid, rnd, long_rules, last, history, ws, extra)
            filler = choose_filler(ctx.values())
            turn, res, new_chat = 0, None, rnd == 1
            while turn < 5:
                turn += 1
                stats["turns"] += 1
                got = sender.ask(tid, apply_filler(text, filler), new_chat, f"R{rnd} T{turn}{' 長い規則' if long_rules and turn == 1 else ''}")
                new_chat = False
                if "error" in got or "timeout" in got:
                    rep.add(sec, f"T{turn} 回答", "NG", got.get("error", "時間切れ"))
                    res = None
                    break
                res = parse(None, tid, rev=M.REV, ctx_sha=sha, allowed=lambda p: path_key(p) in allowed_w | {path_key("docs/hints.md")},
                            segments=segments(parse_cf_html(got["html"])["fragment"]), ctx_text=ctx)
                stats["kinds"][res.kind] = stats["kinds"].get(res.kind, 0) + 1
                for e in res.errors:
                    k = e.split(":")[0]
                    stats["errors"][k] = stats["errors"].get(k, 0) + 1
                for w in res.warnings:
                    k = w.split(":")[0]
                    stats["warnings"][k] = stats["warnings"].get(k, 0) + 1
                info = {"k": res.kind, "E": [e.split(":")[0] for e in res.errors], "W": [w.split(":")[0] for w in res.warnings],
                        "reads": res.reads, "sec": got["seconds"], "chars": len(got["text"] or "")}
                if res.kind == "no_protocol":
                    info.update(response_hints(got["text"], got["html"]))
                rep.add(sec, f"T{turn}", "OK" if res.kind in ("complete", "empty") else "WARN" if res.reads else "NG", info)
                rep.write()
                tid = M.new_tid()
                if res.reads and not res.files:  # 読み取り要求に答える
                    stats["reads"] += 1
                    blocks = [M.ctx_block(p, (ws / p).read_text(encoding="utf-8")) for p in res.reads if path_key(p) == path_key("docs/hints.md")]
                    denied = [f'LLMC-CTX-DENIED path="{p}" reason="not_allowed"' for p in res.reads if path_key(p) != path_key("docs/hints.md")]
                    text = "\n".join([f"llmc プロトコル: llmc/1（規則の版 {M.REV}）\nこのターンの ID: {tid}\n", M.SHORT, "",
                                      "# 読み取り要求への返答", *blocks, *denied, "", "これを踏まえて、このラウンドの提案をしてください。", "",
                                      f"このターンの ID: {tid}（回答の LLMC- の行には、この ID を使ってください）"])
                    continue
                if res.kind == "truncated":
                    stats["conts"] += 1
                    text = build(tid, rnd, False, last, history, ws, "前の回答は途中で切れました。提案全体をもう一度出力してください。")[0]
                    continue
                if res.kind in ("invalid", "no_protocol") and turn == 1:
                    stats["retries"] += 1
                    errs = "、".join(e.split(":")[0] for e in res.errors) or "書式の行が無い"
                    text = build(tid, rnd, True, last, history, ws, f"前の回答は書式の誤り（{errs}）のため使えませんでした。規則どおりに出し直してください。")[0]
                    continue
                break
            if res is None or res.kind not in ("complete", "empty"):
                history.append(f"- ラウンド {rnd}: 形式違反（{res.kind if res else '回答なし'}）")
                continue
            if res.kind == "empty":
                rep.add(sec, "提案", "INFO", "改善案なし")
                break
            bad = [b.path for b in res.files if path_key(b.path) not in allowed_w]
            if bad or not res.files:
                rep.add(sec, "書き込み", "NG", {"許可されないパス": bad})
                history.append(f"- ラウンド {rnd}: 許可されないパス")
                continue
            for b in res.files:  # 空行の代わりの行を空行に戻す（1 回目の実行では戻しておらず、空行が空白 1 個の行になった）
                b.lines = restore_filler(b.lines, filler)
            M.apply(res, ws)
            ws_lines = [i + 1 for i, x in enumerate((ws / CFG).read_text(encoding="utf-8").split("\n")) if x and not x.strip()]
            if ws_lines:
                rep.add(sec, "空白だけの行", "WARN", {"行": ws_lines})
            last = bench(ws)
            improved = last["ok"] and (best is None or last["tp"] > best * 1.0001)
            if improved:
                best = last["tp"]
            rep.add(sec, "評価", "OK" if last["ok"] else "WARN", {"exit": last["exit"], "tp": last["tp"], "best": best, "改善": improved})
            rep.write()
            history.append(f"- ラウンド {rnd}: 成功={'はい' if last['ok'] else 'いいえ'} throughput={last['tp']}"
                           + ("（最良）" if improved else "") + ("" if last["ok"] else f" 出力: {last['out'][-60:]}"))
            if a.auto and a.reopen_at and rnd == a.reopen_at:
                try:
                    url = sender.page.url
                    sender.page.goto(url, timeout=60000)
                    from cp import INPUT
                    sender.page.wait_for_selector(INPUT, timeout=60000)
                    sender.page.wait_for_timeout(2000)
                    rep.add("会話の URL", f"ラウンド {rnd} の後に開き直す", "OK", {"conversation_url": "/chat/conversation/" in url})
                except Exception as e:  # noqa: BLE001
                    rep.add("会話の URL", f"ラウンド {rnd} の後に開き直す", "NG", str(e)[:80])
    finally:
        sender.close()
    rep.add("集計", "全体", "INFO", {"turns": stats["turns"], "kinds": stats["kinds"], "errors": stats["errors"],
                                    "warnings": stats["warnings"], "reads": stats["reads"], "conts": stats["conts"],
                                    "retries": stats["retries"], "best": best})
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    from common.digest import show
    show([rep.name])
    return 0


if __name__ == "__main__":
    sys.exit(main())
