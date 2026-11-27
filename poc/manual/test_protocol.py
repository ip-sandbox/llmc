"""protocol.py の単体試験。python -m unittest poc\\manual\\test_protocol.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from protocol import check_path, content_sha, parse  # noqa: E402

T = "K7Q2MX"
F4 = "````"


def resp(*parts):
    return "\n".join(parts)


PLAN = f"{F4}text\nLLMC-PLAN id={T} write=\"config/app.yaml\"\n{F4}"
FILE = f"{F4}yaml\nLLMC-FILE id={T} path=\"config/app.yaml\" base=new\na: 1\n  b: 2\nLLMC-END id={T} path=\"config/app.yaml\"\n{F4}"
DONE = f"{F4}text\nLLMC-DONE v=1 id={T} rev=abc123\n{F4}"


class TestParse(unittest.TestCase):
    def test_complete(self):
        r = parse(resp(PLAN, FILE, "説明", DONE), T, rev="abc123")
        self.assertEqual(r.kind, "complete", r.summary())
        self.assertEqual(r.files[0].text, "a: 1\n  b: 2")

    def test_nested_fences_in_content(self):
        body = "# 見出し\n```python\nprint(1)\n```\n````\n入れ子\n````"
        f = f"`````markdown\nLLMC-FILE id={T} path=\"docs/a.md\" base=new\n{body}\nLLMC-END id={T} path=\"docs/a.md\"\n`````"
        p = f"{F4}\nLLMC-PLAN id={T} write=\"docs/a.md\"\n{F4}"
        r = parse(resp(p, f, DONE), T)
        self.assertEqual(r.kind, "complete", r.summary())
        self.assertEqual(r.files[0].text, body)

    def test_truncated(self):
        r = parse(resp(PLAN, FILE.rsplit("\n", 2)[0]), T)
        self.assertEqual(r.kind, "truncated")

    def test_missing_end_then_next_file(self):
        f1 = f"{F4}\nLLMC-FILE id={T} path=\"a.txt\" base=new\nx\n{F4}"
        f2 = f"{F4}\nLLMC-FILE id={T} path=\"b.txt\" base=new\ny\nLLMC-END id={T} path=\"b.txt\"\n{F4}"
        p = f"{F4}\nLLMC-PLAN id={T} write=\"a.txt\"\nLLMC-PLAN id={T} write=\"b.txt\"\n{F4}"
        r = parse(resp(p, f1, f2, DONE), T)
        self.assertEqual(r.kind, "truncated", r.summary())
        self.assertEqual([b.complete for b in r.files], [False, True])
        self.assertEqual(r.files[1].text, "y")

    def test_done_wrapped_in_backticks(self):
        r = parse(resp(PLAN, FILE, f"`LLMC-DONE v=1 id={T}`"), T)
        self.assertEqual(r.kind, "complete", r.summary())

    def test_wrong_id(self):
        r = parse(resp(PLAN.replace(T, "AAAAAA"), FILE, DONE), T)
        self.assertEqual(r.kind, "invalid")

    def test_plan_mismatch(self):
        p = f"{F4}\nLLMC-PLAN id={T} write=\"config/app.yaml\"\nLLMC-PLAN id={T} delete=\"x.txt\"\n{F4}"
        r = parse(resp(p, FILE, DONE), T)
        self.assertEqual(r.kind, "invalid")

    def test_plan_outside_fence(self):
        r = parse(resp(f"LLMC-PLAN id={T} write=\"config/app.yaml\"", FILE, DONE), T)
        self.assertEqual(r.kind, "invalid")

    def test_echoed_context(self):
        r = parse(f"{F4}\nLLMC-CTX path=\"a\" sha=1\nx\nLLMC-CTX-END path=\"a\"\n{F4}", T)
        self.assertEqual(r.kind, "no_protocol")
        self.assertIn("W_ECHOED_CONTEXT", r.warnings)

    def test_stale_base(self):
        f = FILE.replace("base=new", "base=deadbeef")
        r = parse(resp(PLAN, f, DONE), T, ctx_sha={"CONFIG/APP.YAML": "12345678"})
        self.assertEqual(r.kind, "invalid")

    def test_end_path_normalized(self):
        f = FILE.replace(f'LLMC-END id={T} path="config/app.yaml"', f'LLMC-END id={T} path="Config\\app.yaml"')
        r = parse(resp(PLAN, f, DONE), T)
        self.assertEqual(r.kind, "complete", r.summary())

    def test_elision_warning(self):
        f = FILE.replace("  b: 2", "# ...（以下省略）")
        r = parse(resp(PLAN, f, DONE), T)
        self.assertTrue(any(w.startswith("W_SUSPECT_ELISION") for w in r.warnings))

    def test_empty(self):
        self.assertEqual(parse(DONE, T).kind, "empty")


class TestCopilotCopy(unittest.TestCase):
    """PoC の実測（個人の Copilot の「応答のコピー」）に基づく形。"""

    def plain(self):
        return "\n".join([f'LLMC-PLAN id={T} write="a.md"', "",
                          f'LLMC-FILE id={T} path="a.md" base=new', "# t", "<br>", "", "x", f'LLMC-END id={T} path="a.md"',
                          "", "説明", "", f"LLMC-DONE v=1 id={T}"])

    def test_plain_copy_rejected_by_default(self):
        self.assertEqual(parse(self.plain(), T).kind, "invalid")

    def test_plain_copy_accepted_with_flag(self):
        r = parse(self.plain(), T, plain_copy=True)
        self.assertEqual(r.kind, "complete", r.summary())
        self.assertEqual(r.files[0].text, "# t\n\n\nx")
        self.assertTrue(any(w.startswith("W_BR_RESTORED") for w in r.warnings))

    def test_br_kept_when_original_has_it(self):
        r = parse(self.plain(), T, plain_copy=True, ctx_text={"A.MD": "# t\n<br>\nx"})
        self.assertIn("<br>", r.files[0].lines)

    def test_segments(self):
        segs = [("code", f'LLMC-PLAN id={T} write="a.md"'),
                ("code", f'LLMC-FILE id={T} path="a.md" base=new\n```py\nx\n```\nLLMC-END id={T} path="a.md"'),
                ("text", "説明 __init__"), ("code", f"LLMC-DONE v=1 id={T}")]
        r = parse(None, T, segments=segs)
        self.assertEqual(r.kind, "complete", r.summary())
        self.assertEqual(r.files[0].text, "```py\nx\n```")

    def test_segments_split_block(self):
        segs = [("code", f'LLMC-PLAN id={T} write="a.md"'),
                ("code", f'LLMC-FILE id={T} path="a.md" base=new\nx'), ("text", "描画された部分"),
                ("code", f'y\nLLMC-END id={T} path="a.md"'), ("code", f"LLMC-DONE v=1 id={T}")]
        r = parse(None, T, segments=segs)
        self.assertNotEqual(r.kind, "complete")
        self.assertTrue(any(e.startswith("E_SPLIT_BLOCK") for e in r.errors), r.summary())

    def test_segments_plan_in_text_rejected(self):
        segs = [("text", f'LLMC-PLAN id={T} write="a.md"'),
                ("code", f'LLMC-FILE id={T} path="a.md" base=new\nx\nLLMC-END id={T} path="a.md"'),
                ("code", f"LLMC-DONE v=1 id={T}")]
        self.assertEqual(parse(None, T, segments=segs).kind, "invalid")

    def test_html_segments(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from htmlseg import segments
        html = ("Version:0.9\r\nStartHTML:0\r\n<html><body><!--StartFragment-->"
                f"<div><pre><code>LLMC-PLAN id={T} write=&quot;a&quot;</code></pre><p>説明 <strong>init</strong></p>"
                f"<pre><code>a\n\n  b &lt;br&gt;\n</code></pre></div><!--EndFragment--></body></html>")
        segs = segments(html)
        self.assertEqual([k for k, _ in segs], ["code", "text", "code"])
        self.assertEqual(segs[2][1], "a\n\n  b <br>")


class TestPath(unittest.TestCase):
    def test_bad(self):
        for p in ("src/../tests/x", "C:x", "/x", "a.py:ads", "tests./x", "con.txt", "CONOUT$", "TESTS~1/x", ""):
            self.assertIsNotNone(check_path(p), p)

    def test_good(self):
        for p in ("pkg/__init__.py", "config/app.yaml", "a b/c.txt"):
            self.assertIsNone(check_path(p), p)

    def test_sha_newline(self):
        self.assertEqual(content_sha("a\r\nb"), content_sha("a\nb"))


if __name__ == "__main__":
    unittest.main()
