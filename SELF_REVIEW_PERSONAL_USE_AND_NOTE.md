# 個人利用・note記事化 自己レビュー

- 対象: `realtime-meeting-transcriber`、`IMPROVEMENT_PROPOSAL.md`
- 日付: 2026-07-10
- 判定: **個人利用は条件付き可。note記事化は開発記録として可、完成品紹介は現時点では不可**
- 注意: 本文は法的助言ではない。勤務先規程、会議サービス規約、参加者との契約・秘密保持条件は利用者が個別に確認する。

## 1. 指摘事項

### P-01 High: GitHub公開版は中国系model禁止方針を満たしていない

対象:

- `README.md:10,24,31,40`
- `meeting/llm.py:1,10`
- `meeting/transcriber.py:2`

GitHub追跡済みの実装とREADMEは現在も`qwen2.5:14b`を使用している。Qwen禁止は法律上の制限ではなく本プロジェクトの調達方針だが、この状態で「非中国系構成へ移行済み」と公開するのは事実と異なる。

修正案:

- 追跡済み実装、README、model設定をGemma等の審査済みmodelへ変更してから移行完了と表記する。
- 起動時にmodel ID、配布元、license、digestを検証する。
- 移行完了まではnoteで「現在は置換設計・検証中」と明記する。

### P-02 High: 現行ログは平文であり、個人利用でも会議情報の保護が不足する

対象:

- `meeting/run.py:23,33-46,90-93`
- `meeting/summarize_file.py:14-49`
- `README.md:84-86`

現行版は発言と要約を`data/meetings/`へ平文保存する。ローカル処理でも、PCの共有、backup、malware、誤添付、画面共有により漏えいし得る。識別可能な通話内容は個人情報に該当し得る。個人利用であることは、他人の発言、会社秘密、NDA対象情報を自由に保存・公開できる根拠にはならない。

修正案:

- 会議参加者へ録音・文字起こし・利用目的・保存期間を事前表示し、同意を確認する。
- accuracy用音声保存は既定OFF、AES-256-GCM暗号化、DPAPI鍵保護、再処理後または24時間後の自動削除とする。
- transcriptにも保存期間、即時削除、NTFS ACL、backup除外を設定可能にする。
- 医療、人事、顧客秘密、未公開製品等は、勤務先の許可がない限り利用・記事化しない。

### P-03 High: projectのMIT licenseだけではmodelと依存物の利用条件を包括できない

対象:

- `LICENSE`
- `requirements.txt`
- `IMPROVEMENT_PROPOSAL.md`のmodel調達policy

本project codeはMITだが、model weight、runtime、diarization model、同梱binaryには別licenseが適用される。個人のローカル利用と、GitHub配布・installer同梱・有料note添付は別の行為である。

確認結果:

| 対象 | 個人ローカル利用 | 公開・再配布時の注意 |
|---|---|---|
| project code | MITの範囲で可 | copyrightとMIT licenseを維持 |
| Whisper code/weights | MITの範囲で可 | license noticeを維持 |
| Gemma 3 | Gemma Termsの範囲で可 | Apache 2.0ではない。再配布時のnotice、利用制限、Prohibited Use Policyを確認 |
| Voxtral Realtime | Apache 2.0の範囲で可 | license・noticeを維持。実務上はhardware/runtime制約あり |
| SeamlessM4T/Streaming | 非商用研究用途に限定 | CC-BY-NC 4.0のため、有料記事付属物や商用製品へ組み込まない |
| WhisperX/diarization | codeと各modelの条件内で可 | pyannote等のmodel規約、利用同意、token条件を別途確認 |
| Ollama上のmodel | modelごとの条件による | Ollama本体のlicenseだけでweight利用権を判断しない |

修正案:

- versionを固定したSBOM/model manifestを作り、license URL、digest、配布有無を記録する。
- noteにはmodel weight、他者code、license対象fileを直接添付せず、公式配布元とGitHubへのlinkを示す。

### N-01 High: 現時点では「完成した非中国系・高精度tool」というnote記事にできない

GitHub追跡済み版はQwenを使用し、非同期翻訳、暗号化音声保存、WhisperX再処理、根拠付き要約は未実装である。`IMPROVEMENT_PROPOSAL.md`も未追跡の内部文書であり、承認済み実装ではない。

修正案:

- 記事の位置付けを「完成報告」ではなく「モデル選びより先に音声pipelineを直すと判断した開発記録」にする。
- 未実装内容は「提案」「次に検証すること」と表記する。
- 公式model cardの数値と自分の実測値を明確に分離する。実測していない値を「検証結果」と書かない。

### N-02 Medium: READMEの公開表現に未達・誤解の余地がある

対象:

- `README.md:3,14,43-46`

`ローカル完結（ゼロ円）`は、hardware、電力、download、保守costまでゼロに読める。`start.bat`はREADMEで推奨されるがGitHub未追跡である。

修正案:

- 「外部API料金なし。既存の対応GPUと電力・storageは必要」へ変更する。
- `start.bat`を安全性review後に追跡するか、READMEから削除する。
- noteでも「無料」「リアルタイム」「高精度」を無条件に使わず、hardwareと実測条件を併記する。

### N-03 High: 実会議の音声・transcriptをnoteへ掲載してはならない

note規約は、他者の著作権、肖像権、名誉、privacy等を侵害する内容を禁止している。会議参加者の発言を本人の許可なく記事へ転載すると、勤務先規程、NDA、privacy、著作権等の問題が生じ得る。

修正案:

- note用の例は自作の合成音声、公開license音声、全員から記事掲載許可を得た再現会話だけにする。
- screen shotから氏名、会社名、会議URL、device名、local path、時刻、通知、背景を除去する。
- benchmark reference setとnote掲載素材を分離する。評価利用の同意だけで記事掲載まで許可されたと解釈しない。
- AI生成画像や引用文にも出典・利用条件を確認する。出所不明の未追跡画像は使用しない。

## 2. 個人使用で可能な範囲

次をすべて満たす場合、個人PCでの試用は可能と判断する。

- 自分だけの音声メモ、または参加者へ目的と保存条件を示して了承を得た会議で使う。
- 外部送信なしを確認し、Ollama等の待受portをLANやInternetへ公開しない。
- 平文logの保存先を保護し、不要になった音声・transcript・要約を削除する。
- 勤務先の録音、生成AI、OSS、機密情報持出し規程を満たす。
- modelごとのlicense・use restrictionを守る。
- ASRと要約結果を正しい記録とみなさず、人が確認する。

個人使用でも避けるもの:

- 同意や社内許可のない機密会議の録音
- 人事評価、採用、医療、法務等でAI要約だけを根拠に判断すること
- 実会議logをそのまま外部AI、GitHub、noteへ渡すこと
- 他人の声を話者認証datasetやmodel学習へ転用すること
- Seamless系modelを収益化記事の付属toolへ組み込むこと

## 3. note記事化の判定

noteアカウント`bota5241`は外部から閲覧でき、既存のAI coding関連記事も検索可能である。本件は既存記事と同じく、完成品宣伝よりも、失敗・判断変更・検証方法を示す開発記録と相性がよい。

推奨する無料記事:

> ローカル会議文字起こしを作って分かった。モデル選びより先に直すべき5つのこと

記事で扱ってよい内容:

- GitHub追跡済みREADMEとcodeから確認できる現在の構成
- Qwen禁止方針へ変えた理由は、性能断定ではなく自分の調達方針として説明
- VAD state共有、resample、queue、shutdown、hallucination metadata等の一般化した学び
- 公式model cardに基づく候補の制約。出典linkを付ける
- synthetic audioを使った将来の評価計画
- まだ解決していないことと次の実験

現時点で記事へ出さない内容:

- 未追跡の`IMPROVEMENT_PROPOSAL.md`、review文書、note下書き、内部patch指示書の全文
- 実会議の音声、transcript、要約、参加者情報
- 未公開code、local path、token、model server設定、社内構成
- 未実測benchmarkを自分の測定結果として見せる表現
- 未実装機能を利用可能と見せる表現

有料記事に回せるのは、実装・試験完了後の再現可能な内容に限る。候補はbenchmark template、annotation規則、hallucination検出test、暗号化保存設計、実測reportである。現段階では無料の開発記録で信頼を作り、完成後の記事へつなぐ方がよい。

## 4. 公開前チェック

- [ ] 記事の各機能がGitHub追跡済み版に存在する
- [ ] Qwenが追跡済みcodeとREADMEから除去されている、または未移行と明記した
- [ ] `start.bat`等の導線が実際に公開されている
- [ ] benchmarkはhardware、音声条件、model digest、正規化規則付きの実測である
- [ ] 実会議情報、個人名、会社名、local path、tokenがない
- [ ] 画像と引用の権利・出典を確認した
- [ ] model licenseと配布条件を確認した
- [ ] 「ゼロ円」「高精度」「リアルタイム」を条件なしで使っていない
- [ ] 読者が現在利用可能な機能と今後の計画を区別できる

## 5. 参照先

- [GitHub公開版README](README.md)
- [project MIT license](LICENSE)
- [OpenAI Whisper license](https://github.com/openai/whisper/blob/main/LICENSE)
- [Gemma Terms of Use](https://ai.google.dev/gemma/terms)
- [Voxtral Mini 4B Realtime model card](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602)
- [Meta Seamless Communication license説明](https://github.com/facebookresearch/seamless_communication#license)
- [個人情報保護委員会: 通話内容と録音](https://www.ppc.go.jp/all_faq_index/faq1-q1-10/)
- [noteご利用規約](https://note.com/terms)
- [bota noteアカウント](https://note.com/bota5241)
