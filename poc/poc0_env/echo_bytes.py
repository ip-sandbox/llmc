"""stdin のバイト列を受け取り、指定のファイルに JSON で記録する。使い方: echo_bytes.py <出力先>"""
import json
import sys

data = sys.stdin.buffer.read()
res = {"len": len(data), "hex": data[:4000].hex()}
for enc in ("utf-8", "cp932", "utf-16-le"):
    try:
        res[enc] = data.decode(enc)
    except UnicodeDecodeError:
        res[enc] = None
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False)
