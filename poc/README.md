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

### S0b: フェンスの書き方ごとに、コードブロックとして表示されるかの診断

```powershell
.\.venv\Scripts\python.exe manual\probe_fence.py
```

1 回だけ。**新しいチャット**に貼り付けて送信し、回答の「コピー」を押す。バッククォート 3/4/5 個、言語名の有無、チルダの 10 通りについて、コピーの HTML が `<pre>`（コードブロック）になったか、`__init__` が太字に変わったかを記録する。回答の画面で、どの番号が枠付きのコードブロックに見えたかも教えてほしい。結果: `out\manual-probe-fence-report.md`

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

## PoC-6: 入出力と抽出の忠実さ（plan 5.6 の 1）

個人版で、人が送信する方式で行う（組織版は最後に 1 回だけ確認する）。

### (a)(d) 空行の代わりの行と、コピーの HTML の忠実さ

```powershell
.\.venv\Scripts\python.exe poc6_io\echo_fidelity.py
```

2 回（E1・E2）、それぞれ**新しいチャット**に貼り付けて送信し、回答の「コピー」を押す。結果: `out\poc6-echo-report.md`。終わったら連絡してほしい（Claude がこの PC で `poc6_io\dom_compare.py` を実行し、同じ会話の DOM と比べる。読むだけで送信しない）。

### (c) 入力と出力の上限

```powershell
.\.venv\Scripts\python.exe poc6_io\limits.py
```

入力 4 回（8,000〜64,000 文字）と出力 3 回（300〜2,000 行。切れたら同じチャットで続きを 1 回）。待っている間のキー: `f` = 画面にエラーが出た・回答が止まった、`a` = 貼り付けたら添付に変わった、`s` = 飛ばす。結果: `out\poc6-limits-report.md`

### (e) クリップボードの履歴への除外の印（Copilot を使わない）

```powershell
.\.venv\Scripts\python.exe poc6_io\clip_privacy.py
```

先に「設定 → システム → クリップボード → クリップボードの履歴」をオンにしておく。案内に従って Win+V の履歴を見て答える。結果: `out\poc6-clip-report.md`

### (b) 入力欄の読み戻し（送信しない）

```powershell
.\.venv\Scripts\python.exe poc6_io\readback.py --url https://copilot.microsoft.com/ --variant msedge-headless
```

個人版は Claude が実行済み（段落ごとの読み方だけが一致）。組織版では `--url https://m365.cloud.microsoft/chat --variant msedge-headed` で実行する。

### 組織版で PoC-6 を確かめる（自動の方式。貼り付けの手間なし）

社内 PC で `git pull` してから、次を順に実行する。どれも最小化した Edge で自動で動く（終わるまで触らない）。

```powershell
$env:POC_URL = "https://m365.cloud.microsoft/chat"
# (b) 入力欄の読み戻し（送信しない）
.\.venv\Scripts\python.exe poc6_ioeadback.py --url $env:POC_URL --variant msedge-headed
# (a)(d) 空行の代わりの行・特殊な文字・コピーの HTML と DOM の比較（3 回送信）
.\.venv\Scripts\python.exe poc6_io\echo_fidelity.py --auto --url $env:POC_URL
# (c) 入力と出力の上限（入力 4 回、出力 3 回＋切れたら続き 1 回）
.\.venv\Scripts\python.exe poc6_io\limits.py --auto --url $env:POC_URL
```

結果: `out\poc6-readback-report.md`、`out\poc6-echo-auto-report.md`、`out\poc6-limits-auto-report.md`。会話の本文は含まない（架空の内容の比較の結果だけ）。**貼るのは、各プログラムの最後に出る「貼り付け用の要約」だけでよい**（下の「結果の貼り方」）。利用の上限が心配なら、`limits.py` に `--lines 300,600` を付けて出力の回数を減らせる。

## 結果の貼り方（要約）

レポートの全文は長いので、チャットには**要約**を貼る。各プログラムは、終わったときに要約を表示し、クリップボードにも入れる（Win+V の履歴とクラウドへの同期からは除外）。表示を確認してから、そのまま Ctrl+V で貼る。

- 要約の中身: レポートごとの件数と指紋（`fp=`。全文と突き合わせるため）、NG と WARN の項目（エラー・警告のコード、数値、差分の先頭）、余裕があれば INFO、OK は節ごとの数だけ。既定で 1,800 文字以内
- 複数のプログラムを続けて実行したときは、最後にまとめて作り直せる

```powershell
.\.venv\Scripts\python.exe common\digest.py                     # 直近 3 時間のレポート全部
.\.venv\Scripts\python.exe common\digest.py poc6-echo-auto poc6-limits-auto --limit 1200
```

- **社内 PC など、クリップボードがこの PC とつながっていない場合**は、英数字だけの短い形（既定 500 文字）を使い、打ち直すか写真から起こして貼る。日本語は略語（`cmp`・`par` など）か `~` に、特殊な文字は `<200b>` のように 16 進で示す

```powershell
.\.venv\Scripts\python.exe common\digest.py --short
```

- Claude が要約から詳しく知りたい項目を挙げたら、その項目だけを貼る（`out\<名前>-report.md` の該当する行）

## PoC-7: ループの模擬（plan 5.6 の 3）

どちらも、個人版は人が送信する方式、組織版は自動の方式（`--auto --url $env:POC_URL`）で動く。終わると貼り付け用の要約を出す（社内 PC からは `common\digest.py --short`）。

### (0) 出力の上限を超えるファイルの書き換え（分割の出力 A と範囲の置き換え B）

```powershell
.\.venv\Scripts\python.exe poc7_loop\split_test.py              # 個人版。A は 3〜5 ターン（同じチャット）、B は 1 ターン（新しいチャット）
.\.venv\Scripts\python.exe poc7_loop\split_test.py --auto --url $env:POC_URL   # 組織版
```

架空の設定ファイル（約 15,000 文字、330 行）の 3 か所の値を変える。結果: `out\poc7-split-report.md`

### (a)〜(e) 同じチャットで 10 ラウンド

```powershell
.\.venv\Scripts\python.exe poc7_loop\loop_sim.py                # 個人版。10〜15 ターン（1 ラウンド目だけ新しいチャット、あとは同じチャット）
.\.venv\Scripts\python.exe poc7_loop\loop_sim.py --auto --url $env:POC_URL     # 組織版。5 ラウンド目の後に会話の URL を開き直す
```

架空のベンチマーク（llmc が用意する `bench.py`。AI が書くのは設定の YAML だけで、AI のコードは実行しない）のスループットを上げる調整を 10 回依頼する。結果: `out\poc7-loop-report.md`

- 個人版の 1 日の上限に注意。足りなければ `--rounds 5` で減らせる

## PoC-8: ウィンドウ・ロック・ログイン（plan 5.6 の 5。組織版の社内 PC で）

v1 はデーモンを作らない（plan 前提 19）、RDP では使わない（前提 20）と決めたので、確かめることを絞った。`git pull` の後、poc フォルダで実行する。送信は (b) の `send` だけ（1 回ごとに架空の短い依頼を 1 つ）。記録に本文・画面の文字は残らない。

### (d) 朝のログインの状態（送信しない。翌朝に 1 回）

```powershell
.\.venv\Scripts\python.exe poc8_daemon\login_check.py --url $env:POC_URL
```

- 前の日にログインしたまま、**翌朝、ふだんのログインをする前に** 1 回だけ実行する。切れていたときの画面（ログインの画面への転送か、サインインのボタンか）を記録する。何日も保たれるかは確かめない（1 日 1 回の手動のログインでよいため。plan 前提 18）
- ログインが切れていたら、`poc1_login\login.py --browser msedge` でログインし直してから続ける（記録は続く）

### (a)(b) ウィンドウとロック・スリープ

`ctl.py` は、最小化した Edge を別のプロセスで開いたままにする（本体の v1 とは形が違うが、ウィンドウとロックの確かめにはそのまま使える）。

```powershell
.\.venv\Scripts\python.exe poc8_daemon\ctl.py start --url $env:POC_URL
.\.venv\Scripts\python.exe poc8_daemon\ctl.py send                       # 最小化したまま 1 回送れるか
.\.venv\Scripts\python.exe poc8_daemon\ctl.py send --delay 60            # (b) 60 秒の間に Win+L でロックし、3 分ほど待って戻る
.\.venv\Scripts\python.exe poc8_daemon\ctl.py stop
.\.venv\Scripts\python.exe poc8_daemon\ctl.py report                     # 最後に要約を貼る
```

- (a)（できれば。`stop` の前に）: Edge のウィンドウを、タスクバーから開いて元に戻す → `status`。次に、そのウィンドウを × で閉じる → `status` → `send`（開き直して送れるか）
- (b) の続き（できれば）: `send --delay 60` の間にスリープし、数分後に復帰する
- やめた確認: ターミナルを閉じた後も残るか、RDP の切断、`ctl.py schedule`。どれもデーモンのための確認だった

### (c) v1 の実行の形（ロック・ジョブ・Ctrl+C・スケジューラ）

本体の v1 と同じ形（pip の console script に当たる起動用のプログラム → venv の python.exe → 本当の Python）で起動し、仕組みを順に確かめる。送信は `--send` を付けたときだけ。

```powershell
.\.venv\Scripts\python.exe poc8_daemon\runtime_check.py make-launcher          # out\poc8c\bin\llmc-poc8.exe を作る（最初に 1 回）
.\out\poc8c\bin\llmc-poc8.exe run --url $env:POC_URL                              # 1. 準備ができたら Ctrl+C を 1 回押す → q で終わる
.\out\poc8c\bin\llmc-poc8.exe run --url $env:POC_URL --send                       # 2. 「sent」と出たら、すぐ Ctrl+C（生成中に停止ボタンを押す）→ q
.\out\poc8c\bin\llmc-poc8.exe run --url $env:POC_URL                              # 3. 準備ができたら、表示された taskkill /F /PID ... を別の PowerShell で実行
.\.venv\Scripts\python.exe poc8_daemon\runtime_check.py check                  #    → Edge とドライバが残っていないか
.\out\poc8c\bin\llmc-poc8.exe run --url $env:POC_URL                              # 4. 準備ができたら、この PowerShell のウィンドウを × で閉じる
.\.venv\Scripts\python.exe poc8_daemon\runtime_check.py check                  #    → 別の PowerShell で
.\out\poc8c\bin\llmc-poc8.exe run --url $env:POC_URL --fix-exit-type              # 5. 強制終了の後の起動。Edge のウィンドウを元に戻し、「ページを復元」の表示が無いかを見る → q
.\.venv\Scripts\python.exe poc8_daemon\runtime_check.py schedule --url $env:POC_URL --send   # 6. タスクスケジューラ（ログオンしているときのみ）から起動して 1 回送る
.\.venv\Scripts\python.exe poc8_daemon\runtime_check.py report                 # 最後に要約を貼る
```

- 5 で「ページを復元」の表示が出ていたら、そのことをチャットに書いてください（画面の写真は要りません）
- 比べるため（できれば）: `run --url $env:POC_URL --send --ctrlc signal` で、入力モードを変えない前の形でも Ctrl+C を試す。ドライバが落ちれば `page_error` が記録される
- 記録の元は `out\poc8c\events.jsonl`。やり直すときはこのファイルを消す
- 記録の元は `out\poc8\events.jsonl`。やり直すときは `stop` の後にこのフォルダを消す
