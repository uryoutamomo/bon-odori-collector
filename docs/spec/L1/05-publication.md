---
id: L1-publication
layer: L1
title: 公開サブシステム
owns:
  - export_public_events.py
  - public_json_postprocessors/**
  - public_export_support/**
  - guard_site_public_event_additions.py
  - venues/export_public_venues.py
  - scripts/export_detail_cleanup_projection.py
depends_on:
  - L1-master
invariants:
  - INV-PUB-001
  - INV-PUB-002
  - INV-PUB-003
  - INV-PUB-004
  - INV-PUB-005
  - INV-PUB-006
  - INV-PUB-007
  - INV-PUB-008
verified_by:
  - tests/test_export_public_events.py
  - tests/test_guard_public_events_sync.py
  - tests/test_public_event_site_addition_tools.py
  - tests/test_classify_public_events_diff.py
  - tests/test_e0b_bridge.py
  - tests/test_verify_detail_cleanup_repair.py
  - tests/test_x_song_materialization_lifecycle.py
updated_for: 64f2371
---

# 公開サブシステム

> 上位は [全体地図](../README.md)。上流は[マスタ](04-master.md)。書き方の決まりは [SPEC-GUIDE](../SPEC-GUIDE.md)。

## この工程は何のためにあるか

Master RDB に溜まった事実を、公開サイト bonsuke.jp が読む形（`events_public.json`）へ変換して届ける工程である。

一見ただの書き出しに見えるが、実際にはここが**いちばん事故が起きる場所**になっている。理由は2つある。

ひとつは、公開が「外に出てしまうと取り消せない」種類の操作だからだ。内部データがおかしくても直せばいいが、
終わった盆踊りを「開催予定」として出してしまえば、それを見た人が実際に会場へ足を運んでしまう。

もうひとつは、公開JSONが **RDBの素直な射影ではない**ことだ。RDBから出した生データに対して、
過去実績の付与・表示段の決定・季節ヒント・日付予測といった後処理が何段も重なる。
つまり「RDBを直したのに公開が変わらない」「RDBは正しいのに公開だけ壊れる」が普通に起きる構造になっている。
公開の不具合を調べるとき、RDBだけ見て納得してはいけないのはこのためである。

## 入力と出力

**入力**

| 何を | どこから |
|---|---|
| イベント・会場・曲目の確定情報 | Master RDB（`data/bon_odori_master.sqlite`） |
| 日付予測 | Master RDB の `predicted_occurrence_dates` |
| 固定日ルール | `data/public_fixed_date_rules.json` |
| 同期の個別承認台帳 | `data/public_sync_exact_approvals.json` |
| 「今日」 | 引数 `--today` または環境変数 `BON_ODORI_PUBLIC_TODAY`（**既定値は無い**） |

**出力**

| 何を | どこへ |
|---|---|
| 公開イベント本体 | `data/public/events_public.json`（`6537e7f` 時点で379件） |
| 同上のJS版 | `data/public/events_public.js` |
| 曲目の確認用 | `data/public/event_songs_public.json` |
| 同期ガードの判定 | `data/public_events_sync_guard.json` / `.md` |
| 追加ガードの判定 | `data/site_public_event_additions_guard.json` / `.md` |

公開サイトへの実際の反映は、このリポジトリではなく `bon-odori-site` 側の `Sync public data` workflow が行う。
**この工程の責任は「正しいJSONを作り、危ないときに止めること」までで、デプロイそのものは含まない。**

一回限りの14件detail修復では、`scripts/export_detail_cleanup_projection.py` が同じMaster RDB snapshotを
固定した `target-year` と `today` で公開射影し、イベントJSONと occurrence へのsource mapを出す。修復前後で
source mapが完全一致し、対象14件の `detail` だけが変わることを検証できない限り公開しない。

## 不変条件

### INV-PUB-001 公開イベントの同一性は「名前 + 会場」で決まる

- **内容**: 公開JSON上のイベントの同一性は `f"{name}||{venue}"` で判定される（`public_json_postprocessors/classify_public_events_diff.py` の `event_key()`）。
  したがって**イベント名か会場名を変えると、機械には「古いイベントが消えて、別の新しいイベントが増えた」と見える。**
- **なぜ**: 公開JSONには安定したIDが無く、名前と会場だけが同一性の手がかりだから。
- **破れたときの症状**: イベント名を整える修正をしただけなのに、同期ガードが「既存イベントの削除」として止まる。
  止まらずに通ってしまった場合は、公開サイト上で同じ盆踊りが2件に増えるか、1件消える。
- **守っているコード**: `public_json_postprocessors/classify_public_events_diff.py` の `event_key()`、
  および改名を明示的に扱う `key_replacement` 承認の経路
- **守っているテスト**: `tests/test_guard_public_events_sync.py::test_exact_key_replacement_preserves_event_count_and_resolves_keys`

> この設計は弱点でもある。名前を1文字直すだけで別イベント扱いになるので、
> 表記ゆれの修正には必ず `key_replacement` の承認が要る。**名前を直す修正を「小さい修正」だと思ってはいけない。**

### INV-PUB-002 既存の公開イベントを消す・書き換えるのは、承認済みの名前と一致するときだけ

- **内容**: `guard_site_public_event_additions.py` は、サイト側に既にあるイベントの削除・改変を既定で `block` する。
  通せるのは、削除するイベント名が `expected_removed_names` と**個数まで含めて一致**するときか、
  変更が `source_urls` だけで、かつ明示的に許可されたときに限る。
- **なぜ**: 日次の自動処理が既存の公開情報を静かに書き換えてしまうと、誰も気づかないまま公開面が劣化するから。
  追加は取り返しがつくが、消失と改変は気づきにくい。
- **破れたときの症状**: 公開されていたイベントが理由なく消える。開催日や詳細が勝手に書き換わる。
- **守っているコード**: `guard_site_public_event_additions.py` の `guard_decision()`
- **守っているテスト**: `tests/test_public_event_site_addition_tools.py::test_existing_event_field_modification_blocks`、
  `tests/test_public_event_site_addition_tools.py::test_existing_event_date_change_blocks_as_removal`

### INV-PUB-003 collector と site で件数とキー集合が一致しないと、一括同期しない

- **内容**: `public_json_postprocessors/guard_public_events_sync.py` の `guard_decision()` は、
  collector 側と site 側でイベント件数が違えば `event_count_mismatch`、
  片側にしか無いキーがあれば `event_key_mismatch` として `block` する。
- **なぜ**: 件数のズレは、後処理のどれかが動かなかったか、想定外の削除が起きたことの最も分かりやすい兆候だから。
  個々の差分を見る前に、まず総数で異常を捕まえる。
- **破れたときの症状**: 公開件数が急に減る・増える。過去に、日次が止まったまま同期だけ進んで
  終了済み38件が「開催予定」のまま残り続けた事故がある。
- **守っているコード**: `public_json_postprocessors/guard_public_events_sync.py` の `guard_decision()`
- **守っているテスト**: `tests/test_guard_public_events_sync.py::test_event_count_mismatch_blocks_wholesale_sync`

### INV-PUB-004 ガードが pass してもデプロイ承認にはならない

- **内容**: 2つのガードはどちらも、`pass` を「差分が危険でない」ことの表明に留め、
  `public_deploy_requires_separate_approval: True` / `deploy_requires_operator_approval: True` を必ず返す。
- **なぜ**: 機械が見ているのは差分の形だけで、「いま公開してよい時期か」は判断していないから。
  ガードの pass を承認とみなす運用にすると、機械が公開の可否を決めていることになってしまう。
- **破れたときの症状**: 人が意図していないタイミングで公開が更新される。
- **守っているコード**: 両ガードの `guard_decision()` が返す `deploy_approval_note`
- **守っているテスト**: `tests/test_guard_public_events_sync.py::test_pass_still_requires_separate_public_deploy_approval`

### INV-PUB-005 公開の「今日」は必ず外から与える。既定値に落ちない

- **内容**: `export_public_events.py` の `public_export_today()` は、引数か環境変数 `BON_ODORI_PUBLIC_TODAY` から
  日付を取り、**どちらも無ければ `ValueError` を投げる**。`date.today()` のような暗黙の既定値を持たない。
- **なぜ**: 「今日」は、開催済みかどうかの判定と、過去実績の表示期限（スライド）に効く。
  実行環境のタイムゾーンや、再実行した日によって公開内容が変わってしまうと、結果が再現できなくなる。
- **破れたときの症状**: 同じRDBから出したはずの公開JSONが、実行した日によって違う。
  終了済み判定がずれて、終わった行事が残るか、まだの行事が消える。
- **守っているコード**: `export_public_events.py` の `public_export_today()`
- **守っているテスト**: `tests/test_export_public_events.py::test_public_export_today_rejects_missing_context`、
  `tests/test_export_public_events.py::test_site_postprocessors_use_export_today_for_historical_slide_expiry`

### INV-PUB-006 日付予測をJSONフォールバックで補ったら、成功させずに落とす

- **内容**: 日付予測は Master RDB の `predicted_occurrence_dates` を正とする。
  ローカルJSON側にしか無い予測が1件でも使われた場合、`require_no_prediction_json_fallback()` が `RuntimeError` を投げて処理を止める。
  フォールバック0件のときだけ通る。
- **なぜ**: RDBと手元JSONの二重管理を許すと、どちらが正しいのか分からなくなる。
  黙って古いJSONを使うくらいなら、止まって気づいたほうが安全だという判断。
- **破れたときの症状**: RDBを直したのに公開の予測日が変わらない。古い予測が残り続ける。
- **守っているコード**: `export_public_events.py` の `require_no_prediction_json_fallback()`
- **守っているテスト**: `tests/test_export_public_events.py::test_json_prediction_fallback_is_a_hard_failure`、
  `tests/test_export_public_events.py::test_zero_json_prediction_fallback_is_accepted`

### INV-PUB-007 公開実績からRDBへ戻す候補は、対象IDなしでは作られない

- **内容**: `build_public_historical_reference_change_requests.py` の `build_request()` は `occurrence_id` が無ければ
  `ValueError` を投げ、対象を名前ヒント（`match_hint`）で表すことはしない。どの開催回か決まらなかった公開イベントは
  リクエストにせず、解決失敗の理由つきで issues に残す。
- **なぜ**: 反映層は E1 で fuzzy による対象解決を止めた。生成側がヒントだけのリクエストを作れると、
  いったん確定したはずの名寄せが適用の瞬間にまたあいまいになる。**閾値を跨ぐかどうかではなく、経路として塞ぐ。**
- **破れたときの症状**: 別の開催回に過去実績が付き、公開ページに他所の行事の実績が出る。
- **守っているコード**: `public_export_support/build_public_historical_reference_change_requests.py` の `build_request()` と `build_payload()`
- **守っているテスト**: `tests/test_e0b_bridge.py::test_build_request_requires_occurrence_id`、
  `tests/test_e0b_bridge.py::test_source_has_no_match_hint_branch_left`、
  `tests/test_e0b_bridge.py::test_unresolved_event_produces_no_request`

### INV-PUB-008 X materializer所有の曲は有効曲・意味対応・accepted根拠が揃った間だけ公開する

- **内容**: `origin='observed_x_post'` の `occurrence_songs` は、song statusが `active/有効`、
  `setlist/announced` または `result/observed`、accepted evidence linkが1件以上、をすべて満たす行だけ読む。
  `x_song_claim_v2` evidenceは同じfact・evidence・song・occurrence・roleを指すactive materializationも必須にし、
  証跡台帳なしに作られたX風の行を公開しない。別経路のaccepted evidenceは従来どおり公開根拠にできる。
  `inherited_prediction` は `origin='observed_x_post'` の行を継承元にせず、acceptedかつ
  `x_song_claim_v2` ではない根拠だけで算出する。これによりactive materializationを持たない派生行へ
  X投稿の判断を写さない。
  他originの既存公開契約は変えない。
- **なぜ**: evidence linkをretractしても行だけを無条件に読むと、削除・訂正された投稿が公開へ残り続ける。
- **破れたときの症状**: 最後のX根拠を撤回しても曲目が消えない、または告知がpredictionとして重複する。
- **守っているコード**: `export_public_events.py::load_rdb_occurrence_songs`、
  `inherit_song_probabilities_rdb.py::find_inheritance_candidates`、`gather_evidence`
- **守っているテスト**: `tests/test_x_song_materialization_lifecycle.py::test_public_export_requires_active_song_and_accepted_evidence_for_x_fact`、
  `tests/test_x_song_materialization_lifecycle.py::test_other_accepted_evidence_keeps_shared_fact_public_on_x_retraction`、
  `tests/test_inherit_song_probabilities_x_safety.py`

## 主要な流れ

1. **RDBから素の公開イベントを組み立てる** — `export_public_events.py`。`--target-year` と `--today` が必須。
2. **後処理を重ねる** — `public_json_postprocessors/` 配下。順序に意味がある。
   `apply_public_historical_references`（過去実績）→ `apply_public_display_tiers`（表示段）→
   `apply_public_season_hints`（季節ヒント）→ 再度 `apply_public_display_tiers`。
   最後にもう一度表示段を計算し直すのは、季節ヒントが表示段の判断材料になるため。
3. **差分を分類する** — `classify_public_events_diff.py`。全フィールドではなく `HIGH_RISK_FIELDS`
   （過去実績・季節・日付予測・日程・詳細・出典・固定日ルール）に絞って見る。
4. **2つのガードで止める** — 一括同期の可否は `guard_public_events_sync.py`、
   追加だけの差分かどうかは `guard_site_public_event_additions.py`。
5. **人が承認してデプロイ** — `bon-odori-site` 側へJSONを同期し、あちらの `Sync public data` workflow が公開する。

## 依存と影響

**上流**: Master RDB。RDBのS3成果物の取得に失敗すると、この工程は古いRDBを見たまま走りうる。
日次では取得→監査→書き出しの順に並んでいるが、**RDBが更新されていないこと自体はこの工程では検出できない**。

**下流**: `bon-odori-site` リポジトリ。公開JSONの形を変えると、あちらの表示側が壊れる。
公開JSONのフィールド構成は事実上の外部契約なので、[公開JSONのフィールド契約](../L2/public-json.md)へ切り出してある。

**曲目まわりだけ、約束の置き場所がここではない。** `export_public_events.py` はこの仕様が `owns` しているが、
その中の `merge_song_occurrence_hints()` と `_song_from_rdb()`（曲の抑制・重複整理・根拠ラベル）が守っているのは
[曲目サブシステム](08-songs.md)の INV-SNG-001 と INV-SNG-002 である。曲は収集から公開まで縦に貫くドメインなので、
約束をそちらへ集めてある。**この2つの関数を触るときは、逆引きに出てこなくても 08-songs を開くこと。**

## 壊れたときの症状

| 症状 | まず見る場所 |
|---|---|
| 公開件数が急に減った・増えた | `data/public_events_sync_guard.md` の `failures` |
| 終わった行事が「開催予定」のまま | 日次が止まっていないか。次に開催回の状態遷移 |
| イベントが二重に出ている | INV-PUB-001。名前か会場を変えていないか |
| RDBを直したのに公開が変わらない | 後処理のどれかが上書きしている。または INV-PUB-006 で止まっている |
| 実行するたび結果が違う | INV-PUB-005。`--today` を渡しているか |

## 未解決・注意点

- **公開JSONのフィールド契約がどこにも書かれていない。** `bon-odori-site` との間の暗黙の合意になっている。L2として切り出したい。
- **`event_key` が名前依存**（INV-PUB-001）。安定IDへの移行は設計上の宿題として残っている。
- **公開JSONの `display_name` が薄く、同名イベントが区別なく並ぶ**問題が未解決。
- ガード出力の `data/*.json` は成果物としてコミットされるため、差分レビュー時にノイズになりやすい。

---

こと（Claude Code）
