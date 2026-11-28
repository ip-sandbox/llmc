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

## PoC-1: ログインの保持（個人の Copilot、copilot.microsoft.com）

メッセージは送りません。画面を開いて状態を見るだけです。

1. ログイン（画面ありのブラウザが開きます。Microsoft アカウントでログインし、チャットの入力欄が出たらコンソールで Enter）

   ```powershell
   .\.venv\Scripts\python.exe poc1_login\login.py --browser chromium
   .\.venv\Scripts\python.exe poc1_login\login.py --browser msedge      # Edge があれば
   ```

2. 確認（ログイン済みのプロファイルを、次の組み合わせで順に開きます）

   ```powershell
   .\.venv\Scripts\python.exe poc1_login\check.py
   ```

   | 組み合わせ | 内容 |
   |---|---|
   | chromium-headed | 同梱 Chromium・画面あり |
   | chromium-headless-shell | 同梱 Chromium・ヘッドレス（既定。別のバイナリ） |
   | chromium-new-headless | 同梱 Chromium・新しいヘッドレスモード |
   | chromium-headless-shell-uafix | 上の既定のヘッドレスで、UA の HeadlessChrome を Chrome に置き換えたもの |
   | msedge-headed / msedge-headless | Edge・画面あり / ヘッドレス |

- 結果: `out\poc1-login-*-report.md` と `out\poc1-check-report.md`
- `check.py` は、**翌日・数日後にも**実行して貼ってもらえると、ログインが保たれる期間の目安になります
- プロファイル（ログイン情報を含む）は `%LOCALAPPDATA%\llmc-poc\profiles\` にあります。PoC が終わったらフォルダごと削除してください
- 記録するのは、URL のホスト名、入力欄やサインインのボタンの有無、cookie の**数**（値は記録しません）、UA の種類だけです

## レポートを貼る前に

- 利用者名、PC 名、ホームのパス、ユーザーの SID は `<USERNAME>` などに置き換えてあります
- それでも、社内の情報（社内のホスト名、フォルダ名など）が残っていないかを確かめてから貼ってください
- `out\` はコミットの対象外です（`.gitignore`）

## PoC-1b / PoC-2b: 組織の Microsoft 365 Copilot Chat での確認（社内 PC）

個人の Copilot では、自動操作したブラウザからの送信がボット対策で拒否された（`docs/poc-findings.md`）。組織版で同じことが起きるかを確かめる。

1. 準備（「準備（初回のみ）」と同じ。社内のプロキシで失敗したら、エラーの最後の 20 行を貼る）
2. 環境の診断（Copilot には接続しない）

   ```powershell
   .\.venv\Scripts\python.exe poc0_env\check_env.py
   .\.venv\Scripts\python.exe poc4_win\check_win.py
   ```

3. ログイン（画面ありの Edge が開く。組織のアカウントでログインし、チャットの入力欄が出たらコンソールで Enter）

   ```powershell
   $env:POC_URL = "https://m365.cloud.microsoft/chat"   # 普段使っている Copilot の URL が違えば、それに変える
   .\.venv\Scripts\python.exe poc1_login\login.py --browser msedge
   .\.venv\Scripts\python.exe poc1_login\check.py --only msedge-headless
   ```

4. 送信の確認（**架空の短い依頼を 1 回だけ送る**。会話の履歴に 1 件残る）

   ```powershell
   .\.venv\Scripts\python.exe poc2_page\send_once.py --url $env:POC_URL --tag org
   ```

   ヘッドレスで NG だった場合だけ、画面ありでも 1 回試す（画面に Edge が開く）:

   ```powershell
   .\.venv\Scripts\python.exe poc2_page\send_once.py --url $env:POC_URL --tag org-headed --variant msedge-headed
   ```

- 貼ってほしいもの: `out\poc0-report.md`、`out\poc4-report.md`、`out\poc1-login-msedge-report.md`、`out\poc1-check-report.md`、`out\poc2-send-org*-report.md`
- 組織版の画面は個人版と DOM が違う可能性がある。`send_once.py` が「画面を開く・ログイン」や「送信ボタン」で NG になった場合は、画面の作りが違うだけの可能性があるので、そのまま貼ってもらえれば調整する
- プロファイル（組織のログイン情報を含む）は `%LOCALAPPDATA%\llmc-poc\profiles\` にある。確認が終わったらフォルダごと削除する

## 人が送信する方式の PoC（manual）

自動操作からの送信が拒否されたため、送信と回答の受け取りを利用者が行う方式を試す。llmc はプロンプトの組み立て、回答の解析、ファイルの書き込みを担当する。

```powershell
.\.venv\Scripts\python.exe manual\run.py
```

1 つの課題（ラウンド）ごとに、次を繰り返す。

1. コンソールの指示に従い、Copilot で**新しいチャット**か**同じチャット**を開く
2. プロンプトがクリップボードに入っているので、Copilot の入力欄に貼り付けて（Ctrl+V）送信する
3. 回答が終わったら、回答の下の「**コピー**」ボタンを押す（llmc がクリップボードを見張っていて、自動で拾う）

- 課題は 4 つ（すべて架空）: S1 YAML の書き換え → S1b 同じチャットの 2 回目 → S2 入れ子のフェンスを含む Markdown → S3 複数ファイルと削除
- 回答が途中で切れたと判定した場合は、続きの依頼が自動でクリップボードに入るので、同じチャットに貼り付けて送る
- 今回のターン ID を含まないコピーは無視する（途中で他のものをコピーしても大丈夫）
- クリップボードを使いたくない場合は `--no-clipboard`（プロンプトを `out\manual\` に書き出し、回答を `out\manual\response.txt` に保存してもらう）
- 結果: `out\manual\report.md`。回答の全文は `out\manual\*-response-*.txt`、書き込んだファイルは `out\manual\workspace\`
- 解析器の単体試験: `.\.venv\Scripts\python.exe -m unittest manual\test_protocol.py`

### S0: 貼り付けた中身が AI にそのまま届くかの診断

```powershell
.\.venv\Scripts\python.exe manual\probe_input.py
```

3 回（A テキスト / B 空行を空白 1 文字に / C テキスト＋HTML）、それぞれ**新しいチャット**に貼り付けて送信し、回答の「コピー」を押す。貼り付けた直後の入力欄の見た目（空行が残っているか、コードの枠になったか）も教えてほしい。結果: `out\manual-probe-input-report.md`

保存した回答の再解析（Copilot には接続しない）: `.\.venv\Scripts\python.exe manual\run.py --replay`

## PoC-3（自動の方式）: 組織版での書式の往復（社内 PC）

画面ありの Edge を最小化して、入力方法の診断（S0 の自動版）と課題 S1・S1b・S2・S3 を自動で行う。架空の依頼を合計 7 回ほど送る。OS のクリップボードは使わない。

```powershell
$env:POC_URL = "https://m365.cloud.microsoft/chat"
.\.venv\Scripts\python.exe poc3_auto\roundtrip.py --url $env:POC_URL
```

- Edge のウィンドウが開いて最小化される。終わるまで（数分）触らない
- 結果: `out\poc3-auto-report.md`（会話の本文は含まない）。全行を詳細も含めて貼ってほしい
- 入力方法の診断だけ: `--only-s0`。診断を飛ばして入力方法を指定: `--method paste_html`
