# 追加パッチ：transcriber.py 誤検出をさらに削減（精度向上 v2）

統合パッチ適用済みの `meeting/transcriber.py` に対する**追加修正**。
異言語の幻聴・自信のない幻聴を破棄し、VADを少し厳しくする。

対象: `meeting/transcriber.py`

---

## 変更①：定数を追加

**現状:**
```python
MIN_TEXT_LEN = 3        # これ未満の文字数は幻聴とみなし破棄
MIN_TRANSLATE_LEN = 8   # これ未満の非日本語は翻訳しない（誤翻訳防止）
LANG_NAME = {"ja": "日本語", "en": "英語", "zh": "中国語"}
```

**変更後:**
```python
MIN_TEXT_LEN = 3        # これ未満の文字数は幻聴とみなし破棄
MIN_TRANSLATE_LEN = 8   # これ未満の非日本語は翻訳しない（誤翻訳防止）
ALLOWED_LANGS = {"ja", "en", "zh"}  # 想定言語。これ以外の判定は誤検出として破棄
AVG_LOGPROB_MIN = -0.8  # 平均logprobがこれ未満は自信なし＝幻聴とみなし破棄
LANG_NAME = {"ja": "日本語", "en": "英語", "zh": "中国語"}
```

---

## 変更②：VADしきい値を上げる

**現状:**
```python
        self.vad = VADIterator(self.vad_model, sampling_rate=SAMPLE_RATE)
```

**変更後:**
```python
        self.vad = VADIterator(self.vad_model, sampling_rate=SAMPLE_RATE, threshold=0.6)
```

---

## 変更③：_finalize() を置き換え（ホワイトリスト＋信頼度フィルタ）

**置き換え後の `_finalize()` 全体:**
```python
    def _finalize(self):
        if not self._utter:
            return
        audio = np.concatenate(self._utter)
        self._utter = []
        if len(audio) < SAMPLE_RATE * MIN_UTTER_SEC:
            return

        segments, info = self.model.transcribe(
            audio,
            language=None,
            beam_size=5,
            vad_filter=True,                  # 無音区間を除外し幻聴を抑制
            no_speech_threshold=0.6,          # 無音判定を強める
            condition_on_previous_text=False, # 直前テキストへの引きずられ防止
        )
        seg_list = list(segments)
        text = "".join(s.text for s in seg_list).strip()
        if len(text) < MIN_TEXT_LEN:          # 極短フラグメントは破棄
            return

        lang = info.language
        if lang not in ALLOWED_LANGS:         # 日中英以外は誤検出として破棄
            return

        if seg_list:                          # 信頼度フィルタ：自信のない出力を破棄
            avg_lp = sum(s.avg_logprob for s in seg_list) / len(seg_list)
            if avg_lp < AVG_LOGPROB_MIN:
                return

        ja = ""
        if lang != "ja" and len(text) >= MIN_TRANSLATE_LEN:
            try:
                ja = llm.translate_to_ja(text, LANG_NAME.get(lang, lang))
            except Exception as ex:
                ja = f"(翻訳失敗: {ex})"

        self.on_entry({
            "ts": dt.datetime.now().strftime("%H:%M:%S"),
            "lang": lang,
            "original": text,
            "ja": ja,
        })
```

---

## 検証

1. 構文チェック:
   ```powershell
   python -c "import ast; ast.parse(open('meeting/transcriber.py', encoding='utf-8').read()); print('OK')"
   ```
2. 起動して数分流し、`[tr]` `[es]` `[ko]` 等の異言語一行が**出なくなる**ことを確認。

## チューニングの目安（必要に応じて）
- **本物の発話まで落ちる**と感じたら `AVG_LOGPROB_MIN` を `-1.0` に緩める。
- **まだ雑音を拾う**なら VAD `threshold` を `0.7` に上げる。
- これらは「誤検出を減らす」フィルタであり、**完全な除去は不可能**（＝記事の「まだ解決していないこと」に該当）。
```
