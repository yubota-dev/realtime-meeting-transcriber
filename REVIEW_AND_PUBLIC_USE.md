# 公開コードレビュー・外部活用可能性調査

## 対象と制約

- 対象リポジトリ: `https://github.com/yubota-dev/realtime-meeting-transcriber`
- 対象コミット: `c4b0798`
- 対象: `git ls-files` で確認できるGit追跡ファイルのみ
- 対象外: 未追跡のスクリプト、記事、画像、PDF、アーカイブ、仮想環境、途中成果物、内部打ち合わせ情報
- レビュー日: 2026-07-10

未追跡ファイルはファイル名だけを `git status` で確認し、内容は開いていない。実行中のプロセス、音声デバイス、会議ログ、Ollama、GPUには接続していない。

## 結論

このツールが解決しようとしている問題は実在する。特に「クラウドへ会議内容を送れない」「日英中が混ざる会議を日本語で追いたい」「離席中だけ短く把握したい」というWindows利用者には価値がある。

ただし、現行GitHub版は一般利用者へ勧められる完成度ではない。音声分離、終了処理、録音時刻、バックプレッシャーに重大な不具合があり、公開READMEが推奨する `start.bat` もGitHubに存在しない。現在は「開発者本人の環境で動く公開プロトタイプ」と評価するのが妥当である。

外部提供を目指すなら、汎用AI議事録アプリとして正面から競合するのではなく、次へ絞るべきである。

> Windows上で、会議サービスを問わず、自分／相手を分けてローカル文字起こしし、日英中混在を日本語化して、離席中だけ即座に追いつける軽量ツール

## 指摘一覧

| ID | 重大度 | 対象ファイル | 要約 |
|---|---|---|---|
| R-01 | High | `meeting/transcriber.py` | 2ストリームが同じstateful VADモデルを共有している |
| R-02 | High | `meeting/run.py`, `meeting/transcriber.py` | 終了時に未処理音声を捨て、閉じたログへ後書きし得る |
| R-03 | High | `meeting/audio.py` | ストリーム開始後に基準時刻を設定している |
| R-04 | High | `meeting/audio.py`, `meeting/transcriber.py` | 同期翻訳中に無制限キューが増え、別ストリームも停止する |
| R-05 | Medium | `meeting/audio.py`, `meeting/transcriber.py` | チャンク単位リサンプルと端数処理で時刻が累積ずれする |
| R-06 | Medium | `meeting/transcriber.py` | VADのstart座標を無視し、発話冒頭を欠落させる |
| R-07 | Medium | `meeting/run.py` | 起動途中の失敗で録音・スレッド・ログを安全に解放できない |
| R-08 | Medium | `README.md`, `requirements.txt` | GitHubから推奨手順どおりに起動できず、CUDA条件も再現できない |
| R-09 | Medium | `meeting/run.py`, `meeting/transcriber.py` | 時刻が時分秒だけで、日跨ぎと同秒発言を正しく扱えない |
| R-10 | Low | `meeting/summarize_file.py` | JSONL末尾が破損すると正常行も要約できない |
| R-11 | Medium | 全体 | 自動テストとCIがなく、音声境界条件を検証できない |
| R-12 | High（公開時） | `README.md`, `meeting/run.py` | 録音通知、保存期間、削除、アクセス保護が不足している |

## コードレビュー詳細

### R-01: 2ストリームが同じstateful VADモデルを共有している

- 対象: `meeting/transcriber.py:34-42`, `meeting/transcriber.py:54-56`
- 重大度: High

**指摘**

`load_silero_vad()` で生成したモデルを1個だけ作り、自分用と相手用の2つの `VADIterator` へ渡している。コメントでは「本体は共有、Iteratorだけ分ける」としているが、Sileroの `VADIterator` は呼出しごとに `self.model(...)` を実行し、`reset_states()` も共有モデルの状態をリセットする。Iterator側のtrigger状態だけ分けても、モデル内部の再帰状態は分離されない。

Silero公式実装でも `VADIterator.reset_states()` が `self.model.reset_states()` を呼び、各チャンクで同じmodel instanceを実行していることを確認できる。

**影響**

- 相手音声を処理した直後のVAD状態が自分音声の判定へ混入する。
- 発話開始・終了の誤判定、短い発言の欠落、無音の誤検出が起こり得る。
- 「自分／相手を別ストリームで正確に記録する」という主要価値を損なう。

**修正案**

- ストリームごとに独立したVADモデルinstanceと `VADIterator` を持たせる。
- またはhidden stateを呼出し側で明示管理できる推論APIへ変更する。
- 2つの人工音声ストリームを交互に与え、一方の入力が他方のVADイベントへ影響しないテストを追加する。

根拠: [Silero VADの公式VADIterator実装](https://github.com/snakers4/silero-vad/blob/master/src/silero_vad/utils_vad.py)

### R-02: 終了時に未処理音声を捨て、閉じたログへ後書きし得る

- 対象: `meeting/run.py:144-153`, `meeting/transcriber.py:59-81`, `meeting/transcriber.py:107-132`
- 重大度: High

**指摘**

終了時は最初に `stop_event.set()` を呼ぶため、Transcriberはキューをdrainせずrun loopを抜ける。その後に各ストリームの `st.utter` だけを確定し、キュー内の音声と `st.buf` の端数は捨てる。

さらに `trans.join(timeout=10)` の完了確認をせず、要約後にJSONLを閉じる。Whisper処理時間に上限はなく、翻訳timeoutは30秒であるため、10秒後もTranscriberが動いている可能性がある。そのスレッドが後から `session.add_entry()` を呼ぶと、閉じたJSONLへの書込みになり得る。

**影響**

- 会議終了直前の発言がログと要約から欠落する。
- 終了時にバックグラウンドスレッドが例外終了する。
- 「qで全体要約を保存」という操作が完全な記録を保証しない。

**修正案**

1. 先に録音ストリームを停止して新規入力を止める。
2. 各音声キューへsentinelを入れる。
3. Transcriberが全キュー、VAD端数、発話中bufferをdrainしてから終了する。
4. 翻訳は別workerへ分離し、終了時に処理方針を選べるようにする。
5. Transcriberの終了を確認するまでJSONLを閉じない。timeout後に黙って続行しない。

### R-03: ストリーム開始後に基準時刻を設定している

- 対象: `meeting/audio.py:68-80`
- 重大度: High

**指摘**

`PyAudio.open()` は `start` 未指定時に即時開始するが、コードは `open()` の後で `_t0 = time.time()` を設定する。最初のcallbackが `_t0` 更新前に動けば、初期値0.0を基準に1970年相当の時刻を付ける。その後、既に開始済みのstreamへ `start_stream()` も呼んでいる。

PyAudio公式仕様では `start` の既定値は `True` であり、callbackには `input_buffer_adc_time` 等の時刻情報も渡される。

**修正案**

- `open(..., start=False)` とする。
- `_t0`, sample counter, resampler stateを初期化してから `start_stream()` を1回だけ呼ぶ。
- 可能ならcallbackの `time_info` をPortAudio時刻から壁時計へ対応付け、実際のcapture timeを使う。
- 最初のcallbackが基準時刻設定後にしか動かないことをmockで検証する。

根拠: [PyAudio 0.2.14公式ドキュメント](https://people.csail.mit.edu/hubert/pyaudio/docs/)

### R-04: 同期翻訳中に無制限キューが増え、別ストリームも停止する

- 対象: `meeting/audio.py:38`, `meeting/transcriber.py:59-75`, `meeting/transcriber.py:107-125`, `meeting/llm.py:32-47`
- 重大度: High

**指摘**

音声キューは上限なしである。1本のTranscriber threadが2ストリームのVAD、Whisper、Ollama翻訳をすべて直列実行する。非日本語発話の翻訳が最大30秒止まる間もcallbackは音声を追加し続ける。1ストリームにbacklogがある間は、そのストリームを空にするまで次ストリームへ移らない。

**影響**

- 多言語会議ほど表示遅延が増え、リアルタイム性を失う。
- 長時間障害時にメモリ使用量が増え続ける。
- loopbackのbacklogがmic処理を飢餓させ、自分側の発言確定も遅れる。
- callback内のSciPyリサンプル処理も重く、音声I/O deadlineを超える可能性がある。

**修正案**

- callbackは時刻とraw frameをbounded queueへ渡すだけにする。
- capture/resample/VAD、ASR、翻訳を別workerへ分離する。
- 2音源を公平に処理し、結果だけcapture sequenceで並べ直す。
- queue深度、最古音声の遅延、overflow/drop件数を表示・記録する。
- 上限超過時の方針を明示する。無言でdropせず、ログへ欠落区間を記録する。
- 独自streaming制御を拡張する代わりに、WhisperLive等の実績あるstreaming engineを利用する案も比較する。

参考: [WhisperLive公式リポジトリ](https://github.com/collabora/WhisperLive)

### R-05: チャンク単位リサンプルと端数処理で時刻が累積ずれする

- 対象: `meeting/audio.py:50-65`, `meeting/transcriber.py:64-73`
- 重大度: Medium

**指摘**

`resample_poly` をcallback単位で独立実行するため、filter stateを引き継がず、各境界でpaddingの影響が入る。出力長も毎回切り上げられる。実環境のSciPyで4096 sampleを検証すると、48kHzでは理想1365.333 sampleに対して毎回1366、44.1kHzでは理想1486.077に対して毎回1487となった。sample数だけで時計を進めるため、概算で1時間あたり約1.8〜2.2秒の累積ずれになる。

またTranscriberは前チャンクの端数を `st.buf` に残したまま、次チャンク到着時に `st.clock = t_chunk` で時刻を上書きする。端数を含む最初のVAD windowへ次チャンクの開始時刻を付けてしまう。

**修正案**

- filter stateとfractional phaseを保持するstreaming resamplerを使う。
- source sample positionまたはPortAudio capture timeを正とし、resample後の切上げ誤差から時刻を作らない。
- `buf_start_time` を別途保持し、buffer先頭sampleの時刻を上書きしない。
- 1〜3時間のsynthetic streamで最終時刻誤差、連続性、境界波形をテストする。

### R-06: VADのstart座標を無視し、発話冒頭を欠落させる

- 対象: `meeting/transcriber.py:83-95`
- 重大度: Medium

**指摘**

Sileroの `VADIterator` はspeech paddingを考慮したsample座標を `{'start': ...}` で返す。しかしコードは値を使わず、startイベントを受けた現在windowだけから `st.utter` を作る。VADが発話を確信する前のwindowと公式の30ms paddingを保持していない。

**影響**

- 発話の語頭や短い相づちが欠け、Whisper精度が低下する。
- 記録開始時刻が実際の発話開始より遅くなる。

**修正案**

- VAD判定前のring bufferを保持し、返却されたstart sampleから音声を復元する。
- end座標も使用し、余分な無音を含めない。
- 語頭直前に無音を置いたfixtureで、発話全体とtimestampを検証する。

### R-07: 起動途中の失敗で資源を安全に解放できない

- 対象: `meeting/run.py:99-122`, `meeting/run.py:137-153`
- 重大度: Medium

**指摘**

マイクのfallbackは `MicRecorder()` のconstructor失敗だけを捕捉する。デバイスは見つかっても `rec.start()` が失敗する場合があり、その例外はmainの `try/finally` より前で発生する。loopback、Transcriber、JSONLを開始済みでもcleanupされない。

**修正案**

- session、recorders、transcriberをcontext managerまたは `ExitStack` で管理する。
- 各recorderのopen/start失敗を個別に処理し、開始済み資源を逆順に解放する。
- mic start失敗でもloopback-onlyへ移行できるようにする。
- loopbackは必須なので、失敗時に診断情報を出して完全終了する。

### R-08: GitHubから推奨手順どおりに起動できず、CUDA条件も再現できない

- 対象: `README.md:35-51`, `requirements.txt:1-7`
- 重大度: Medium

**指摘**

READMEは `start.bat` のダブルクリック起動を推奨するが、そのファイルはGit追跡対象に存在しない。GitHub利用者は説明どおりに起動できない。

依存バージョンはすべて未固定であり、faster-whisperの現行GPU要件であるCUDA 12のcuBLASとcuDNN 9、CTranslate2との組合せもREADMEにない。公式ドキュメントはCUDA/cuDNN世代によってCTranslate2のdowngradeが必要になる場合を明記している。

**修正案**

- 公開可能な `start.bat` を追跡するか、READMEから推奨記述を削除する。
- Pythonと主要依存をlockし、検証済みCUDA/cuDNN/CTranslate2組合せを記載する。
- 起動前診断コマンドを追加し、GPU、CUDA runtime、Ollama、モデル、loopback、mic、書込み先を検査する。
- `large-v3/cuda/float16` を固定せず、small/medium/large-v3、CPU int8、CUDA float16を設定可能にする。
- GitHub Releaseへ検証済み版とセットアップ手順を出す。

根拠: [faster-whisper公式README](https://github.com/SYSTRAN/faster-whisper/blob/master/README.md)

### R-09: 時刻が時分秒だけで、日跨ぎと同秒発言を正しく扱えない

- 対象: `meeting/transcriber.py:127-132`, `meeting/run.py:48-77`
- 重大度: Medium

**指摘**

entryには `HH:MM:SS` だけを保存し、その文字列でsortと範囲抽出を行う。深夜0時を跨ぐと、0時以降の発言が前日分より前にsortされ、離席・直近5分の抽出も壊れる。同じ秒の複数発言もcapture順を表現できない。

**修正案**

- timezone付きISO 8601のcapture datetime、UNIX epoch、単調増加sequenceを保存する。
- 表示用 `HH:MM:SS` は保存値から生成する。
- 日跨ぎ、同秒、自分／相手の処理完了順逆転をテストする。

### R-10: JSONL末尾が破損すると正常行も要約できない

- 対象: `meeting/summarize_file.py:17-24`
- 重大度: Low

**指摘**

異常終了で最後のJSON行が途中まで書かれた場合、`json.loads` の例外でファイル全体の再要約が失敗する。

**修正案**

- 行番号付きでdecode errorを報告し、正常行を救済するモードを設ける。
- 最終行だけの破損は既定でskipし、出力へ警告を残す。
- JSONL書込みは必要に応じてflushに加えfsync、または一時journalを検討する。

### R-11: 自動テストとCIがない

- 対象: リポジトリ全体
- 重大度: Medium

Git追跡されたtest fileは0件である。最低限、次をhardware/networkなしのmockで検証すべきである。

- VAD stateのストリーム分離
- capture timestampと長時間resample誤差
- queue backlog、overflow、2ストリーム公平性
- shutdown drainとclosed-file race
- mic open失敗時のfallback
- 日跨ぎの離席・直近要約
- Ollama timeoutと部分要約失敗
- JSONL破損時の復旧

WindowsのGitHub Actionsでunit testとcompileを実行し、音声デバイスを必要とする試験は明示的なmanual integration testに分ける。

### R-12: 録音通知、保存期間、削除、アクセス保護が不足している

- 対象: `README.md`, `meeting/run.py:23-45`
- 重大度: High（他者利用・組織利用時）

**指摘**

ローカル処理はクラウド送信を減らすが、文字起こしは平文JSONLとして無期限保存される。起動時の録音通知、目的表示、保存期間、削除コマンド、保存先権限、除外区間、参加者への表示がない。WASAPI loopbackは会議アプリ以外のシステム音も取り込むため、通知音や別音声を記録する可能性もある。

日本の個人情報保護委員会は、通話内容から個人を識別できる場合は個人情報に該当し、個人情報取扱事業者には利用目的の通知または公表義務があると説明している。録音告知そのものが個人情報保護法上常に必須という意味ではないが、会議規程、契約、就業規則、他国法、会議サービス規約は別途確認が必要である。

**修正案**

- 起動時に「録音・文字起こし中」を明示し、利用目的と保存先を表示する。
- 利用組織の承認と参加者への通知を必須運用としてREADMEへ記載する。
- retention日数、会議単位削除、即時停止、保存しないlive-caption modeを実装する。
- Windows user-only ACLの保存先を使い、任意の暗号化保存を検討する。
- loopbackが全system audioを対象にすることを明記する。
- 法令適合を製品が保証する表現は避ける。

根拠: [個人情報保護委員会 Q1-10](https://www.ppc.go.jp/all_faq_index/faq1-q1-10/)

## 他者の困りごとを解決できるか

### 解決可能性が高い課題

| 困りごと | 適合度 | 理由 |
|---|---:|---|
| 機密会議をクラウドAIへ送れない | 高 | Whisper、VAD、翻訳、要約がローカルで完結する設計である |
| 日英中が混ざる技術会議を日本語で追いたい | 高 | 発話単位の言語判定と日本語訳が中心機能である |
| 離席中の決定事項・宿題だけ知りたい | 高 | `a`/`b` の離席window要約は明確な独自価値である |
| Teams・Zoom・Meetをまたいで同じ方法を使いたい | 中〜高 | Windows system audioを取るため会議サービス固有APIへ依存しない |
| 会議後に個人用の検索可能な記録を残したい | 中 | JSONLとMarkdownをローカル保存できるが検索UIはない |
| 聴覚支援として字幕を補助利用したい | 中 | live textは価値があるが、精度保証、字幕UI、遅延管理がなく補助用途に限る |

聴覚支援の需要自体は大きく、WHOは4.3億人がdisabling hearing lossへのrehabilitationを必要としていると報告している。ただし本ツールを合理的配慮やCARTの代替として保証してはならない。

根拠: [WHO Deafness and hearing loss](https://www.who.int/en/news-room/fact-sheets/detail/deafness-and-hearing-loss)

### 既存サービスで残っている隙間

- Microsoft Teamsはlive captionを提供するが、翻訳字幕はTeams PremiumまたはMicrosoft 365 Copilot等の対象ライセンスが必要である。transcriptは主催者のOneDrive for Businessへ保存され、外部参加者の事後アクセスにも制約がある。
- Google Meetの翻訳字幕も対象Workspace editionに限定される。
- Zoomは2026年5月18日以降、closed captionsの保存・downloadを終了し、保存にはMeeting transcriptsを使う必要がある。

このため「個人参加者が、会議サービスや主催者権限に依存せず、承認された範囲でローカル記録を持つ」という需要は残る。ただし、主催者権限を迂回する用途として訴求してはならない。

根拠:

- [Microsoft Teams live captions](https://support.microsoft.com/en-us/teams/meetings/use-live-captions-in-microsoft-teams-meetings)
- [Microsoft Teams live transcripts](https://support.microsoft.com/en-US/teams/meetings/start-stop-and-download-live-transcripts-in-microsoft-teams-meetings)
- [Google Meet translated captions](https://support.google.com/meet/answer/10964115)
- [Zoom closed caption保存仕様](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0063899)

### 現状では適さない課題

- 相手が複数いる会議の個人別話者分離
- Mac、Linux、スマートフォンでの利用
- NVIDIA GPUがない一般PCでの即時利用
- 企業全体の監査、保持ポリシー、権限管理、共有、検索
- 医療、法務、人事等で正確性や証拠性を保証する正式議事録
- 非技術者がinstallerだけで使う用途
- 同時通訳として低遅延を保証する用途
- 会議アプリ以外のsystem audioを確実に除外する用途

## 競合と差別化

ローカル会議アシスタント市場は既に混雑している。

- [Meetily](https://github.com/Zackriya-Solutions/meetily) はWindows/macOS対応、ローカル文字起こし、話者分離、Ollama要約、installer、履歴、crash recoveryを備える。
- [WhisperLive](https://github.com/collabora/WhisperLive) はstreaming、word timestamp、hotwords、speaker diarization、複数backend、browser clientを備える。
- [anarlog](https://github.com/fastrepl/anarlog) はローカル文字起こしとMarkdown保存、任意LLM接続を提供する。

したがって「ローカル・無料・Whisper・Ollama」だけでは差別化にならない。本プロジェクトで残る差別化候補は次である。

1. **離席キャッチアップ**: 離席区間だけを即時に4観点で要約する。
2. **日本語中心の混在言語処理**: 日英中の会議を日本語へ揃える。
3. **自分／相手の物理2系統分離**: bot参加や会議APIなしで最低限の話者ラベルを付ける。
4. **小さく監査可能なCLI**: 大規模desktop appよりコードとデータフローを把握しやすい。

## 公開状況の評価

公開GitHubは4 commits、0 stars、0 forks、0 issues、releaseなしである。これは需要がない証拠ではないが、外部利用の検証、installer配布、versioning、support履歴がまだないことを示す。

根拠: [公開GitHubリポジトリ](https://github.com/yubota-dev/realtime-meeting-transcriber)

## 推奨ロードマップ

### 公開前P0

1. R-01〜R-04を修正する。
2. lossless shutdownと長時間timestamp testを追加する。
3. `start.bat` を公開版へ含め、検証済み依存を固定する。
4. 録音中表示、利用目的、削除、保存期間、loopback範囲を実装・文書化する。
5. 旧GitHub版の既知不具合をREADMEまたはIssueへ明記する。

### 利用者拡大P1

1. Whisper model、device、compute type、Ollama modelを設定可能にする。
2. GPUなし用のsmall/medium int8 profileを用意する。
3. backlog、capture loss、処理遅延を画面へ出す。
4. 専門用語hotwordsと会議別辞書を追加する。
5. transcript訂正、検索、exportを追加する。
6. Windows用installerまたは署名付きrelease archiveを提供する。

### 差別化P2

1. 離席区間の開始・終了をGUIまたはglobal hotkeyで操作できるようにする。
2. 「決定事項」「担当者」「期限」「自分への質問」を構造化JSONでも保存する。
3. 日本語技術会議向け辞書・prompt templateを用意する。
4. acoustic echoによる自分／相手の重複を検出する。
5. 必要なら相手側だけspeaker diarizationを追加する。

## 最終判定

- **他者の困りごとを解決できるか**: 条件付きでYes。
- **現在のGitHub版を他者へ推奨できるか**: No。
- **最初の対象者**: Windows、NVIDIA GPU、Ollamaを自力で準備でき、クラウドへ出せない日英中会議を扱う技術者。
- **最も強い価値**: ローカル処理そのものではなく、「離席中だけ追いつく」「日本語中心に混在言語を揃える」「会議サービス非依存」の組合せ。
- **公開継続の判断**: 汎用製品として機能を広げるより、上記の狭い用途を高信頼に仕上げる方が勝算がある。

## 実施した検証

- Git追跡ファイルがworking tree上でHEADと一致することを確認した。
- Git追跡Pythonファイルの `compileall` は成功した。
- Git追跡test fileは0件であった。
- SciPy `resample_poly` の4096 sample出力長を48kHz、44.1kHzで数値確認した。
- PyAudio、Silero VAD、faster-whisperの公式仕様を照合した。
- 公開GitHub、Teams、Google Meet、Zoom、個人情報保護委員会、WHO、主要ローカル競合の一次情報を調査した。
- 実行中プロセスを止める試験、音声デバイス試験、GPU推論、Ollama通信、実会議ログ確認は行っていない。
