# 修正指示書：公開前チェックと2点修正（コミット済みの状態から）

`realtime-meeting-transcriber` は既にコミット済み。公開（または公開済みの是正）の前に、
**①ログ混入の確認 → ②.gitignore名の是正 → ③requirements修正 → ④再コミット** を行う。

作業ディレクトリ:
```powershell
cd F:\git\realtime-meeting-transcriber
```

---

## ステップ1：ログ・不要物が追跡されていないか確認（最重要）

```powershell
git ls-files | findstr /I "jsonl summary .mp4 .wav data/"
```

- **何も表示されない** → ログ混入なし。ステップ3へ進んでよい。
- **何か表示された** → 実データがコミットに含まれている。ステップ2で除去する。

あわせて .gitignore の状態も確認:
```powershell
git ls-files | findstr /I "gitignore"
```
- `.gitignore` と出る → 正常
- `_gitignore` と出る → 名前が誤り（ステップ2で是正）
- 何も出ない → .gitignore が未追跡（ステップ2で追加）

---

## ステップ2：是正（必要な場合のみ）

### 2-A. `.gitignore` の名前を直す
`_gitignore` が追跡されている場合:
```powershell
git mv _gitignore .gitignore
```
ファイルは存在するが未追跡の場合:
```powershell
ren _gitignore .gitignore
git add .gitignore
```

### 2-B. 追跡されてしまったログを除去
ステップ1でjsonl/summary/data等が出た場合のみ:
```powershell
git rm -r --cached data
git rm --cached *.jsonl 2>$null
git rm --cached *_summary.md 2>$null
```
> `--cached` は**ローカルのファイルは消さず、Gitの追跡からのみ外す**。実ログ自体は手元に残る。

### 2-C. 無視設定が効いているか検証
```powershell
git check-ignore data/meetings/dummy.jsonl
```
→ `data/meetings/dummy.jsonl` とエコーされれば正常。

---

## ステップ3：requirements.txt に numpy / torch を追加

`transcriber.py` が `import torch`、`audio.py`/`transcriber.py` が `import numpy` を直接使うため明記する。

**requirements.txt を以下に置き換え:**
```
faster-whisper
silero-vad
pyaudiowpatch
scipy
numpy
torch
requests
```

---

## ステップ4：再コミットと最終確認

```powershell
git add .gitignore requirements.txt
git status
```
`git status` で **jsonl / summary / data/ が含まれていないこと**を目視確認。

問題なければコミット:
```powershell
git commit -m "Fix: rename .gitignore, exclude logs, add numpy/torch to requirements"
```

最終確認（追跡ファイルにログが無いこと）:
```powershell
git ls-files | findstr /I "jsonl summary .mp4 data/"
```
→ 何も出なければ完了。

---

## ステップ5：プッシュ

未プッシュなら:
```powershell
git push
```

---

## 付録：すでに GitHub へログを push してしまっていた場合

ステップ1でログが見つかり、**かつ既にpush済み**だった場合、`git rm --cached` だけでは
**過去の履歴に残り、GitHub上からも参照可能**。この場合は履歴の書き換えが必要。

1. まずGitHub上のリポジトリを一旦 private に変更（流出範囲を止める）
2. 履歴からログを完全削除（要 `git-filter-repo`）:
   ```powershell
   pip install git-filter-repo
   git filter-repo --path data --invert-paths --force
   git filter-repo --path-glob "*.jsonl" --invert-paths --force
   git filter-repo --path-glob "*_summary.md" --invert-paths --force
   ```
3. リモートを再設定して強制プッシュ:
   ```powershell
   git remote add origin https://github.com/yubota-dev/realtime-meeting-transcriber.git
   git push --force origin main
   ```
4. 問題ないことを確認してから public に戻す

> ログ混入が無ければ（ステップ1で何も出なければ）この付録は不要。

---

## チェックリスト
- [ ] `git ls-files` にログ（jsonl/summary/data）が無い
- [ ] `.gitignore`（先頭ドット）として追跡されている
- [ ] `git check-ignore` が data 配下を無視している
- [ ] requirements.txt に numpy / torch がある
- [ ] 再コミット・プッシュ後も `git ls-files` にログが無い
