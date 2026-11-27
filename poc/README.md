# llmc PoC（使い捨ての動作確認プログラム）

llmc 本体ではありません。設計の仮説（`docs/plan.md` 5.2）を実物で確かめるためのプログラムです。
結果のレポートは**チャットに貼って**ください（リポジトリにはコミットしません）。

## 準備（初回のみ）

OneDrive の配下ではない場所（例: `C:\work`）に、このリポジトリの作業ブランチを置いてください。

```powershell
cd C:\work\llmc\poc
py -m venv .venv            # py が無ければ python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

- `Activate.ps1` は実行ポリシーで止められることがあるので、上のように venv の `python.exe` を直接使います
- `pip install` か `playwright install` が失敗した場合は、**エラーの最後の 20 行ほど**もチャットに貼ってください（社内のプロキシで止まっていないかの確認。H-11）

## PoC-0: 環境の診断（Copilot には接続しません）

```powershell
.\.venv\Scripts\python.exe poc0_env\check_env.py
```

- 確かめること: Python と venv、コンソールのコードページ、PowerShell 5.1 と cmd.exe のパイプ・リダイレクトでの日本語、Playwright でのブラウザの起動（同梱 Chromium と Edge。ログインはしません）
- 結果: `out\poc0-report.md`
- PowerShell と cmd.exe のウィンドウが一瞬開くことはありません（裏で実行します）。1〜2 分かかります

## PoC-4: Windows の仕組みの試験（Copilot には接続しません）

```powershell
.\.venv\Scripts\python.exe poc4_win\check_win.py
```

- 確かめること: ジョブからの切り離しとプロセスツリーの終了、`pythonw` での Playwright、名前付きパイプの権限、`ReplaceFileW`、ジャンクションと OneDrive のリパースタグ、末尾のドットや 8.3 形式の名前
- 作業ファイルは `out\poc4\` の下にだけ作ります（OneDrive の中は、ファイルを開かずに属性だけを読みます）
- 結果: `out\poc4-report.md`
- 通常の権限（管理者ではない）で実行してください

## レポートを貼る前に

- 利用者名、PC 名、ホームのパス、ユーザーの SID は `<USERNAME>` などに置き換えてあります
- それでも、社内の情報（社内のホスト名、フォルダ名など）が残っていないかを確かめてから貼ってください
- `out\` はコミットの対象外です（`.gitignore`）
