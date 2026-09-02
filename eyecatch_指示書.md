# 見出し画像 作成指示書 — 「離席要約ツールの続き（音声デバイスの沼）」

## 1. 目的・用途
- note 記事のアイキャッチ（見出し画像）。シリーズ第2回。
- ひと目で伝えたいこと：**ローカルAI × 音声まわり × ハマり（沼）**。
- 前回（第1回）と並べたとき、同じシリーズだと分かるトーンの連続性を持たせる。

## 2. 仕様
- サイズ：**1280 × 670 px**（note 推奨、比率 約1.91:1）。
- 生成解像度：SDXL 系なら **1216 × 640** で生成 →1280×670 に拡大/微トリミング。
- 形式：PNG（テキストを後載せするなら背景は潰れない構図に）。
- セーフエリア：**左下〜下1/3 を空け気味**にしておく（タイトル後載せ用の余白）。

## 3. コンセプト（2案）

### A案（推奨・メタファー寄り／キャラなし）
中央にワイヤレスイヤホン。そこから **2本の音の波形**が伸びる。片方が「自分」、
片方が「相手」のニュアンス。波形は画面（ログ/字幕）へ流れ込むが、足元は
**ケーブルとデバイスが絡まった"沼"**になっていて、そこに一部が沈んでいく。
技術記事らしいクリーンなフラット/アイソメ調。タイトル後載せに強い。

### B案（IllustriousXL 向け／キャラあり）
夜のデスクで、Bluetooth イヤホンを着けたエンジニアが、宙に浮く波形パネルと
「自分／相手」の吹き出し、絡まった音声ケーブルに囲まれて、少し呆れ顔。
モニタの光が顔に当たるアニメ調。シリーズに"顔"を作りたいならこちら。

## 4. 構図
- 主役（イヤホン or キャラ）は中央〜やや上。視線誘導は「音源 → 波形 → 画面」。
- 下1/3は"沼"（絡まったケーブル・デバイス）で重心を作る＝記事の「沼に落ちた」を可視化。
- 余白：左下 or 下帯にタイトルを置ける平坦域を確保。

## 5. スタイル / 配色
- スタイル：モダンなフラット〜セミアイソメ（A）／クリーンなアニメイラスト（B）。
- 配色（ダークテック）：
  - 背景：ディープネイビー〜チャコール `#0E1B2A`
  - メイン：テックシアン `#22D3EE` / ティール `#2DD4BF`（音・データ）
  - アクセント：アンバー `#F59E0B`（"沼"・トラブルの暖色1点）
  - 文字/ハイライト：オフホワイト `#E5E7EB`
- 質感：ほのかなグロー（発光する線）、強すぎないグラデ。にじみ系は避ける。

## 6. 文字入れの方針
- 画像生成では**文字を描かせない**（生成文字は崩れる）。タイトルは Canva 等で後載せ推奨。
- 後載せ文言の候補：
  - 「自分の声が録れない」
  - 「音声デバイスの沼」
  - 「離席要約ツール #2」
- どうしても画中にラベルを入れたいなら「自分／相手」程度の短語に留める。

## 7. 生成プロンプト

### A案：自然文プロンプト（DALL·E / Imagen / Midjourney 等）
```
A clean modern flat isometric tech illustration for a blog header.
Center: a pair of wireless earbuds emitting two distinct glowing sound
waveforms (cyan and teal) that flow toward a floating screen showing a
chat/transcript log. Below them, a tangled "swamp" of audio cables and
small device icons, with one earbud half-sinking into it. Dark navy
background, cyan and teal glow, a single warm amber accent in the swamp.
Minimal, high contrast, empty space in the lower-left for title text.
No text, no logos, no brand names. 1.91:1 aspect ratio.
```

### B案：タグ式プロンプト（IllustriousXL / SDXL）
Positive:
```
masterpiece, best quality, very aesthetic, 1person, engineer at desk at night,
wearing wireless earbuds, slightly exasperated expression, surrounded by
floating holographic audio waveforms, two glowing sound streams, tangled
audio cables, computer monitors, dark room, cyan and teal rim light,
monitor glow on face, cinematic lighting, cyberpunk-lite, clean vector-ish
shading, depth of field, copyspace on lower left
```
Negative:
```
lowres, worst quality, bad anatomy, bad hands, extra fingers, extra limbs,
text, watermark, signature, logo, brand name, jpeg artifacts, blurry,
distorted, oversaturated, busy background, cluttered, nsfw
```
推奨パラメータ目安：Steps 28–32 / CFG 4.5–6 / Sampler DPM++ 2M Karras /
解像度 1216×640 →Hires.fix 1.5x → 1280×670 にリサイズ。

## 8. 避けること / 注意
- **実在ブランドのロゴ・製品名・型番を描かない**（Technics 等の文字や形状の特定再現は避ける）。
- 文字の描き込みに頼らない（崩れる）。意味は構図と色で伝える。
- ごちゃつかせない。"沼"はあくまで下1/3のアクセントで、主役を埋めない。
- 前回画像と色温度・明度を合わせ、サムネ一覧で並んだとき同シリーズに見えるようにする。

## 9. 仕上げチェック
- [ ] サムネ縮小（横300px相当）でも主役と"沼"が判別できるか
- [ ] タイトル後載せの余白が確保されているか
- [ ] 暖色アクセントが1箇所に効いて視線が定まるか
- [ ] 文字・ロゴの崩れ/混入がないか
