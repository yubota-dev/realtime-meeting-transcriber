# realtime-meeting-transcriber

日本語・英語・中国語（code-switchを含む）のWeb会議を、ローカルで
文字起こし、翻訳し、根拠event ID付きで要約するWindows向けツールです。

## 主な機能

- WASAPI loopbackとマイクを同時取得し、自分／相手のsource labelを保存
- faster-whisper `large-v3`による文字起こし
- sourceごとの言語lock、またはja/en/zh内での自動判定fallback
- ASRとOllama翻訳を別threadで実行
- `no_speech_prob`、`avg_logprob`、`compression_ratio`と低信頼flagを保存
- 音声欠落をgap eventとしてJSONLへ明示
- 要約を構造化抽出し、存在するevent IDだけを根拠として採用
- 任意のWAV保存と会議後の高精度再処理
- reference音声によるASR model比較benchmark

## 処理構成

```text
PortAudio callback
  -> bounded raw queue
  -> resample worker (16kHz mono / optional WAV)
  -> bounded ASR queue
  -> source別Silero VAD + faster-whisper
       -> transcript eventを即時保存・表示
       -> bounded translation queue -> Ollama -> translation update event
  -> JSON Schema要約抽出 -> evidence ID検証 -> Markdown生成
```

終了時は録音、resample、ASR、翻訳の順にqueueをdrainしてから要約します。

## 必要環境

- Windows 10 1903以降
- Python 3.11
- NVIDIA GPU + CUDA（`large-v3`はVRAM 12GB以上を目安）
- Ollama
- 既定要約LLM: `llama3-ja:latest`（Meta Llama 3系、Qwen不使用）
- 既定翻訳LLM: `translategemma:4b`（Googleの翻訳専用モデル）

LLMは環境変数またはCLIで変更できます。Gemma 3 12Bを利用する例:

```powershell
$env:OLLAMA_MODEL="gemma3:12b"
```

モデルは事前にOllamaへ導入してください。本リポジトリは自動downloadしません。

```powershell
ollama pull translategemma:4b
```

## セットアップ

```powershell
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
```

PowerShellでは上記の`activate`が内部的に`Activate.ps1`へ解決されます。
実行ポリシーで有効化できない場合は、仮想環境を
有効化せず、そのPythonを直接指定できます。

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m meeting.run --mode concurrent
```

コマンドプロンプトの場合:

```bat
venv\Scripts\activate.bat
python -m meeting.run --mode concurrent
```

## 実行モード

通常の並行処理:

```powershell
# venv\Scripts\activate を実行済みの場合
python -m meeting.run --mode concurrent
```

翻訳優先（発話を最大8秒で区切り、翻訳queueへ早く渡す）:

```powershell
python -m meeting.run --mode translate
```

会議後の高精度再処理:

```powershell
python -m meeting.run --mode accuracy
```

`accuracy`はWAV保存を自動的に有効化し、終了後に`large-v3`、`beam_size=10`で
再処理します。リアルタイムeventは保持し、最終要約にはaccuracy eventを優先します。

## 言語制御

自動判定はja/en/zhだけを候補にします。sourceの言語が既知ならlockできます。

```powershell
python -m meeting.run --mic-language ja --loopback-language en
```

指定値は`auto`、`ja`、`en`、`zh`です。

翻訳先は`--target-language`で`ja`、`en`、`zh`から選択できます。たとえば、
日本語入力を固定して日本語原文と英訳を同時に表示する場合:

```powershell
python -m meeting.run --mode translate `
  --mic-language ja --loopback-language ja --target-language en
```

表示は同じコンソールに2段で出ます。原文は翻訳待ちなしで先に表示され、
英訳は完了後に同じ発言の更新として表示・JSONL保存されます。
翻訳側は句点までの短い断片を結合します。翻訳専用モデルには過去文を渡さず、
現在のまとまりだけを翻訳するため、前の英訳が重複しません。
句点が来ない場合も、無音4秒、10秒分、240文字、8断片のいずれかで
強制的に翻訳を開始します。`[LOW]`を含むまとまりは英訳にも警告を表示します。
英語入力はニュース音声の短い間を考慮し、通常のピリオド、`...`、
または無音2秒でも確定します。
`translate`モードで入力言語を`en`へ固定した場合は、連続発話も最大4秒で
文字起こしへ渡し、従来の最大8秒より表示遅延を短縮します。

カフェ接客などの場面指定は利用者へ要求しません。発話内の`latte`、`espresso`、
`muffin`、`single/double shot`などから自動検出し、注文、店内・持ち帰り、金額、
受取場所などの定型句をWhisperの初期promptとhotwordsへ自動反映します。
`tall / grande / venti`は物理的な高さではなく、飲料サイズとして扱います。
起動時は要約モデルをGPUから解放して翻訳モデルを優先し、終了時は逆に
翻訳モデルを解放してから最終要約を生成します。

```text
[10:00:00.123][自分/ja] 本日の議題を確認します
        -> [en] Let's review today's agenda.
```

環境変数`TARGET_LANGUAGE=en`でも翻訳先を指定できます。既定値は`ja`なので、
既存の非日本語から日本語への翻訳動作は変わりません。
翻訳モデルは`--translation-model`または環境変数`TRANSLATION_MODEL`で変更できます。
要約用の`--llm-model`とは分離されているため、翻訳の遅延が要約モデルの選択に
影響しません。

## 音声保存とプライバシー

音声保存は既定OFFです。明示的に保存する場合:

```powershell
python -m meeting.run --save-audio
```

保存先は`data/audio/`です。WAVは暗号化されません。保存を有効にする場合は、
会議参加者の同意、組織の規則、保存先のアクセス権を確認してください。
`data/`と`*.wav`は`.gitignore`対象です。

## 会議中コマンド

| コマンド | 動作 |
|---|---|
| `a` | 離席を記録 |
| `b` | 離席中を要約 |
| `s` | 直近5分を要約 |
| `f` | 会議全体を要約して保存 |
| `q` | 終了、queue drain、最終要約 |

ログはappend-only JSONLです。原文eventは上書きせず、翻訳を同じevent IDへの
update recordとして追記します。

保存済みログから再要約:

```powershell
python -m meeting.summarize_file data/meetings/20260711_100000.jsonl
```

## 音声対話（ローカルLLM）

マイクに話しかけ、ローカルLLMの応答を読み上げで返します。文字起こしと同じ
取り込み・ASR部品を再利用しています。

```powershell
python -m meeting.voice_chat
python -m meeting.voice_chat --model llama3-ja:latest --tts sapi --language ja
```

| オプション | 既定 | 説明 |
| --- | --- | --- |
| `--model` | `OLLAMA_MODEL` | 対話に使う Ollama model |
| `--tts` | `sapi` | 読み上げ backend（`sapi` / `voicevox` / `none`） |
| `--language` | `ja` | ASR の言語固定。`auto` は短い発話で誤判定しやすい |
| `--history-turns` | `8` | LLM に渡す直近の往復数 |
| `--barge-in` | OFF | 読み上げ中の発話を割り込みとして扱う |
| `--think` | OFF | thinking model の推論出力を有効にする |

VRAM 16GB クラスでは `gemma4:12b`（7.6GB、256K context）を推奨します。Whisper
`large-v3` と同時に載せても GPU 100% 常駐で、約 74 tok/s、最初の1文が返るまで
0.4〜0.6 秒です。

```powershell
ollama pull gemma4:12b
python -m meeting.voice_chat --model gemma4:12b
```

thinking model は既定で推論出力を切ります（`--think` で有効化）。推論部分は
本文より先に数秒流れるため、その間は読み上げる文が1つも出ず、音声対話では
応答開始が 4〜8 秒遅れます。

応答は stream で受け取り、文が閉じた時点で読み上げに回すため、生成完了を
待たずに声が返ります。会話ログは `data/voice_chat/<session_id>.jsonl`。

読み上げ backend は既定が Windows 標準の SAPI（追加インストール不要）です。
VOICEVOX を使う場合は engine を起動し、`--tts voicevox`（話者は環境変数
`VOICEVOX_SPEAKER`）を指定してください。

**スピーカー再生時の注意**: 音響エコーキャンセルは実装していません。読み上げ
中と終了直後 0.6 秒の発話は自分の声の回り込みとみなして捨てます。割り込んで
話したい場合は**ヘッドホンを使い**、`--barge-in` を付けてください。

## ASR benchmark

reference manifestをJSONLで作成します。

```json
{"audio":"refs/ja.wav","reference":"本日の議題を確認します","language":"ja","condition":"clean"}
```

実行:

```powershell
python -m meeting.benchmark_asr refs/manifest.jsonl `
  --models large-v3,large-v3-turbo `
  --out benchmark_asr_report.json
```

正規化順序はNFKC、Latin小文字化、中国語の繁体字から簡体字、数字表記統一、
句読点・空白除去です。英語はWER、ja/zh/mixedはCERを計算します。
modelを変更する前に、同じmanifestと条件で比較してください。

## デバイス選択

```powershell
python -m meeting.audio
$env:LOOPBACK_HINT="ヘッドセット"
$env:MIC_HINT="ヘッドセット"
python -m meeting.run
```

## テスト

```powershell
python -m unittest discover -s tests -v
```

## 制約

- Bluetooth A2DPとHFPは同時利用に制約があり、loopback deviceが変わる場合があります。
- 相手側の複数話者diarizationには対応していません。
- `accuracy`の音声保存は暗号化されません。
- Voxtral、Omnilingual ASR等は標準runtimeへ組み込まず、benchmark候補として扱います。
- 自動要約は根拠IDを検証しますが、元のASR誤認識までは訂正できません。

## ライセンス

MIT
