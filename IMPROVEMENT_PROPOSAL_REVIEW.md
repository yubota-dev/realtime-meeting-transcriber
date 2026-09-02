# IMPROVEMENT_PROPOSAL.md レビュー

- 対象: `IMPROVEMENT_PROPOSAL.md`
- 初回レビュー: 2026-07-10
- 再レビュー: 2026-07-11 01:53 JST
- 判定: **改善提案書は承認。Phase 0は開始不可で、Phase -1の実施と人間確認が先**
- レビュー方針: 実装可能性、評価の妥当性、privacy、性能目標、phase間の整合性を確認した。

## 再レビュー結果

再レビュー対象SHA-256:

`1BD772AABC382D65AA521D76A58D5898034CB1F5333A95E45BD4C5A934EA9255`

### 提案書の指摘対応

| ID | 状態 | 再確認した設計上の証拠 |
|---|---|---|
| R-01 | 解消 | reference translation、blind review、翻訳pipeline単位の数値gateを8章へ追加 |
| R-02 | 解消 | audio、transcript、translation、summary、spoolをsession keyで保護し、record単位の破損復旧を定義 |
| R-03 | 解消 | live queue 8件、絶対deadline、暗号化offline queueへの移送を定義 |
| R-04 | 解消 | runtime別load/unload、memory reservation、context上限、失敗eventを定義 |
| R-05 | 解消 | 30〜60分のdev setと90分以上のheld-out testを会議・話者単位で分離 |
| R-06 | 解消 | Qwen停止とenvironment manifestをPhase -1としてPhase 0の前へ追加 |
| R-07 | 解消 | 低confidence eventを削除せず「要確認」へ隔離し、重要表現はhuman reviewへ送る |
| R-08 | 解消 | DER/JER、speaker count、`unknown` fallback、owner評価の責任境界を定義 |
| R-09 | 解消 | Phase -1の環境manifestとPhase 3前のdependency lockを追加 |
| R-10 | 解消 | 要約matching規則、二重annotation、micro/macro評価、重大誤り件数を定義 |

再レビューで検出した残存事項も修正済みである。

- live翻訳の絶対deadlineを`capture_ended_at + 10秒`とし、生成時間予測で開始可否を決める。
- 翻訳の意味保持、重大欠落・追加、否定、数値、固有名詞、切断率に暫定合格値を設定する。
- remote diarizationはDER 20%以下をgateとし、不合格時は`相手`または`unknown`へ戻す。
- `lossless transcript`を「capture frameとtranscript eventの欠落なし」へ修正し、ASR正解保証と区別する。
- 暗号化のthreat modelを明記し、同一user malware、screen capture、process memoryは保護対象外とする。
- `git commit`、tag、pushは差分と検証結果を人間が確認し、明示承認した後だけ実行する。

### Phase 0着手判定

| Phase -1 gate | 現在 | 根拠 |
|---|---|---|
| Qwen modelがruntimeにloadされていない | 合格 | `ollama ps`にload中modelなし |
| Qwen routeを追跡済み設定・codeから無効化 | 不合格 | `README.md`、`meeting/llm.py`、`meeting/transcriber.py`が`qwen2.5:14b`を参照 |
| 禁止model起動前検査 | 不合格 | 追跡済みcodeに未実装 |
| environment manifestとhash | 不合格 | tracked fileはversion未固定`requirements.txt`だけで、manifest/lockなし |
| ASR large-v3回帰smoke test | 未確認 | 実行中processを変更しない条件のため未実施 |
| 人間による差分確認 | 未実施 | 本再レビュー後に確認が必要 |

したがって、**Phase 0はまだ開始しない**。人間確認後にPhase -1だけを実装し、全gateを再確認してからPhase 0へ進む。今回、GitHub追跡済みcode、実行中process、git commitには変更を加えていない。

## 反映状況

2026-07-10に次を`IMPROVEMENT_PROPOSAL.md`へ反映した。

- 翻訳品質のreference translation、blind human review、pipeline単位の採用判定
- session artifact全体の暗号化・retention・公開export
- deadline付きlive queueと暗号化offline queueの分離
- resource managerのprocess制御、memory reservation、context上限
- dev/smoke setとheld-out test setの分離
- Qwen停止とenvironment manifestを行うPhase -1
- 低confidence eventのquarantine表示
- DER/JER、speaker不明時`unknown`、owner評価の分離
- Phase 3前のdependency lock
- 要約matching規則、二重annotation、micro/macro評価

## 指摘事項

以下は反映前に検出した問題と、その修正方針である。現在の提案書には上記「反映状況」の改善を追加済みであり、実装時は各項目の完了条件として使用する。

### R-01 Critical: 翻訳modelを翻訳品質で評価していない

対象:

- `IMPROVEMENT_PROPOSAL.md` 8.1、8.3、8.4

8.3の指標はCER/WER、言語判定、latencyが中心で、8.4は翻訳modeを「latency制約内でCER/WERが最良」のmodelで選ぶとしている。これはASR原文が正確かを測るだけで、日本語訳の欠落、追加、否定反転、数値、固有名詞、敬語、code-switchの訳し分けを評価できない。ASRが最良でも翻訳LLMとの組合せが最良とは限らない。

修正案:

- 日英中から日本語へのreference translationを作成する。
- 発言単位で「意味保持」「欠落」「事実追加」「否定反転」「数値・単位」「固有名詞」「訳文切断」を採点する。
- 自動指標は補助とし、blind human reviewを主判定にする。少なくとも2名評価または不一致調停を定義する。
- 採用単位をASR単体ではなく、`ASR + language policy + translation model + prompt + context length`のpipelineとする。
- translate modeの採用条件を、翻訳品質の下限を満たしたpipelineの中でp50/p95が最良、へ変更する。

### R-02 High: 音声だけ暗号化され、より検索しやすいtranscript・要約・spoolが平文で残る

対象:

- `IMPROVEMENT_PROPOSAL.md` 4.5、4.6、5.2、12章「音声一時保存」

暗号化仕様はaccuracy用音声だけを対象としている。一方、JSONL、translationの`pending_overflow` disk spool、summary Markdown、benchmark出力には氏名、会社名、決定事項が平文で残る。音声を削除してもprivacy上の主要リスクが残る。

修正案:

- session artifactを`audio / transcript / translation / summary / spool / benchmark export`に分類し、各artifactの暗号化・retention・export方針を表にする。
- 既定ではsession artifact全体を同じsession keyで暗号化する。検索用indexを作る場合も暗号化または明示opt-inとする。
- note用exportは元sessionから直接公開せず、匿名化したcopyを別処理で生成する。
- backup、Windows Search index、crash dump、temporary fileをthreat modelへ含める。
- 「音声だけ削除」「transcriptも削除」をUIで明確に分ける。

### R-03 High: translation queueの初期値がlatency目標と矛盾する

対象:

- `IMPROVEMENT_PROPOSAL.md` 4.5、5.2、9章「翻訳優先モード」

queue上限32件、1件15秒timeout、単一workerなら、最悪時は後続発言が数分待つ。p95 10秒を目標にするlive queueとして深すぎる。原文を捨てないことと、古い翻訳をlive表示し続けることは別問題である。

修正案:

- `live translation queue`と`offline completion queue`を分離する。
- live queueはdeadline付き4〜8件を初期値とし、期限超過eventは`offline_pending`へ移す。原文とeventは失わない。
- source間の公平性を維持しつつ、final、現在議題、利用者が選択したeventを優先する。
- queue待機時間が残りdeadlineを超えた場合はLLMを呼ばず、即座にofflineへ送る。
- `num_predict=384`固定ではなく、入力長と対象言語から上限を決め、切断検出時だけ再処理する。
- 負荷試験では通常会話だけでなく、2音源同時発話とLLM timeout連続を含める。

### R-04 High: resource managerが別processのGPU占有を制御できる仕様になっていない

対象:

- `IMPROVEMENT_PROPOSAL.md` 2章「実機メモリの活用方針」、7.8、9章

faster-whisper/CTranslate2、Ollama/llama-swap、WhisperX/PyTorchは別runtime・別processになり得る。単に優先順位を決めても、OllamaのmodelがVRAMへ残ったままならASRを優先できない。また、Gemma 3 12B Q4_0の約6.6GBはweightだけの目安であり、KV cache、runtime buffer、長いcontextは別に必要である。128K contextをRTX 5070 Ti上で実用できるとは限らない。

修正案:

- resource managerが管理するprocess、API、load/unload command、timeout、失敗時動作を明記する。
- Ollamaの`keep_alive`、llama-swapのroute、CTranslate2/PyTorchのmodel解放を実際に確認し、解放後VRAMを計測する。
- mode別にASR、翻訳、要約の最大contextを設定し、128Kはmodel仕様であって運用値ではないと明記する。
- model swap時間、CPU offload時tokens/sec、page file増加、再load失敗を性能指標へ追加する。
- watermark超過後に切替えるだけでなく、load前のmemory reservationと拒否判定を定義する。

### R-05 High: 30〜60分のreference setを調整と最終採用の両方に使うと過学習する

対象:

- `IMPROVEMENT_PROPOSAL.md` 8.1、8.3

30〜60分を9条件・3言語へ分けると、各条件は数分になる。VAD閾値、hallucination閾値、prompt、modelを同じsetで調整し、同じsetで採用すると比較値が楽観的になる。話者や会議単位の偏りも大きい。

修正案:

- 30〜60分はpipelineのsmoke/dev setと位置付ける。
- model結果を見ないheld-out test setを別に作り、会議・話者単位でdev/testを分割する。
- 日本語、英語、中国語、code-switch、noise、重なり発話の最低時間を事前に決める。
- CER/WERだけでなくbootstrap confidence intervalまたは会議別分布を出す。
- annotationの二重確認、不一致修正、固有名詞正解表を記録する。
- test setの再利用回数を記録し、繰り返し調整後は新しいholdoutで確認する。

### R-06 High: Phase 0で「modelを変更しない」が中国系model禁止と衝突する

対象:

- `IMPROVEMENT_PROPOSAL.md` 10章「Phase -1」「Phase 0」、13章

Phase 0は現行large-v3で音声系を直す方針自体は正しい。しかし現行翻訳・要約はQwenであり、「modelを変更しない」を全modelへ適用すると禁止modelを継続利用することになる。

修正案:

- 「ASRはlarge-v3のまま変更しない」と限定する。
- Phase 0開始前のPhase -1として、Qwen translation/summaryを無効化するか、運用中のGemma routeへ設定だけ切替える。
- Phase 0の回帰試験はASR・capture中心とし、翻訳LLM性能比較は行わない。
- 禁止model検出を起動前診断へ先行実装する。

### R-07 Medium: 低confidence eventの自動非表示が記録優先方針と緊張する

対象:

- `IMPROVEMENT_PROPOSAL.md` 4.4、7.2

`discard_candidate`を監査eventへ残す点はよいが、通常表示と要約から完全除外すると、低音量で発言された重要な決定まで利用者から見えなくなる可能性がある。閾値はhallucinationと難聴取を完全には分離できない。

修正案:

- `discard_candidate`を削除ではなく「要確認」欄へ折りたたみ表示する。
- 要約本文から除外しても、末尾に低信頼event件数と時刻を提示する。
- 重要語、数値、否定、依頼表現を含む低信頼eventは自動除外せずhuman reviewへ送る。
- threshold変更履歴と、除外によるrecall低下を評価する。

### R-08 Medium: diarizationの評価条件と責任境界がない

対象:

- `IMPROVEMENT_PROPOSAL.md` 2章、5.3、8.3、8.4

WhisperXの限界は記載されているが、話者割当の合格基準がない。誤ったspeaker IDはToDoの担当者や「自分への質問」の誤判定へ直結する。micの「自分」とloopback側の複数話者を同じ信頼度で扱ってはならない。

修正案:

- mic sourceは`self`として確定し、remote diarizationとは別confidenceにする。
- remote側はDER/JER、speaker count誤差、overlap区間、speaker label安定性を評価する。
- speaker不明時は推測で担当者へ割り当てず`unknown`を保持する。
- 要約のowner正解率を、ASR/diarization込みとgold speaker入力の2通りで測る。

### R-09 Medium: benchmark前にdependencyを固定しないと再現性がない

対象:

- `IMPROVEMENT_PROPOSAL.md` 10章「Phase -1」「Phase 0」「Phase 3」「Phase 4」
- `requirements.txt`

version lockがPhase 4に置かれているが、model採用benchmarkはPhase 3で行う。現行`requirements.txt`はversion無指定であり、faster-whisper、CTranslate2、PyTorch、Transformers、VADの更新で精度・速度・metadata APIが変わり得る。

修正案:

- Phase 0で現行環境のfull version、CUDA、driver、model digestを採取する。
- Phase 3開始前にbenchmark用lockfile/container manifestを凍結する。
- dependency更新は同じreference setで回帰確認してから採用する。
- reportへgit commit、lock hash、model hash、runtime、driver、GPU設定を必須出力する。

### R-10 Medium: 要約目標値の採点方法が未定義

対象:

- `IMPROVEMENT_PROPOSAL.md` 7.9、7.10

precision/recall、owner正解率、取消見落とし0件という目標はあるが、言い換えを同一事項とみなす規則、複数根拠、部分一致、annotator不一致が定義されていない。10〜20会議では0件目標の統計的意味も弱い。

修正案:

- decision/ToDo単位のmatching規則と部分一致をschema化する。
- gold作成者と評価者を分離し、少なくとも一部を二重annotationする。
- micro/macro平均、会議別結果、重大誤り件数を併記する。
- 「0件」はsample内の結果として示し、一般的保証にしない。
- prompt injectionを含む発話、訂正連鎖、担当未定、期限変更をadversarial fixtureへ追加する。

## 承認できる点

- model交換より前にVAD、resample、timestamp、shutdownを直す順序
- 音声取得、ASR、翻訳、要約を分離し、原文eventを非破壊で保存する設計
- Qwen系を含む中国系modelを禁止し、model manifestで配布元とdigestを管理する方針
- large-v3を精度baseline、large-v3-turboをlatency候補とする役割分担
- WhisperXを文字訂正器ではなくalignment/diarizationとして扱う点
- 根拠event ID付き構造化抽出と、検証済みJSONだけから最終要約を作る設計
- 音声保存を既定OFF・明示opt-inとする方針
- CER/WER正規化順序を事前固定する方針

## 推奨反映順

1. R-01の翻訳品質評価を8章へ追加する。
2. R-02のsession artifact全体の暗号化・retention表を追加する。
3. R-03のlive/offline translation queue分離を4.5、5.2、9章へ反映する。
4. R-04のresource manager制御契約とcontext上限を4章へ追加する。
5. R-05のdev/test分離を8.1へ追加する。
6. R-06を反映し、Phase 0前にQwenを無効化する。
7. R-07〜R-10をPhase 0〜3の完了条件とtest一覧へ組み込む。
