"""PoC 共通: 結果の記録と、個人情報の置き換え（レポートはチャットに貼る前提）。"""
from __future__ import annotations

import datetime
import json
import os
import platform
import re
import sys
from pathlib import Path

POC_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = POC_ROOT / "out"

_REDACT_ENV = ("LOCALAPPDATA", "APPDATA", "OneDriveCommercial", "OneDriveConsumer", "OneDrive",
               "USERPROFILE", "HOMEPATH", "TEMP", "TMP", "USERDOMAIN", "COMPUTERNAME", "USERNAME")

_extra: list[tuple[str, str]] = []


def add_redaction(value: str, label: str) -> None:
    """環境変数以外の秘匿すべき値（SID など）を登録する。"""
    if value and len(value) >= 3:
        _extra.append((value, label))


def _pairs() -> list[tuple[str, str]]:
    pairs = list(_extra)
    for k in _REDACT_ENV:
        v = os.environ.get(k)
        if v and len(v) >= 3:
            pairs.append((v, f"<{k}>"))
            pairs.append((v.replace("\\", "/"), f"<{k}>"))
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def redact(obj):
    if isinstance(obj, str):
        s = obj
        for v, label in _pairs():
            s = re.sub(re.escape(v), label, s, flags=re.IGNORECASE)
        return s
    if isinstance(obj, dict):
        return {redact(k): redact(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


def first_line(e: BaseException, limit: int = 300) -> str:
    text = f"{type(e).__name__}: {e}".strip().splitlines()
    return (text[0] if text else type(e).__name__)[:limit]


class Report:
    """status は OK / NG / WARN / INFO / SKIP のいずれか。"""

    def __init__(self, name: str, title: str):
        self.name = name
        self.title = title
        self.items: list[dict] = []
        self.started = datetime.datetime.now()

    def add(self, section: str, item: str, status: str, detail=None) -> None:
        self.items.append({"section": section, "item": item, "status": status, "detail": detail})
        mark = {"OK": "o", "NG": "x", "WARN": "!", "INFO": "-", "SKIP": "s"}.get(status, "?")
        print(f"[{mark}] {section} / {item}", file=sys.stderr, flush=True)

    def to_markdown(self) -> str:
        lines = [f"## {self.title}", "",
                 f"- 実行日時: {self.started:%Y-%m-%d %H:%M}",
                 f"- Python: {platform.python_version()} ({platform.architecture()[0]})",
                 f"- OS: {platform.platform()}", ""]
        section = None
        for it in self.items:
            if it["section"] != section:
                section = it["section"]
                lines += ["", f"### {section}", "", "| 項目 | 結果 | 詳細 |", "|---|---|---|"]
            d = it["detail"]
            if isinstance(d, (dict, list)):
                d = json.dumps(d, ensure_ascii=False)
            d = "" if d is None else str(d)
            d = d.replace("|", "\\|").replace("\n", "<br>")
            lines.append(f"| {it['item']} | {it['status']} | {d} |")
        counts = {}
        for it in self.items:
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        lines += ["", "集計: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))]
        return redact("\n".join(lines))

    def write(self) -> Path:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        md = self.to_markdown()
        path = OUT_DIR / f"{self.name}-report.md"
        path.write_bytes(md.encode("utf-8"))
        (OUT_DIR / f"{self.name}-report.json").write_bytes(
            json.dumps(redact(self.items), ensure_ascii=False, indent=1).encode("utf-8"))
        return path


def is_windows() -> bool:
    return sys.platform == "win32"
