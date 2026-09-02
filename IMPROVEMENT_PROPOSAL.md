# リアルタイム多言語会議支援ツール 改善提案書

## 1. 目的

`realtime-meeting-transcriber` を、次の2つの利用目的へ対応させる。

1. **記録目的**: 会議音声を取りこぼさず、高精度な文字起こしと議事要約を残す。
2. **理解目的**: 多言語会議中に、発話内容を低遅延で日本語表示する。

対象言語は**日本語・英語・中国語**とし、1発話内および発話間のcode-switchを含む。通常モードでは各言語の原文を保持し、翻訳優先モードでは日本語以外の発話を低遅延で日本語表示する。

現在は音声取得、文字起こし、翻訳が1本の処理経路で直列実行されている。そのため、翻訳が遅れると文字起こしも停止し、両目的を同時に満たせない。本提案では処理を分離し、「通常モード」と「翻訳優先モード」を選択可能にする。

## 2. 結論

改善の中心はモデル交換だけではなく、次の3点である。

1. 音声取得、VAD、ASR、翻訳、保存を独立したworkerへ分離する。
2. 用途に応じて処理優先度とモデルを切り替える。
3. Whisper `large-v3` 固定を廃止し、中国系を除外した複数ASR backendを実測比較する。

### モデル調達ポリシー

- 中国企業・中国系組織が開発・提供するmodelは採用しない。
- Qwen3-ASRは採用禁止とする。
- 現行の翻訳・要約model `qwen2.5:14b` もAlibabaのQwen系であるため置換対象とする。
- modelの性能だけでなく、開発主体、配布元、license、更新経路、hashをmanifestへ記録する。
- 禁止model名を設定と起動前診断で検出し、誤使用を防止する。
- agentは編集・test・差分提示まで行えるが、`git commit`、tag作成、pushは人間が差分と検証結果を確認して明示承認した後だけ実行する。

公式model cardと公式repositoryを照合した推奨モデル構成は次である。

| 用途 | 第一候補 | 役割 |
|---|---|---|
| 通常文字起こし | Whisper `large-v3` / faster-whisper | 精度を優先した原文文字起こし |
| 翻訳優先・低遅延 | Whisper `large-v3-turbo` + Gemma 3 4B等の非中国系翻訳LLM | ASRと翻訳を非同期実行する速報表示 |
| 精度優先・会議後確定 | Whisper `large-v3` + glossary + 長文再処理 + WhisperX | 最終文字起こし、単語時刻、話者分離 |
| 非中国系の実験候補 | Meta Omnilingual ASR | 日英中を含む実音声でlarge-v3と比較 |
| 日本語専用比較 | Kotoba-Whisper v2.x | 日本語主体会議でのみ評価 |
| 会議後の翻訳・要約 | Gemma 3 12Bを第一候補として比較 | 現行Qwen2.5:14Bを置換 |

`large-v3-turbo` は速度候補であり、`large-v3`より高精度であることを前提にしない。精度向上は音声前処理、VAD、文脈、glossary、会議後の長文再処理を先に実施する。別modelとしてはMeta Omnilingual ASRを実験候補にするが、日英中の実会議でlarge-v3を上回るかはreference setで確認してから採用する。

### 提示されたモデル構成の検証結果

| 候補 | 判定 | 公式情報に基づく理由 |
|---|---|---|
| Qwen3-ASR 1.7B / 0.6B | 採用禁止 | 中国系modelを採用しない本プロジェクトの調達方針に反する。ASR専用であり、日本語訳を直接生成する翻訳器としても扱えない |
| Whisper `large-v3-turbo` | 条件付き採用 | 32層のdecoderを4層へ削減した高速版で、公式model cardも小幅な品質低下を明記している。通常の精度優先枠ではなく速報ASRへ使う |
| Kotoba Whisper bilingual v1.0 | 主構成では不採用 | 日英ASRと日英双方向翻訳だけを対象とし、中国語を扱えない。公式評価でも翻訳精度は同card掲載のcascaded構成より低い |
| NVIDIA Parakeet TDT 0.6B v3 | 不採用 | 公式対応は欧州25言語だけで、日本語と中国語を含まない。公式の推奨OSもLinuxである |
| Voxtral Mini 4B Realtime | 実験候補 | 日本語・中国語を含む13言語のstreaming ASRだが翻訳modelではない。BF16でGPU 16GB以上を単体で要求するため、同一GPUで翻訳LLMと常駐させにくい |
| WhisperX | 会議後処理に採用 | forced alignment、単語時刻、話者分離を付加する。文字列の誤認識を自動訂正するmodelではなく、重なり発話とdiarizationにも限界がある |
| Meta SeamlessM4T / SeamlessStreaming | 製品候補から除外 | 直接speech-to-text translationは可能だが、modelはCC-BY-NC 4.0で商用利用に適さない。研究用比較に限定する |

このため、提示された `turbo / kotoba-bilingual / large-v3+WhisperX / parakeet` の4枚構成は採用しない。中国語会議を扱えず、翻訳modelではないASRを翻訳枠へ置き、WhisperXを文字認識の精度向上器として誤解しているためである。

### 最終推奨構成

1. **通常文字起こし**: Whisper `large-v3`をfaster-whisperで実行する。まずVAD分離、pre-roll、streaming resampler、文脈、glossaryを修正する。
2. **翻訳優先モード**: Whisper `large-v3-turbo`で原文を速報表示し、Gemma 3 4B等の非中国系LLMへ非同期で翻訳を送る。翻訳待ちでASRを止めない。
3. **会議後の高精度再処理**: 保存音声をWhisper `large-v3`で長めの文脈とglossary付きで再処理し、WhisperXは単語時刻と話者割当のために使う。
4. **会議後の要約**: 原文と翻訳を別々に保持し、Gemma 3 12B等で根拠event ID付きの構造化抽出を行う。自由文の再要約だけに依存しない。
5. **fallback**: 精度側は`large-v3`、遅延側は`large-v3-turbo`とする。日本語・中国語非対応のParakeetは使わない。
6. **比較候補**: Voxtral RealtimeとMeta Omnilingual ASRは、同じ会議音声でCER/WER、固有名詞、言語切替、遅延、VRAMを測り、合格時だけ追加する。

16GB VRAMで「全modelを余裕で同時常駐できる」という説明も正しくない。Voxtral Realtimeは公式に単体で16GB以上を要求する。1 GPU構成ではASRを常駐させ、翻訳LLMを量子化するかCPUへ一部offloadする。会議後処理はmodelを排他loadするresource managerで実行する。

### 実機メモリの活用方針

2026-07-10の実測では、GPUはRTX 5070 Ti 16GB（総量16,303MiB、計測時空き14,258MiB）、system RAMは95.7GB（計測時空き65.4GB）である。RAMを単なる予備領域にせず、次の用途へ明示的に割り当てる。

- live時はASRをGPUへ優先配置し、翻訳LLMは量子化してGPUへ部分offloadする。VRAM不足時は翻訳側をRAM/CPUへ退避し、ASRを止めない。
- ASR、翻訳、alignment、diarizationを同時常駐させない。resource managerがmodeごとの許可modelを管理し、会議後処理では順番にload/unloadする。
- model weightのdownload cacheとCPU側weightをRAMへ保持し、mode切替時のdisk readを減らす。ただし空きRAMが16GBを下回る前にcacheを解放する。
- audio queueをRAM拡張で無制限化しない。短いbounded queueとdisk spoolを組み合わせ、長時間会議でもmemory leakとOOMを防ぐ。
- Voxtral Realtimeを試す場合はGPU単独常駐とし、翻訳LLMはRAM/CPU側で動かす。翻訳p95が目標を超える場合は採用しない。
- peak VRAM、process working set、available RAM、page file、queue長を定期記録し、VRAM 85%または空きRAM 16GBを切替判断の初期watermarkとする。値は負荷試験後に確定する。

推奨するlive時の優先順位は `GPU: ASR > 翻訳 > 要約`、RAM使用の優先順位は `未保存音声 > model weight/cache > 翻訳context > 要約context` とする。要約は会議中に資源が不足したら停止し、会議後に再開する。

#### Resource manager制御契約

resource managerは優先順位を表示するだけでなく、次の操作を一元管理する。

- faster-whisper/CTranslate2、Ollama/llama-swap、WhisperX/PyTorchについて、process ID、model ID、load状態、VRAM/RAM、最終利用時刻を追跡する。
- llama-swapのrouteとOllamaの`keep_alive`を制御し、不要modelを明示的にunloadする。CTranslate2/PyTorchもobject解放とcache解放後にVRAM減少を確認する。
- model load前に必要memoryを予約判定し、watermarkを超える場合はloadを開始しない。ASRを維持したまま翻訳をCPU offloadまたはofflineへ切り替える。
- unload timeout、model process異常終了、VRAM未解放を状態eventとして記録する。無断でASR processを終了しない。
- model swap時間、load失敗、CPU offload時tokens/sec、page file増加をmetricsへ含める。

mode別contextの初期上限は、live翻訳input 4K tokens、要約抽出chunk 8K tokens、最終統合16K tokensとする。Gemma 3の128Kはmodel仕様であり、この実機での運用値とはみなさない。reference hardwareでVRAM/RAMと品質を確認した場合だけ上限を変更する。

参考:

- [faster-whisper公式リポジトリ](https://github.com/SYSTRAN/faster-whisper)
- [Whisper large-v3-turbo model card](https://huggingface.co/openai/whisper-large-v3-turbo)
- [Kotoba Whisper bilingual v1.0 model card](https://huggingface.co/kotoba-tech/kotoba-whisper-bilingual-v1.0)
- [NVIDIA Parakeet TDT 0.6B v3 model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
- [Voxtral Mini 4B Realtime model card](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602)
- [WhisperX公式リポジトリ](https://github.com/m-bain/whisperX)
- [Meta Seamless Communication公式リポジトリ](https://github.com/facebookresearch/seamless_communication)
- [Kotoba-Whisper v2.0](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0)
- [Meta Omnilingual ASR](https://ai.meta.com/research/publications/omnilingual-asr-open-source-multilingual-speech-recognition-for-1600-languages/)
- [Gemma 3 model card](https://ai.google.dev/gemma/docs/core/model_card_3)

## 3. 現状の主要課題

### 3.1 音声処理の信頼性

- 自分／相手の2ストリームが同じstateful Silero VADモデルを共有している。
- PyAudio stream開始後に基準時刻を設定している。
- callback単位の `resample_poly` によりfilter stateとsample端数が失われる。
- VADが返すspeech start座標を使用せず、発話冒頭を切り落とす。
- 終了時にキューをdrainせず、最後の発話を失う可能性がある。

### 3.2 並列性と遅延

- 音声取得queueが無制限である。
- 1本のthreadが2音源のVAD、Whisper、翻訳を直列処理する。
- 翻訳中は最大30秒、両音源の文字起こしが停止する。
- backlog、処理遅延、drop件数が可視化されない。

### 3.3 認識精度

- ASR modelが `large-v3/cuda/float16` に固定されている。
- 専門用語、人名、製品名を与える辞書機能がない。
- 発話単位が短く、前後文脈を利用していない。
- マイクへ相手音声が回り込んだ場合の重複検出がない。
- 認識精度を比較する評価データと指標がない。

### 3.4 公開利用

- READMEが推奨する `start.bat` がGitHubに登録されていない。
- 依存バージョンとCUDA構成が固定されていない。
- 録音通知、保存期間、削除、アクセス保護が不足している。
- 自動テストとCIがない。

### 3.5 要約精度

- 40発言という固定件数で分割しており、token数、話題、時間、発言の連続性を考慮していない。
- 各chunkを自由文で短く要約してから、自由文同士を再要約するため、決定事項、否定、担当者、期限が中間段階で失われる。
- 要約結果がどの発言を根拠にしたか追跡できない。
- `ja` が存在するとoriginalではなく翻訳文だけを要約へ渡すため、翻訳誤りが要約へ固定される。
- 「自分宛て」の判定規則がpromptだけに依存し、誰から誰への質問・依頼かを構造化していない。
- 要約内容の正解データと評価指標がない。

詳細は `REVIEW_AND_PUBLIC_USE.md` を参照すること。

## 4. 提案アーキテクチャ

```text
                       ┌─ loopback raw queue ─ resampler ─ VAD ─┐
PyAudio callbacks ─────┤                                        ├─ ASR scheduler
                       └─ mic raw queue ────── resampler ─ VAD ─┘       │
                                                                        ↓
                                                               transcript events
                                                          ┌─────────────┼─────────────┐
                                                          ↓             ↓             ↓
                                                     JSONL writer   原文表示     translation queue
                                                                                      │
                                                                                      ↓
                                                                                日本語訳表示
                                                                                      │
                                                                                      ↓
                                                                                summary worker
```

### 4.1 絶対に守る優先順位

処理モードにかかわらず、優先順位は次とする。

1. **音声取得を止めない**
2. capture時刻とsource sequenceを失わない
3. 原文文字起こしを保存する
4. 翻訳する
5. 要約する

「翻訳優先」とは音声取得やASRを犠牲にすることではない。ASR完了後のeventを翻訳workerへ即時投入し、要約や会議後処理より優先するという意味である。

### 4.2 Audio capture layer

- callback内ではraw frame、PortAudio時刻、source ID、sequenceだけをbounded queueへ入れる。
- SciPyリサンプル、VAD、ログ出力をcallback内で実行しない。
- `open(..., start=False)` とし、時刻基準と状態を設定後にstreamを開始する。
- sourceごとに独立したstreaming resamplerを持つ。
- queue上限超過時は無言で破棄せず、欠落時刻とsample数をeventとして記録する。

### 4.3 VAD layer

- loopbackとmicでVAD model instanceを分離する。
- sourceごとにpre-roll ring bufferを持つ。
- Silero VADのstart/end sample座標を利用する。
- 発話前後のpadding、最短発話時間、最大発話時間を設定可能にする。
- 翻訳モードでは短い発話区間、記録モードでは文脈を保ちやすい長めの区間を使う。

### 4.4 ASR layer

ASRをinterface化する。

```python
class ASRBackend(Protocol):
    def transcribe(self, utterance: AudioUtterance, context: ASRContext) -> TranscriptResult:
        ...
```

実装候補:

- `FasterWhisperBackend`
- `MetaOmnilingualASRBackend`（accuracy modeの会議後再処理に限定した実験候補）
- 将来の `CloudASRBackend`（明示的opt-inのみ）

共通出力:

- source ID
- capture開始・終了時刻
- sequence
- detected language
- ja/en/zhのlanguage probability
- original text
- model ID
- confidenceまたはscore
- `no_speech_prob`
- `avg_logprob`
- `compression_ratio`
- confidence status（`normal` / `low` / `discard_candidate`）
- processing latency
- provisional/final

`no_speech_prob`、`avg_logprob`、`compression_ratio`はevent metadataの必須keyとする。FasterWhisper以外のbackendが同じ値を返せない場合もkeyを省略せず`null`とし、backend固有scoreを別に保存する。Whisper系の初期判定値は次とし、reference setで調整する。

- `no_speech_prob > 0.6`かつ`avg_logprob < -1.0`: 無音hallucinationの破棄候補
- `avg_logprob < -1.0`: provisional表示へ低信頼フラグを付与
- `compression_ratio > 2.4`: 繰り返しhallucinationの破棄候補
- 無音区間における同文反復、既知の定型句反復、直前発言の異常反復: rule-based detectorで破棄候補

破棄候補も監査用eventとして保存し、通常画面の「要確認」欄へ折りたたみ表示する。要約本文からは除外するが、低信頼eventの件数と時刻を末尾へ表示する。数値、否定、依頼、決定表現、固有名詞を含む場合は自動除外せずhuman review候補へ送る。元音声と原認識結果は人手確認できるよう残す。

言語判定は次の2段構成にする。

1. sourceごとに `auto` / `ja` / `en` / `zh` のlanguage lockを設定できるようにする。例えば日本語話者のmicを`ja`へ固定できる。
2. `auto`でja/en/zh以外が検出された場合、ja/en/zhの確率だけを再正規化してfallback判定する。短い発話では直前の確定言語をpriorにし、低confidenceの1発話だけで翻訳要否を反転させない。

code-switch評価では、language lock使用時と`auto`時を分けて測る。lockは利用者が明示したsourceにだけ適用し、loopback全体へ一律適用しない。

### 4.5 Translation layer

- ASR threadからOllama呼出しを分離する。
- deadline付き`live translation queue`と、暗号化永続化する`offline completion queue`を分離する。
- live queueは初期上限8 final eventsとし、source間の公平性を維持する。
- live deadline内に処理開始できないeventはLLMを呼ばず`offline_pending`へ移す。原文とeventは失わない。
- 日本語訳の絶対deadlineは`capture_ended_at + 10秒`とする。translation workerは直近の生成時間EWMAから必要時間を予測し、残り時間が予測値を下回ったeventを開始せずofflineへ移す。初期予測値は3秒とし、ASR完了時点ですでにdeadlineを超えたeventもofflineへ送る。
- final、現在議題、利用者が選択したeventを優先し、provisionalは同一event IDの最新版へcoalesceする。
- 翻訳結果が遅れても原文表示とログ保存は継続する。
- original eventを上書きせず、同じevent IDへtranslationを追記する。
- timeout、再試行回数、未翻訳状態を明示する。
- 同一人物の直前1〜3発言を翻訳contextとして渡せるようにする。
- prompt injection対策として、会議発話を命令ではなく翻訳対象データとして明確に区切る。

### 4.6 Storage layer

eventは時分秒だけでなく次を保存する。

session artifactの保護方針を次へ固定する。

| artifact | 既定保存 | 暗号化 | retention |
|---|---|---|---|
| audio | OFF、accuracy時だけopt-in | AES-256-GCM | 再処理成功後または24時間 |
| transcript JSONL | ON | session keyで暗号化 | 利用者設定、既定30日 |
| translation / offline spool | ON | session keyで暗号化 | transcriptと同じ |
| summary | ON | session keyで暗号化 | transcriptと同じ |
| benchmark export | 明示操作のみ | 匿名化後に別file | 利用者設定 |
| note/public export | 明示操作のみ | 公開用copyは平文可 | 元sessionと分離 |

session keyはDPAPI CurrentUserで保護し、音声以外のartifactも同じsecurity boundaryへ入れる。transcriptとspoolはeventごとに独立したnonceとauthentication tagを持つlength-prefixed AES-GCM recordとして追記し、末尾recordが破損しても直前まで復旧できるようにする。nonce再利用を禁止し、session内counterとrandom prefixを永続化する。summaryはtemporary平文fileを作らずmemoryから暗号化fileへ書く。Windows Search index、backup、crash dump、temporary fileへ平文が残らない設計とする。公開用exportは元sessionを直接使用せず、匿名化検査を通したcopyとして生成する。

この暗号化は保存媒体、backup、誤添付等に対するat-rest保護である。同一Windows user権限のmalware、unlocked session、screen capture、process memory、利用者自身による公開操作からは保護できない。UIと公開資料でこのthreat modelを明示し、暗号化を参加者同意や端末管理の代替として扱わない。

```json
{
  "event_id": "...",
  "session_id": "...",
  "source": "mic",
  "speaker": "自分",
  "capture_started_at": "2026-07-10T20:00:00.123+09:00",
  "capture_ended_at": "2026-07-10T20:00:03.456+09:00",
  "sequence": 123,
  "language": "en",
  "language_probabilities": {"ja": 0.02, "en": 0.96, "zh": 0.02},
  "original": "...",
  "translation": "...",
  "asr_model": "whisper-large-v3",
  "no_speech_prob": 0.03,
  "avg_logprob": -0.21,
  "compression_ratio": 1.14,
  "confidence_status": "normal",
  "translation_model": "gemma3:12b",
  "status": "translated",
  "latency_ms": 2400
}
```

終了時は次の順とする。

1. recorder停止
2. capture queueへsentinel
3. resample/VAD/ASRをdrain
4. original transcriptを確定・保存
5. 翻訳queueをdrainまたは「未翻訳」として保存
6. summary生成
7. JSONL close

### 4.7 Summary layer

要約を1回の自由文生成として扱わず、次のpipelineへ分離する。

```text
transcript events
      │
      ├─ token・話題・時間境界でchunk作成
      ↓
根拠付き構造化抽出(JSON Schema)
      ↓
schema・event ID・引用内容の機械検証
      ↓
重複統合・訂正反映・矛盾保持
      ↓
検証済みJSONだけから最終Markdownを生成
```

要約生成はASR・翻訳workerとは別にし、翻訳モード中は最低優先度とする。離席要約だけは利用者操作により優先度を上げる。

## 5. 処理モード

### 5.1 通常モード `transcript`

目的は完全な記録である。

```powershell
python -m meeting.run --mode transcript
```

推奨設定:

- ASR: Whisper large-v3または非中国系候補の評価で勝った高精度model
- 長めの発話区間
- original transcript eventを欠落なく保存する。ここでの欠落なしはevent保存の完全性を意味し、ASR文字列が音声の正解であることは保証しない
- 翻訳は非同期・best effort
- 要約コマンド利用可
- backlogが発生しても音声を保持し、遅延を表示する

### 5.2 翻訳優先モード `translate`

目的は会議中の理解である。

```powershell
python -m meeting.run --mode translate --target-language ja
```

推奨設定:

- ASR: Whisper large-v3-turboを第一候補とし、large-v3低遅延設定およびVoxtral Realtimeを同一音声で比較
- 翻訳: Gemma 3 4B等の非中国系LLMを別workerで実行し、ASRとは独立にbackpressureを制御
- 短い発話区間
- 原文を先にprovisional表示し、`avg_logprob`等が閾値外なら低信頼表示にする
- 翻訳完了後、同じ発言へ日本語訳を追記
- translation queueをsummary queueより優先
- 会議中の全体要約を停止または低優先度化
- backlogが閾値を超えたら軽量modelへ切替可能にする
- target languageを将来日本語以外にも拡張可能な設計にする

翻訳workerの初期値はlive queue上限8 final events、1発話15秒timeoutとする。output上限は入力長と対象言語から決め、初期hard capを`num_predict=384`（OpenAI互換APIでは`max_tokens=384`）とする。provisional eventは同一event IDの最新版へcoalesceする。deadline超過または上限到達時も原文を捨てず、翻訳状態を`offline_pending`として暗号化queueへ移し、会議後に再処理する。値は実機のp50/p95、訳文切断率、offline移送率を見て調整する。

### 5.3 精度優先モード `accuracy`

目的は会議後の確定記録である。

```powershell
python -m meeting.reprocess SESSION_ID --mode accuracy
```

推奨設定:

- 会議中のchunkではなく、連続性を保った長い音声区間を再処理
- ASR: Whisper large-v3を主軸に、Meta Omnilingual ASR等の非中国系候補と比較
- hotwords、会議用語集、参加者名、製品名を利用
- WhisperX等でword timestamp、forced alignment、speaker diarizationを生成する。ただしASR文字列の自動訂正には使わない
- live transcriptを上書きせず、final transcriptとして別version保存
- 差分を表示し、人間が確定できるようにする

現状は音声そのものを保存していないため、accuracy modeを実現するには、参加者への通知と承認を前提に、一時音声保存を選択可能にする必要がある。保存しない運用では、live処理中に高精度modelを使う。

## 6. 精度向上策

### 6.1 モデル変更前に直す項目

次の問題を残したままmodel比較を行ってはならない。

1. VAD state共有
2. 発話冒頭欠落
3. callback単位resample
4. capture時刻ずれ
5. micへのloopback回り込み
6. shutdown時の末尾欠落

これらはmodel性能ではなく入力品質の問題であり、どのmodelへ変更しても精度を下げる。

### 6.2 専門用語辞書

会議ごとに次を設定可能にする。

- 参加者名
- 会社名・部署名
- 製品名
- 技術用語
- 略語
- 地名

Whisper backendでは `hotwords` と `initial_prompt` を使用する。ただし長すぎるpromptは逆効果になり得るため、会議ごとに必要語だけを渡す。

ASR後の補正は次の2種類を分離する。

1. **決定的補正**: 登録済み辞書による明確な表記統一
2. **LLM補正候補**: 原文を残し、人間へ候補として提示

LLMの推測でoriginal transcriptを黙って書き換えない。

### 6.3 文脈利用

- sourceごとに直前の確定発言を短いcontextとして保持する。
- failure loopや反復が発生した場合はcontextをresetする。
- 自分と相手のcontextを混ぜない。
- 会議topicと用語集はstatic context、発言履歴はdynamic contextとして分離する。

### 6.4 音響改善

- sourceごとの音量、clipping、無音率を診断する。
- micへ相手音声が回り込んだ場合、時間近接・text類似度・波形相関で重複候補を検出する。
- Bluetooth HFP/A2DP切替を検知し、device変更を警告する。
- 全system audioをloopback取得することを画面へ明示する。

## 7. 要約精度の改善

### 7.1 現行方式を変更する理由

現在の `llm.py` は、40発言以下なら直接4観点を自由文生成し、40発言を超える場合は各chunkを3〜6項目へ圧縮してから再要約する。この方式では、最初の圧縮で消えた担当者、期限、否定、訂正をreduce段階で復元できない。また、LLMがもっともらしい補足をしても検出できない。

改善後は「文章をうまく要約する」前に、「会議で明示された事実を漏らさず抽出する」ことを優先する。

### 7.2 入力の作り方

- original transcriptを一次情報とする。
- 翻訳文は理解補助としてoriginalと併記し、originalを置換しない。
- 翻訳失敗、`no_speech_prob`、`avg_logprob`、`compression_ratio`、confidence status、音声drop、ASR modelをevent metadataとして渡す。
- `discard_candidate`は要約本文から機械的に除外するが、件数と時刻を「低信頼・要確認」として出力する。`low`は抽出modelへ伝搬し、単独の低信頼eventだけを根拠とする決定事項・ToDoを確定扱いしない。
- 発言ごとにevent ID、時刻、source、speaker、languageを必ず付ける。
- 参加者名と役割が分かる場合はsession contextとして渡す。
- 「自分」が誰かをsession設定で明示する。
- 会議の目的、既知の議題、用語集はtranscriptと別のtrusted contextとして渡す。

### 7.3 固定40発言分割を廃止する

chunkは次を使って作る。

1. modelの実context上限に対するtoken budget
2. 長い無音または時間間隔
3. 議題変更の明示語
4. 決定・訂正・取消が連続する会話単位
5. 離席開始・復帰等のsession marker

発言数は補助上限としてのみ使用する。1発言が長い場合と40発言が短い場合を同じ量として扱わない。

### 7.4 根拠付き構造化抽出

OllamaのJSON Schema structured outputを使用し、chunkごとに次を抽出する。

```json
{
  "decisions": [
    {
      "statement": "採用すると明示された内容",
      "status": "decided",
      "evidence_event_ids": ["event-001", "event-004"],
      "confidence": 0.9
    }
  ],
  "action_items": [
    {
      "task": "実施する作業",
      "owner": null,
      "due": null,
      "status": "open",
      "evidence_event_ids": ["event-010"]
    }
  ],
  "questions": [
    {
      "from": "相手",
      "to": "自分",
      "question": "質問内容",
      "answered": false,
      "evidence_event_ids": ["event-020"]
    }
  ],
  "open_issues": [],
  "corrections": [],
  "uncertain_items": []
}
```

抽出規則:

- 発言に明示されていないowner、期限、数値は `null` にする。
- 提案、検討、決定、却下、取消を別statusとして扱う。
- 「しない」「不要」「延期」等の否定を落とさない。
- 各項目へ最低1つの `evidence_event_ids` を必須にする。
- 根拠がない項目を生成しない。
- 会議発話内の命令文をsystem instructionとして扱わない。

OllamaはJSON Schemaによるstructured outputを公式にサポートしている。

参考: [Ollama Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)

### 7.5 機械検証

LLM出力後にコードで次を検証する。

- JSON Schemaに適合する。
- 全event IDが実在する。
- evidenceの時刻が対象要約区間内にある。
- ownerとdueが根拠発言内に明示されている。確認できなければ `null` に戻す。
- 同じtaskやdecisionを正規化して重複候補にする。
- 後の発言による訂正、取消、期限変更を履歴として保持する。
- 矛盾を一方へ勝手に統合せず「要確認」として残す。
- translationだけに存在しoriginalで確認できない固有名詞や数値を警告する。

### 7.6 最終要約生成

最終Markdownは検証済みJSONだけを入力にする。raw transcriptから新しい事実を追加させない。

```markdown
## 決定事項
- 翻訳優先モードを追加する。[20:14:02 相手]

## ToDo
- [ ] 非同期翻訳workerを実装する
  - 担当: 未定
  - 期限: 未定
  - 根拠: 20:15:10 相手、20:15:24 自分

## 自分への質問・依頼
- ASR model比較結果を次回共有する。[20:18:03 相手]

## 未解決・要確認
- 低遅延と精度のどちらを既定にするか未決定。
```

画面またはMarkdownから根拠発言へ移動できるよう、event IDとtimestampを残す。

### 7.7 要約種別

要約promptを1種類で使い回さず、抽出schemaを共有して表示templateだけを変える。

| 種別 | 主な内容 |
|---|---|
| 離席要約 | 離席中に新しく決まったこと、自分への質問、変更点 |
| 直近要約 | 時系列の要点、現在話している論点 |
| 全体要約 | 決定、ToDo、質問、未解決、訂正履歴 |
| 技術会議 | 選択案、採否、理由、制約、検証結果 |
| 勉強会 | 主題、重要概念、参考資料、後で調べること |

### 7.8 要約model

現行 `qwen2.5:14b` は中国系model禁止方針に抵触するため、継続利用しない。置換の第一候補は、現行運用環境のOllamaとllama-swapに登録済みのGemma 3 12B QAT（Q4_0、約6.6GB）を流用する。新しい推論基盤は不要だが、実際に使用するmodel tag、digest、量子化方式、配布元は起動前診断とmanifestで再確認する。Gemma 3は140以上の言語と128K contextを公式に案内しているが、model変更だけで要約精度が保証されるわけではない。

Gemma model weightはApache 2.0ではなく、商用利用を一律禁止していない一方で利用制限を含むGemma Terms of Useに従う。商用利用を含む用途ごとにtermsとProhibited Use Policyを審査し、再配布時はnotice等の条件を満たす。純Apache 2.0が必須となる配布形態では、Ministral 3等のMistral系modelを比較候補にする。

比較候補:

- Gemma 3 12B（第一候補）
- Gemma 3 4B（低遅延比較）
- Mistral系の同規模instruct model（licenseと日本語性能を確認して比較）
- cloud利用が許可される場合だけ、OpenAI等のAPI modelを明示的opt-inで比較

要約では自由な推論より再現性を優先し、temperatureは0〜0.1、JSON Schemaを使用する。thinking modelはlatencyと出力の安定性を評価してから採用する。ASRとLLMを同じGPUで同時に保持できない場合、resource managerでmodelを切り替えるか、要約を会議後へ遅延させる。

参考: [Gemma 3 model card](https://ai.google.dev/gemma/docs/core/model_card_3)、[Gemma Terms of Use](https://ai.google.dev/gemma/terms)

### 7.9 要約評価データ

10〜20会議分のgold summaryを人手で作成する。内部情報をGitHubへ登録せず、評価結果だけを匿名化して保存する。

各会議について次を正解データにする。

- 決定事項
- 却下・延期・取消
- ToDo
- 担当者
- 期限
- 自分への質問・依頼
- 未解決論点
- 各項目の根拠event ID

gold作成者とmodel評価者を分離し、最低20%の会議は2名で独立annotationする。不一致は第三者または合意手順で確定し、元の不一致率もreportへ残す。prompt injection発話、訂正の連鎖、担当未定、期限変更、低confidenceの重要発言をadversarial fixtureへ含める。

### 7.10 要約評価指標

| 指標 | 目標 |
|---|---:|
| 決定事項precision | 95%以上 |
| 決定事項recall | 90%以上 |
| ToDo precision | 95%以上 |
| ToDo recall | 90%以上 |
| owner正解率 | 95%以上 |
| 期限正解率 | 95%以上 |
| 根拠event ID有効率 | 100% |
| 根拠のない記述率 | 0% |
| 取消・否定の見落とし | 0件 |
| 人手評価「そのまま使える」 | 5段階で平均4以上 |

ASR誤りと要約誤りを分けて測るため、同じgold transcriptを全modelへ入力する評価と、実ASR出力からのend-to-end評価を両方行う。

採点単位はdecision、ToDo、question、unresolved itemとする。完全一致、意味一致、部分一致、誤りを事前定義し、複数根拠eventは集合として評価する。micro平均、会議ごとのmacro平均、重大誤り件数を併記する。「0件」は評価sample内の結果であり、一般的な無誤り保証として表示しない。

### 7.11 要約改善の完了条件

- fixed 40-entry chunkingを使用していない。
- 全要約項目に根拠event IDがある。
- JSON Schema validation失敗時に再試行または明示的失敗となる。
- original transcriptとtranslationを区別している。
- 訂正、取消、否定、担当未定、期限未定を保持できる。
- 離席・直近・全体で同じ事実抽出結果を再利用する。
- gold summary評価reportを生成できる。

## 8. モデル評価計画

### 8.1 評価データ

公開可能または評価利用の承認を得た音声だけを使用する。

最初に30〜60分のdev/smoke setを人手で作り、pipeline、閾値、promptの調整に使用する。最終採用には、model結果を見ずに作成・凍結した90分以上のheld-out test setを別に使用する。会議・話者単位で分割し、同じ話者・同じ会議の音声をdevとtestへ跨がせない。

- 日本語のみ
- 英語のみ
- 中国語のみ
- 日英中code-switch
- 技術用語・製品名・人名
- 静かな環境
- background noiseあり
- 自分／相手の重なり
- Bluetooth HFP音質

内部会議音声をGitHubへ登録しない。fixture公開時は合成音声または明示的に再配布可能な音声だけを使う。

reference setはPhase 3の直前に一括作成しない。Phase 0で同意、匿名化、文字起こしannotation、正規化規則、採点scriptの仕様を確定する。Phase 1のcapture安定化後からPhase 2完了までに承認済み音声を収集し、model比較結果を見る前にheld-out testの正解transcriptを凍結する。日本語・英語・中国語・code-switchの最低時間、noise、重なり発話、固有名詞の件数をmanifestへ記録する。Phase 3は凍結済みtest setで開始し、閾値変更はdev setだけで行う。test setの評価回数を記録し、繰り返し調整後は新しいholdoutを追加する。

翻訳評価用には、英語・中国語・code-switch発話から日本語へのreference translationを別に作る。固有名詞、数値、単位、否定、依頼、決定、敬語を含む発話を必須とする。評価者はmodel名を見ないblind reviewとし、意味保持、欠落、事実追加、否定反転、数値・単位、固有名詞、訳文切断を採点する。

### 8.2 比較対象

- Whisper large-v3
- Whisper large-v3-turbo
- Voxtral Mini 4B Realtime（下記のVoxtral実験条件をすべて満たす場合）
- Meta Omnilingual ASR（accuracy modeの会議後再処理だけで、license・Windows動作・日英中精度を確認できた場合）
- Kotoba-Whisper v2.x（日本語区間のみ）

Parakeet TDT 0.6B v3とKotoba Whisper bilingual v1.0は対象言語要件を満たさないため、この比較対象には含めない。

#### Voxtral実験条件

- 公式のproduction-grade推奨経路はvLLMである。一方、現在の公式model cardでは`Transformers >= 5.2`にも対応しているため、「vLLMのみ」とは扱わない。
- vLLMをWindowsで使う場合はWSL2またはDocker側に推論serverを置き、WASAPI loopback captureはWindows側へ残す。localhost WebSocket経由の音声転送、時刻・sequence保持、切断復帰が成立するかをモデル精度比較より先に確認する。
- native WindowsのTransformers経路も起動性、streaming latency、VRAMで比較し、framework、version、commitまたはcontainer digestを実験reportへ記録する。
- encoder/KV cache関連の停止・劣化リスクを検出するため、2時間連続sessionで無応答、切断、音声drop、出力停止がないことを合格条件にする。
- 短いaudio chunkと日英中code-switchで、発話全体が別言語として出力されるlanguage flip率を測る。language lockあり/なし、chunk長、transcription delayをreportへ記録する。
- 公式推奨に従い、1時間sessionでは`--max-model-len >= 45000`を設定する。2時間試験では必要長とVRAMの両方を満たす設定を使用し、実際の値をreportへ残す。
- RTX 5070 Ti 16GBでは余裕が小さいため、Voxtral実行中の翻訳LLMはRAM/CPU側へ置く。ASRと翻訳を含むend-to-end p50/p95が目標を満たさなければ採用しない。

### 8.3 評価指標

| 指標 | 対象 | 目的 |
|---|---|---|
| CER | 日本語・中国語 | 文字単位の誤り率 |
| WER | 英語 | 単語単位の誤り率 |
| 固有名詞正解率 | 全言語 | 実務上重要な語の精度 |
| 言語判定正解率 | 混在音声 | 翻訳要否の正確性 |
| 翻訳意味保持率 | en/zh/code-switchからja | 原発言の意味を保持できるか |
| 翻訳欠落・追加率 | translate mode | 情報欠落とhallucinationの検出 |
| 否定・数値・固有名詞正解率 | translate mode | 実務上重大な翻訳誤りの検出 |
| 訳文切断率 | translate mode | output上限の妥当性 |
| 発話冒頭欠落率 | 全音声 | VAD品質 |
| RTF | 各model | 実時間内に処理可能か |
| 原文表示latency | streaming | 会話追従性 |
| 翻訳表示latency | translate mode | 会議理解の速度 |
| VRAM/RAM peak | 各model | 対応hardware判断 |
| 音声drop時間 | 長時間試験 | 信頼性 |
| DER/JER | remote diarization | 話者割当の誤り率 |
| speaker count誤差 | remote diarization | 話者数推定の安定性 |

`benchmark_asr.py`ではraw transcriptとnormalized transcriptを両方保存し、CER/WER計算用の正規化を次の順序へ固定する。

1. UnicodeをNFKCへ正規化する。
2. 改行、tab、連続空白を単一spaceへ統一する。
3. 中国語区間だけ、versionと設定を固定したOpenCC `t2s`で繁体字を簡体字へ統一する。日本語漢字へ適用しない。
4. 独立した数値表現だけを固定parserでASCII算用数字へ統一する。漢数字の位取りを解釈するが、製品名、型番、固有名詞、慣用句内は変換しない。
5. CERではUnicode category `P*`の句読点と全spaceを除去する。WERでは英字をcasefoldし、句読点をspaceへ置換して連続spaceを1つにする。
6. code-switchはreference annotationの言語spanごとに上記規則を適用してから結合する。

正規化関数のversion、OpenCC設定、数字parser version、適用順序をreportへ記録する。変換対象・除外対象のgolden testを用意し、規則変更時は旧結果と混在させない。

CER/WERと翻訳品質は平均値だけでなく、会議別分布とbootstrap confidence intervalを出す。diarizationはmic sourceの`self`を確定labelとしてremote diarizationと分離し、speaker不明時は推測せず`unknown`を保持する。owner正解率はgold speaker入力と実diarization入力の両方で測る。

### 8.4 採用判断

平均値だけでなく、用途ごとにmodelを採用する。

- 翻訳モード: 翻訳意味保持、欠落・追加、否定・数値・固有名詞の最低基準を満たしたpipelineの中でp50/p95が最良
- 通常モード: capture frameとtranscript eventの欠落がない動作を満たした中で総合精度が最良
- accuracy mode: latencyを問わず固有名詞を含む最終精度が最良

翻訳modeはASR単体でなく、`ASR + language policy + translation model + prompt + context上限`を1つのpipelineとして採用する。

翻訳pipelineの暫定合格基準は次とする。基準値はheld-out testを開く前に凍結し、test結果を見て緩和しない。

| 指標 | 暫定合格基準 |
|---|---:|
| blind human reviewの意味保持 | 5段階平均4.0以上 |
| 意味保持3未満の発話率 | 2%以下 |
| 重大な事実追加・欠落 | 1%以下 |
| 否定反転 | 0件 |
| 数値・単位正解率 | 98%以上 |
| 登録済み固有名詞正解率 | 95%以上 |
| 訳文切断率 | 1%以下 |

remote diarizationはaccuracy modeの任意機能とし、DER 20%以下、speaker count誤差が会議あたり1人以下を採用基準とする。満たさない場合はremote speakerを推測せず従来どおり`相手`または`unknown`と表示する。担当者の確定には、明示的なspeaker mappingがある場合だけremote diarization labelを使用する。

## 9. 性能目標

reference hardwareを明記したうえで、暫定目標を次とする。

### 信頼性

- 2時間連続試験の音声drop: 0秒
- 正常終了時の未処理queue: 0件
- 異常終了後の正常JSONL救済率: 100%
- timestamp累積誤差: 1時間あたり100ms以内
- queueは有界であり、上限超過を必ず記録する

### 通常モード

- 発話終了からoriginal表示までのp95: 5秒以内
- 会議終了時に全original transcriptを保存
- 翻訳障害がASRと保存へ影響しない

### 翻訳優先モード

- provisional original表示のp95: 2秒以内
- 日本語訳表示のp50: 5秒以内
- 日本語訳表示のp95: 10秒以内
- summary処理が翻訳latencyへ影響しない

訳表示latencyは発話終了から最終訳表示までとし、VAD確定、ASR、translation queue待機、LLM生成をすべて含む。上記は未実測の暫定目標であり、turboと翻訳LLMのGPU競合を含めてRTX 5070 Ti 16GB上で測る。

live翻訳の既定候補はGemma 3 4Bとする。運用中のGemma 3 12B QATも `large-v3-turbo` と同居させて比較するが、VRAM watermarkまたはp95を満たさない場合はRAM/CPU offload、model切替、または会議後処理へ下げる。初期値はoutput hard cap `num_predict=384`、live translation queue 8 final events、15秒timeoutとし、訳文切断率、offline移送率、RAM/VRAM peakとともにreportへ残す。

数値は実機計測後に調整する。達成していない状態で「リアルタイム」を無条件に表記しない。

## 10. 実装段階

### Phase -1: 禁止model停止と環境凍結

対象:

- Qwen translation/summary routeを無効化
- 運用中Gemma routeへの設定切替、または翻訳・要約を一時停止
- 禁止model IDの起動前検査
- Python、dependency、CUDA、driver、model digest、GPU設定の現況manifest

完了条件:

- Qwen processとrouteが起動していない
- ASRはWhisper large-v3のまま起動できる
- 現行環境manifestとhashを保存できる
- 翻訳LLM停止時も原文記録が動作する

### Phase 0: 信頼性修正

対象:

- VAD model分離
- lossless shutdown
- PyAudio start順序
- streaming resampler
- capture timestamp
- bounded queueと計測
- JSONL破損救済
- reference setの同意・匿名化・annotation・正規化仕様
- hallucination metadataと低信頼eventのquarantine表示

完了条件:

- hardware非依存unit testが成功
- 2時間synthetic testでdropなし
- 現行large-v3を使った回帰試験が成功
- reference set作成手順と`benchmark_asr.py`の正規化golden testがreview済み

### Phase 1: 同時並行化

対象:

- capture/VAD/ASR/translation/storage worker分離
- event IDと状態管理
- 2音源の公平なscheduler
- backlog表示
- 原文先行表示・翻訳後追記
- reference set用の承認済み音声収集開始
- live/offline translation queueとdeadline制御

完了条件:

- Ollamaを30秒sleepさせても音声取得とASRが継続
- 翻訳timeout後も他発話を処理
- 終了時に全queueを処理
- deadline超過翻訳が暗号化offline queueへ移り、live latencyを塞がない

### Phase 2: モード追加

対象:

- `--mode transcript`
- `--mode translate`
- `--target-language`
- model、device、compute type設定
- mode別VAD・ASR・queue policy
- accuracy mode向け暗号化一時音声保存とopt-in UI
- session artifact全体の暗号化・retention・公開export
- resource managerのload/unload、memory reservation、失敗event

完了条件:

- 同一音声からmode別のlatency/精度reportを生成
- mode切替でcapture invariantを壊さない
- 音声保存が既定OFFで、暗号化・DPAPI鍵保護・retention cleanupのtestが成功
- transcript、summary、offline spoolが平文でdiskへ残らない
- model unload後のVRAM減少とswap失敗時のASR継続を確認

### Phase 3: ASR backend・要約pipeline比較

対象:

- ASR interface
- Meta Omnilingual ASR adapter（accuracy mode限定、実験・採用審査後）
- large-v3 fallback
- glossary/hotwords
- benchmark command
- Phase 2までに凍結したreference set
- benchmark用dependency lockfileとenvironment manifest
- 根拠付き要約JSON Schema
- summary validation・deduplication・correction merge
- gold summary benchmark

完了条件:

- reference setのCER/WER/固有名詞/latency/VRAMを一覧化
- 翻訳意味保持、欠落・追加、否定・数値・固有名詞、訳文切断をpipeline別に一覧化
- DER/JERとowner正解率を一覧化
- 採用modelを数値で決定
- 要約precision/recallと根拠なし記述率をmodel別に一覧化

### Phase 4: 外部利用対応

対象:

- 公開可能な `start.bat` またはinstaller
- version lock
- 起動前診断
- 録音通知・保存期間・削除
- Windows CI
- GitHub Release

完了条件:

- clean Windows環境でREADMEだけを見て起動可能
- 未追跡の内部資料を含めずrelease作成可能
- 会議データを誤commitしない自動検査が成功

## 11. 変更ファイル案

```text
meeting/
  audio.py                 # callback、streaming resampler、capture queue
  vad.py                   # source別VAD stateとutterance生成
  events.py                # event dataclass/schema
  asr/
    base.py                # ASR interface
    faster_whisper.py      # large-v3 backend
    meta_omnilingual.py    # 非中国系の実験ASR backend
  translation.py           # 非同期translation worker
  resource_manager.py      # process/model load、unload、memory reservation
  summary.py               # 根拠付き構造化抽出と最終要約
  summary_schema.py        # decision/ToDo/question等のschema
  summary_validation.py    # event根拠・重複・訂正検証
  storage.py               # JSONL writer/recovery
  encrypted_audio.py       # AES-GCM chunk保存、DPAPI鍵保護、retention cleanup
  secure_session.py        # transcript、summary、spoolの暗号化と公開export
  pipeline.py              # worker lifecycleとshutdown
  modes.py                 # mode別設定
  run.py                   # CLI/UIだけを担当
  summarize_file.py        # 破損行救済と再要約
tests/
  test_audio_clock.py
  test_streaming_resampler.py
  test_vad_isolation.py
  test_pipeline_shutdown.py
  test_translation_backpressure.py
  test_translation_deadline.py
  test_resource_manager.py
  test_model_unload.py
  test_summary_extraction.py
  test_summary_evidence.py
  test_summary_corrections.py
  test_event_ordering.py
  test_jsonl_recovery.py
  test_encrypted_audio.py
  test_audio_retention.py
  test_secure_session_artifacts.py
  test_public_export_redaction.py
  test_diarization_metrics.py
  fixtures/
scripts/
  benchmark_asr.py
  benchmark_translation.py
  benchmark_diarization.py
  benchmark_summary.py
  doctor.py
```

初期段階で過剰に分割せず、責務が確定した時点でmoduleを分けること。

## 12. リスクと判断事項

### 非中国系ASR候補の導入

- Meta Omnilingual ASR等は現行faster-whisperとは別の依存とGPU memory特性を持つ。
- 公式benchmarkが日英中の実会議で再現するとは限らない。
- Windowsでの導入容易性、license、配布物のhash、保守性を確認する必要がある。

対策:

- backend interfaceで切替可能にする。
- original model IDをeventへ保存する。
- reference setで採用を決める。

### 音声一時保存

- accuracy modeには有効だが、privacyと保存容量のリスクが増える。
- 音声だけでなく、transcript、translation、summary、offline spoolも4.6のsession artifact方針で保護する。

対策:

- 既定は保存しない。
- 明示的opt-in、録音中の常時表示、保存期間、即時削除、保存先表示を必須にする。
- UIでは次の確認を表示する。

> 高精度な会議後処理のため、会議音声をこのPCへ一時保存します。参加者全員の同意を確認してください。音声は暗号化して保存し、再処理の成功後または24時間後の早い方で自動削除します。

- 操作は「暗号化して保存し開始」と「保存せず開始」を明示し、前者を既定選択にしない。
- 保存先は `%LOCALAPPDATA%\RealtimeMeetingTranscriber\sessions\<session_id>\audio` とし、利用者本人だけにNTFS ACLを限定する。
- 音声はchunk単位のAES-256-GCMで暗号化し、sessionごとの鍵をWindows DPAPI CurrentUserで保護する。永続的な平文音声をdiskへ書かない。
- 暗号化初期化または鍵保護に失敗した場合はfail closedとし、accuracy用音声保存を開始しない。原文文字起こしだけの通常モードは継続可能にする。
- 再処理時は必要chunkだけをmemory上で復号する。正常完了時に暗号化音声と鍵を削除し、異常終了時も次回起動時のretention cleanupで24時間超過分を削除する。
- session画面に保存容量、削除予定時刻、「今すぐ音声を削除」を表示し、削除後もtranscriptを残すか同時削除するか選択できるようにする。

### 低遅延と精度

- 発話を短く切るほど翻訳は速くなるが、ASRと翻訳の文脈が減る。

対策:

- provisional/finalの2段階表示を採用する。
- UI上で速報と確定を区別する。
- mode別に評価する。

## 13. 推奨着手順

1. Phase -1でQwen routeを無効化し、禁止model検査と現行environment manifestを作る。ASRはlarge-v3のまま維持する。
2. Phase 0開始時にreference setの同意、匿名化、annotation、CER/WER・翻訳評価仕様を確定する。
3. ASR modelを変更せず、VAD state共有、発話冒頭欠落、callback内resample、時刻基準、queue drain、shutdown欠落を修正する。
4. 音声取得、ASR、翻訳を分離し、翻訳停止時も原文記録が継続する状態を作る。live/offline translation queueも分離する。
5. `transcript`と`translate`の2モード、resource manager、session artifact暗号化、accuracy用opt-in音声保存を追加する。capture安定化と保存test完了後から承認済みreference音声を収集する。
6. Phase 2完了までにheld-out testの正解transcriptとreference translationをmodel結果を見ずに凍結し、benchmark scriptと正規化golden testを完成させる。
7. benchmark環境をlockし、Whisper large-v3-turboと審査済み非中国系ASR候補をlarge-v3と数値比較する。Meta Omnilingual ASRはaccuracy modeだけで比較する。
8. 根拠付き要約pipeline、gold summary、diarization評価を追加する。
9. ASR、翻訳pipeline、要約で合格したmodelをmodeごとに採用する。
10. 録音通知・削除、公開export、release用依存固定、起動診断を外部利用水準へ仕上げてから案内する。

## 14. 最終提案

本ツールの改善方針は、単に「large-v3をより大きなmodelへ交換する」ことではない。

- 通常モードでは、取りこぼしのない確実な記録を優先する。
- 翻訳モードでは、原文と日本語訳の表示latencyを優先する。
- 精度モードでは、会議後に高精度modelと用語集で確定版を作る。
- 要約では、根拠付き事実抽出と機械検証を通した内容だけを提示する。

この3段階を分離することで、「正確な議事録」と「その場で会話を理解する」という異なる利用目的を同じ基盤で扱える。ASRは当面Whisper large-v3を精度基準とし、非中国系候補だけを実会議に近いreference setで比較する。翻訳・要約は現行Qwen2.5を廃止し、Gemma 3等の審査済みmodelへ置換する。
