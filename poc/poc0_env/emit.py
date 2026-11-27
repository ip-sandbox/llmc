"""決まった日本語の文字列を stdout に出す。使い方: emit.py utf-8|cp932|default"""
import sys

TEXT = "日本語テスト①ｱ～ABC"

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "default"
    if mode == "default":
        print(TEXT)  # Python の標準出力の文字コードに任せる
    else:
        sys.stdout.buffer.write(TEXT.encode(mode) + b"\n")
