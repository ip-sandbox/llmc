"""クリップボードの HTML（CF_HTML）から、区分（code / text）の列を作る。spec-file-protocol 6.1・6.5。"""
from __future__ import annotations

import re
from html.parser import HTMLParser

BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "ul", "ol", "table"}


def cf_html_fragment(raw: str) -> str:
    """CF_HTML のヘッダ（StartFragment など）を取り除き、断片の HTML を返す。"""
    m = re.search(r"<!--StartFragment-->(.*)<!--EndFragment-->", raw, re.S)
    if m:
        return m.group(1)
    i = raw.find("<")
    return raw[i:] if i >= 0 else raw


class _Seg(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.segs: list[list] = []  # [kind, text]
        self.pre = 0
        self.skip = 0

    def _text(self, kind: str, s: str):
        if self.segs and self.segs[-1][0] == kind and kind == "text":
            self.segs[-1][1] += s
        else:
            self.segs.append([kind, s])

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self.skip += 1
        elif tag == "pre":
            self.pre += 1
            if self.pre == 1:
                self.segs.append(["code", ""])
        elif tag == "br":
            if self.pre:
                self.segs[-1][1] += "\n"
            else:
                self._text("text", "\n")
        elif tag in BLOCK_TAGS and not self.pre:
            self._text("text", "\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            if self.pre == 0:
                self._text("text", "\n")
        elif tag in BLOCK_TAGS and not self.pre:
            self._text("text", "\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.pre:
            self.segs[-1][1] += data
        else:
            self._text("text", data)


def segments(html: str) -> list[tuple[str, str]]:
    p = _Seg()
    p.feed(cf_html_fragment(html))
    p.close()
    out = []
    for kind, text in p.segs:
        text = text.replace("\r\n", "\n")
        if kind == "code":
            text = text[:-1] if text.endswith("\n") else text
        if kind == "text" and not text.strip():
            continue
        out.append((kind, text))
    return out
