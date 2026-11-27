"""架空の課題。社内の情報は含めない。"""
from __future__ import annotations

import re


def _check_s1(ws, res):
    t = (ws / "config/app.yaml").read_text(encoding="utf-8")
    return {"workers が 8": bool(re.search(r"^\s*workers:\s*8\b", t, re.M)),
            "timeout が 60": bool(re.search(r"^\s*timeout:\s*60\b", t, re.M)),
            "コメントが残っている": t.count("#") >= 3,
            "retries が残っている": "retries: 3" in t}


def _check_s1b(ws, res):
    t = (ws / "config/app.yaml").read_text(encoding="utf-8")
    return {"timeout が 90": bool(re.search(r"^\s*timeout:\s*90\b", t, re.M)),
            "workers が 8 のまま": bool(re.search(r"^\s*workers:\s*8\b", t, re.M)),
            "コメントが残っている": t.count("#") >= 3}


GUIDE = """# 架空ツールの手引き

## 概要

これは動作確認用の架空の文書です。

```python
def hello():
    print("hello")
```

## 使い方

次の設定を書きます。

````markdown
```yaml
key: value
```
````

## 注意

特になし。
"""


def _check_s2(ws, res):
    t = (ws / "docs/guide.md").read_text(encoding="utf-8")
    return {"bash の例が追加": "```bash" in t,
            "python の例が残っている": 'print("hello")' in t,
            "4 個のフェンスの例が残っている": t.count("````") >= 2 and "key: value" in t,
            "見出しの数（4 以上）": t.count("\n## ") >= 3}


INIT = '''"""架空のパッケージ。"""
from .old import legacy
from .util import add

__all__ = ["add", "legacy"]
'''
UTIL = '''def add(a, b):
    return a + b
'''
OLD = '''def legacy(x):
    """古い関数。"""
    return x * 2
'''


def _check_s3(ws, res):
    init = (ws / "pkg/__init__.py").read_text(encoding="utf-8") if (ws / "pkg/__init__.py").exists() else ""
    util = (ws / "pkg/util.py").read_text(encoding="utf-8") if (ws / "pkg/util.py").exists() else ""
    return {"old.py が削除された": not (ws / "pkg/old.py").exists(),
            "util.py に legacy がある": "def legacy" in util,
            "util.py に add が残っている": "def add" in util,
            "__init__.py が old を参照しない": ".old" not in init,
            "__init__.py が legacy を公開": "legacy" in init}


SCENARIOS = {
    "S1": {
        "title": "YAML の書き換え（新しいチャット）",
        "new_chat": True,
        "files": {"config/app.yaml": "# 架空のサーバの設定\nserver:\n  # 同時に動かす数\n  workers: 4\n  # 秒\n  timeout: 30\n  retries: 3\n"},
        "allow": ["config/app.yaml"],
        "task": "config/app.yaml の workers を 8 に、timeout を 60 にしてください。コメントと他の値はそのまま残してください。",
        "check": _check_s1,
    },
    "S1b": {
        "title": "同じチャットの 2 回目（短い規則だけを送る）",
        "new_chat": False,
        "after": "S1",
        "files": {},
        "allow": ["config/app.yaml"],
        "task": "続けて、config/app.yaml の timeout を 90 にしてください。他はそのままにしてください。",
        "check": _check_s1b,
    },
    "S2": {
        "title": "入れ子のフェンスを含む Markdown（新しいチャット）",
        "new_chat": True,
        "files": {"docs/guide.md": GUIDE},
        "allow": ["docs/guide.md"],
        "task": "docs/guide.md の「## 使い方」の節の最後に、bash のコード例（```bash で始まるコードブロック。中身は echo hello の 1 行）を追加してください。他の部分は一字一句変えないでください。",
        "check": _check_s2,
    },
    "S3": {
        "title": "複数ファイルの書き換えと削除（新しいチャット）",
        "new_chat": True,
        "files": {"pkg/__init__.py": INIT, "pkg/util.py": UTIL, "pkg/old.py": OLD},
        "allow": ["pkg/__init__.py", "pkg/util.py", "pkg/old.py"],
        "task": "pkg/old.py の関数 legacy を pkg/util.py に移し、pkg/old.py を削除してください。pkg/__init__.py の import を合わせて直してください。",
        "check": _check_s3,
    },
}
