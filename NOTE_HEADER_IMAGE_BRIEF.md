# 見出し画像 作成指示書（第3回記事用）

対象記事: 「会議ツールを翻訳ツールにしたら、『tall latte』が『高くカットしたラテ』になった」
完成サイズ: 1280×670 px（note推奨）
作成日: 2026-07-12

---

## 手順（この順番を守る）

1. ChatGPTの**新しい会話**を開く（記事やブリーフを渡した会話は使わない。
   文脈が残っていると画像へ文字や表を描き込んでしまう）
2. 下の「■ 画像生成プロンプト」のコードブロックの中身**だけ**を貼って生成する。
   前後に日本語の説明や記事タイトルを付けない。
3. 生成結果を検品する（下の「■ 検品基準」）。不合格なら再生成。
4. 合格した画像をCanva等で1280×670へトリミングし、日本語コピーを後乗せする。
5. 最終画像をもう一度検品基準で確認してから、noteへ設定する。

---

## ■ 画像生成プロンプト（このブロックの中身だけを渡す）

```text
Create a cinematic editorial illustration for a Japanese technology essay,
wide 1280x670 landscape composition, one single scene, not an infographic.
A developer's dark desk at night, two laptop/terminal screens side by side
showing only abstract glowing rectangles and blurred unreadable marks,
an audio waveform flowing from left to right through a small local AI box,
and a takeaway latte cup in the center. The left side feels confused with
subtle red error glow and a fragmented waveform; the right side feels calmer
with teal and blue light and a clean continuous waveform.
Realistic but slightly illustrated, thoughtful personal development-log mood,
not corporate advertising.
Strictly no text, no letters, no numbers, no words, no subtitles, no captions,
no tables, no charts, no diagrams, no UI elements, no logos, no watermark.
Large simple shapes, strong contrast, ample empty negative space in the upper
area reserved for a title that will be added later by a human.
```

---

## ■ 検品基準（1つでも該当したら再生成）

- 判読できる文字・数字・単語が描かれている（英語・日本語・崩れた文字を含む）
- 表・グラフ・フロー図・マークダウン風の画面が描かれている
- インフォグラフィック（複数パネルの要約図）になっている
- ロゴ・ウォーターマークがある
- 横長でない、またはタイトル用の余白（上部）がない

過去の失敗例: ブリーフ全体を渡したところ、`loopbad`等の崩れた文字入りの
要約インフォグラフィックが生成された（2026-07-12、不採用）。
原因は指示の渡しすぎ。プロンプトブロック単体なら再発しない。

---

## ■ Canvaで後乗せする文字（画像には生成させない）

メインコピー（どれか1つ。上部の余白へ大きく）:

- 会議ツールが、翻訳ツールになった
- “tall latte”が訳せない
- 動いた。でも訳が変だ。

サブコピー（任意。小さく）:

- ローカル翻訳の失敗記録（第3回）

文字入れの注意:

- 記事タイトル全文は載せない（noteでは画像の下にタイトルが表示されるため重複する）
- 文字色は背景の明暗に合わせ、縁取りか半透明の帯で可読性を確保
- スマートフォンでの縮小表示を想定し、メインコピーは画面幅の1/2以上の大きさ

---

## ■ 完成チェック

- [ ] 1280×670 pxで書き出した
- [ ] AI生成の文字・数字・表・UIが残っていない
- [ ] 後乗せ文字がスマートフォン縮小でも読める
- [ ] 完成品広告ではなく「試行錯誤の記録」の雰囲気になっている
