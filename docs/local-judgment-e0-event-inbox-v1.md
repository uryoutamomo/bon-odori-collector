# PR-E0 仕様：event inbox candidate v1（正本）

決定者: こと（Claude Code） / 2026-08-11（**v1.1 追記 同日**：おとの仕様レビュー指摘2件＋補足2件を反映。改訂箇所は §3.2 / §4.2 / §5.1 / §5.2 / §10.1 / §11-26〜35）
前提: `docs/local-judgment-contract-v1.md`（v1.1、SHA-256 `3b47f5e4e2618c209c1d8b0fb42cbaa1f5687b9a3f167719bd2939ceb4756a05`）
段階: 10本立てのうち3本目（E1・J0-contract は merge 済み）

この文書が PR-E0 の**正本**です。過去のメッセージ本文・artifact と食い違う場合はこちらが優先します。
実装時は `docs/local-judgment-e0-event-inbox-v1.md` としてPRに含め、コードと一緒に version 管理してください。

**この仕様は実コード（origin/main、2026-08-11 時点 `c7a55a6`）を読んで書いています。** 各所に実測値を添えました。
食い違いを見つけたら実装前に指摘してください（黙って仕様に寄せない）。

---

## 0. 不変条件（これを壊す実装は不合格）

> **E0 は canonical な正本事実を1行も書かない。**
> E0 が書いてよいのは (1) raw evidence（`evidence_items`）と (2) 判断待ち候補（`review_inbox_items` の E0 行）だけ。
> 系列・開催回・会場・日付・曲は、E2a/E2b 以降が typed finite action と decision lineage を伴って書く。

> **E0 は「どれと同じか」を決めない。** 候補集合を高再現率で集めて添えるだけ。
> 閾値による自動解決（`STRONG_MATCH_SCORE = 0.92`）は E0 に持ち込まない。決めるのは J0-read 以降の agent 判断。

導かれる帰結を2つ明記する。

1. **E0 実行の前後で、canonical テーブルの行数が1行も変わらない。**（§7 に対象表と検査方法）
2. **候補に「解決済みの対象ID」が入るのは、レポートが明示的にIDを書いていたときだけ。** 名寄せの結果は入らない。

---

## 1. 範囲

### 入れるもの

| 入力 | 実体 | 現状の件数 |
|---|---|---|
| 公式・準公式のお知らせレポート | `data/official_notice_reports/*.json` → `report_apply/apply_official_notice_report.py` | origin/main に 40件超 |
| 現地報告（新規イベント） | `data/firsthand_reports/*.json` → `report_apply/apply_firsthand_field_report.py` の `report_type = "new_event"` | 1件 |

### 入れないもの（意図的な先送り。抜け漏れではない）

- **`review_inbox` → change request の橋渡し**（`review_inbox_adapters/build_change_requests_from_review_inbox.py`）。E1 で `occurrence_id` 必須化済みで、`.github/workflows/` からの参照はゼロ、実績9件は全件 `occurrence_id` 付き。**いま壊れていない経路をこのPRで触ると、差し戻し時の切り分けが難しくなる**ので E0b（E2a の直前）へ回す。
- **`merge_existing_series`**（お知らせレポートの5番目の action）。系列同士の統合は occurrence 単位の候補に落ちず、`event_create` / `event_update` のどちらの lane にも収まらない。E2b で専用の finite action を設計する。**E0 は黙って落とさず、「対象外」として実行レポートに列挙する**（§10）。
- **`firsthand` の `existing_event_songs`**。これは domain=`song` の判断で、既に6月から動いている曲の経路がある。E0 で event lane に混ぜない。
- **`public_export_support/build_public_historical_reference_change_requests.py`**（E1 の既知の不整合）。E0b で一緒に扱う。

### なぜこの切り方か

E0 の目的は「イベント候補の入り口を1本にする」ことだが、**一度に全部の入り口を付け替えると、差し戻しが起きたとき原因の切り分けができない。** J0-contract で2度差し戻した経験から、1PRで確定させる範囲を狭く取る。お知らせレポートは内田さんが日々使う主入口（実績40件超）なので、ここが通れば E0 の目的の大半は達成できる。

---

## 2. 実コードで確認した前提（実装者はここを読んでから書く）

以下はすべて origin/main で実測した事実です。仕様の根拠になっているので、変わっていたら報告してください。

**(a) `review_inbox_items.domain` は契約の `domain` ではない。** 実データの値は `曲・用語・低緊急度`（399件）／`YouTube`（175件）／`X`（2件）の3つだけで、これは**レビュー画面のバケツ名（日本語）**です（手元の master RDB 複製 = 2026-08-08 の snapshot `20260808T082520Z` で実測。件数は日々動きますが、**語彙が3つとも日本語である**という事実が仕様の根拠です）。**event ドメインの行は現時点で1件も存在しません**——E0 が最初の1件を作ります。契約 v1.1 §3 は「`domain` は `review_inbox_items` に既にある列」と書いていますが、**列名が同じだけで語彙が違います**。`songs.status` が `active 29 / 有効 77 / 候補 274 / 無効 19` と語彙二重になって今も困っているのと同じ轍を踏まないため、E0 は既存列を再解釈せず、**契約用の列を別に足します**（§3）。

**(b) 既存の読み手は `status` だけで絞っている。** `review_inbox.inbox_rows(conn, status=...)` は status 以外で絞りません。E0 行に `status='pending'` を入れると、**既存のレビュー画面・エクスポートにそのまま混ざります**（判断待ち561件の器へ合流してしまう）。だから E0 行は `status='candidate'` を使います（§3）。`review_inbox_items` に status の CHECK 制約は無く、`master_rdb/audit.py` も status 値は見ていない（列の有無だけ）ので、新しい値を足しても既存検査は壊れません。

**(c) 列を足しても schema version 判定は壊れない。** `review_inbox.inbox_schema_version()` は `set(V2_COLUMNS).issubset(実際の列)` で判定しており、**列の追加は安全**です（完全一致判定ではない）。`inbox_rows` の SELECT も列を明示列挙しているので影響しません。

**(d) 既存の writer は使えない。** `review_inbox.upsert_inbox_items()` は列を固定列挙しているため、新しい列に書けません。E0 は自前の writer を持ちます（§3）。

**(e) 現行の apply 経路が書いている表**（`report_apply/event_report_helpers.py`）: `venues`(136行) / `event_series`(196) / `event_occurrences`(223) / `occurrence_dates`(259, 394) / `evidence_items`(438) / `occurrence_evidence_links`(472) / `songs`(504) / `occurrence_songs`(520) / `occurrence_song_evidence_links`(551)。**このうち E0 が触ってよいのは `evidence_items` だけです。**

**(f) `register_new` は名前どおりではない。** `ensure_series_and_occurrence`（同 161行）は series_key 完全一致で既存系列を再利用し、同一系列・同一年の開催回があれば `ON CONFLICT DO UPDATE` で `venue_id`/`date_start`/`date_end` を上書きし、`date_status='confirmed'` `lifecycle_status='published'` を固定で入れます。**「追加」と「上書き」が1つの操作に同居している**のが E0 で解く問題そのものです。

**(g) 候補検索の既存関数はそのまま使える。** `find_occurrence_candidates` / `find_venue_candidates` は `FUZZY_MATCH_MIN_SCORE = 0.45` 以上を最大8件返す**高再現率の検索器**で、除外器ではありません。E0 はこれを候補集合の生成に使います（ただし §6 の変更あり）。

**(h) `stable_id(prefix, *parts, length=16)`**（`master_rdb/master_db.py:490`）は SHA-1 先頭16桁。ID生成はこの家の作法に合わせます。

---

## 3. 出力先とスキーマ

### 3.1 判断待ち候補は `review_inbox_items` に置く（新テーブルを作らない）

器を2つに割ると J0-read が両方を見る羽目になり、「どっちに入っているか」という質問が永久に増えます。既存表に**追加列**で相乗りします。

### 3.2 migration v2（additive・idempotent）

`event_model/local_judgment_migration.py` に **version 2 / name `event_inbox_candidate_v1`** を追加します。v1 の DDL は変更しないこと。

`review_inbox_items` へ追加する列（すべて nullable、既存行は NULL のまま）:

```
contract_domain        TEXT      -- event | song | term（契約の domain。日本語の legacy domain とは別物）
contract_lane          TEXT      -- event_create | event_update | song | term
first_eligible_at      TEXT      -- ISO-8601 tz必須
expires_at             TEXT      -- ISO-8601 tz必須。null 可
superseded_by_inbox_id TEXT
depends_on_inbox_id    TEXT      -- 導出値。§5.1 の規則で更新される
revision_family_key    TEXT      -- base source_key（改訂しても不変）。§4
revision               INTEGER   -- 0 起点。§4
```

`revision_family_key` / `revision` は v1.1 で追加しました（おとの指摘1）。`source_key LIKE 'base@r%'` で家族を引くと、report_id に含まれる `_` が LIKE のワイルドカードに当たって別家族を拾いうるため、**パターン一致ではなく等値比較で引けるようにする**ためです。

追加インデックス:

```
CREATE INDEX IF NOT EXISTS idx_review_inbox_contract_lane
ON review_inbox_items(contract_domain, contract_lane, status, expires_at);
```

**実装条件**: `ALTER TABLE ADD COLUMN` は `PRAGMA table_info` で存在確認してから発行し、2回流して差分ゼロにすること。既存行の値は一切変更しない。

### 3.3 E0 行の各列の値（固定）

| 列 | 値 | 理由 |
|---|---|---|
| `inbox_id` | `stable_id("inbox", "event_candidate", source_id, source_key)` | 家の作法（`review_inbox.inbox_id_for` と同形）。決定的で冪等 |
| `kind` | `event_candidate` | 固定 |
| `domain`（legacy・NOT NULL） | `イベント` | 既存の日本語バケツ語彙に合わせる。**`event` は入れない**（§2a） |
| `contract_domain` | `event` | 契約側 |
| `contract_lane` | `event_create` / `event_update` | §5 の判定表で決まる |
| `status` | `candidate` | 既存の読み手（`status='pending'`）に混ざらないため（§2b） |
| `time_scope` | 開催日が実行日以降なら `future`、過去なら `historical`、日付なしは `reference` | 既存語彙 `{future, historical, reference}` に従う |
| `source_id` | `official_notice:{report_id}` / `firsthand:{report_id}` | §4 |
| `source_key` | `{source_id}#{entry_key}` | §4 |
| `source_payload_hash` | `sha256_hex(canonical_json(proposal))`（64桁） | 契約の `_sha` が64桁を要求 |
| `title` | `{event_name_hint}（{venue.name}／{date_start}）` | 人が読む用 |
| `event_name` / `venue` / `event_year` | proposal の値をそのまま | 既存列の素直な利用 |
| `source_url` | 出典URL（無ければ null） | |
| `recommended_action` | **null** | E0 は推奨を出さない。判断は agent の仕事 |
| `priority_label` / `priority_score` | null / null | E0 では順位付けをしない（流量設計は J0-read の担当） |
| `decision` 系4列 | null | E0 は判断しない |
| `first_eligible_at` | 実行時刻（tz付き） | |
| `expires_at` | §9 | |
| `revision_family_key` | base `source_key`（`@rN` を付けない形） | §4。改訂しても不変 |
| `revision` | 0 起点の整数 | §4 |
| `depends_on_inbox_id` | §5.1（rename 分割時のみ。ほかは null） | 導出値 |

`canonical_json` は契約実装（`review_inbox_adapters/local_judgment_contract.canonical_json`）を再利用すること。自前で書かない。

### 3.4 `payload_json` の構造（v1 固定）

```jsonc
{
  "candidate_version": 1,
  "report": {
    "report_type": "official_notice" | "firsthand_new_event",
    "report_id": "nerima_august_first_wave_2026",
    "report_path": "data/official_notice_reports/nerima_august_first_wave_2026.json",
    "reported_at": "2026-08-01T10:15:00+09:00",
    "notice_kind": "third_party_current_year",   // official_notice のみ。無ければ null
    "source_title": "...",
    "source_url": "https://..."
  },
  "proposal": {                                   // ← source_payload_hash はこの dict だけから作る
    "legacy_action": "register_new",
    "event_name_hint": "...",
    "event_year": 2026,
    "date_start": "2026-08-07",
    "date_end": "2026-08-08",
    "venue": {"name": "...", "area": "...", "address": "..."},
    "detail_addendum": "...",
    "songs": [{"title": "...", "uncertain": false}],
    "explicit_occurrence_id": null,               // レポートが明示したIDのみ
    "explicit_series_id": null,
    "explicit_source_occurrence_id": null,
    "depends_on_family_key": null                 // §5.1。rename 分割の create 側のみ
  },
  "targets": {
    "occurrence_candidates": [
      {"occurrence_id": "...", "series_id": "...", "display_name": "...",
       "venue_name": "...", "date_start": "...", "event_year": 2026, "match_score": 0.87}
    ],
    "venue_candidates": [
      {"venue_id": "...", "canonical_name": "...", "area": "...", "address": "...", "match_score": 0.91}
    ],
    "retrieved_at": "2026-08-11T14:00:00+09:00",
    "calculation_version": "e0-candidate-search/v1",
    "input_hash": "<sha256 64桁>"
  },
  "evidence_ids": ["evidence_xxxxxxxxxxxxxxxx"],
  "raw_excerpt": "レポート source.raw_text の該当部分（無ければ全文の先頭1000字）"
}
```

`targets.input_hash` は `sha256_hex(canonical_json({event_name_hint, venue_name, event_year, limit}))`。
候補集合を後から凍結して照合できるようにするためのもので、契約 §7 の retry packet の `input_hash` と同じ役割です。

**`targets` の候補は「上位1件」ではなく取得した全件を保存すること。** 「正解が候補に含まれていた率」を独立KPIとして後から測るためで、選ばれた1件しか残っていないと測れません（契約 v1.1 §7 の `candidate_ids` 凍結と同じ理由）。

### 3.5 writer

`review_inbox_adapters/event_inbox_writer.py` を新設し、E0 行の upsert はここだけが行う。

- 既存 `review_inbox.upsert_inbox_items()` は列固定で新列に書けないため、共用しない
- 逆に E0 writer は `kind != 'event_candidate'` の行を書かない（引数で来たら `ValueError`）
- 既に同じ `inbox_id` の行があり `status not in ('candidate',)` なら **書かずに ValueError**（legacy 行との衝突を握りつぶさない）

---

## 4. 候補の識別と冪等性

### 4.1 キーの決め方

- `source_id` = `official_notice:{report.source.report_id}` または `firsthand:{report_id}`
  （firsthand のレポートには `report_id` が無いので、**ファイル名の stem** を `report_id` とする）
- `entry_key` = レポートの entry に `entry_id` があればその値。無ければ `stable_id("entry", normalize_text(event_name_hint), str(event_year), length=12)`
  **配列の index は使わない**（レポートを並び替えただけで別候補になるため）
- `source_key` = `{source_id}#{entry_key}`
- `inbox_id` = `stable_id("inbox", "event_candidate", source_id, source_key)`

同一レポート内で `entry_key` が衝突したら（同名・同年のイベントが2件並ぶ）、**高severityで停止**する。黙って1件に潰さない。

### 4.2 再実行時の分岐（v1.1 で全面改訂 — おとの指摘1）

**v1 の規則には冪等性のバグがありました。** base の `source_key` だけを見て「判断済みなら改訂を作る」としていたため、`@r1` を作った後の3回目の実行でも base（判断済み・hash 差分あり）を見て `@r2` を作り、以後 `@r3`, `@r4` と無限に増えます（§11-6 の再実行冪等性にも反する）。指摘のとおりなので、**revision family 単位で引く**規則に直します。

**revision family** = `revision_family_key`（= base の `source_key`）が同じ行の集合。`revision` の昇順に並び、`revision = 0` が base。

再実行時は必ず**家族の最新 revision** を見て、次の4通りに分岐します。

| 状況 | 動作 |
|---|---|
| 家族が存在しない | `revision = 0` の行を新規作成 |
| 最新 revision の `source_payload_hash` が入力と**一致** | **no-op**（`last_seen_at` のみ更新）。判断済みかどうかを問わない |
| hash が違い、最新 revision に canonical decision が**無い** | その行を in-place 更新（`inbox_id`・`revision_family_key`・`revision` は不変）。誰も判断していないので lineage を壊さない |
| hash が違い、最新 revision に canonical decision が**ある** | `revision = 最新+1` の行を新規作成（`source_key = {base}@r{N}`、`inbox_id` は §4.1 の式で再計算）。**その最新行の `superseded_by_inbox_id` に新 `inbox_id` を書く** |

これで3回目以降は「最新 revision の hash が一致 → no-op」に落ちます。

**家族の健全性チェック**（違反したら high severity で停止、黙って直さない）
- `superseded_by_inbox_id` が既に埋まっている行を、もう一度 supersede しようとした（家族の分岐）
- `revision` に欠番や重複がある
- 同一家族に `contract_lane` が混在している

最後の分岐で旧行の `superseded_by_inbox_id` を書くのは、判断のやり直しではなくリンク付けなので契約の「closed からの再判断禁止」には抵触しません。**旧行の `status`・`decision` 系の列は触らないこと。**

canonical decision の有無は `canonical_decision_ledger`（J0 で作った表）に当該 `inbox_id` の行があるかで判定します。**表が無いDBでは「decision 無し」とみなさず停止**します（判断の有無を確かめられないまま上書きしないため）。表が無い場合の扱いは §10.1 に集約しました。

---

## 5. lane の判定表

**判定は「レポートが何と名乗ったか」ではなく「何を生じさせる提案か」で決めます。**
`event_create` = 新しい開催回を生じさせる提案 / `event_update` = 既存の開催回を変える提案。

| 入力 | lane | proposal に入る明示ID | 備考 |
|---|---|---|---|
| official_notice `confirm_existing`（`occurrence_id` あり） | `event_update` | `explicit_occurrence_id` | 実在確認は行う。無ければ §8 の issue |
| official_notice `confirm_existing`（`match_hint` のみ） | `event_update` | なし（null） | **fuzzy 解決しない。** 候補集合だけ添える |
| official_notice `register_new` | `event_create` | なし | **系列名が完全一致しても自動結合しない**（§2f の上書き問題の発生源） |
| official_notice `add_occurrence_to_existing_series` | `event_create` | `explicit_source_occurrence_id` | 系列は既存、開催回は新規 |
| official_notice `rename_series_and_register_new` | **2件に分割** | 下記 | |
| official_notice `merge_existing_series` | **候補化しない** | — | 実行レポートに `out_of_scope` として列挙 |
| firsthand `new_event` | `event_create` | なし | |
| firsthand `existing_event_songs` | **候補化しない** | — | 同上（domain=song の経路） |

### 5.1 `rename_series_and_register_new` の分割と、依存の追従（v1.1 で追記）

1件目 = `event_update`（系列名の変更提案。`explicit_source_occurrence_id` 必須、`entry_key` は `{entry_key}:rename`）
2件目 = `event_create`（今年の開催回。`entry_key` は `{entry_key}:create`）

**1つの候補が2つの canonical な変更を含んではいけない**（typed finite action の原則）ので分けます。E2b は依存先が accept されるまで create 側を適用してはならない — この制約は E2b の仕様で扱いますが、E0 の時点でリンクを作ります。

**依存の持ち方**（おとの補足1への回答）。改訂で inbox_id が変わると、依存先ポインタが古くなります。そこで**依存を2つに分けます**。

- `proposal.depends_on_family_key` = rename 側の **`revision_family_key`**。改訂しても不変なので `source_payload_hash` を揺らさない。**これが依存の正体**
- `depends_on_inbox_id`（列）= そこから導出した**現時点のポインタ**。値は「rename 家族の最新 revision の `inbox_id`」

更新規則は次の2つだけです。

1. **create 行に canonical decision が無い** → 実行のたびに `depends_on_inbox_id` を rename 家族の最新 revision へ張り替える。列の更新であって proposal は変わらないので、hash も revision も動かない
2. **create 行に canonical decision が既にある**のに、rename 家族に新しい revision ができている → **張り替えず、medium severity の issue `dependency_superseded_after_decision` を出す**。判断済みの行を黙って書き換えない／人か agent が見直せるように記録を残す、の両立

**create 側を rename の改訂に連動して revision 化はしません。** create 自身の proposal が変わっていないのに改訂を増やすと、判断のやり直しを無から作ることになるためです。

---

### 5.2 firsthand レポートの写像（v1.1 で追記 — おとの補足2）

firsthand は official notice と形が違い、**1ファイル＝1イベントで `events[]` を持たず、フィールドが root 直下**にあります（実レポートは `data/firsthand_reports/` に1件のみ）。写像を固定します。

| firsthand（root） | proposal のキー |
|---|---|
| `event_name_hint` | `event_name_hint` |
| `series_name`（任意） | 無ければ `event_name_hint` を使う。**両方 payload に残す**（`series_name_hint` として別キーで保持） |
| `event_year` | `event_year` |
| `event_date` | `date_start` |
| `event_date_end`（任意） | `date_end` |
| `venue{name, area, address, access}` | `venue`（`access` も含めてそのまま） |
| `raw_note` | `detail_addendum` |
| `songs[]` | `songs` |
| `source_url` | `report.source_url` |
| `uncertain` | `proposal.uncertain`（bool、既定 false） |

- `report_id` = ファイル名の stem（firsthand には `report_id` フィールドが無い）
- `entry_key` = §4.1 の既定式（`stable_id("entry", normalize_text(event_name_hint), str(event_year), length=12)`）
- `legacy_action` = `new_event`
- **実レポートが1件しか無いので、この写像はテスト fixture で固定すること**（実データだけでは網羅できない）

## 6. ターゲット解決と候補集合

- `find_occurrence_candidates(conn, event_name_hint, venue_name_hint, event_year, limit=8)` と
  `find_venue_candidates(conn, venue_name_hint, area_hint, limit=8)` をそのまま使う（新しい検索器を書かない）
- **`STRONG_MATCH_SCORE`（0.92）による自動解決は E0 に持ち込まない。** 候補が1件でスコア 0.99 でも `explicit_occurrence_id` は null のまま
- `event_year` は `find_occurrence_candidates` の絞り込みに渡す。ただし `event_create` の候補では **年を渡さずにも1回引き、両方の和集合**を保存する（去年の同名イベントが見えないと「既存系列の今年分」かどうかを agent が判断できないため）。重複は `occurrence_id` で除去し、`match_score` の高い方を残す
- 候補が0件でも候補化は行う（0件であること自体が判断材料）
- 会場の候補は `find_venue_candidates` のみ。**`ensure_venue` は絶対に呼ばない**（暗黙 create があるため。8/7 の鹿骨中学校の会場二重化はこれ）

---

## 7. 書いてよいもの・書いてはいけないもの

### 書いてよい

- `evidence_items`：1レポートにつき1行。`upsert_evidence_item` 相当を使い、`evidence_id = stable_id("evidence", source_id)` で冪等に。**`occurrence_evidence_links` は書かない**（リンク先の開催回はまだ確定していない）
- `review_inbox_items`：E0 行のみ（§3）
- `local_judgment_schema_migrations`：migration 記録

### 書いてはいけない（検査対象）

`venues` / `venue_aliases` / `event_series` / `event_series_aliases` / `event_occurrences` / `occurrence_dates` /
`occurrence_evidence_links` / `songs` / `occurrence_songs` / `occurrence_song_evidence_links` /
`canonical_decision_ledger` / `review_queue_state_ledger` / `review_hold_ledger`

**検査方法**（テストで固定すること）: E0 実行の前後で上記すべての `COUNT(*)` が一致し、かつ `review_inbox_items` の `status != 'candidate'` の行数と `MAX(updated_at)` が変わらないこと。

**構造的な検査も置くこと**: E0 のモジュールが `ensure_venue` / `ensure_series_and_occurrence` / `confirm_occurrence_schedule_venue` / `upsert_occurrence_song` / `link_occurrence_evidence` を import していないことをテストで固定する。将来うっかり呼ばれるのを防ぐため、実行時の行数比較だけに頼らない。

---

## 8. queue state の初期値

**`review_queue_state_ledger` に行が無い候補は `eligible` とみなす。** E0 は同表に書きません。

理由: `review_queue_state_ledger.decision_id` は NOT NULL で、まだ何の判断も起きていない候補には入れる値がありません。`system` の genesis action を新設すれば書けますが、それは J0-contract の registry と遷移表に手を入れることになり、**merge 済みの契約を E0 の都合で変えることになる**ので却下しました。「行が無い＝ eligible」という規則を J0-read が実装する前提で固定します。

この規則は `docs/local-judgment-e0-event-inbox-v1.md` に書き、J0-read の実装者（＝次段階）が参照できるようにすること。

---

## 9. 期限と流量

**`expires_at`**（判断が間に合わなくなる時刻。8/15 の行事を 8/20 に提案しても無意味なので必須）

- `date_end` があれば `date_end` の JST 23:59:59（`+09:00`）
- 無く `date_start` があれば `date_start` の JST 23:59:59
- どちらも無ければ `first_eligible_at + 90日`

**期限切れの entry は候補化しない。** 実行時刻が `expires_at` を過ぎている entry は行を作らず、実行レポートに `expired` として件数と内訳を出す（黙って捨てない）。既存の E0 行が期限切れになった場合、E0 は状態を変えません（掃除は J0-read/J1 の担当）。

**流量の上限**: `--max-candidates`（既定 200）。1回の実行で作る**新規行**がこれを超える場合、**1行も書かずに非zero終了**する。部分適用にすると「何件が入って何件が入っていないか」が読めなくなるためで、既存 apply スクリプトの partial-apply ポリシーとは意図的に変えています。超過時のメッセージには、対象レポートと必要な件数を出すこと。

---

## 10. CLI と安全装置

### 10.1 migration の適用境界（v1.1 で確定 — おとの指摘2）

**指摘のとおり、v1 の §4.2・§10・§12 は両立していませんでした。** 本番DBには J0 の migration（v1）がまだ当たっていないので、そこからコピーした dry-run 用DBにも台帳がありません。「台帳が無ければ停止」と「本番へは適用しない」を同時に守ると、§13 の実データ dry-run が永久に実行できません。**おとの選択肢 (a) を採ります。**

| モード | migration の扱い |
|---|---|
| dry-run（既定） | コピーしたDBに対して **v1 → v2 の順で適用してよい**。コピーは使い捨てなので本番は変わらない |
| `--apply`（本番書き込み） | **migration を一切実行しない。** 必要な表が無ければ high severity で停止し、「migration runner を内田さんの承認のもとで先に流すこと」をメッセージに出す |
| `--no-auto-migrate`（新設フラグ） | dry-run でも適用しない。**§11-9（台帳欠落で停止する）を検証するための入口** |

守るべき境界を3つ明記します。

1. **適用先はコピーだけ。** 適用前に、対象DBのパスが `--db` で指定された本番パスと**異なること**を実行時に確認する（同じなら停止）。「dry-run のつもりで本番へ当てた」を仕組みで防ぐ
2. **DDL を E0 が持たない。** `event_model/local_judgment_migration.py` の関数（v1・v2）を呼ぶだけ。同じ定義が2か所にあると必ずずれる
3. **実行レポートに、どちらの migration を適用したかを必ず記録する**（`migrations_applied: ["local_judgment_contract_v1", "event_inbox_candidate_v1"]`）。黙って当てない

`--apply` 時に停止する設計にしたのは、**本番のスキーマ変更は内田さんの承認事項**だからです（E0 が勝手に当てられる経路を作らない）。承認をいただいたら migration runner で当て、その後で `--apply` を通します。

### 10.2 CLI

`review_inbox_adapters/build_event_inbox_candidates.py`（新設、entry point）

- 引数: `--report PATH`（複数可） / `--report-dir DIR` / `--db PATH` / `--max-candidates N` / `--apply` / `--confirm PHRASE` / `--no-auto-migrate`
- **既定は dry-run**。本番DBをコピーして `data/event_inbox_candidates_dry_run.sqlite` へ書く（既存 apply スクリプトと同じ `report_apply/rdb_apply_support` の `copy_db` / `backup_db` / `audit_db` を使う）
- 本番書き込みは `--apply` ＋ `operation_safety/manual_apply_guards` の確認フレーズが揃ったときのみ。定数 `EVENT_INBOX_CANDIDATE_CONFIRMATION` を新設する
- 出力: `data/event_inbox_candidates_report.json` と `.md`。内訳は `created` / `updated` / `noop` / `superseded` / `expired` / `out_of_scope` / `issues` の件数と、各件の `inbox_id`・`source_key`・理由
- 終了コード: high severity issue があれば非zero。`out_of_scope` と `expired` は issue ではない（正常系）
- **argparse の実パースを経由するテストを必ず1本置く**（PR #165 の `seed` が `AttributeError` で落ちた再発防止。関数直接呼び出しのテストだけでは検出できない）

### issue の severity

| 事象 | severity |
|---|---|
| `explicit_occurrence_id` が実在しない | medium（その entry のみスキップ、他は続行） |
| 同一レポート内の `entry_key` 衝突 | high（全体停止） |
| `canonical_decision_ledger` が存在しない（`--apply` 時、または `--no-auto-migrate` 時） | high（全体停止、§10.1） |
| revision family の健全性違反（二重 supersede・欠番・lane 混在） | high（全体停止、§4.2） |
| 判断済み create の依存先 rename が改訂された | medium（`dependency_superseded_after_decision`、§5.1） |
| dry-run の適用先が本番DBパスと同一 | high（全体停止、§10.1） |
| `--max-candidates` 超過 | high（全体停止、§9） |
| レポートの必須項目欠落 | high（そのレポートのみ停止し、他レポートは続行） |

---

## 11. negative test 一覧（= 受け入れ条件）

**各件について「修正を外したら落ちる」ことを確認できる形にすること。「テスト全通過」は合格の根拠にしません。**
PR本文に、どのテストがどの修正を外すと落ちるかを1行ずつ書いてください。

1. 候補が1件・`match_score` 0.99 でも `explicit_occurrence_id` が null のまま（fuzzy 自動解決の禁止）
2. E0 実行前後で §7 の canonical テーブルの `COUNT(*)` がすべて不変
3. E0 のモジュールが §7 の書き込みヘルパーを import していない（構造検査）
4. `evidence_items` は1レポート1行で、2回実行しても増えない
5. `occurrence_evidence_links` が1行も増えない
6. 同一レポート2回実行で `review_inbox_items` の行数不変、`last_seen_at` 以外の列が不変
7. proposal を1文字変えると `source_payload_hash` が変わり、**未判断の行はその場更新・`inbox_id` 不変**
8. 判断済み（`canonical_decision_ledger` に行あり）の候補の proposal を変えると、**`revision = 1` の新行ができ、旧行に `superseded_by_inbox_id` が入り、旧行の `status`・decision 列は不変**
9. `--no-auto-migrate` で台帳の無いDBを渡すと high severity で停止し、1行も書かない
10. `merge_existing_series` は候補化されず `out_of_scope` に出る（黙って消えない）
11. `firsthand` の `existing_event_songs` も同様に `out_of_scope`
12. `rename_series_and_register_new` が2行になり、`event_create` 側に `depends_on_inbox_id` が入り、`event_update` 側には入らない
13. `date_start` が実行日より前の entry は候補化されず `expired` に出る
14. `--max-candidates` 超過で**1行も書かずに**非zero終了
15. dry-run 既定で本番DBのファイルが変わらない（実行前後の checksum 一致）
16. `--apply` を確認フレーズ無しで拒否する
17. E0 行は `status='candidate'` で、`review_inbox.inbox_rows(conn, 'pending')` の結果件数が実行前後で不変（既存レビュー画面に混ざらない）
18. E0 行の legacy `domain` が `イベント`、`contract_domain` が `event`。既存行の `contract_domain` は NULL のまま
19. migration v2 が冪等（2回流して差分なし）で、既存 `review_inbox_items` の行の値が変わらない
20. migration v2 適用後も `review_inbox.inbox_schema_version()` が 2 を返す（列追加で退行しない）
21. 同一レポート内の `entry_key` 衝突で high severity 停止
22. `entry_key` が配列 index に依存しない（events の並び順を入れ替えても同じ `inbox_id` になる）
23. `argparse` の実パース経由でサブコマンド全経路が動く（属性欠落が無い）
24. `targets` の候補が上位1件でなく取得全件保存されている
25. 候補0件でも行は作られる

### v1.1 で追加（おとの指摘への対応。ここが今回の差し戻しの核なので必ず実測すること）

26. **判断済み→改訂→もう一度同じ入力で実行、の3回目が no-op になる**（`@r2` を作らない）。`revision` の最大値が 1 のままであること。**これが v1 のバグそのもの**なので、家族単位の検索を外すと落ちることを確認する
27. 4回目・5回目も no-op（`last_seen_at` 以外に差分が出ない）
28. revision family の健全性違反（`superseded_by_inbox_id` が既に埋まった行を再度 supersede しようとする）で high severity 停止
29. `depends_on_family_key` が改訂をまたいで不変で、**未判断の create 行の `depends_on_inbox_id` だけが最新 rename revision へ張り替わる**（proposal の hash と `revision` は動かない）
30. **判断済みの create 行の `depends_on_inbox_id` は張り替わらず、`dependency_superseded_after_decision` が medium で出る**
31. dry-run で v1→v2 の migration がコピーへ適用され、**`--db` に渡した本番DBのファイル checksum が実行前後で一致**する
32. `--apply` モードでは migration を実行せず、台帳が無ければ high severity で停止する（自動適用の経路が無いこと）
33. dry-run の適用先が本番DBパスと同一になる呼び方をしたとき停止する
34. 実行レポートに `migrations_applied` が出る（何も当てなかった場合は空配列）
35. firsthand の root 直下フィールドが §5.2 のとおり proposal へ写り、`report_id` がファイル名 stem になる（fixture で固定）

---

## 12. やらないこと（E0 の範囲外）

- canonical fact write（系列・開催回・会場・日付・曲のいずれも）
- 判断・推奨（`recommended_action` は null 固定）
- 名寄せの確定、閾値による自動解決
- packet 生成・hold・decision の記録（J0-read / J1）
- console UI
- 橋渡し（`build_change_requests_from_review_inbox.py`）の付け替え → **E0b**
- `merge_existing_series` の設計 → E2b
- 既存 apply スクリプトの削除・無効化（strangler：旧経路は残す）
- **本番 `data/bon_odori_master.sqlite` への migration 適用（v1 と v2 の両方。内田さんの承認を別途取る）。** dry-run 用コピーへの適用は §10.1 のとおり可

---

## 13. 完了条件

1. §11 の 35件がすべて通り、かつ各件が「修正を外すと落ちる」ことを確認済み
2. dry-run を実際の `data/official_notice_reports/` 全件（40件超）に対して回し、実行レポートの内訳（created / expired / out_of_scope / issues）を PR 本文に貼る
3. §7 の canonical テーブル行数が dry-run 前後で不変であることを、実データで実測して PR 本文に貼る
4. 仕様書（この文書）を `docs/local-judgment-e0-event-inbox-v1.md` として同梱
5. 本番 migration は適用しない（PRにはスクリプトのみ）

**着手前に、この仕様の矛盾・実装不能点・§2 の実測との食い違いを指摘してください。** 前回（J0-contract）は仕様を確定させずにポインタで渡したせいで2度差し戻しました。今回は仕様側の穴を先に潰したいので、実装より先に読んで、疑問を返してもらうところから始めます。
