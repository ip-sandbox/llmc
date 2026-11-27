# PoC の結果と設計への影響

PoC の生のレポートはリポジトリに置かず、ここには結論と設計への影響だけを記録する。

## 実行環境についての注意

| 回 | 環境 | 社内 PC との違い |
|---|---|---|
| 2026-11-28 | 利用者の個人の PC（Windows 10 Pro 19045、日本語版、Python 3.11.9、Playwright 1.65.2）。Claude Code が実行 | プロキシなし、管理者権限のあるアカウント（実行は通常の権限）。**Claude Code の実行環境の影響**として、コンソールのコードページが 65001、`PYTHONIOENCODING=utf-8`、プロセスがジョブ（`SILENT_BREAKAWAY_OK`）の中にある。PoC ではこれらを外した条件でも測った |

社内 PC では、プロキシ、ウイルス対策ソフト、グループポリシーで結果が変わり得る。PoC-0 と PoC-4 は社内 PC でも一度実行する。

## PoC-0: 環境（H-10, H-11）

### H-11 ブラウザ: 確認済み（個人の PC）

- `pip install playwright` と `playwright install chromium` は管理者権限なしで成功（プロキシなしの環境）
- 同梱 Chromium（既定のヘッドレス = headless-shell、新しいヘッドレス）と Edge（`channel=msedge`）のどれもヘッドレスで起動できた
- どのヘッドレスでも UA に `HeadlessChrome` が含まれる。`navigator.webdriver` は画面ありでも `true`

### H-10 パイプと文字コード: 想定どおり。PowerShell 5.1 は既定では使えない

コードページ 932 の新しいコンソール（社内 PC の既定に近い条件）での結果:

| 経路 | 結果 |
|---|---|
| cmd.exe のパイプ（`type` → python、python → python） | **バイト列をそのまま渡す**。UTF-8 で書けば UTF-8 のまま届く |
| cmd.exe のリダイレクト（`>`） | バイト列のまま |
| PowerShell 5.1 の文字列 → ネイティブコマンド（既定） | `$OutputEncoding` が us-ascii のため、日本語が **`?` に化ける** |
| PowerShell 5.1 のネイティブ → ネイティブ（既定） | PS が `[Console]::OutputEncoding`（cp932）で読み、us-ascii で書き直すので **`?` に化ける**。UTF-8 で出力すると読み違いでさらに崩れる |
| PowerShell 5.1 で `$OutputEncoding` と `[Console]::OutputEncoding` の両方を UTF-8 にした場合 | 正しく届く |
| PowerShell 5.1 のリダイレクト（`>`） | UTF-16LE で書かれる。UTF-8 の出力を cp932 として読んでから書くので、日本語が崩れる |
| Python がパイプに書く既定の文字コード | cp932（ロケール）。`PYTHONUTF8=1` で UTF-8 |

コードページ 65001 のコンソールでは、PowerShell 5.1 がネイティブコマンドへ書くときに **UTF-8 の BOM を先頭に付けた**（`$OutputEncoding` を UTF-8 にした場合も）。

設計への影響（spec-shell-integration で確定する）:

1. PowerShell 5.1 で日本語をパイプで使うには、`$OutputEncoding` と `[Console]::OutputEncoding` を UTF-8 にする設定が必須。llmc はこの設定を行う手順（プロファイルに書く数行）を示し、`llmc doctor` で確認する
2. llmc の stdin の読み込みは、先頭の UTF-8 BOM を取り除く
3. llmc の stdout の文字コードは、`--encoding` で指定でき、既定は「コンソールなら Unicode で書く／パイプやリダイレクトなら UTF-8」とする案を第一候補にする。PowerShell 5.1 の既定の環境では、UTF-8 で書いても cp932 で書いても日本語が崩れるので、どちらを既定にしても設定が必要
4. PowerShell 5.1 の `>` は使わず、`-o` か `--output` でファイルに書く使い方を案内する
5. Python の入出力の文字コードは、llmc の起動時に明示的に設定する（`PYTHONIOENCODING` などの環境変数や、Python のバージョンに依存しない）

## PoC-4: Windows の仕組み（H-12〜H-17）

| 仮説 | 結果 | 設計への影響 |
|---|---|---|
| H-12 名前付きパイプ | `multiprocessing.connection` のパイプの既定の DACL は **Everyone（WD）と匿名（AN）に読み取りを許す**（`(A;;FR;;;WD)(A;;FR;;;AN)`）。ctypes で `D:P(A;;FA;;;<本人>)(A;;FA;;;SY)` を指定したパイプを作れた。同名のパイプを `FILE_FLAG_FIRST_PIPE_INSTANCE` で作ると拒否（エラー 5）。クライアントから `GetNamedPipeServerProcessId` でサーバのプロセスの所有者 SID を確かめられた | **確定**: IPC は ctypes で DACL を指定した名前付きパイプ。標準ライブラリの `Listener` はそのままでは使わない。pywin32 は必須にしない |
| H-13 pythonw と Playwright | `pythonw.exe` を `DETACHED_PROCESS` で起動し、Playwright でヘッドレスの Chromium を開けた | デーモンは pythonw で動かせる |
| H-13 ジョブからの切り離し | 切り離しを許さないジョブの中から `CREATE_BREAKAWAY_FROM_JOB` で起動すると、**CreateProcess は成功するが、実際にはジョブの中に残った**（ジョブを終了すると孫も終了した）。許すジョブからは実際に切り離せた | デーモンの起動は「起動できたか」ではなく、**ジョブの外に出られたかを確かめる**（`IsProcessInJob` など）。出られない場合は警告し、タスクスケジューラなどからの利用では、デーモンを先に別に起動しておく手順を案内する（spec-daemon） |
| H-14 プロセスツリーの終了 | Job Object（`KILL_ON_JOB_CLOSE`）と `TerminateJobObject` で、子と孫まで終了できた | **確定**: 実行器は Job Object を使う |
| H-15 ファイルの置き換え | `ReplaceFileW` は ACL・属性・代替データストリームを保った。`os.replace` は属性（`NOT_CONTENT_INDEXED`）と代替データストリームを**失った**（明示的な ACE は継承の設定のため変化なし）。他のプロセスが読み取りで開いていると、`ReplaceFileW` はエラー 32（共有違反）、`os.replace` はエラー 5 で失敗 | **確定**: 既存ファイルは `ReplaceFileW`。他のプロセスが開いている場合の再試行は必要（エラー 32 と 5 の両方を対象にする） |
| H-16 リパースタグ | ジャンクションは `0xA0000003`、シンボリックリンクは `0xA000000C`（どちらも名前の差し替えのビットが立つ）。`os.lstat().st_reparse_tag` で取れた。OneDrive のフォルダはこの PC では見つからず、未確認 | ジャンクションとシンボリックリンクの判定は想定どおり。**OneDrive のクラウドファイルのタグは社内 PC で確かめる** |
| H-17 パスの挙動 | `mkdir("tdot.")` は `tdot` を作った。`"tfile .txt "` は `tfile .txt` になった（末尾の空白が切り詰められる）。8.3 形式の短い名前（`LONGDI~1`）が生成される | 末尾のドット・空白、8.3 形式の名前を文字列の段階で拒否する規則（spec-file-protocol 8.2）は必要 |

## PoC-1（一部）: 未ログインでの表示

ログインしない使い捨てのプロファイルで、各組み合わせで `https://copilot.microsoft.com/` を開いた（メッセージは送らない）。

- `copilot.com` に転送され、**「Sign into Copilot」のページ**が表示される。未ログインで使えるチャットの入力欄は無い（どの組み合わせでも同じ）
- ページには「One Microsoft Copilot experience across…」「Several Copilot features have new names」「Work / Life / School」とあり、**個人と仕事向けの Copilot の統合が進んでいる可能性がある**（推測。ログイン後の画面で確かめる）
- `locale=ja-JP` を指定しても表示は英語（en-US）だった
- ボット対策の画面は、どの組み合わせでも出なかった
- 個人の Copilot も、組織と同じく**ログインが前提**であると分かった。5.2.1 の「個人の Copilot には、ログインしていなくても使える状態がある」は誤りなので直す

## PoC-1: ログインの保持（H-01、個人の Copilot）

利用者が画面ありの Chromium と Edge でそれぞれ手動でログインした後、同じプロファイルを各組み合わせで開き直した（メッセージは送らない）。

### 結果

1. ログイン直後は、どちらのブラウザでも入力欄があり、サインインのボタンは無かった
2. **プロファイルを開き直すと、どの組み合わせでも「Sign into Copilot」のページに戻る**（画面ありでも同じ）。cookie はすべて永続的なもので、消えていない。copilot.com は、開いただけでは自動でログインしない
3. 「Sign in」を押すと、login.microsoftonline.com → login.live.com → copilot.com と転送され、**資格情報を入力せずにログインが完了する**組み合わせがある

| 組み合わせ | 「Sign in」を押した後 |
|---|---|
| 同梱 Chromium・headless-shell（既定のヘッドレス） | ログインできた |
| 同上、UA の HeadlessChrome を置き換え | ログインできた |
| 同梱 Chromium・画面あり | **メールアドレスの入力画面で止まった** |
| 同梱 Chromium・新しいヘッドレス（`channel=chromium`） | **メールアドレスの入力画面で止まった**（再試行でも同じ） |
| Edge・画面あり | ログインできた |
| Edge・ヘッドレス | ログインできた |

- 同梱 Chromium の本体のバイナリ（画面あり・新しいヘッドレス）だけが失敗し、headless-shell（別のバイナリ）は成功した。同じプロファイルを読んだときに見える login・live.com の cookie の名前とドメインは、両者で同じだった（27 件）。サードパーティ cookie の制限を無効にしても変わらなかった。**原因は未特定**
- ボット対策の画面は一度も出なかった。`navigator.webdriver` は常に `true` だが、ログインには影響しなかった
- ログインの完了までにかかった時間は、測り方に問題があり正確ではない（数秒〜数十秒）。PoC-2 で測り直す

### 設計への影響

1. **ログイン状態の判定は「ページを開いて入力欄があるか」だけでは足りない**。「Sign in」のボタンがあれば押して、黙ってログインできるかを試す手順（自動の再ログイン）をドライバに入れる。サイト別プロファイルに `login.resume`（押すボタンと、待つ条件）を持たせる（spec-auth、spec-browser-driver）
2. 黙ってログインできずに、資格情報の入力画面で止まった場合は `LoginRequired` とし、`llmc login` を案内する。llmc が資格情報を入力することはしない
3. **ブラウザの既定値の候補は Edge**（画面あり・ヘッドレスの両方で成功。組織の PC でも入っている見込みが高い）。ただし最終的には組織の Copilot（PoC-1b）で決める
4. 同じブラウザでもバイナリ（ヘッドレスの方式）によって結果が変わるので、`llmc probe` と `llmc doctor` で、使う組み合わせで実際に再ログインできるかを確かめる
5. ログインに使うブラウザと、普段使うブラウザ（ヘッドレス）は、**同じ種類にそろえる**ことを推奨する（Chromium の画面ありでログイン → headless-shell で使う、のような組み合わせは成功したが、仕組みが分からないまま頼らない）

未確認: ログインが保たれる期間（日を空けて check.py を実行する）、組織のアカウントでの挙動（PoC-1b）。
