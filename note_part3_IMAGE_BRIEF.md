# 第3回 記事画像 依頼文

対象記事: `note_part3_PUBLISH_REVISED.md`

## 現状

画像は4枚とも作成済みで、そのまま公開できる品質。

| ファイル | 用途 | 状態 |
|---|---|---|
| `note_part3_header_1280x670.png` | 見出し画像 | 作り直し不要 |
| `fig1_flow_2.png` | 処理の流れ | 作り直し不要 |
| `fig3_latency_2.png` | 翻訳時間 | 番号のみ要変更 |
| `fig2_causes_2.png` | 症状から原因を切り分ける | 番号のみ要変更 |

**実際に必要な作業は「図2と図3の番号入れ替え」だけ。** 本文の登場順が
処理の流れ → 翻訳時間 → 原因切り分け なのに対し、画像に焼き込まれた番号が
図1 → 図3 → 図2 になっているため。番号を気にしないならこのまま公開できる。

---

## 依頼A（推奨・最小）: 図の番号入れ替え

**依頼先: Claude（私）。ChatGPT の画像生成には出さないこと。**
文字が主役の図を画像生成AIに描かせると、必ず崩れた文字が入る。
HTML/SVG で正確なテキストとして描き出す。

以下をそのまま渡す。

```
fig3_latency_2.png と fig2_causes_2.png を、既存のデザインを保ったまま
番号だけ入れ替えて再出力してください。

- 現「図3：同じ英→日の1文にかかった翻訳時間」→ 「図2：同じ英→日の1文にかかった翻訳時間」
- 現「図2：症状から原因を切り分ける」→ 「図3：症状から原因を切り分ける」

タイトル以外の要素（配色、レイアウト、文言、数値、キャプション）は
一切変更しないでください。幅1280px、背景は既存と同じオフホワイト。
出力形式はPNG。
```

入れ替え後は、記事の貼り付け手順6を次のように読み替える。

- 1番目の★ → `fig1_flow_2.png`
- 2番目の★ → 新・図2（翻訳時間）
- 3番目の★ → 新・図3（原因切り分け）

---

## 依頼B（任意）: 原因切り分け図に1行追加

ChatGPT のレビューで指摘された追加。
文字コードの章が図に反映されていないため、記事全体の対応が取れる。

依頼Aと同時に出す場合、上の依頼文へ次を追記する。

```
あわせて、原因切り分けの図に次の1行を最下段へ追加してください。

  症状「日本語入力だけ異常」→ 原因「文字コードと入力データ」

既存4行と同じ書式・同じ配色にしてください。
```

---

## 依頼C（任意）: 図を一から作り直す場合の仕様

既存画像を紛失した、またはデザインを変える場合のみ使う。
**画像生成AIではなく、HTML/SVG または draw.io / Excalidraw で作る。**

共通仕様: 幅1280px、背景オフホワイト、日本語ゴシック、
タイトルは左上に太字、キャプションは最下部にグレーの1行。

### 図1：処理の流れ（現在の形）

2段のフロー。上段は青、下段はオレンジ。

- 上段ラベル「即時：原文」（青）
  - 音声入力 loopback + mic
  - Silero VAD 発話の区切り
  - faster-whisper 音声認識（ASR）
  - 原文を即時表示 JSONLへ保存 ← 左端に青の縦バー
- faster-whisper から下段の先頭へ、オレンジの矢印を分岐させる
- 下段ラベル「非同期：訳文」（オレンジ）
  - 翻訳キュー（別スレッド）
  - 文を確定 文末記号／無音 文字数／断片数
  - TranslateGemma 翻訳
  - 同じevent IDに訳文を追記 ← 左端にオレンジの縦バー
- キャプション: 原文は訳文で置き換えない。先に原文を表示し、あとから同じevent IDに訳文を追加する。

### 図2：同じ英→日の1文にかかった翻訳時間

横棒グラフ2本。青。

- サブタイトル（タイトル直下・グレー）: 手元PCでの限定的な実測。一般的な性能値ではない。
- 棒1「要約・翻訳モデルをGPUに同時常駐」= 18.39秒（棒の中に白抜きで数値）
- 棒2「翻訳モデルだけを常駐（同じ例）」= 0.86秒（棒の外に黒で数値）
- X軸 0秒〜20秒、5秒刻み
- キャプション: ウォーム状態で複数文を測ると 0.72〜0.89秒／文。ただし音声を8秒ためれば、生成が1秒未満でも利用者には遅く見える。

数値は改変しないこと。18.39 と 0.86 の比が視覚的に効く図なので、
軸を対数にしたり途中で省略したりしない。

### 図3：症状から原因を切り分ける

左に起点、中央に症状、右に原因の3列。右列の左端に青の縦バー。

起点: 訳がおかしい／表示が遅い

| 症状 | 原因 |
|---|---|
| 英語の原文も変 | ASRの誤認識 |
| 文が途中で切れている | 文の分割の問題 |
| 前の文が繰り返される | コンテキストの混入 |
| 表示が遅い | バッファ／キュー／モデル常駐 |
| （依頼B適用時）日本語入力だけ異常 | 文字コードと入力データ |

キャプション: 原文と訳文を両方表示したことで、この切り分けができるようになった。

---

## 依頼D: 見出し画像から「AI臭」を消す

図1〜3にAI臭はない。フラットな作図で、人が Figma や HTML で描いたものに見える。
**問題は見出し画像だけ。**

### 現行画像がAI生成に見える理由

`note_part3_header_1280x670.png` は品質は高いが、AI画像の定番構図をほぼ全部踏んでいる。

1. **左右対称の「混沌→秩序」構図** — 左が赤（壊れている）、右が青緑（直った）。
   同じ大きさのノートPCが左右対称に置かれ、カップが正確に中央。
   これがAI生成イラストで最も見慣れた型。
2. **ダークネイビー＋ティールの発光配色** — 「AI・テック」を表す既定パレット。
3. **文字の代わりに光る短冊が並んだ偽の画面** — 実在するUIに見えない。
4. **環境がない** — 机の面、部屋、散らかり、光源がない。物が暗闇に浮いている。
5. **波形が画面外から画面外へ一直線に流れ、中央の四角い箱を通る** — 写実的な絵の中に
   図解の記号が混ざっている。
6. カップの湯気が装飾的な曲線。

「もっと良いAI画像を作る」のでは消えない。**ジャンルを変えるのが確実。**

### 案1（最も推奨）: 実際の画面を見出しにする

誤訳が出ているターミナルの実物をスクリーンショットし、該当部分を切り出す。

```
[en] I'll have a tall latte, please.
[ja] 高くカットしたラテを一杯お願いします。
```

- この記事の主題そのものなので、説明が要らない
- AI臭はゼロ。撮影物なので構図の型に当たらない
- 図1〜3のオフホワイト背景に載せれば、記事全体でデザインが揃う
- 1280×670に収まるよう余白を作り、タイトルは Canva で後乗せ

**注意**: ユーザー名、ローカルパス、会議内容、個人名が写り込んでいないか確認する。
写っていれば該当部分を切り落とすか、塗りつぶす。

### 案2: タイポグラフィだけの見出し

イラストを使わず、文字と余白だけで作る。AI臭は構造上ゼロ。

- 背景: 図1〜3と同じオフホワイト
- 大きく「高くカットしたラテ」、小さく「ローカル翻訳の失敗記録（第3回）」
- 誤訳の一文を等幅フォントで小さく添える
- 装飾は罫線1本程度

Canva か HTML/SVG で作る。画像生成AIは使わない。

### 案3: 写真を撮る

実際の机、実際のPC、実際のコーヒーを撮る。ピントが甘くても、
散らかっていても、そのほうが開発記録に見える。整えすぎないこと。

### 案4: それでも画像生成AIを使う場合

定番構図を明示的に禁止する。下のブロックだけを渡す。

```
A single photograph-like editorial image, 1280x670 landscape.
One laptop on a real wooden desk at night, seen from a low three-quarter
angle, positioned off-center to the right. A paper takeaway coffee cup sits
near the front-left edge, slightly out of focus. The only light source is one
warm desk lamp outside the frame on the left, plus the pale glow of the screen.
Real room behind it, softly out of focus: a wall, a cable, ordinary clutter.
Muted natural colors, warm neutrals and desaturated blue-grey. Film-like grain,
shallow depth of field, slight lens imperfection.

Avoid: symmetry, split left-right composition, red-versus-teal contrast,
neon or glowing edges, dark navy tech gradients, floating objects, vignette
glow, audio waveforms, circuit patterns, holograms, abstract data shapes,
infographic elements, decorative steam swirls.
Strictly no text, no letters, no numbers, no UI, no charts, no logos.
Leave calm empty space in the upper left for a title added later by a human.
```

生成後の確認:

- 左右対称になっていないか
- 赤と青緑の対比になっていないか
- 光っている線・発光する縁がないか
- 判読できる文字・数字・UI・表が1つでも入っていないか

1つでも当てはまれば作り直す。

### 運用ルール（過去に失敗済み・厳守）

- 画像生成AIへ渡してよいのは下のプロンプトブロック**だけ**。
  この文書の他の部分を渡すと、タイトル・表・ターミナル文字まで
  画像内へ描き込み、崩れた文字入りのインフォグラフィックになる。
- 生成段階では**文字ゼロ**の1枚絵のみを作る。
- 文字は生成後に Canva 等で後乗せする。
- 生成後、判読できる文字・数字・UI・表・グラフが1つでも描かれていたら作り直す。

### 画像生成プロンプト（このブロックだけを渡す）

```
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

### 後乗せする文字（画像生成AIへは渡さない）

現行画像に入れてある文言:

- 動いた。でも訳が変だ。
- ローカル翻訳の失敗記録（第3回）

差し替え候補:

- “tall latte”が訳せない
- 会議ツールが、翻訳ツールになった
- コンテキストを選ばせるな
