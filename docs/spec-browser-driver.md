# ブラウザドライバ仕様

> **状態: 暫定版**。実物で確かめる仮説は plan.md 5.2 にまとめた。PoC の結果を受けて確定・修正する。

## 1. 範囲

- `ChatBackend`（共通インタフェース）と、その Playwright 実装（汎用ドライバ＋サイト別プロファイル）を定める
- 第一ターゲットは Microsoft 365 Copilot Chat。Copilot の実際の DOM は調べていないため、本書の Copilot に関する値は**仮の値**であり、`open-questions.md` の調査項目の結果で確定する
- ドライバはデーモンの中で動き、要求は直列に処理する（spec-daemon）。ファイルシステムには触らない（ダウンロードを除く）

## 2. 共通インタフェース `ChatBackend`

実装言語の型ではなく、操作と受け渡すデータの形で定める。

### 2.1 操作

| 操作 | 入力 | 出力 | 説明 |
|---|---|---|---|
| `open()` | — | `BackendInfo` | ブラウザを起動し、画面の準備完了まで待つ |
| `health()` | — | `Health` | ログイン状態、画面の準備、プロファイルの版、直近のエラー |
| `capabilities()` | — | `Capabilities` | 入力の上限、添付、ダウンロード、エージェント、会話の一覧などの対応状況 |
| `new_conversation(agent?)` | エージェントの指定（任意） | `ConversationRef` | 新しいチャットを開く |
| `open_conversation(ref)` | `ConversationRef` | `ConversationRef` | 既存のチャットへ移る |
| `list_conversations(limit)` | 件数 | `ConversationRef` の列 | 対応するサイトのみ |
| `send(conv, message, on_event)` | 会話、`OutboundMessage`、イベントを受け取る関数 | `TurnResult` | 送信して、完了と抽出まで行う |
| `cancel(turn_id)` | — | — | 生成を止める（画面の停止ボタン） |
| `download(turn_id, artifact)` | 回答中のファイル | ダウンロードしたファイルのパス | 対応するサイトのみ |
| `close()` | — | — | 終了 |

### 2.2 データ

| データ | 主な項目 |
|---|---|
| `ConversationRef` | `url`（続行に使う）、`title`、`site`、`agent`、`created_at` |
| `OutboundMessage` | `text`、`attachments`（**クライアントが用意したマスキング済みの一時ファイル**のパスの列。デーモンは `%LOCALAPPDATA%\llmc\daemon\staging\` にあるものだけを読む）、`turn_id`（ファイル書式のターン ID）、`expect_protocol`（書式の回答を期待するか） |
| `TurnResult` | `raw_text`、`segments`（DOM 復元の場合の区分）、`extract_method`（`copy_button` か `dom`）、`completion_signals`（どの条件で完了とみなしたか）、`artifacts`（ダウンロードできるファイルの一覧）、`conversation`（送信後の URL）、`timings`、`warnings` |
| `Capabilities` | `max_input_chars`、`attachments`（対応・最大サイズ・最大個数・拡張子）、`downloads`、`agents`、`list_conversations`、`streaming` |
| イベント | 2.3 を参照 |

### 2.3 イベント

進捗イベントの名前と意味は本書を正とする（architecture 4 章はこれを参照する）。

| イベント | 発生元 | 内容 |
|---|---|---|
| `queued` | デーモン | キューに入った。`position`（前に何件あるか） |
| `sending` | ドライバ | 入力を始めた |
| `sent` | ドライバ | 送信を確認した（4.3） |
| `first_token` | ドライバ | 回答の要素に文字が現れた |
| `delta` | ドライバ | `mode`（`append` = 前回の続きだけ / `replace` = 全体を送り直し）と `text` |
| `completing` | ドライバ | 完了の条件の確認を始めた |
| `extracting` | ドライバ | 抽出を始めた |
| `artifact_found` | ドライバ | 回答の中にダウンロードできるファイルを見つけた |

### 2.4 エラー

| エラー | 意味 | 利用者への案内 |
|---|---|---|
| `LoginRequired` | ログイン画面へ転送された、またはセッション切れの表示 | `llmc login` |
| `SelectorMissing(name, stage)` | 必要な要素が見つからない（画面の変更の可能性） | 診断の報告（7 章）と `llmc probe` |
| `InputRejected` | 入力が上限を超えた、または入力が反映されない | 内容の削減か添付 |
| `NotSent` | 送信を確認できない | 再実行（自動では再送しない） |
| `Timeout(stage)` | 最初の応答、完了、抽出のいずれかの時間切れ | 時間の設定 |
| `GenerationFailed(message)` | 画面にエラーが表示された | 再実行 |
| `RateLimited(retry_after?)` | 利用上限の表示 | 待ってから再実行 |
| `AgentUnavailable` | 指定のエージェントが開けない | spec-agent の方針に従う |
| `ModeMismatch` | サイトのモードが設定と違う（Copilot の「職場」と「Web」など） | 画面でモードを直す。送信はしない |
| `AttachmentRejected` | 添付に失敗した | 本文への埋め込み |
| `BrowserCrashed` | ブラウザかページが異常終了した | デーモンが 1 回だけ再起動を試みる |
| `Cancelled` | 利用者が取り消した | — |

**自動で再送はしない**。送信できたかどうか分からない状態で再送すると、同じ依頼が二重に届き、利用量も二重になるためである。再送するかは呼び出し元（ループエンジンなど）が決める。

## 3. サイト別プロファイル

### 3.1 置き場所と重ね合わせ

- 同梱の既定値: `src/llmc/backend/sites/<site>.yaml`
- 利用者の上書き: `%LOCALAPPDATA%\llmc\sites\<site>.yaml`（同じキーだけを上書きする）

### 3.2 形式（Copilot 用の例。値は仮）

```yaml
profile_version: 1
site: copilot-m365
display_name: Microsoft 365 Copilot Chat
url: https://m365.cloud.microsoft/chat        # 仮。実際の URL を確認する
browser:
  channel: msedge          # PoC の結果、組織では Edge（docs/poc-findings.md）
  headless: false          # 組織の PC では Edge のヘッドレスがポリシーで禁止されている。回避しない
  window: minimized        # 起動後に最小化する（DevTools プロトコルの Browser.setWindowBounds）。最小化しても処理は間引かれなかった
  locale: ja-JP
  viewport: {width: 1280, height: 900}

login:
  # 次のどれかに当たればログインが必要とみなす
  url_patterns: ["^https://login\\.microsoftonline\\.com/", "^https://login\\.live\\.com/"]
  selectors: []

selectors:
  # 各項目は候補の列。先頭から試し、最初に見つかったものを使う
  ready:            ["role=textbox[name=/メッセージ|Message/]"]
  input:            ["role=textbox[name=/メッセージ|Message/]", "div[contenteditable=true]", "textarea"]
  send_button:      ["role=button[name=/送信|Send/]"]
  stop_button:      ["role=button[name=/停止|Stop/]"]
  new_chat:         ["role=button[name=/新しいチャット|New chat/]"]
  message_list:     ["[role=log]", "main"]
  user_message:     ["[data-author=user]"]          # 仮
  assistant_message: ["[data-author=bot]"]          # 仮
  actions_bar:      []       # 回答全体の操作欄（本文の Markdown の外）。回答の要素の中で探す
  message_done:     ["role=button[name=/^コピー$|^Copy$/]"]   # 完了後にだけ現れる要素。actions_bar の中だけで探す
  copy_button:      ["role=button[name=/^コピー$|^Copy$/]"]   # 回答全体のコピー。actions_bar の中だけで探す
  code_block:       ["pre"]
  error_banner:     ["[role=alert]"]
  system_notice:    []       # 利用上限などの、画面からのお知らせの要素
  mode_indicator:   []       # Copilot の「職場 / Web」などのモードの表示
  attach_button:    []
  file_input:       ["input[type=file]"]
  attachment_ready: []
  download_link:    []
  agent_picker:     []

mode:
  # 送信の前に、サイトのモードが期待どおりかを確かめる（Copilot の「職場」と「Web」の切り替えなど）
  required: null           # 例: {indicator_text: "/職場|Work/"}。一致しなければ送信しない（ModeMismatch）

input:
  modes: [paste_html, fill]                   # PoC の結果、paste_html を第一とする（下の 4.1 の注）
  max_chars: null                             # null = probe で測る
  newline: paste                              # 改行の入れ方（paste / shift_enter）
  readback: textContent                       # 読み戻しに使うプロパティ

completion:
  require_any: [stop_button_gone, message_done]
  stable_ms: 3000
  fallback_stable_ms: 10000      # 停止ボタンも完了の要素も使えない場合
  first_token_timeout_s: 120
  stall_timeout_s: 180           # 停止ボタンが出たまま本文が変わらない時間
  total_timeout_s: 900

extract:
  order: [copy_button, dom]
  code_text: textContent         # pre の中身の取り方（textContent / innerText）。probe で決める
  copy_length_ratio: [0.5, 2.0]  # コピーで取れた長さ / DOM の本文の長さ の許容範囲

errors:
  # パターンは error_banner と system_notice の要素の文字にだけ当てる。回答の本文には当てない
  rate_limit_patterns: ["上限に達しました", "利用制限", "too many requests", "rate limit"]
  generation_failed_patterns: ["問題が発生しました", "Something went wrong"]

variants:
  agent:                          # エージェントの画面で値が違う場合の上書き（調査の結果、必要なら使う）
    selectors: {}
```

- セレクタは Playwright のセレクタ（`role=`、`text=`、CSS、`data-testid=` など）。**ARIA のロールと名前を優先**し、CSS のクラス名は使わない（クラス名は画面の更新でよく変わるため）
- 日本語と英語の両方の表示名に一致するよう正規表現を使う
- `variants` で、エージェントの画面など DOM が違う場合の値を上書きする（spec-agent）
- エラーのパターンは単語 1 つ（`limit` など）にしない。SQL の `LIMIT` のような回答の本文の語に当たる誤検出を避けるため、当てる要素も `error_banner` と `system_notice` に限る
- 予約: DOM の構造が大きく違い、セレクタで表せないサイトのためのフック（同梱の JavaScript の関数を名前で指定する）と、`llmc probe --write-profile`（診断で見つけた値を上書きファイルに書く）。**v1 では作らず**、Copilot の実際の DOM を調べてから必要なものだけ加える

## 4. 入力

### 4.1 入力欄の種類と方式

| 方式 | 内容 | 向いている入力欄 | 注意 |
|---|---|---|---|
| `fill` | Playwright の `locator.fill`。要素を選んでから、本文を一度に入れる（contenteditable では文字の挿入に相当する） | textarea、contenteditable | リッチエディタでは内部の状態が更新されず、送信ボタンが有効にならないことがある |
| `insert_text` | Playwright の `keyboard.insert_text`。フォーカスのある位置に、1 回の操作で本文を挿入する（`keydown` などのキーのイベントは出ない） | どちらも | 1 文字ずつの入力ではないので速い。改行の扱いはエディタによって違う |
| `paste_event` | JavaScript で `DataTransfer` に本文を入れ、入力欄に `paste` イベントを送る | 貼り付けを独自に処理するリッチエディタ | **OS のクリップボードを使わない**。エディタが改行を段落にする、長文を「貼り付けたテキスト」の添付に変える、などの変換が起き得る |

- **PoC の結果（docs/poc-findings.md）**: Copilot の入力欄（Lexical）では、空行を含むテキストを `fill` やテキストだけの貼り付けで入れると、AI に届く時点で空行が崩れる（`<br>` という文字になる、または空行が増える）。**貼り付けイベントに `text/plain` と `text/html` の両方を入れ、ファイルの部分を `<pre><code>` にする方法（`paste_html`）だけが、一字一句そのまま届いた**（組織版の自動の方式と、個人版の人が送信する方式の両方で確認）。入力欄の中ではコードのブロックになる。そのため、文脈のファイルを含む本文は `paste_html` で入れる。読み戻しの比較は、入力欄がコードのブロックと段落に分かれるので、`textContent` の全体ではなく、コードのブロックごとの中身と送る文脈の中身を比べる
- 入力した後に入力欄のテキストを読み戻して、送る本文と比べる。比べるときは **NBSP（U+00A0）を空白に戻し、行末の空白を無視するだけ**とし、行頭の空白とタブは比べる（YAML や Python のインデントの崩れを見逃さないため）。一致しなければ次の方式を試す。全部失敗したら `InputRejected`
- 送信後に、利用者のメッセージとして表示された本文とも同じ方法で比べ、違えば警告を記録する
- 長文を貼り付けたときに、画面が本文を添付に自動で変える挙動があるかは probe の調査項目とする。変える場合は、その長さの手前を上限（`max_chars`）とみなす
- 文字の入力（`type`）は使わない（遅く、Enter で送信されてしまう）

### 4.2 長文

- `max_chars` は `llmc probe --measure-input` で測る。入力欄に長さを変えて入れ、読み戻しの一致、文字数の表示、送信ボタンの状態から上限を二分探索で求める。**送信はしないので利用量を消費しない**
- 上限を超える場合の方針（順序）

| 順序 | 方針 | 担当 |
|---|---|---|
| 1 | 送る内容の削減（変わっていないファイルを省く、ログを先頭と末尾だけにする、履歴を要約する） | プロンプト組み立て（spec-loop） |
| 2 | 添付機能の利用（文脈ファイルを 1 つのテキストファイルにまとめて添付し、本文には指示だけを書く） | プロンプト組み立て（マスキングした一時ファイルを作る）＋ドライバ |
| 3 | エラー | `InputRejected` |

分割送信（複数回に分けて送る）は v1 では作らない。利用量が増え、AI が途中で答え始める危険があるうえ、既定で無効のまま残す利点が小さいため。

プロンプト組み立ては、`capabilities().max_input_chars` を予算として受け取り、送る前に収める。ドライバ側では収まっていることを確認するだけにする。

### 4.3 送信と送信の確認

1. 送信ボタンが有効になるまで待つ（最大 10 秒）。有効にならなければ `NotSent`
2. 送信ボタンを押す（ボタンが無いサイトでは Enter）
3. 次の**両方**を確認する（最大 15 秒）。確認できなければ `NotSent`
   - 入力欄が空になった、または送信ボタンが無効になった
   - 新しい利用者のメッセージが現れ、その本文にターン ID が含まれる（5.1）

## 5. 回答の特定

要素の数を数える方式は使わない（仮想スクロールで古い要素が消えると破綻し、自分のメッセージを取り違えるため。参考実装 #9・A2）。

### 5.1 主な方式: 自分のメッセージを起点にする

1. 送る本文の冒頭と末尾に、ターン ID を含む行（`このターンの ID: K7Q2MX`）を入れる（spec-file-protocol 5 章）。利用者のメッセージが長いと画面で折りたたまれることがあるので、両方に入れる。冒頭に入れるので、会話の題名が似たものになるが、実害は小さい
2. 送信後、`user_message` のうち本文にターン ID を含む要素を探す
3. その要素より**後ろ**にある、最初の `assistant_message` を、このターンの回答とする
4. 見つけた回答の要素に、JavaScript で印（`data-llmc-turn="K7Q2MX"`）を付ける。以降はこの印で参照する
5. 監視の各回で、次を確かめる。どちらかが崩れていれば、2 からやり直す
   - 印の付いた要素が DOM につながっている（`isConnected`）。「考え中」の仮の要素が回答の要素に置き換わる画面では、印の付いた要素が外れるため
   - 印の付いた要素の直前の利用者のメッセージに、まだターン ID が含まれる。仮想スクロールで要素が使い回された場合に気付くため
6. やり直したときは、仕掛けていた `MutationObserver` も新しい要素に付け直す

### 5.2 補助の方式

| 方式 | 内容 | 使う場面 |
|---|---|---|
| 送信前に仕掛ける監視 | 送信の直前に、会話の一覧に `MutationObserver` を仕掛け、送信後に追加された回答の要素を記録する | 5.1 の 2 で自分のメッセージが見つからない場合（画面が利用者のメッセージを省略表示する、など） |
| 回答の中の ID | 書式の回答なら、`LLMC-DONE` の ID がターン ID と一致することを抽出後に確かめる | 書式の回答で常に行う（最後の確認） |

- 生成中は会話の一覧を最下部へスクロールし続ける（仮想スクロールで回答の要素が外れないようにする）
- 回答は 1 つのメッセージとは限らない（途中で別の要素に分かれる画面がある）。印の付いた要素から、次の利用者のメッセージまでの回答の要素を 1 つの回答としてまとめる

## 6. ストリーミングと完了判定

### 6.1 ストリーミング

- 回答の要素に `MutationObserver` を仕掛け、変化があれば最大 200 ミリ秒に 1 回、`innerText` をデーモンへ渡す（`expose_binding` を使う）。仕掛けられない場合は 500 ミリ秒ごとの読み取りに切り替える
- 前回のテキストが今回の先頭と一致すれば差分だけを `delta` として送る。一致しなければ（描画のやり直しで前の部分が変わった場合）全体を送り直す
- ストリーミングのテキストは**表示のためだけの仮のもの**で、解析には使わない。解析には完了後に抽出したテキストを使う

### 6.2 完了の条件

| 信号 | 内容 |
|---|---|
| `stop_button_gone` | 送信後に停止ボタンが現れ、その後に消えた。出現と消滅は `MutationObserver` で記録し、短い出現も見落とさない |
| `message_done` | 回答の**操作欄**（`actions_bar`）の中に、完了後にだけ現れる要素（回答全体のコピーボタン、評価ボタンなど）が現れた。コードブロックごとのコピーボタンは生成中から表示されることが多いので、操作欄の外のものは数えない |
| `stable` | 本文が `stable_ms` の間変化していない |
| `no_error` | エラーの表示が出ていない |

- 完了 = （`require_any` のどれか）かつ `stable` かつ `no_error`
- ただし、**停止ボタンを一度でも観測した場合は `stop_button_gone` を必須にする**（`message_done` だけでは完了とみなさない）
- 停止ボタンも完了の要素も見つけられない画面では、`fallback_stable_ms`（既定 10 秒）の安定だけで完了とみなし、警告を記録する
- どの信号で完了とみなしたかを `completion_signals` に記録する（不具合の調査のため）

### 6.3 時間の上限

| 上限 | 既定 | 超えた場合 |
|---|---|---|
| 最初の応答（回答の要素に文字が現れるまで） | 120 秒 | `Timeout(first_token)` |
| 停滞（停止ボタンが出たまま本文が変わらない） | 180 秒 | `Timeout(stall)`。停止ボタンを押す |
| 全体 | 900 秒 | `Timeout(total)`。停止ボタンを押す |

## 7. 抽出

### 7.1 コピーボタン方式（第一候補）

1. ページの読み込み時（`add_init_script`）に、クリップボードへの書き込みを横取りする仕掛けを入れる。仕掛けは「横取りの準備」の目印が立っているときだけ働き、それ以外のときは元の動作に任せる
   - `navigator.clipboard.writeText` を置き換え、書き込もうとした文字列を保存する
   - `navigator.clipboard.write` を置き換え、`ClipboardItem` の `text/plain` と `text/html` を保存する。値は Blob か Promise<Blob> なので、非同期に読み出す
   - `document.execCommand` を置き換え、`'copy'` のときは `copy` イベントを自分で発生させる。ページの処理が `clipboardData.setData` で入れた値を保存し、既定の動作（選択範囲のコピー）は止める
   - `DataTransfer.prototype.setData` も置き換え、`copy` イベントの中で入れられた値を保存する（ページが自前で `copy` イベントを処理する場合に備える）
   - どの経路でも、**OS のクリップボードには何も書き込まない**（利用者のクリップボードを上書きしない。参考実装 #12）。probe では、画面ありの実行で OS のクリップボードが変わっていないことも確かめる
2. 回答の要素の**操作欄（`actions_bar`）の中**で、`copy_button` に一致するボタンを探す。コードブロックのコピーボタンは `pre` の外の見出し部分にあることが多いので、「`pre` の中に無い」だけでは除外できないため
3. 保存用の変数を空にしてからボタンを押し、変数に値が入るまで待つ（最大 3 秒）
4. 取れたテキストの長さと、DOM の本文の長さの比が `copy_length_ratio` の範囲外なら、抽出の失敗とする（補助の確認）
5. 取れたテキストが**生の Markdown か、描画後のテキストか**を判定する。DOM に `pre` があるのに、取れたテキストにフェンスの行が無ければ描画後のテキストとみなす。描画後のテキストにはコードブロックの境界の情報が無いので、DOM 方式を使う
6. 書式の回答を期待している場合は、DOM 方式でも抽出して両方を解析する
   - 両方とも `complete` で、ファイルの中身が一致: コピーボタンの結果を採用する
   - 両方とも `complete` で、中身が違う: コピーボタンの結果を採用し、警告を記録する（DOM の `code` 区分の取り方の問題の可能性が高い）
   - 片方だけ `complete`: そちらを採用し、警告を記録する
   - どちらも `complete` でない: コピーボタンの結果を解析の対象にする

コピーボタンで取れるのが生の Markdown なのか、描画後のプレーンテキストなのか、HTML なのかはサイトによって違う。Copilot でどうなるかは調査項目とする。`text/html` しか取れない場合は、HTML から 7.2 と同じ方法で区分付きテキストを作る。

### 7.2 DOM 方式（次善）

- 回答の要素を走査し、区分の列を作る
  - `code` 区分: `pre` 要素 1 つにつき 1 つ。取り方はプロファイルの `extract.code_text` で選ぶ。`textContent` は文字を改変しないが、1 行を 1 つの `div` で描くハイライタでは行がつながる。`innerText` は描画どおりの改行になるが、空白が変わることがある。どちらが正しく取れるかは probe で、既知の中身（入れ子のフェンス、タブ、行末の空白を含む）を依頼して比べて決める。行番号の表示や、コピーボタンなどの UI 部品の文字は取り除く（プロファイルで除外するセレクタを指定できる）
  - `text` 区分: それ以外。見出しは `#`、箇条書きは `- `、番号付きは `1. `、インラインコードは ``` ` ```、強調は `**` を付けて、Markdown に近い形に戻す
- 表示用の Markdown は区分を連結して作るが、**ファイル書式の解析は区分の列を使う**（spec-file-protocol 6.4）
- DOM 方式で取ったことを `extract_method: dom` として記録し、呼び出し元に「描画で記号が失われている可能性がある」ことを伝える

### 7.3 回答に含まれるファイル

- 回答の要素の中で `download_link` に一致するリンクを `artifacts` として返す（名前、種類、リンク先）
- ダウンロードは `download()` で行い、`page.expect_download()` で受け取る。リンクが新しいタブで開く、または OneDrive・SharePoint への保存になる場合の扱いは、Copilot での挙動を調べてから決める（spec-convert、open-questions）

## 8. 会話の操作

| 操作 | 方法 |
|---|---|
| 新規 | `new_chat` のボタンを押す。ボタンが見つからなければ `url` を開き直す。入力欄が空で、会話の一覧に回答が無いことを確認する |
| 続行 | `ConversationRef.url` を開き、最後の回答が表示されるまで待つ |
| 一覧 | サイドバーの会話の一覧を読む（対応するサイトのみ） |
| 切り替え | 続行と同じ |

- 送信して最初の回答が出た後のページの URL を、その会話の `url` として保存する。会話ごとの URL が無いサイトでは、続行は「直前の会話」だけとし、`capabilities` で示す
- 要求ごとに会話を指定するので、キューで他の要求が間に入っても混ざらない（architecture 4 章）

## 9. 添付

1. `attach_button` を押して `file_input` が現れるのを待つ。または `filechooser` イベントを待つ
2. `set_input_files` でファイルを渡す
3. `attachment_ready` に一致する要素（添付の表示）が、ファイルの数だけ現れるまで待つ。エラー表示が出たら `AttachmentRejected`
4. 添付してから本文を入力して送信する

添付の対応の有無・サイズの上限・拡張子の制限・添付したファイルを AI が全文読めるのか（要約や検索だけか）は、調査項目とする。

## 10. 画面の変更への耐性と、壊れたときの報告

### 10.1 検知

- `open()` のとき、`ready` と `input` が見つかることを確かめる
- 各操作の段階（送信、特定、完了、抽出）で、必要なセレクタが見つからなければ `SelectorMissing(name, stage)` を出す
- 候補の列の 2 番目以降で見つかった場合は警告を記録する（1 番目が古くなっている兆候）

### 10.2 報告

エラーのたびに、`%LOCALAPPDATA%\llmc\diag\<日時>-<実行 ID>\` に次を保存する。

| ファイル | 内容 |
|---|---|
| `report.json` | エラーの種類、段階、試したセレクタと結果、URL、プロファイルの版、llmc の版、時間 |
| `screenshot.png` | ページ全体の画面 |
| `dom.html` | 会話の一覧の周辺の DOM（`script` と `style` を除く。大きすぎる場合は省略する） |

- 画面と DOM には**会話の中身や社内の情報が写る**。保存先は本人だけが読める場所とし、7 日後に自動で削除する。保存しない設定（`diag.capture: false`）も用意する
- 利用者には、何が起きたか、どのファイルを見ればよいか、次に何をすればよいか（`llmc probe`、`llmc login`、プロファイルの修正）を 1 画面に収まる文章で示す

### 10.3 `llmc probe`

| 段階 | 確認すること |
|---|---|
| 1. 起動 | ブラウザの起動、`url` の表示、ログイン状態 |
| 2. セレクタ | すべてのセレクタについて、見つかったか、何番目の候補か |
| 3. 入力 | 各入力方式の読み戻し。`--measure-input` で上限を測る。長文の添付への自動変換の有無 |
| 4. 往復 | 短い依頼を送り、送信の確認、回答の特定、完了判定、抽出（両方式）を確かめる |
| 5. 書式 | `__init__.py`、入れ子のフェンス、タブ、行末の空白、日本語を含む書式の回答を依頼し、両方式の抽出結果を解析して比べる。コピーで取れるのが生の Markdown かを判定する。`code_text` の推奨値を決める。OS のクリップボードが変わっていないか |
| 6. 報告 | 段階ごとの合否、推奨する設定（どの入力方式、どの抽出方式）、見つかった問題 |

### 10.4 ブラウザと SSO の組み合わせの調査（最優先）

社内の Entra ID に「準拠デバイス必須」などの条件付きアクセスがある場合、Playwright 同梱の Chromium はデバイスの情報を渡せず、ログインできない可能性がある。ヘッドレスの実行では UA（`HeadlessChrome`）で拒否される可能性もある。また Playwright 1.49 以降、ヘッドレスの既定は別のバイナリ（`chromium-headless-shell`）で、画面ありで行うログインとは別のバイナリで同じプロファイルを使うことになる。

全体の成否を決める前提なので、実装の最初の段階で次の組み合わせを確かめ、`browser.channel` と `headless` の既定値を決める（open-questions の最優先の項目）。

| 組み合わせ | 確かめること |
|---|---|
| 同梱 Chromium・画面あり | ログインできるか |
| 同梱 Chromium・ヘッドレス（headless-shell） | 画面ありでログインしたプロファイルで、ログイン状態が保たれるか |
| 同梱 Chromium・新しいヘッドレスモード（`channel: chromium`） | 同上 |
| Edge（`channel: msedge`）・画面あり / ヘッドレス | 同上。社内の SSO が Edge を前提にしていないか |
| 上のそれぞれ | ログイン状態がどのくらいの期間保たれるか（spec-auth） |

- 4 と 5 は実際に送信するので利用量を使う。`--offline` で 1〜3 だけ行える
- エージェントごとに `llmc probe --agent <名前>` で行える

## 11. エラーの扱い

| 事象 | 検知 | 対応 |
|---|---|---|
| ログイン切れ | URL がログイン画面のパターンに一致、またはログインを促す表示 | `LoginRequired`。デーモンはログインが必要な状態になり、以降の要求は即座にこのエラーで返す（spec-auth） |
| 生成の失敗 | 回答の要素の中か近くに `error_banner` が出る、またはその文字が `generation_failed_patterns` に一致 |
| モードの不一致 | `mode.required` が `mode_indicator` に一致しない（Copilot が「Web」になっている、など） | `ModeMismatch`。送信しない。送った内容が Web 検索に使われ得るため | `GenerationFailed`（画面の文言を添える） |
| レート制限 | `error_banner` か `system_notice` の文字が `rate_limit_patterns` に一致 | `RateLimited`。表示から待ち時間が読み取れれば添える。自動で待つかは呼び出し元の設定（ループの既定は、上限 30 分まで指数的に待って再試行 3 回） |
| 応答なし | 6.3 の上限 | `Timeout`。停止ボタンを押す |
| ブラウザの異常 | Playwright の接続切れ、ページの異常終了 | `BrowserCrashed`。デーモンがブラウザを 1 回だけ起動し直し、要求そのものは失敗として返す |
| 予期しないダイアログ | `dialog` イベント、画面を覆う表示 | 既知のもの（お知らせなど）はプロファイルの指定で閉じる。それ以外は `SelectorMissing` として報告する |

## 12. 他サイトへの対応

- 新しいサイトは、サイト別プロファイルを追加し、`llmc probe` が全段階で合格すれば対応とする
- プロファイルで表せない違いは、同梱のフックで吸収する。フックが増えすぎる場合は、そのサイト専用の `ChatBackend` 実装を作る（共通インタフェースは変えない）
