# 公開されている類似の実装と公式 API の調査

> 2026-11-28。利用者から紹介された 4 つの公開プロジェクトと、Microsoft の公式 API（Copilot Chat API、プレビュー）を読み、llmc の設計に取り入れるもの・取り入れないもの・確かめるものをまとめる。各プロジェクトは README と設計の文書だけを読んだ（ソースコードは読んでいない）。**コードは流用しない**（考え方だけを参考にする。M365CopilotBridge には利用許諾の表示が無い）。

## 1. 読んだもの

| 名前 | 方式 | 目的 | 利用許諾 |
|---|---|---|---|
| copilot-operator（ivan-markov-666） | Playwright、画面ありの Edge、TypeScript | Copilot が出したコマンドを Windows で実行し、結果を添付で返すループ | MIT |
| M365CopilotBridge（saadatzi） | Playwright、C# | OpenAI 互換の API として Copilot Chat を中継（VS Code の agent mode 用） | 表示なし |
| ask-m365copilotchat-mcp（ElSrJuez） | ブラウザ拡張、Python（FastAPI） | OpenAI 互換・MCP の中継 | Apache 2.0 |
| m365-copilot-proxy（cramt） | 画面の内部の WebSocket（非公開の通信） | OpenAI 互換の中継、ツール呼び出しの模擬 | MIT |
| Microsoft 365 Copilot Chat API（Microsoft Learn） | Microsoft Graph の `/beta/copilot/conversations/{id}/chat`・`chatOverStream` | 公式の会話 API（プレビュー） | 利用規約（プレビュー） |

## 2. llmc の PoC の結果と一致した点（設計の裏付け）

| 項目 | 類似の実装 | llmc |
|---|---|---|
| ブラウザ | copilot-operator は画面ありの Edge（`channel: msedge`）、専用のプロファイル（既定の User Data は使わない）。ヘッドレスは対象外 | 同じ（PoC-1b。組織ではヘッドレスがポリシーで禁止） |
| 送信 | Enter では送れず、送信ボタンを押す。送信ボタンは入力欄の枠の中で探す（ページ全体で探すと、フィードバックの窓の別の「Send」に当たった） | 送信ボタンを押す。**枠の中で探す**ことを spec-browser-driver 4.3 に加える |
| 抽出 | DOM の `innerText` はコードに使えない。回答全体の「応答のコピー」を押し、クリップボードへの書き込みをページの中で横取りする（OS のクリップボードを使わない） | 同じ（PoC-2・PoC-3） |
| 完了 | 停止ボタンが消え、最後の回答の中に応答のコピーのボタンがあり、本文が約 1.5 秒変わらない | ほぼ同じ（spec-browser-driver 6.2） |
| 一覧の仮想化 | 描かれている数は当てにならない。`aria-setsize` の最大値を使う | 数えない（spec-browser-driver 5 章、PoC-7 で実際に誤った） |
| 入力の上限 | 約 120,000 文字で断られる（copilot-operator）、128,000 文字が会話の上限（Bridge） | 64,000 文字まで送れた。既定 60,000（spec-file-protocol 11） |
| 出力の上限 | 回答は約 11,000〜12,000 文字が上限（proxy） | 個人版で約 8,000〜9,000 文字（PoC-6） |
| 断りの扱い | 断りの文言の型で検出し、1 回だけ直すよう頼む。繰り返したら新しい会話で規則を送り直す（Bridge） | 手がかりのコード（PoC-6）、spec-loop 6.3。新しい会話でのやり直しも spec-loop 8.5 に同じ |
| 直列の処理 | 3 つとも、1 度に 1 つの要求だけ | 同じ（前提 8） |

## 3. 取り入れるもの

| 項目 | 内容 | 反映先 |
|---|---|---|
| **`[名前]:` の破壊** | copilot-operator の報告: Copilot は `[math]::Round($x, 2)` を `:Round($x, 2)` に変える（**コードブロックの中でも**）。Markdown の参照リンクの定義（`[name]: url`）として扱われると見られる。PowerShell の型の書き方（`[string]::Join` など）はこれに当たる | **PoC-6 の E4 で確かめる**（`echo_fidelity.py --only E4`）。壊れるなら、`[` で始まり `]:` を含む行を代わりの記号にして送る（U+00A0 と同じ方式）か、そのファイルを書き換えられないものとして扱う。spec-file-protocol 9.6 |
| 長いコードブロックの DOM | DOM の `innerText` では、長いコードブロックに行番号が混ざり（120 行が 242 行に）、「さらに表示」で折りたたまれる | DOM 方式（PoC-7 で加えた代わりの抽出）は、**短い回答に限る**。行番号の混入・折りたたみを検出したら抽出の失敗にする。spec-browser-driver 7.2 |
| 送信ボタンの範囲 | 入力欄の枠（`chat-input-wrapper`）の中だけで探す | spec-browser-driver 3.2・4.3 |
| 初回の窓 | 「後で」「閉じる」など**断る側**のボタンだけを押す。「確認」など受け入れる側は押さない | spec-browser-driver 11 章 |
| 添付 | 隠れた `input[type=file]` に `setInputFiles`。`.ps1` は受け付けないので `.txt` にする。アップロードは利用者の OneDrive にコピーされる | PoC-5、spec-convert。OneDrive にコピーされることは spec-security の対象 |
| ダウンロード | `a[download]`（`blob:`）は押さない（Edge が落ちた報告）。ページの中で `fetch` して取り出す | PoC-5、spec-convert |
| 会話の付け直し | 保存した会話の URL → 一覧の名前 → 検索の順で探し、**黙って新しい会話にしない** | spec-loop 10.3 |
| 同じ操作の繰り返し | 同じコマンドで同じ結果が続いたら止める | spec-loop 8.4（同じ失敗の判定）と同じ考え方 |
| 会話の長さの上限 | 会話の文字数が上限（約 128,000 文字）に近づいたら、要約を付けて新しい会話へ移る | spec-loop 5.5（`new_every`）に、会話の累計の文字数による切り替えを加える |
| 利用量 | 1 時間あたりの送信の上限（既定 60） | spec-loop 11 章、NFR-14 |

## 4. 取り入れないもの

| 項目 | 理由 |
|---|---|
| 画面の内部の通信（WebSocket・SignalR）を直接使う（m365-copilot-proxy） | 非公開の通信で、画面より変わりやすい。利用規約・組織の方針の面でも、画面の操作より踏み込む。llmc は画面の操作か公式 API に限る |
| MFA の秘密鍵を保存して自動でログインする（m365-copilot-proxy） | 認証の仕組みを回避する方向で、llmc の方針（ログインは利用者が行う）に反する |
| ブラウザ拡張（ask-m365copilotchat-mcp） | 組織の PC で拡張を入れられるか分からない。Playwright で足りている |
| AI にコマンドを決めさせる（copilot-operator） | llmc は、実行するコマンドを利用者がループ定義に書く（FR-UC3-04）。AI が決めるのはファイルの中身だけ |
| 長い出力を添付で返す（copilot-operator） | 添付は利用者の OneDrive にコピーされる。llmc は本文に入れる（入力は 60,000 文字まで送れる）。必要になったら spec-convert で検討する |

## 5. 公式 API（Microsoft 365 Copilot Chat API、プレビュー）

| 項目 | 内容 |
|---|---|
| 入り口 | `POST https://graph.microsoft.com/beta/copilot/conversations/{conversationId}/chat`（同期）、`.../chatOverStream`（SSE）。会話は `copilot/conversations` で作る |
| ライセンス | **Microsoft 365 Copilot のアドオンのライセンスが必要**。無料の Copilot Chat だけの利用者は使えない |
| 権限 | 委任のみ（職場・学校のアカウント）。`Sites.Read.All`、`Mail.Read`、`People.Read.All`、`OnlineMeetingTranscript.Read.All`、`Chat.Read`、`ChannelMessage.Read.All`、`ExternalItem.Read.All` の**すべて**が必要。アプリの登録と、組織によっては管理者の同意が要る（ページには同意の要否の記載なし） |
| できないこと | ファイルの作成などの操作、コードインタープリター、画像の生成、長い処理（ゲートウェイのタイムアウト）。応答はテキストだけ |
| 位置づけ | `/beta`。本番での利用はサポート外 |

- llmc にとって: UC3 は回答のテキストだけを使う（実行は手元）ので、**公式 API の制約に当たらない**。画面の操作より壊れにくく、空行・U+00A0・`[名前]:` などの描画の問題も（Markdown のテキストで返るなら）避けられる可能性がある
- ただし、アドオンのライセンス、7 つの読み取りの権限（メール・会議の文字起こし・チャットなどを広く読む権限）を持つアプリの登録、管理者の同意が要る。前提 3（管理者権限なし）の下では、利用者だけでは用意できない
- 方針: `ChatBackend` の別の実装（`GraphChatBackend`）として**v1 の範囲外の候補**に置く。利用者の組織でライセンスと権限が用意できるかを確かめてから決める（open-questions）
- 利用者の回答（2026-11-28）: 用意できるかは分からない。**当面は画面の操作で進め**、分かったら利用者が知らせる。`ChatBackend` の差し替えの構造（FR-COM-01）は、この実装を後から加えられるように保つ
