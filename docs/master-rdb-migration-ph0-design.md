# マスタ正本DB移行 Ph0 詳細設計 dry-run

作成: 2026-06-20 / おと（Codex）

## 2026-06-21 方針更新

Ph2以降は、当面の運用を **RDB primary / no Notion write-back** に寄せる。
Notion は既存データの読み取り専用参照・過去の作業ログとして扱い、
SQLite 正本でレビュー済みになった開催日・会場変更を Notion へ自動同期しない。

この文書内には初期案として `RDB -> Notion` / dual-write 前提の記述が残る。
新規実装や runbook では、`docs/ph2-event-occurrence-apply-runbook.md` の
RDB-primary 方針を優先する。

## 目的

Notion と JSON に分散している盆踊りマスタの正本を、ローカル SQLite に段階移行する。
公開サイトは静的 JSON を維持し、DynamoDB の裏取りキューは今回の移行対象外とする。

今回の Ph0 は設計 dry-run であり、既存データの正本切替は行わない。既存の
`build_all_rdb.py`、`data/notion_snapshot.sqlite`、`data/bon_odori.sqlite` を土台に、
現在の「Notion ミラー」RDB を「SQLite 正本」へ昇格するためのスキーマ、運用、同期境界を定義する。

## 現状整理

### 既存RDB

- `data/notion_snapshot.sqlite`
  - Notion 主要 DB の読み取り専用スナップショット。
  - 対象は会場マスタ、イベントDB、予定管理DB、曲マスタ、用語集V2。
  - 2026-06-20 時点の行数は events 214、venues 207、songs 141、plans 17、glossary_v2 121。
- `data/bon_odori.sqlite`
  - Notion、X、YouTube の横断分析用スナップショット。
  - 既存テーブルは `events`、`venues`、`songs`、`event_song_links`、`evidence_items` など。
  - まだ年次開催回を正規表現する `event_series` / `event_occurrences` は持たない。
- `data/event_occurrence_observations.json`
  - YouTube 観測から作った統一モデルv2の足場。
  - `series_key`、`year`、`observed_dates`、`songs` を持つ。
- `data/song_occurrences.json`
  - 年次 occurrence 単位の曲証拠・予測スナップショット。

### 現行Notionプロパティ

イベントDB:

- `イベント名`
- `会場`
- `開催日`
- `状態`
- `例年開催月`
- `開催パターン種別`
- `開催パターン詳細`
- `プログラム型`
- `公開紹介文`
- `情報源URL`

会場マスタ:

- `会場名`
- `所在区・市`
- `住所`
- `アクセス`
- `規模`
- `公開紹介文`
- `過去メモ`
- `出典URL`
- `要レビュー`
- `築地30分圏内`

曲マスタ:

- `曲名`
- `分類`
- `状態`
- `証拠数`
- `出典・音源URL`
- `対象地域`
- `prior階層`
- `イベント`
- `会場`
- `メモ`

## 正本境界

### Ph0/Ph1前の境界

- 正本: Notion、既存 JSON。
- SQLite: 読み取り専用ミラー、分析用スナップショット。
- 書き込み: 既存の `apply_*` スクリプトが Notion / JSON へ直接書く。

### dual期間の境界

- 正本候補: 新 SQLite `data/bon_odori_master.sqlite`。
- 既存正本: Notion / JSON を読み取り可能なまま維持。
- 書き込み: 同じ変更を SQLite と旧正本へ dual write する。
- 判定: SQLite から再エクスポートした結果と旧正本ベースの出力が一致することを監査する。

### 切替後の境界

- 正本: `data/bon_odori_master.sqlite`。
- Notion: レビューUI、表示用ミラー、手動昇格入力の場所。
- JSON: 公開サイト用の生成物、またはレビューファイル。正本ではない。
- `data/notion_snapshot.sqlite`: Notion ミラーとして継続。正本ではない。
- `data/bon_odori.sqlite`: 横断分析・後方互換用ビュー/スナップショットとして継続。正本ではない。

## ファイル構成案

- `data/bon_odori_master.sqlite`
  - SQLite 正本。
- `data/bon_odori_master.schema.sql`
  - DB 作成用 schema dump。レビューと再生成確認用。
- `data/bon_odori_master_manifest.json`
  - DB の論理バージョン、最終ビルド元、各テーブル件数、チェックサム。
- `build_master_rdb.py`
  - Notion/JSON/RDB スナップショットから master DB を dry-run 生成する。
- `audit_master_rdb.py`
  - 主キー、外部キー、件数差分、公開エクスポート差分を監査する。
- `master_db.py`
  - SQLite 接続、トランザクション、write batch、lock、checksum の共通処理。
- `sync_master_to_notion.py`
  - SQLite 正本から Notion 表示フィールドへ同期する。
- `promote_notion_master_fields.py`
  - Notion 上で明示された手動修正だけを SQLite へ昇格する。

## ID方針

既存 Notion page_id は外部IDとして保持するが、正本IDにはしない。
Notion から離れた後も安定するよう、正本IDは内容ベースの stable id とする。

- `venue_id`: `ven_` + 正規化会場名 + 住所/区の hash。
- `song_id`: `song_` + 正規化曲名の hash。曲名統合時は alias を残す。
- `series_id`: `ser_` + 正規化シリーズ名 + 代表会場の hash。
- `occurrence_id`: `occ_` + `series_id` + `event_year` + `occurrence_sequence` の hash。
- `evidence_id`: 既存の URL / tweet_id / video_id ベースの hash を継承。

Notion page_id、既存 JSON キー、YouTube video_id は `external_record_links` で正本IDへ対応付ける。

## コアスキーマ

### 共通メタ

```sql
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL
);

CREATE TABLE master_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE write_batches (
  batch_id TEXT PRIMARY KEY,
  actor TEXT NOT NULL,
  operation TEXT NOT NULL,
  dry_run INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL,
  input_checksum TEXT,
  output_checksum TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  summary_json TEXT NOT NULL DEFAULT '{}'
);
```

### 外部レコード対応

```sql
CREATE TABLE external_record_links (
  system TEXT NOT NULL,
  source_key TEXT NOT NULL,
  external_id TEXT NOT NULL,
  master_table TEXT NOT NULL,
  master_id TEXT NOT NULL,
  relation_kind TEXT NOT NULL DEFAULT 'primary',
  last_seen_at TEXT,
  last_synced_at TEXT,
  source_checksum TEXT,
  read_only_after_cutover INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (system, source_key, external_id, master_table, master_id)
);
```

用途:

- Notion page_id と `venue_id` / `series_id` / `occurrence_id` / `song_id` の対応。
- 旧 JSON の key と正本IDの対応。
- 旧正本を読み取り専用に降格したあともロールバック参照できるようにする。

### venues

```sql
CREATE TABLE venues (
  venue_id TEXT PRIMARY KEY,
  canonical_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  area TEXT,
  address TEXT,
  access TEXT,
  scale TEXT,
  public_intro TEXT,
  past_memo TEXT,
  source_url TEXT,
  latitude REAL,
  longitude REAL,
  review_status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(normalized_name, address)
);

CREATE TABLE venue_aliases (
  venue_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'manual',
  PRIMARY KEY (venue_id, normalized_alias),
  FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
);
```

Notion の会場マスタは切替後、`venues` の表示先になる。
人間が Notion で会場名・住所などを直す場合は、後述の昇格フラグを使う。

### songs

```sql
CREATE TABLE songs (
  song_id TEXT PRIMARY KEY,
  canonical_title TEXT NOT NULL,
  normalized_title TEXT NOT NULL UNIQUE,
  category TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  prior_tier TEXT,
  target_area TEXT,
  evidence_count REAL,
  source_url TEXT,
  memo TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE song_aliases (
  song_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'manual',
  PRIMARY KEY (song_id, normalized_alias),
  FOREIGN KEY (song_id) REFERENCES songs(song_id)
);
```

曲名の表記ゆれは `song_aliases` に寄せ、`occurrence_songs.song_title_raw` には検出時の原文を残す。

### event_series

```sql
CREATE TABLE event_series (
  series_id TEXT PRIMARY KEY,
  series_key TEXT NOT NULL UNIQUE,
  canonical_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  usual_venue_id TEXT,
  area TEXT,
  program_type TEXT,
  annual_months_json TEXT NOT NULL DEFAULT '[]',
  schedule_rule_type TEXT,
  schedule_rule_detail TEXT,
  public_intro TEXT,
  source_url TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (usual_venue_id) REFERENCES venues(venue_id)
);
```

AGENTS.md の方針に従い、イベント名に年号は原則入れない。
年次差分は `event_occurrences` 側に持たせる。

### event_occurrences

```sql
CREATE TABLE event_occurrences (
  occurrence_id TEXT PRIMARY KEY,
  series_id TEXT NOT NULL,
  event_year INTEGER NOT NULL,
  occurrence_sequence INTEGER NOT NULL DEFAULT 1,
  display_name TEXT NOT NULL,
  venue_id TEXT,
  date_start TEXT,
  date_end TEXT,
  date_status TEXT NOT NULL DEFAULT 'unknown',
  lifecycle_status TEXT NOT NULL DEFAULT 'draft',
  confidence TEXT NOT NULL DEFAULT 'unknown',
  source_kind TEXT,
  source_url TEXT,
  inherited_from_occurrence_id TEXT,
  public_intro_override TEXT,
  detail TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(series_id, event_year, occurrence_sequence),
  FOREIGN KEY (series_id) REFERENCES event_series(series_id),
  FOREIGN KEY (venue_id) REFERENCES venues(venue_id),
  FOREIGN KEY (inherited_from_occurrence_id) REFERENCES event_occurrences(occurrence_id)
);

CREATE TABLE occurrence_dates (
  occurrence_date_id TEXT PRIMARY KEY,
  occurrence_id TEXT NOT NULL,
  date_start TEXT NOT NULL,
  date_end TEXT,
  date_type TEXT NOT NULL,
  confidence TEXT NOT NULL,
  source_evidence_id TEXT,
  basis TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (occurrence_id) REFERENCES event_occurrences(occurrence_id)
);
```

`date_status` は公開表示で使う概念を明示的に分ける。

- `confirmed`: 今年の公式HP、主催発表、信頼できるX投稿などで確認済み。
- `ended`: confirmed と同等だが開催日が過去。
- `predicted`: 過去年や固定日ルールからの予測。確定情報ではない。
- `historical_reference`: 過去年の実績。未来年の確定情報には使わない。
- `unknown`: 日程未確認。
- `cancelled`: 中止確認。

日付の正本は `occurrence_dates` とし、`event_occurrences.date_start/date_end/date_status/confidence`
は公開一覧・Notion表示・検索で使う代表値キャッシュとする。
代表値キャッシュは `occurrence_dates` のうち、`date_type` と `confidence` の優先順位で1件を選んで同期する。
優先順位は `confirmed` / `ended`、`predicted`、`historical_reference`、`unknown` の順とし、
キャッシュと明細が不一致の場合は `audit_master_rdb.py` で high issue にする。

公開表示への写像:

| `date_status` | 公開 `display_tier` / category | 現行表示との互換 |
| --- | --- | --- |
| `confirmed` | `upcoming` または confirmed badge | 今年の開催日あり |
| `ended` | `ended` | 終了済み |
| `predicted` | `rule_predicted` | 予測日・確度バッジ |
| `historical_reference` | `recurring_last_year` 相当 | 文言は「過去実績」に寄せる |
| `unknown` | `date_unknown` | 日程未確認 |
| `cancelled` | `cancelled` または非表示候補 | 中止確認 |

切替 dry-run では、現行 `app.js` が扱う `upcoming` / `recurring_last_year` /
`date_unknown` / `ended` と、5段階の確度バッジが変わらないことを公開出力監査に含める。

### occurrence_songs

```sql
CREATE TABLE occurrence_songs (
  occurrence_song_id TEXT PRIMARY KEY,
  origin TEXT NOT NULL DEFAULT 'curated',
  occurrence_id TEXT NOT NULL,
  song_id TEXT,
  song_title_raw TEXT NOT NULL,
  normalized_title TEXT NOT NULL,
  role TEXT NOT NULL,
  evidence_status TEXT NOT NULL,
  probability REAL,
  confidence TEXT NOT NULL DEFAULT 'unknown',
  source_count INTEGER NOT NULL DEFAULT 0,
  evidence_count INTEGER NOT NULL DEFAULT 0,
  inherited_from_year INTEGER,
  first_observed_at TEXT,
  last_observed_at TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(occurrence_id, normalized_title, role),
  FOREIGN KEY (occurrence_id) REFERENCES event_occurrences(occurrence_id),
  FOREIGN KEY (song_id) REFERENCES songs(song_id)
);
```

`role`:

- `result`: 当年の実測・動画・公式曲目表に基づく実績。
- `prediction`: 当年開催前の予測。
- `historical_basis`: 過去年の根拠として保持。
- `hint`: 弱い言及。公開の主表示には使わない。

`evidence_status`:

- `observed`
- `announced`
- `inherited`
- `predicted`
- `review`

Ph1 ではこのテーブルを最初に正本化する。

Ph0 dry-run で重要な境界:

- `venues` / `event_series` / `event_occurrences` は `origin='curated'` の Notion 精査済み行だけを入れる。
- `song_occurrences.json` 由来で Notion精査済み開催回へ一致しない観測は、正本テーブルへ昇格させない。
- 未精査観測は `observed_occurrences` / `observed_occurrence_songs` に隔離し、`raw_event_name` / `raw_venue_name` / `quality_status` / `quality_flags_json` を保持する。
- 動画タイトル・説明文の断片らしい会場名は `quality_status='discard_candidate'` とし、公開・Notion同期・正本会場一覧には出さない。
- 東京23区外らしい観測は `quality_status='out_of_scope'` とし、公開対象外として扱う。
- 公開エクスポート、Notion同期、正本としての会場・イベント一覧は curated テーブルのみを読む。

観測層スキーマ:

```sql
CREATE TABLE observed_occurrences (
  observed_occurrence_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_occurrence_id TEXT,
  raw_event_name TEXT NOT NULL,
  raw_venue_name TEXT,
  normalized_event_name TEXT NOT NULL,
  normalized_venue_name TEXT,
  event_year INTEGER NOT NULL,
  matched_occurrence_id TEXT,
  match_status TEXT NOT NULL DEFAULT 'unmatched',
  quality_status TEXT NOT NULL DEFAULT 'review',
  quality_flags_json TEXT NOT NULL DEFAULT '[]',
  source_payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE observed_occurrence_songs (
  observed_occurrence_song_id TEXT PRIMARY KEY,
  observed_occurrence_id TEXT NOT NULL,
  occurrence_song_id TEXT,
  raw_song_title TEXT NOT NULL,
  normalized_title TEXT NOT NULL,
  matched_song_id TEXT,
  match_status TEXT NOT NULL DEFAULT 'unmatched',
  role TEXT NOT NULL,
  evidence_status TEXT NOT NULL,
  probability REAL,
  evidence_count INTEGER NOT NULL DEFAULT 0,
  source_payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 登録済み未整備イベント調査キュー

Notion events に登録済みだが、開催日または会場 relation が欠けているイベントは、
DB移行前にすべて本調査するのではなく、SQLite 側の調査キューへ載せて移行する。

Ph0 dry-run では `build_registered_event_investigation_queue.py` が以下を生成する。

- `event_investigation_tasks`: SQLite 内の調査タスク。
- `data/registered_event_investigation_queue.json`: 機械処理用の全件キュー。
- `data/registered_event_investigation_queue.md`: 人間レビュー用の優先度一覧。

対象の扱い:

- 主対象は `status='未確認'` かつ開催日または会場が欠けているイベント。
- `確認済み` / `終了` だが欠けがあるイベントは secondary とし、移行前の即調査対象からは原則外す。
- 観測データ由来の昇格候補、情報源URL、東京23区ヒント、欠落種別を使って P0/P1/P2 を付ける。
- P0 は移行前に短時間で見られる即調査候補、P1/P2 はDB移行後にキューから順に処理する。
- 東京23区外ヒントがあるものは、誤ってP0に上がらないようにする。

スキーマ:

```sql
CREATE TABLE event_investigation_tasks (
  task_id TEXT PRIMARY KEY,
  occurrence_id TEXT,
  notion_page_id TEXT NOT NULL,
  event_name TEXT NOT NULL,
  event_year INTEGER NOT NULL,
  status TEXT NOT NULL,
  missing_date INTEGER NOT NULL DEFAULT 0,
  missing_venue INTEGER NOT NULL DEFAULT 0,
  known_venue_names_json TEXT NOT NULL DEFAULT '[]',
  source_url TEXT,
  observed_candidate_count INTEGER NOT NULL DEFAULT 0,
  observed_candidate_confidence TEXT,
  priority_score INTEGER NOT NULL DEFAULT 0,
  priority_label TEXT NOT NULL,
  recommended_action TEXT NOT NULL,
  reason_codes_json TEXT NOT NULL DEFAULT '[]',
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 複数年過去実績の機械昇格

2025年またはそれ以前の実績が2年分以上ある登録済みイベントは、
2026年開催日へコピーせず、`historical_reference` / 過去実績ありの根拠として機械昇格候補にする。

Ph0 dry-run では `build_historical_promotion_candidates.py` が
`data/song_occurrences.json` と `data/event_date_predictions.json` を入力にして以下を生成する。

- `historical_promotion_candidates`: SQLite 内の複数年実績昇格候補。
- `data/historical_promotion_candidates.json`: 機械処理用の候補一覧。
- `data/historical_promotion_candidates.md`: 人間レビュー用の候補一覧。

自動昇格条件:

- 同じ curated event occurrence へ一致する観測が、2025年以前で2年以上ある。
- 原則として2025年実績を含む。`event_date_predictions.json` 側で2年以上の exact date 根拠と予測ルールがある場合は、
  2025年を含まない 2023/2024 の組み合わせも historical_reference 候補にはできる。
- curated event との match score が閾値以上。
- `2024-01-01` のような year backfill 由来のプレースホルダー日付は exact date として扱わず、year-only evidence として保持する。
- 自動昇格先は `historical_reference` / 過去実績であり、未来年の開催日 `confirmed` ではない。
- `event_date_predictions.json` の `predicted_date_start` / `predicted_date_end` は参考予測として保持するが、公式確認なしに confirmed へは上げない。
- 2026年の予測日は `predicted_occurrence_dates` に入れる。既存の `event_occurrences.date_start` は confirmed/curated キャッシュなので、予測で上書きしない。
- 予測日はまず `target_series_id` へ紐づける。2026年の curated occurrence が存在する場合だけ `target_occurrence_id` も入れる。
- 2026年 curated occurrence が既に confirmed/ended の場合は、予測を上書きに使わず `application_status='superseded_by_curated'` または `matches_curated` として保持する。
- 予測日の根拠は `basis_type_label` で `日にちベース` / `曜日ベース` を明記する。
- `candidate_for_existing_2026_occurrence` と `candidate_for_2026_occurrence` だけを `notion_sync_jobs` の dry-run 対象にする。
  `matches_curated` と `superseded_by_curated` はNotion更新ジョブを作らない。

スキーマ:

```sql
CREATE TABLE historical_promotion_candidates (
  candidate_id TEXT PRIMARY KEY,
  target_series_id TEXT NOT NULL,
  target_occurrence_id TEXT NOT NULL,
  target_event_name TEXT NOT NULL,
  source_types_json TEXT NOT NULL DEFAULT '[]',
  historical_years_json TEXT NOT NULL,
  exact_dates_json TEXT NOT NULL DEFAULT '{}',
  year_only_evidence_json TEXT NOT NULL DEFAULT '{}',
  prediction_json TEXT NOT NULL DEFAULT '{}',
  source_occurrence_ids_json TEXT NOT NULL DEFAULT '[]',
  evidence_url_count INTEGER NOT NULL DEFAULT 0,
  song_title_count INTEGER NOT NULL DEFAULT 0,
  match_score INTEGER NOT NULL DEFAULT 0,
  promotion_confidence TEXT NOT NULL,
  auto_promote_eligible INTEGER NOT NULL DEFAULT 0,
  recommended_action TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE predicted_occurrence_dates (
  predicted_date_id TEXT PRIMARY KEY,
  historical_candidate_id TEXT NOT NULL,
  target_series_id TEXT NOT NULL,
  target_occurrence_id TEXT,
  target_event_name TEXT NOT NULL,
  predicted_year INTEGER NOT NULL,
  date_start TEXT NOT NULL,
  date_end TEXT,
  date_status TEXT NOT NULL DEFAULT 'predicted',
  basis_type TEXT NOT NULL,
  basis_type_label TEXT NOT NULL,
  rule_type TEXT NOT NULL,
  basis TEXT,
  confidence TEXT NOT NULL,
  score REAL,
  application_status TEXT NOT NULL DEFAULT 'candidate_for_2026_occurrence',
  source TEXT NOT NULL,
  source_payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### evidence

```sql
CREATE TABLE evidence_items (
  evidence_id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  source_key TEXT,
  source_id TEXT,
  account_key TEXT,
  title TEXT,
  text_excerpt TEXT,
  url TEXT,
  published_at TEXT,
  observed_at TEXT,
  detected_event_date TEXT,
  raw_status TEXT,
  raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE occurrence_evidence_links (
  occurrence_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  target TEXT NOT NULL,
  link_status TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  notes TEXT,
  PRIMARY KEY (occurrence_id, evidence_id, target),
  FOREIGN KEY (occurrence_id) REFERENCES event_occurrences(occurrence_id),
  FOREIGN KEY (evidence_id) REFERENCES evidence_items(evidence_id)
);

CREATE TABLE occurrence_song_evidence_links (
  occurrence_song_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  link_status TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  notes TEXT,
  PRIMARY KEY (occurrence_song_id, evidence_id),
  FOREIGN KEY (occurrence_song_id) REFERENCES occurrence_songs(occurrence_song_id),
  FOREIGN KEY (evidence_id) REFERENCES evidence_items(evidence_id)
);
```

既存 `data/bon_odori.sqlite` の `evidence_items` と互換寄りにして、横断分析コードを段階移行しやすくする。

### Notion同期キュー

```sql
CREATE TABLE notion_sync_jobs (
  job_id TEXT PRIMARY KEY,
  direction TEXT NOT NULL,
  target_table TEXT NOT NULL,
  target_id TEXT NOT NULL,
  notion_source_key TEXT NOT NULL,
  notion_page_id TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  requested_by TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  applied_at TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}'
);
```

direction:

- `rdb_to_notion`: 正本を Notion 表示へ反映。
- `notion_to_rdb`: Notion の明示フラグ付き手動編集を正本へ昇格。

## Notion同期設計

### RDB -> Notion

切替後、Notion は「見やすいレビュー画面」として使う。
SQLite 正本から Notion へ同期するのは、公開・レビューに必要な表示フィールドに限定する。

イベントDBへ同期:

- `イベント名`: `event_series.canonical_name`
- `会場`: `event_occurrences.venue_id` から Notion 会場ページ relation
- `開催日`: `event_occurrences.date_start/date_end`
- `状態`: `lifecycle_status` / `date_status` から既存 select に写像
- `例年開催月`: `event_series.annual_months_json`
- `開催パターン種別`: `event_series.schedule_rule_type`
- `開催パターン詳細`: `event_series.schedule_rule_detail`
- `プログラム型`: `event_series.program_type`
- `公開紹介文`: `event_series.public_intro` または occurrence override
- `情報源URL`: occurrence 優先、なければ series

会場マスタへ同期:

- `会場名`
- `所在区・市`
- `住所`
- `アクセス`
- `規模`
- `公開紹介文`
- `過去メモ`
- `出典URL`

曲マスタへ同期:

- `曲名`
- `分類`
- `状態`
- `証拠数`
- `出典・音源URL`
- `対象地域`
- `prior階層`
- `メモ`

### Notion -> RDB

Notion 側の通常編集を自動で全部吸い上げると、正本境界が曖昧になる。
そのため、Notion から RDB へ昇格できるのは「昇格フラグ付き」の編集だけにする。

Notion に追加する同期用プロパティ案:

- `RDB ID`: text。対応する `venue_id` / `series_id` / `occurrence_id` / `song_id`。
- `RDB同期状態`: select。`synced` / `needs_promote` / `conflict` / `readonly`。
- `RDB最終同期`: date。
- `RDBへ昇格`: checkbox。
- `RDB昇格フィールド`: multi_select。例: `公開紹介文`, `開催日`, `状態`, `住所`, `アクセス`, `規模`, `曲名`, `分類`。
- `RDB昇格メモ`: rich_text。

昇格手順:

1. 人間が Notion で対象フィールドを編集する。
2. `RDBへ昇格` を ON にし、`RDB昇格フィールド` を指定する。
3. `promote_notion_master_fields.py --dry-run` が差分を検出し、`notion_sync_jobs` に候補を作る。
4. ことレビュー。
5. `promote_notion_master_fields.py --apply` が SQLite に反映し、`RDBへ昇格` を OFF、`RDB同期状態` を `synced` に戻す。

競合判定:

- Notion の `last_edited_time` が `external_record_links.last_synced_at` より新しい。
- かつ RDB 側の対象 row checksum も前回同期から変わっている。
- この場合は自動昇格せず `conflict` として止める。

例外として、用語集V2の「複数一致」「公式確認」など既存のレビュー運用で機械的に昇格できる状態遷移は、
用語集専用の適用スクリプトで SQLite へ直接 write batch として記録する。
人間が自由記述フィールドを Notion 上で直した場合だけ、上記の `RDBへ昇格` フラグを必須にする。

## SQLite永続化と競合回避

### gitコミット運用

SQLite 正本は Git にコミットする。
バイナリ差分が読みづらいため、毎回以下を同時更新する。

- `data/bon_odori_master.sqlite`
- `data/bon_odori_master.schema.sql`
- `data/bon_odori_master_manifest.json`
- dry-run/apply レポート `data/master_migration_*.json` / `.md`

コミット前チェック:

```bash
python3 audit_master_rdb.py
python3 build_all_rdb.py
python3 export_public_events.py
python3 export_public_venues.py
```

公開デプロイは既存方針どおり、明示依頼がない限り行わない。

SQLite はバイナリなので、短期の6月末移行では通常コミットで扱う。
中長期で履歴が肥大化した場合は、月次 squash、古い dry-run DB の削除、または Git LFS 化を検討する。
この判断は移行完了後の未決事項として残す。

### 単一writer

SQLite 正本への書き込みは必ず `master_db.py` の write transaction を通す。
同一プロセス/同一runner内の同時書き込みはファイルロックで防ぐ。

方針:

- `BEGIN IMMEDIATE` で write lock を取る。
- `data/.bon_odori_master.lock` を作り、プロセス開始時刻と actor を記録する。
- lock が残っていてもプロセスが存在しない場合だけ stale として回収する。
- 収集ジョブ、Notion 同期、公開エクスポートは同時 apply しない。
- 読み取りは SQLite の snapshot として許可するが、公開エクスポート中は対象 manifest checksum を固定する。

GitHub Actions では別 workflow が別 runner / 別 checkout で走るため、ファイルロックは runner 間では効かない。
そのため SQLite 正本へ書く apply、Notion 同期、公開 export は、dual期間中は1つの正本更新 workflow に集約する。
既存の `collect.yml`、`send_mail.yml` など複数 workflow が SQLite を直接更新しないようにし、
必要な場合は GitHub Actions の `concurrency` group を同じキーにする。

推奨 concurrency:

```yaml
concurrency:
  group: bon-odori-master-rdb
  cancel-in-progress: false
```

SQLite 正本へ push する workflow はこの group に参加させる。
それ以外の workflow は読み取り専用、または正本更新 workflow が生成した成果物を読むだけにする。
これにより、2つの runner が別々に SQLite を更新して後勝ち push で変更を消す事故を防ぐ。

### 現行writer棚卸しと制御

2026-06-20 時点で、以下が repo へ commit/push し得る。

| 実行元 | 現行 concurrency | 主な書き込み | 移行中の扱い |
| --- | --- | --- | --- |
| `.github/workflows/collect.yml` | `bon-odori-collect` | `data/voices*.json`, `data/public/events_public.json`, `data/song_occurrences.json`, `data/public/event_song_occurrences_public.json` など | 正本更新 workflow へ統合、または共通 group 化 |
| `.github/workflows/weekly_harvest.yml` | `manual-song-glossary-harvest-fallback` | 手動fallbackレビューJSON、`data/public/events_public.json`, `data/song_occurrences.json` など | Ph1中は song/public song occurrence 書き込みを止める |
| `.github/workflows/send_mail.yml` | `bon-odori-send-mail` | `data/pending_mail.json` の削除 commit | 共通 group 化。メール送信自体は継続可 |
| ローカル `run_daily_youtube_backfill.py --commit --push` | なし | YouTube backfill候補、`event_occurrence_observations`, `event_schedule_rules`, `event_date_predictions`, `data/public/events_public.json`, `data/song_occurrences.json` など | 移行中は commit/push 停止、または候補・レポートのみ |

Ph0実装前に行う制御:

1. commit/push する Actions workflow の `concurrency.group` を `bon-odori-master-rdb` に統一する。
2. SQLite 正本化の apply / Notion同期 / public export は、原則として `collect.yml` ではなく単一の正本更新 workflow に集約する。
3. `weekly_harvest.yml` は Ph1 中、レビューキュー生成までは許可し、`data/song_occurrences.json` と `data/public/event_song_occurrences_public.json` の commit をしない。
4. `send_mail.yml` は共通 group に入れ、`pending_mail.json` 削除 commit が正本更新 commit と並走しないようにする。
5. ローカル `run_daily_youtube_backfill.py --commit --push` は Ph1 中に使わない。必要な場合は `--dry-run` または `--mail-reminder` なしのレポート生成に限定する。

Ph1中の凍結ファイル:

- `data/song_occurrences.json`
- `data/song_prediction_snapshots.json`
- `data/song_prediction_calibration.json`
- `data/public/event_song_occurrences_public.json`
- `data/public/event_songs_public.json`

Ph2中に追加で注意するファイル:

- `data/event_occurrence_observations.json`
- `data/event_schedule_rules.json`
- `data/event_date_predictions.json`
- `data/public/events_public.json`
- `data/public/events_public.js`

解除条件:

- master DB 由来の生成物と旧経路生成物の差分監査が完了している。
- 対象 workflow の共通 concurrency が入っている。
- ローカル backfill の commit/push を再開しても、master DB への取り込み順序が明示されている。
- ことレビューと内田さんGOが済んでいる。

### Ph1本適用後の段階freeze解除案

Ph1 本適用と本番デプロイは完了したが、freeze ファイルは削除しない。
現行 workflow は `data/master_rdb_migration_freeze.json` の存在だけで
`build_song_occurrences.py` と `calibrate_song_predictions.py` を止めているため、
ファイル削除は旧 `song_occurrences.json` 経路の再開を意味してしまう。

Ph1 後に解除候補とするのは、公開 export 側の2ファイルに限定する。

- `data/public/event_song_occurrences_public.json`
- `data/public/event_songs_public.json`

凍結維持:

- `data/song_occurrences.json`
- `data/song_prediction_snapshots.json`
- `data/song_prediction_calibration.json`

提案詳細は以下に置く。

- `data/master_rdb_ph1_freeze_release_proposal.json`
- `data/master_rdb_ph1_freeze_release_proposal.md`

### ジョブ直列化

日次運用では以下の順に固定する。

1. 外部収集（X / YouTube / blog）
2. 裏取りキュー更新（DynamoDB、今回の移行外）
3. RDB dry-run ingest
4. audit
5. apply
6. 旧設計: RDB -> Notion 表示同期（2026-06-23以降の通常運用では行わない）
7. 公開 JSON export
8. メール配信

dual期間は 5 の apply 時に旧正本への書き込みも続ける。

移行期間中の作業衝突を避けるため、Ph1 の対象である `data/song_occurrences.json` と
`data/public/event_song_occurrences_public.json` は一時的に正本移行担当ファイルとして扱う。
YouTube 過去年 backfill や他の apply 系が同じファイルを更新する場合は、Ph1 apply 前に止めるか、
先に取り込みを終えてから master DB dry-run を再生成する。
少なくとも Ph1 dual write 期間は、`song_occurrences.py` 由来の更新と backfill apply を同時に走らせない。

メール配信は切替前は現行 JSON を参照し続ける。
SQLite 正本由来の公開 JSON へ切り替えた後の初回メール配信は、送信前プレビューをことと内田さんが目視確認してから送る。

## Ph1: occurrence_songs から始める理由

曲 occurrence は以下の理由で最初に切り替える。

- 公開サイトの補助情報であり、イベント日程そのものより事故影響が小さい。
- 既に `song_occurrences.py` と `data/song_occurrences.json` が年次 occurrence 形式に近い。
- YouTube 実績、過去年根拠、予測の役割分離を確認しやすい。
- `event_series` / `event_occurrences` のID設計を小さい範囲で検証できる。

Ph1の成功条件:

- `data/song_occurrences.json` から `occurrence_songs` へ欠落なく移せる。
- Notion精査済み開催回へ一致しない観測は `observed_occurrences` に隔離され、curated な会場・イベント正本へ混入しない。
- `observed_occurrences.quality_status` により、`matched_curated` / `review` / `out_of_scope` / `discard_candidate` へ機械分類できる。
- SQLite から生成した `data/public/event_song_occurrences_public.json` が現行出力と意味的に一致する。
- 曲名未解決 row は `song_id NULL` + `song_title_raw` として保持され、レビュー対象に出る。
- 旧 JSON を読み取り専用バックアップとして残せる。

### Ph1入口 dry-run 実測

2026-06-21 に `export_master_rdb_song_occurrences.py` を追加し、
`observed_occurrences` / `observed_occurrence_songs` から
`event_song_occurrences_public.json` 相当を生成する dry-run を実施した。

成果物:

- `data/master_rdb_event_song_occurrences_public.dry_run.json`
- `data/master_rdb_event_song_occurrences_diff.json`
- `data/master_rdb_event_song_occurrences_diff.md`

結果:

- public occurrence: 1856 件。
- SQLite export occurrence: 1856 件。
- public song relation: 28107 件。
- SQLite export song relation: 28105 件。
- missing occurrence: 0 件。
- extra occurrence: 0 件。
- missing song row: 2 件。
- extra song row: 0 件。

差分2件は、同一開催回内の同一曲が表記ゆれで重複していたものを
SQLite 側の `normalized_title + role` 一意制約で折り畳んだ結果。

- `山王音頭と民踊大会 / 赤坂日枝神社 / 2025`
  - `ダンシングヒーロー`
  - `ダンシング・ヒーロー`
- `シタマチ.ふるさと盆踊り大会 / おかちまちパンダ広場（御徒町駅南口駅前広場） / 2025`
  - `かわいいだけじゃだめですか`
  - `かわいいだけじゃだめですか?`

公開JSONで必要な以下のフィールドは SQLite 側にも保持するようにした。

- `speaker_count`
- `setlist_complete`
- `prediction_reliability`
- `evidence_urls`

現時点の判定:

- Ph1のDB移行は進められる。
- ただし本番切替前に、表記ゆれ重複2件を「SQLite側で統合してよい意味差分」として承認するか、
  旧JSON側も同じ正規化で出力するかを決める。
- `event_songs_public.json` / `events_public.json` 側の差分確認は次のdry-run対象。

次の full public export dry-run は、通常の公開ファイルを上書きせずに以下の環境変数で実行できる。

```bash
BON_ODORI_PUBLIC_OUT_DIR=data/master_rdb_public_dry_run \
BON_ODORI_SONG_OCCURRENCES_JSON=data/master_rdb_event_song_occurrences_public.dry_run.json \
BON_ODORI_PUBLIC_DATE_PREDICTION_REPORT=data/master_rdb_public_dry_run/public_date_prediction_apply_result.json \
python3 export_public_events.py
```

このとき `events_public.json` / `events_public.js` / `event_songs_public.json` は
`data/master_rdb_public_dry_run/` 配下へ出力される。
未指定時の通常実行は従来どおり `data/public/` を読む。

同じ Notion 入力で、旧 `event_song_occurrences_public.json` と SQLite 由来 dry-run を
A/B 出力した結果:

- `events_public.json`: 182 件 / 182 件。
- `event_songs_public.json`: 45 件 / 45 件。
- 差分イベント: 1 件。
  - `シタマチ.ふるさと盆踊り大会 / おかちまちパンダ広場（御徒町駅南口駅前広場）`
  - `かわいいだけじゃだめですか?` が、SQLite側では表記ゆれ統合の影響で
    probability / basis 付き曲目ではなく、既存テキスト抽出由来の名前だけの曲目として残る。

したがって Ph1 の公開面差分は、現時点では曲名表記ゆれの正規化方針に集約されている。

ことレビュー指摘を受け、公開export段に以下を追加した。

- 曲名を NFKC 正規化し、空白・記号・記号相当文字を除いた dedupe key で名寄せする。
- 重複時は probability / source_count / evidence_count が濃い行を代表に残す。
- 同点の場合は先に出た表記を維持する。
- 通常出力の挙動は維持し、dry-run時のみ `BON_ODORI_PUBLIC_DATE_PREDICTION_REPORT` で
  日付予測適用レポートも別ディレクトリへ逃がせるようにした。

再dry-run結果:

- 旧 `event_song_occurrences_public.json` 入力:
  - `data/current_public_dry_run/events_public.json`
  - `data/current_public_dry_run/event_songs_public.json`
- SQLite 由来入力:
  - `data/master_rdb_public_dry_run/events_public.json`
  - `data/master_rdb_public_dry_run/event_songs_public.json`

比較結果:

- `events_public.json`: 182 件 / 182 件、差分 0。
- `event_songs_public.json`: 45 件 / 45 件、差分 0。
- `audit_master_rdb.py`: issue_count 0。

Ph1本適用プレビュー:

```bash
python3 export_master_rdb_song_occurrences.py \
  --production \
  --out-json data/master_rdb_event_song_occurrences_public.production_preview.json \
  --out-diff data/master_rdb_event_song_occurrences_production_preview_diff.json \
  --out-md data/master_rdb_event_song_occurrences_production_preview_diff.md
```

上記で作った本番形プレビューを公開exportに入力しても、旧入力との公開出力差分は 0。

本適用時は、ことレビューOK後に以下を実行する。

```bash
python3 export_master_rdb_song_occurrences.py \
  --production \
  --out-json data/public/event_song_occurrences_public.json
```

このスクリプトは、上書き前の現行 `data/public/event_song_occurrences_public.json` を比較対象にしてから
本番ファイルを書くため、raw song relation の差分2件は diff レポートへ残る。
公開面では export 側の名寄せ後に差分 0 であることを再確認してから commit する。

## dry-run監査項目

Ph0/Ph1 dry-run では以下を必須にする。

### スキーマ監査

- `PRAGMA foreign_key_check` が 0 件。
- 主キー重複 0 件。
- `event_occurrences(series_id, event_year, occurrence_sequence)` 重複 0 件。
- `occurrence_songs(occurrence_id, normalized_title, role)` 重複 0 件。
- `venues.origin != 'curated'` 0 件。
- `event_series.origin != 'curated'` 0 件。
- `event_occurrences.origin != 'curated'` 0 件。

### 件数監査

- Notion events 214 件から series/occurrence 生成件数を説明できる。
- Notion venues 207 件から venues 生成件数を説明できる。
- Notion songs 141 件から songs 生成件数を説明できる。
- `song_occurrences.json` の occurrence/song 件数と SQLite の `occurrence_songs` 件数差分を説明できる。
- `observed_occurrences` の `matched_curated` / `review` / `out_of_scope` / `discard_candidate` 件数を説明できる。
- `event_investigation_tasks` の primary/secondary 件数と P0/P1/P2 件数を説明できる。

### 公開出力監査

- `events_public.json` のカード数、イベント名、会場、日付、ステータスの差分。
- `venues_public.json` の会場名、区、住所、公開紹介文の差分。
- `event_song_occurrences_public.json` の occurrence/song 差分。
- `date_status` から公開 `display_tier` / category / 確度バッジへの写像差分。
- メール配信が読む公開 JSON の切替前後差分。

### Notion同期監査

- RDB -> Notion の dry-run payload 件数。
- Notion -> RDB 昇格候補件数。
- conflict 件数。
- 旧正本にだけ存在する row。
- SQLite にだけ存在する row。

## 段階移行スケジュール案

### 2026-06-20: Ph0設計dry-run

- 本書をことレビューへ提出。
- `build_master_rdb.py` の実装範囲を確定。
- Notion に追加する同期プロパティを確認。
- ことレビュー指摘A/Bを反映し、Actions単一writerと移行中の担当ファイル凍結を明記。

### 2026-06-21: Ph0実装dry-run

- `data/bon_odori_master.sqlite` を dry-run 生成。
- `audit_master_rdb.py` を作成。
- 件数・外部キー・公開出力差分をレポート。
- ことレビュー。

### 2026-06-22: Ph1 occurrence_songs dual write

- `occurrence_songs` の dry-run/apply。
- `song_occurrences.py` の出力を SQLite へ取り込む。
- 既存 JSON 生成は継続。
- Ph1 apply 前に YouTube backfill / 他 apply 系による `song_occurrences.json` 更新を止める。

### 2026-06-23: Ph1公開出力切替dry-run

- `event_song_occurrences_public.json` を SQLite 由来で生成。
- 現行 JSON 由来と比較。
- 問題がなければ SQLite 由来を採用。

### 2026-06-24: Ph2 event_series/event_occurrences dry-run

- Notion events と YouTube observations から series/occurrence を構築。
- 開催日 confirmed/predicted/historical_reference の分類監査。
- `export_public_events.py` の RDB 入力化を dry-run。

### 2026-06-25: Ph2 event_occurrences dual write

- 日付昇格系 `apply_*` / `promote_*` を SQLite + Notion dual write にする。
- 旧 Notion は読み取り可能なまま維持。

### 2026-06-26: Ph3 venues/songs master化

- venues/songs を SQLite 正本へ昇格。
- Notion 表示同期と昇格フラグ運用を開始。

### 2026-06-27: 全公開エクスポートdry-run

- `events_public.json`
- `venues_public.json`
- `event_songs_public.json`
- `event_song_occurrences_public.json`

全て SQLite 正本由来で生成し、旧経路との差分を監査。

### 2026-06-28: 正本切替apply

- SQLite 正本を採用。
- Notion / 旧 JSON を読み取り専用バックアップへ降格。
- ロールバック手順を確認。
- 本適用前に内田さんGOを挟む。

### 2026-06-29: soak

- 日次収集、メール配信、公開エクスポートを通常実行。
- 差分・競合・未同期を確認。
- 切替後初回メール配信は送信前プレビューをこと＋内田さんで目視確認。

### 2026-06-30: 6月末締め

- 旧正本への通常書き込み停止。
- dual write を必要最小限に縮退。
- ことレビューで完了判定。

## ロールバック

切替後に重大問題が出た場合:

1. `data/bon_odori_master.sqlite` の採用コミットを revert する。
2. 公開エクスポート入力を旧 Notion / JSON 経路へ戻す。
3. Notion は読み取り専用バックアップとして残っているため、旧経路から再生成する。
4. dual期間中の SQLite-only 差分は `write_batches` と `notion_sync_jobs` から抽出し、再適用可否をレビューする。

ロールバック対象に DynamoDB 裏取りキューは含めない。

## 実装順の確認

推奨順:

1. `master_db.py` と schema。
2. `build_master_rdb.py --dry-run`。
3. `audit_master_rdb.py`。
4. `occurrence_songs` 取り込み。
5. `event_song_occurrences_public.json` の SQLite 由来生成。
6. `event_series` / `event_occurrences` 取り込み。
7. 日付昇格スクリプトの dual write 化。
8. venues/songs の正本化。
9. 旧設計: RDB -> Notion 表示同期。
10. 旧設計: Notion -> RDB 昇格。

この順なら、Ph1で一番小さいユーザー影響範囲を使って ID、lock、監査、git永続化を検証できる。

## 未決事項

- Notion に同期用プロパティを追加するタイミング。
- `series_id` の生成に代表会場を含めるか、同名イベントの複数会場を別 series として固定するか。
  - 現行方針では `series_key = canonical event name + usual venue` を推奨。
- Notion の既存 `状態` select と `date_status` / `lifecycle_status` の完全な写像。
- 曲マスタの統合・別名管理で、どの表記を canonical にするかの人間レビュー基準。
- SQLite バイナリ履歴が肥大化した場合の月次 squash / 古い dry-run DB 削除 / Git LFS 化の判断。
- GitHub Actions の既存 workflow 棚卸しと、SQLite write workflow の `concurrency` 適用範囲。

## ことレビュー依頼ポイント

1. `event_series` / `event_occurrences` / `occurrence_songs` の分割粒度は、年次イベント設計方針に合っているか。
2. Notion -> RDB を昇格フラグ付きに限定する境界で問題ないか。
3. 6月末までの圧縮日程で、Ph1 occurrence_songs から始める順に異論がないか。
4. `data/bon_odori_master.sqlite` を git 正本にし、manifest/schema/report を同時コミットする運用で十分か。
5. 切替後に `data/bon_odori.sqlite` を互換スナップショットとして残す方針で問題ないか。
