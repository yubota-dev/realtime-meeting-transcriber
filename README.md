# realtime-meeting-transcriber

日本語・英語・中国語が混在するWeb会議を、**ローカル完結（ゼロ円）**で
リアルタイム文字起こし＆日本語訳し、離席中・会議後に要約するツール。

## 特徴
- スピーカー出力（会議相手の声）を WASAPI ループバックで取得
- faster-whisper (large-v3) で文字起こし、言語を自動判定
- 非日本語は qwen2.5:14b（Ollama）でローカル翻訳
- 「離席 → 復帰」で離席中だけを要約／会議後に全体要約
- 外部API不要・追加課金なし

## 構成
```
会議の音声（日・中・英）
  → audio.py        WASAPIループバックで取り込み・16kHz化
  → transcriber.py  silero-VADで発話を切り出し → faster-whisper
                    → 非日本語は qwen2.5:14b で日本語訳
  → run.py          タイムスタンプ付きログ／離席要約／会議後要約
```

## 必要環境
- Windows 10 (1903以降) … WASAPIループバック
- NVIDIA GPU + CUDA … faster-whisper large-v3（VRAM 12GB+目安）
- Ollama + `qwen2.5:14b`
- Python 3.11

## セットアップ
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
Ollama を起動し、`ollama pull qwen2.5:14b` 済みであること。

## 使い方
```powershell
python -m meeting.run
```
| コマンド | 動作 |
|---------|------|
| a | 離席を記録 |
| b | 復帰（離席中を要約） |
| s | 直近5分を要約 |
| f | 会議全体を要約して保存 |
| q | 終了（全体要約を保存） |

保存済みログから要約を作り直す:
```powershell
python -m meeting.summarize_file
```

## ログの保存先
`data/meetings/` に保存される（`.gitignore` 対象）。
実データを含むためコミットしないこと。

## 既知の制約 / まだ解決していないこと
- **言語混在の誤判定**：話者が外国語の専門用語を挟むと言語判定を誤ることがある
- **翻訳が同期実行**：翻訳が文字起こしを一時的に止めうる（非同期化は今後）
- **話者分離なし**：「誰が話したか」は未対応

## ライセンス
MIT
