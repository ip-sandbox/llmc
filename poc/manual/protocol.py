"""llmc/1 の解析器（PoC 版）。docs/spec-file-protocol.md の 4〜8 章の主要部分を実装する。

未実装: 区分付きテキスト（DOM 復元）、READ の処理、文字コードの判定（UTF-8 のみ）、実パスの確認。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

ZW = "​‌‍﻿"
DIRECTIVE = re.compile(r"^LLMC-(PLAN|FILE|END|DELETE|READ|DONE)\b(.*)$")
ATTR = re.compile(r"""([A-Za-z_][\w-]*)=(?:"([^"]*)"|'([^']*)'|(\S+))""")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[0-9¹²³]|LPT[0-9¹²³])(\..*)?$", re.I)
ELISION = re.compile(r"^\s*(\.\.\.|…)\s*$|(省略|以下同じ|以下同様|変更なし|変更しない部分|rest of (the )?file|unchanged|existing code)", re.I)


def content_sha(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()[:8]


def norm_path(p: str) -> str:
    p = unicodedata.normalize("NFC", p).replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return re.sub(r"/+", "/", p)


def path_key(p: str) -> str:
    return "/".join(c.upper() for c in norm_path(p).split("/"))


def check_path(p: str) -> str | None:
    """文字列として不正なら理由を返す（spec-file-protocol 8.2）。"""
    n = norm_path(p)
    if not n or n.endswith("/"):
        return "空、または / で終わる"
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        return "絶対パス・ドライブ指定"
    if ":" in n:
        return ": を含む"
    if re.search(r'[\x00-\x1f<>"|?*]', n):
        return "使えない文字"
    for c in n.split("/"):
        if c in ("", ".", ".."):
            return ". や .. の構成要素"
        if c[-1] in ". ":
            return "末尾がドットか空白"
        if RESERVED.match(c):
            return "予約デバイス名"
        if re.search(r"~\d", c):
            return "8.3 形式の短い名前に見える"
        if len(c) > 255:
            return "長すぎる"
    return None


def parse_attrs(s: str) -> dict[str, str]:
    out = {}
    for m in ATTR.finditer(s):
        out[m.group(1)] = next(g for g in m.groups()[1:] if g is not None)
    return out


def clean_outside(line: str) -> str:
    s = line.strip().strip(ZW).strip()
    s = re.sub(r"^(>\s*)+", "", s)
    s = re.sub(r"^[-*]\s+", "", s)
    s = s.strip("`*").strip()
    return s


@dataclass
class Block:
    path: str
    base: str | None
    lines: list[str] = field(default_factory=list)
    complete: bool = False
    in_info: bool = False

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class Result:
    kind: str = "no_protocol"   # no_protocol / invalid / truncated / empty / complete
    plan: list[tuple[str, str]] = field(default_factory=list)  # (op, path)
    files: list[Block] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)
    done: dict | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fence_lines: int = 0

    def summary(self) -> dict:
        return {"kind": self.kind, "plan": self.plan,
                "files": [(b.path, "complete" if b.complete else "unterminated", len(b.lines)) for b in self.files],
                "deletes": self.deletes, "done": self.done, "errors": self.errors, "warnings": self.warnings,
                "fence_lines": self.fence_lines}


def parse(text: str, tid: str, rev: str | None = None, ctx_sha: dict[str, str] | None = None,
          allowed=lambda p: True) -> Result:
    r = Result()
    tid_u = tid.upper()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cur: Block | None = None
    fence: tuple[str, int] | None = None  # ファイルの外側でのフェンスの開閉
    seen_any = False
    after_done = False

    def id_ok(attrs):
        return attrs.get("id", "").upper() == tid_u

    for raw in lines:
        if FENCE.match(raw):
            r.fence_lines += 1
        if cur is not None:
            s = raw.strip().strip(ZW).strip()
            m = DIRECTIVE.match(s)
            if m:
                kind, attrs = m.group(1), parse_attrs(m.group(2))
                if kind == "END" and id_ok(attrs) and path_key(attrs.get("path", "")) == path_key(cur.path):
                    cur.complete = True
                    cur = None
                    continue
                if kind in ("FILE", "DONE") and id_ok(attrs):
                    r.errors.append(f"E_UNTERMINATED: {cur.path}")
                    cur = None  # 打ち切って下で処理する
                elif kind == "END":
                    r.warnings.append(f"W_FOREIGN_END: {attrs.get('path')}")
                    cur.lines.append(raw)
                    continue
                else:
                    cur.lines.append(raw)
                    continue
            else:
                cur.lines.append(raw)
                continue
        # ---- ファイルの外側
        fm = FENCE.match(raw)
        if fm:
            mark, info = fm.group(1), fm.group(2).strip()
            if "LLMC-FILE" in info:
                r.errors.append("E_HEADER_IN_INFO")
            if fence is None:
                fence = (mark[0], len(mark))
            elif mark[0] == fence[0] and len(mark) >= fence[1] and not info:
                fence = None
            continue
        s = clean_outside(raw)
        if s.startswith("LLMC-CTX"):
            r.warnings.append("W_ECHOED_CONTEXT")
            continue
        m = DIRECTIVE.match(s)
        if not m:
            continue
        seen_any = True
        kind, attrs = m.group(1), parse_attrs(m.group(2))
        if after_done:
            r.errors.append(f"E_AFTER_DONE: {kind}")
        if not id_ok(attrs):
            r.errors.append(f"E_ID_MISMATCH: {kind} id={attrs.get('id')}")
            continue
        if kind == "FILE":
            p = attrs.get("path", "")
            cur = Block(path=norm_path(p), base=attrs.get("base"))
            r.files.append(cur)
            if fence is None:
                r.warnings.append(f"W_FILE_OUTSIDE_FENCE: {p}")
            continue
        if kind == "DONE":
            if r.done is not None:
                r.errors.append("E_MULTIPLE_DONE")
            r.done = attrs
            after_done = True
            continue
        if kind == "END":
            r.warnings.append(f"W_STRAY_END: {attrs.get('path')}")
            continue
        if fence is None:
            r.errors.append(f"E_RENDERED_DIRECTIVE: {kind}")
            continue
        if kind == "PLAN":
            for op in ("write", "delete", "read"):
                if op in attrs:
                    r.plan.append((op, norm_path(attrs[op])))
        elif kind == "DELETE":
            r.deletes.append(norm_path(attrs.get("path", "")))
        elif kind == "READ":
            r.reads.append(norm_path(attrs.get("path", "")))

    if cur is not None:
        r.errors.append(f"E_UNTERMINATED: {cur.path}")

    # ---- 検査
    if r.done is not None:
        if r.done.get("v") != "1":
            r.warnings.append(f"W_VERSION_MISMATCH: {r.done.get('v')}")
        if rev and r.done.get("rev") != rev:
            r.warnings.append(f"W_REV_MISMATCH: {r.done.get('rev')}")
    ops = [("write", b.path) for b in r.files if b.complete] + [("delete", p) for p in r.deletes] + \
          [("read", p) for p in r.reads]
    keys = [(o, path_key(p)) for o, p in ops]
    if len(set(k[1] for k in keys)) != len(keys):
        r.errors.append("E_DUPLICATE_PATH")
    if ops and not r.plan:
        r.errors.append("E_NO_PLAN")
    for _o, p in ops:
        why = check_path(p)
        if why:
            r.errors.append(f"E_PATH_INVALID: {p}（{why}）")
        elif not allowed(p):
            r.errors.append(f"E_PATH_DENIED: {p}")
    for b in r.files:
        if not b.complete:
            continue
        if ctx_sha is not None:
            want = ctx_sha.get(path_key(b.path))
            if want and b.base != want:
                r.errors.append(f"E_STALE_BASE: {b.path} base={b.base} 期待={want}")
            if not want and b.base not in ("new", None):
                r.warnings.append(f"W_BASE_FOR_NEW: {b.path} base={b.base}")
            if want is None and b.base is None:
                pass
        if any(ELISION.search(l) for l in b.lines):
            r.warnings.append(f"W_SUSPECT_ELISION: {b.path}")
        if any(l.strip().startswith("LLMC-") for l in b.lines):
            r.warnings.append(f"W_DIRECTIVE_IN_CONTENT: {b.path}")

    # ---- 分類（spec-file-protocol 6.4）
    hard = ("E_ID_MISMATCH", "E_HEADER_IN_INFO", "E_MULTIPLE_DONE", "E_AFTER_DONE", "E_RENDERED_DIRECTIVE")
    if not seen_any:
        r.kind = "no_protocol"
    elif any(e.startswith(hard) for e in r.errors):
        r.kind = "invalid"
    elif r.done is None or any(not b.complete for b in r.files):
        r.kind = "truncated"
    else:
        plan_set = {(o, path_key(p)) for o, p in r.plan}
        if plan_set != set(keys):
            r.errors.append(f"E_PLAN_MISMATCH: 計画={sorted(r.plan)} 実際={sorted(ops)}")
        if r.errors:
            r.kind = "invalid"
        elif not ops and not r.plan:
            r.kind = "empty"
        else:
            r.kind = "complete"
    return r
