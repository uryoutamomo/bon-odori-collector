# Review inbox B4: 曲・用語と低緊急度backlog

## 対象

- `weekly_song_candidates_review.json`
- `weekly_harvest_review_candidates.json`
- `accepted_venue_song_missing_venue_review.json`
- `historical_reference_quality_review.json`
- `publication_gap_review.json`

adapterは既存JSONを読む純粋変換とし、この段階ではdomain DB、公開JSON、既存applyを変更しない。全itemは `time_scope=reference` または `historical`、`priority_label=P3` として未来系より後に表示する。

## identityと重複

- 曲候補: 正規化したcanonical song name
- 用語: category・type・正規化term
- 曲×会場共起: 正規化song・venue
- 会場候補: 正規化suggested venue
- historical quality / publication gap: builderが付ける不変ID

evidence URL、件数、説明、抽出日時はidentityに含めない。同じ会場の複数行は一つの判断対象へまとめ、元行・曲・URLをpayloadに残す。2026-07-20時点のaccepted venue-song 14行は、日枝神社2行を統合して13itemになる。

## 有限route

採用は `stage_song_candidate`、`stage_term_candidate`、`stage_song_venue_evidence`、`stage_venue_candidate` のdomain stagingだけへ送り、直接applyしない。historical qualityは日付または曲のresearch follow-up、publication gapはneeds_research/hold/rejectだけに制限する。未知action、部分決定、identity欠落はfail closedする。

adapter合格後にconsoleのkind別選択肢とstaging packetを別PRで追加し、その後default-off CAS dual-writeを配線する。legacy writer/readerは連続2回の実スケジュールparityまで維持する。

scheduled dual-writeではsong/termを日次収集のfresh commitから読み、venueとhistorical qualityを同runで再生成してcommitする。publication gapはprivateなsite repositoryとの比較が必要でcollect Actionsから正しく再生成できないため、2026-07-20の確認済み159件snapshotを固定入力として移す。site入力が無い状態でbuilderを動かして偽陽性を増やさない。publication gapの再生成入口は既存ローカルbuilderのまま保持し、site比較を安全に自動化するまでは固定snapshotのparityを監視する。

おと（Codex）
