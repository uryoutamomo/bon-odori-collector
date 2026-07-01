# Official venue source research 2026-06-30

- generated_by: おと（Codex）
- purpose: 公式URLで裏取りできる未登録会場を洗い出し、公開デプロイに混ぜてよいものと止めるものを分ける。
- safety_rule: 会場URLだけで確認できるものは会場マスタ登録まで。開催日・今年開催・公式/主催ソースが揃うまで公開JSONやサイト同期には入れない。

## Applied to master, not public

### 銀座一丁目東町会・新富町会 納涼盆踊り大会

- occurrence_id: `occ_225f239652267ed9`
- new venue: `京橋プラザ区民館`
- venue_id: `ven_3823a14944e4649f`
- official venue URL: https://www.city.chuo.lg.jp/a0013/kurashi/chiikicommunity/kuminkan/syukaisisetu02.html
- official venue evidence: 中央区の施設ページで会場名と住所 `東京都中央区銀座一丁目25番3号` を確認。
- current event source: https://www.chuo-kanko.or.jp/pages/other_details/115655
- applied action: 会場を新規作成し、発生候補に `venue_id` を付与。シリーズの通常会場も同じ会場に設定。
- public/deploy decision: まだ公開対象外。`date_status=unknown` かつ `lifecycle_status=未確認` のため、公開JSONへ追加しない。
- public guard: `data/public_event_overrides.json` に `skip` ルールを追加済み。会場登録だけで公開エクスポートへ混入しない。
- next step: 2026年の開催日と主催/公式告知が見つかった時点で、別途 `official_current_year` として昇格する。

### 月島第二児童公園 盆踊り

- occurrence_id: `occ_e5ea459ea88de16c`
- new venue: `月島第二児童公園`
- venue_id: `ven_456beaee9aa43b0e`
- official venue URL: https://www.city.chuo.lg.jp/a0037/machizukuri/kouenryokka/kouen/kouen_hiroba_ichiran.html
- official venue evidence: 中央区の公園・広場一覧で会場名と住所 `東京都中央区勝どき一丁目9番8号` を確認。
- current event source: https://x.com/harumichiku/status/1955267713292435643
- applied action: 会場を新規作成し、発生候補に `venue_id` を付与。シリーズの通常会場も同じ会場に設定。
- public/deploy decision: まだ公開対象外。`date_status=unknown` かつ `lifecycle_status=未確認` のため、公開JSONへ追加しない。
- public guard: `data/public_event_overrides.json` に `skip` ルールを追加済み。会場登録だけで公開エクスポートへ混入しない。
- next step: 2026年の開催日と主催/公式告知が見つかった時点で、別途 `official_current_year` として昇格する。

## Existing venue source enrichment candidates

### あかつき公園

- venue status: 既存会場行あり。イベント発生への紐付けはなし。
- official venue URL: https://www.city.chuo.lg.jp/a0037/machizukuri/kouenryokka/kouen/kouen_hiroba_ichiran.html
- official venue evidence: 中央区の公園・広場一覧で `あかつき公園` と住所 `東京都中央区築地七丁目19番1号` を確認。
- deploy decision: 公開追加なし。曲目/会場メモ由来の補完候補で、公開イベント候補ではない。

### 有馬小学校

- venue status: 既存会場行あり。イベント発生への紐付けはなし。
- official venue URL: https://ame.edu-chuo.tokyo/access
- official venue evidence: 中央区立有馬小学校の公式アクセスページで住所 `東京都中央区日本橋蛎殻町2-10-23` を確認。
- deploy decision: 公開追加なし。盆踊り練習会メモ由来で、公開イベント候補ではない。

### 羽根木公園

- venue status: 既存会場行あり。イベント発生への紐付けはなし。
- official venue URL: https://www.city.setagaya.lg.jp/02075/9123.html
- official venue evidence: 世田谷区公式ページで `羽根木公園` と所在地 `東京都世田谷区代田4-38-52` を確認。
- deploy decision: 公開追加なし。梅まつり出演/曲目メモ由来で、公開イベント候補ではない。

## Hold

### 佃島の盆踊り

- occurrence_id: `occ_b0ac40639f5d2d5c`
- current source: https://www.chuo-kanko.or.jp/pages/other_details/115655
- related local URL checked: https://www.tsukuda.chuo.tokyo.jp/
- hold reason: 中央区観光協会ページはイベント文脈として使えるが、会場マスタへ入れるべき正確な会場名・住所をまだ公式URL単体で固定できない。
- current internal hint: X由来メモには `佃一丁目中央通り`、別回として `佃島一丁目佃小橋横` が出ているため、混同リスクがある。
- deploy decision: 追加しない。会場が曖昧なまま公開すると、あとで候補へ戻る原因になる。

### 雷門盆踊り（浅草）

- occurrence_id: `occ_90f1aef84c0ad6f7`
- current source: https://x.com/STBA_Bonodori/status/2059220925862883623
- official spot URL checked: https://t-navi.city.taito.lg.jp/spot/1003
- candidate venue: `雷門付近`
- hold reason: 台東区の公式観光ページは雷門スポットの確認には使えるが、盆踊りの正確な開催会場・日付・主催告知ではない。
- deploy decision: 追加しない。`雷門付近` のまま会場登録すると粒度が粗すぎる。

### えどぐらん（江東区）

- occurrence_id: `occ_ef4845b7ed9ac900`
- current source: https://www.edogrand.tokyo/event/6924
- hold reason: 名称は京橋エドグランに見えるが、候補名が `江東区` になっており地域矛盾がある。京橋エドグランへ自動リンクしない。
- deploy decision: 追加しない。イベント名または地域の修正確認が先。

## Current safe deploy batch

- サイト公開データ側で安全に増やせるのは、すでに別手順で公開JSONに入っている `鉄砲洲納涼盆踊り` と `すみだ河内音頭 小盆踊り` の2件。
- この調査で新たに登録した `京橋プラザ区民館` と `月島第二児童公園` は、会場データの整備であり、今回の公開追加バッチには含めない。
