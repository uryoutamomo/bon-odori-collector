# PR-J0-read 仕様：agent judgment intake v1（正本）

決定者: こと（Claude Code） / 2026-08-14（**v1.1 追記 同日**：おとの仕様レビュー指摘2件を反映。§3.5＝`--max-packets` の単位、§5.4＝dry-run の migration を v3 まで、§6.3＝claim の書き込み先、§9-45〜49）
前提:
- `docs/local-judgment-contract-v1.md`（v1.1、SHA-256 `3b47f5e4e2618c209c1d8b0fb42cbaa1f5687b9a3f167719bd2939ceb4756a05`）
- `docs/local-judgment-e0-event-inbox-v1.md`（v1.3、SHA-256 `fbe5788a…`）
段階: 10本立てのうち4本目（E1・J0-contract・E0 は merge 済み）

この文書が PR-J0-read の**正本**です。過去のメッセージ本文・artifact と食い違う場合はこちらが優先します。
実装時は `docs/local-judgment-j0-read-v1.md` としてPRに含め、コードと一緒に version 管理してください。

**この仕様は origin/main の実コード（2026-08-14 時点 `953a936`）を読んで書いています。** 各所に実測を添えました。
食い違いを見つけたら実装前に指摘してください（黙って仕様に寄せない）。

---

## 0. 不変条件（これを壊す実装は不合格）

> **判断を台帳へ書けるのは、`validate_canonical_decision` を通った packet だけである。**
> 台帳への書き込みは、canonical decision・queue state・hold の3表が**同一トランザクション**で整合する形でのみ行う。
> LLM の出力は untrusted。actor identity と時刻は**ローカルの entrypoint が stamp** し、入力JSONの自己申告は採用しない。

> **J0-read は canonical な正本事実を1行も書かない。**
> 書いてよいのは判断の台帳（`canonical_decision_ledger` / `review_queue_state_ledger` / `review_hold_ledger` / 新設の claim 表）と、`review_inbox_items` の E0 行の queue 由来の列だけ。
> 系列・開催回・会場・日付・曲は E2a 以降が typed finite action で書く。

導かれる帰結を3つ明記する。

1. **J0-read 実行の前後で、canonical テーブルの行数が1行も変わらない**（E0 §7 と同じ検査を流用する）。
2. **同じ候補に同じ判断を2回入れても、台帳の行は増えない。** 冪等性は `decision_id` が担保する（§3.2）。
3. **agent は accept / reject を出せる。** hold しか出せない実装は契約 v1.1 §0 の不変条件そのものに反する。

---

## 1. 範囲

### 入れるもの

E0 が作った候補を、こと／おとが実際に判断して台帳へ残せるようにする最小の経路。

| 工程 | 実体 |
|---|---|
| 候補の読み出しと packet 生成 | 新設 `review_inbox_adapters/build_judgment_packets.py` |
| LLM の raw judgment 取り込み → builder → validator → 台帳書き込み | 新設 `review_inbox_adapters/apply_judgment_results.py` |
| 台帳 writer（3表 + claim 表） | 新設 `review_inbox_adapters/judgment_ledger_writer.py` |
| claim / lease（minimal） | 同上。§6 |
| 実行レポート | `data/judgment_packets_report.json` / `data/judgment_results_report.json` |

### 入れないもの（意図的な先送り。抜け漏れではない）

- **内田さんの裁定コンソール（user terminal decision の経路）** → **J0-adjudication（次のPR）**。
- **一括裁定**（`grouping_fingerprint` での束ね、`adjudication_batch_id`）→ 同上。ただし §8 に申し送りを書く。
- **scheduler による `requeue` の自動実行** → J1。J0-read は `deferred_retry` の hold を**開くところまで**。時刻到達で戻す実装は持たない。
- **domain write**（E2a 以降）。accept された候補が実際に master RDB へ反映されるのは E2a。**J0-read の accept は「採用と判断した」という記録だけで、イベントは1件も増えない。**
- song / term ドメイン。E0 が event しか作っていないため、入力が存在しない。registry は4レーンとも登録済みなので、コード上の分岐は domain 固有にしないこと。

### なぜ user コンソールを分けたか

契約 v1.1 §0 のとおり、**user は agent hold を経ていない候補に手を出せません**。つまり user の経路は agent の経路が動き始めるまで入力がゼロで、先に作っても試せません。順序として agent 側が先に立つのは必然です。

加えて、J0-contract で2度差し戻した経験から、1PRで確定させる範囲は狭く取ります。agent 経路（CLI 2本と writer）と user 経路（Webの画面・一括操作・排他）は、壊れ方も検証方法も別物です。

**この切り方の代償を正直に書きます。** J0-read だけが入った状態では、`awaiting_user` の hold は溜まるのに裁く手段がありません。ただし判断は台帳に残るので失われず、accept / reject は agent が出せるので全件が滞留するわけでもありません。J0-adjudication を続けて作ることが前提です。

---

## 2. 実コードで確認した前提（実装者はここを読んでから書く）

すべて origin/main で実測した事実です。変わっていたら報告してください。

**(a) 契約モジュールは DB を持たない。** `review_inbox_adapters/local_judgment_contract.py`（432行）の docstring は "This module has no database or domain writer." で、実際に `canonical_decision_ledger` へ書くコードは存在しません。**判断を保存する実装は現在どこにもなく、J0-read が最初に作ります。**

**(b) `build_hold_ledger_entry` は dict を返し、`hold_packet_json` の値が dict のままです**（`local_judgment_contract.py:427`）。列名は `_json` ですが直列化はしていません。**writer 側で `canonical_json` によりシリアライズすること。** 同様に `allowed_actions` と `candidate_ids` も list のままなので、JSON 文字列へ直してから INSERT します。契約実装を変えないこと（merge 済みで、他のテストが dict を前提にしています）。

**(c) `adjudication_batch_id` は現状かならず null になります。** `build_user_decision`（同 299行）は `open_hold.get("adjudication_batch_id")` から取りますが、`review_hold_ledger` にその列がありません（`event_model/local_judgment_migration.py` の DDL と契約 §8 の列一覧の両方に無い）。**J0-read では user 経路を実装しないので実害はありませんが、J0-adjudication が最初に踏む穴です。** 対処方針は §8 に書きました。

**(d) `review_queue_state_ledger` は `inbox_id` が PRIMARY KEY で、状態は1行しか持ちません**（履歴は `canonical_decision_ledger` 側）。したがって queue state の更新は INSERT ではなく **upsert** です。`decision_id` は NOT NULL なので、E0 §8 のとおり「行が無い＝ `eligible`」を規則として実装します。**J0-read がこの規則の実装者です。**

**(e) E0 候補の読み出し条件。** `review_inbox_items` の `kind = 'event_candidate'` かつ `status = 'candidate'`。`contract_domain` / `contract_lane` / `revision_family_key` / `revision` / `superseded_by_inbox_id` / `expires_at` / `payload_json` を使います。E0 の writer（`event_inbox_writer.py`）は `status` を `candidate` 固定で書き、`update_candidate` は `status != 'candidate'` の行を書き換えないので、**J0-read が status を動かすと E0 の再実行が ValueError で止まります**（§4.4）。

**(f) 既存レビューコンソールは別系統です。** `review_console/server.py`（240行）＋`data.py`（3928行）は `data/review_inbox.json` を読むローカルWebサーバー（`http://127.0.0.1:8751/`）で、master RDB の `review_inbox_items` は読みません。**判断待ち561件の器はこちらで、E0 候補とは経路が完全に分かれています。** J0-adjudication の画面をここへ相乗りさせるかは §8 の申し送り事項です。

**(g) `stable_id(prefix, *parts, length=16)`**（`master_rdb/master_db.py:490`）は SHA-1 先頭16桁。ID生成はこの家の作法に合わせます。

---

## 3. packet の生成

### 3.1 対象の選び方

次をすべて満たす `review_inbox_items` の行が対象です。

1. `kind = 'event_candidate'` かつ `status = 'candidate'`
2. `superseded_by_inbox_id IS NULL`（改訂された古い行は判断させない）
3. `review_queue_state_ledger` に行が無い、または `queue_state = 'eligible'`
4. `expires_at` が実行時刻より未来、または `expires_at IS NULL`
5. `first_eligible_at` が実行時刻以前
6. 有効な claim が他のセッションに握られていない（§6）

**`queue_state = 'closed'` の候補は絶対に packet 化しない。** 契約の「closed からの再判断禁止」をここで担保します。`deferred_retry` / `awaiting_user` も対象外です（前者は J1 の scheduler が戻すまで、後者は user が裁くまで）。

並び順は `expires_at` の昇順、次に `first_eligible_at` の昇順。**期限が近いものから判断させる**ためで、優先度スコアは使いません（E0 が `priority_score` を null 固定にしているため、そもそも入っていません）。

### 3.2 packet_id の決め方（**これが冪等性の要**）

```
packet_id = stable_id("packet", inbox_id, source_payload_hash, PACKET_CALCULATION_VERSION)
PACKET_CALCULATION_VERSION = "judgment-packet/v1"
```

**ランダムな UUID にしてはいけません。** `decision_id` は契約 §4 で `packet_id` を材料に含むため、実行のたびに packet_id が変わると、**同じ候補への同じ判断が毎回別の decision_id になり、台帳へ何行でも積める**ようになります。決定的にしておけば、二重取り込みが冪等な no-op に落ちます（§5.3）。

候補が改訂されれば `source_payload_hash` が変わるので packet_id も変わります。これは正しい挙動で、改訂後は別の判断として扱われます。

**候補集合（`targets`）が変わっても packet_id は変わりません。** レポートは1文字も変わっていないので当然ですが、「どの候補集合を見て判断したか」は `packet_sha256`（packet 全体のハッシュ、契約実装が `canonicalize_raw_judgment` で自動計算）が台帳に残るため、後から区別できます。E0 §3.4 が `resolved_target` を `proposal` の外に置いたのと同じ考え方です。

### 3.3 packet の中身（v1 固定）

LLM へ渡す1件分の JSON。**候補行の `payload_json` をそのまま埋め込まず、判断に要る形へ整えます。**

```jsonc
{
  "packet_version": 1,
  "packet_id": "packet_xxxxxxxxxxxxxxxx",
  "inbox_id": "inbox_xxxxxxxxxxxxxxxx",
  "domain": "event",
  "lane": "event_create",
  "source_id": "official_notice:nerima_august_first_wave_2026",
  "source_key": "official_notice:...#entry_xxxxxxxxxxxx",
  "source_payload_hash": "<sha256 64桁>",
  "generated_at": "2026-08-14T21:00:00+09:00",
  "expires_at": "2026-08-16T23:59:59+09:00",
  "proposal": { /* E0 payload_json の proposal をそのまま */ },
  "targets": { /* E0 payload_json の targets をそのまま */ },
  "resolved_target": { /* E0 payload_json の resolved_target。null 可 */ },
  "evidence": [
    {"evidence_id": "evidence_xxxxxxxxxxxxxxxx", "source_url": "https://...",
     "excerpt": "レポート raw_excerpt", "retrieved_at": "..."}
  ],
  "retry_candidates": [ /* §3.4。空配列可 */ ],
  "allowed_actions": ["accept", "reject", "defer_for_retry", "hold_for_user"],
  "reason_codes": { /* reason_code → hold_mode の対応表を丸ごと同梱 */ }
}
```

**`reason_codes` を packet に同梱するのは、LLM に対応表を推測させないためです。** 契約実装の `REASON_CODE_HOLD_MODE` をそのまま出力します。LLM が返した `hold_mode` は採用せず（§5.2）、あくまで表示のためですが、選べる code の一覧が手元に無いと未知の code を作文するので入れます。

**`allowed_actions` は registry から引きます。** ハードコードしないこと。`(domain, lane, action)` の3つ組で `agent` が許可されている action を列挙し、`hold` は raw の語彙である `defer_for_retry` / `hold_for_user` の2つへ展開します（契約 §6）。

### 3.4 retry_candidates（`deferred_retry` を選べるようにする）

契約 §7 のとおり、**`next_eligible_at` は機械が算出し、LLM は提示された候補から選ぶだけ**です。範囲外を選んだら `_retry_hold_packet` が拒否します。

J0-read が生成する候補は、当面**1本だけ**にします。

```jsonc
{"candidate_id": "retry_xxxxxxxxxxxx",
 "next_eligible_at": "<実行時刻 + 14日>",
 "window_start": "<実行時刻 + 7日>",
 "window_end": "<expires_at と (実行時刻+30日) の早い方>",
 "occurrence_ids": ["..."], "evidence_ids": ["..."],
 "retrieved_at": "...", "calculation_version": "retry-window/v1",
 "input_hash": "<sha256 64桁>"}
```

**過去の告知実績から算出する仕組みは J0-read では作りません。** 契約 §6 の `insufficient_announcement_history` は「再試行日を算出する履歴が足りないときは根拠のない日付を作らず人へ回す」という規則で、J0-read の時点では**履歴を見る実装がそもそも無いので、固定窓を使う**ことを明示します。

**制約が2つあります。** 契約実装の `_retry_hold_packet` は `occurrence_ids` と `evidence_ids` が**両方とも1件以上**でないと `ContractError` を投げます（`local_judgment_contract.py:255`）。E0 候補は evidence を必ず1件持ちますが、**`event_create` の候補は既存の開催回を持たないため `occurrence_ids` が空になりえます**。

したがって次の規則にします。

- `targets.occurrence_candidates` が1件以上ある候補 → その `occurrence_id` を最大8件まで凍結し、`retry_candidates` を1本出す
- 1件も無い候補 → **`retry_candidates` は空配列**。LLM は `defer_for_retry` を選べず、保留したいなら `hold_for_user` になる
- packet に「なぜ retry を選べないか」を書く（`retry_unavailable_reason: "no_occurrence_candidates"`）

**これは実装上の妥協ではなく、契約が要求している凍結内容を満たせない以上、選ばせてはいけないという判断です。** 空の `occurrence_ids` で hold packet を作ろうとすると、builder が例外を投げてバッチ全体が止まります。

### 3.5 出力

- `data/judgment_packets/batch_{YYYYMMDD}_{NN}.json`（1ファイル = 1バッチ、既定20件）
- `--batch-size N`（既定 20）= **1バッチに入れる packet 数**
- `--max-packets N`（既定 100）= **1回の実行で生成する packet の総数**。バッチ数ではありません。既定では 100 packet ＝ 5バッチが出ます。この 100 という値は業務フロー v3 で決めた「日次100件（5バッチ）」に由来します
- **claim を取るのは実際に生成した packet の分だけ**です。上限で切られて生成しなかった候補は未 claim のまま残し、次回の実行対象になります
- **`--max-packets` を超える場合は、超えた分を出さずに正常終了する**（E0 の `--max-candidates` が「1行も書かず非zero終了」なのと**意図的に変えています**。E0 は本番DBへの書き込みで部分適用が読みにくくなるのを嫌いましたが、packet はファイル出力で何も壊さないため、日次の流量上限として素直に切ります）。レポートに「残り何件が待機中か」を出すこと
- 実行レポート `data/judgment_packets_report.json`：生成件数・バッチ一覧・除外理由別の件数（`superseded` / `expired` / `not_eligible` / `claimed_by_other`）と、除外された候補の `inbox_id` 一覧

---

## 4. LLM への渡し方と、戻ってくる形

### 4.1 raw judgment の形

LLM は1バッチにつき1ファイルを返します。`data/judgment_results/batch_{...}.json`。

```jsonc
{
  "batch_id": "batch_20260814_01",
  "results": [
    {"packet_id": "packet_...", "inbox_id": "inbox_...",
     "domain": "event", "lane": "event_create",
     "source_id": "...", "source_key": "...", "source_payload_hash": "...",
     "requested_action": "accept",          // accept | reject | defer_for_retry | hold_for_user
     "reason_code": null,                    // hold のとき必須
     "selected_retry_candidate_id": null,    // defer_for_retry のとき必須
     "payload": {"reason_detail": "…", "target_id": null, "evidence_class": "official"},
     "rationale": "人が読むための説明。台帳へは payload.reason_detail のみ入る"}
  ]
}
```

### 4.2 untrusted として扱うこと

**入力JSONの `actor_type` / `actor_id` / `decision_channel` / `decided_at` は、書かれていても無視します。** 取り込み CLI が `trusted_actor` を組み立てて `canonicalize_raw_judgment` に渡します。

```
actor_type = "agent"（固定）
actor_id   = --actor-id 引数、無ければ環境変数 LOCAL_JUDGMENT_ACTOR_ID、無ければ停止
decision_channel = "llm"（固定。ACTOR_CHANNELS が強制する）
decided_at = 取り込み実行時刻（tz付き）
```

**`actor_id` を必須にするのは、こととおとのどちらが判断したかを後から分けるためです。** 影実験でモデル差を測ったのと同じ理由で、`koto-opus-5` / `oto-codex` のような値を想定しています。既定値を持たせず、指定が無ければ停止します。

`rationale` は台帳の列に入れません。**`payload` に入れてよいキーは registry の `allowed_payload_fields`（`target_id` / `reason_detail` / `evidence_class`）だけ**で、それ以外は `canonicalize_raw_judgment` が拒否します。説明文を残したい場合は `payload.reason_detail` に入れること。

### 4.3 packet との照合

取り込み時に、result の `packet_id` に対応する packet ファイルを読み、次を照合します。**1件でも違えば、その result を捨てて medium issue を出します**（バッチ全体は止めない）。

- `inbox_id` / `domain` / `lane` / `source_id` / `source_key` / `source_payload_hash` が packet と一致
- `packet_id` が §3.2 の式で再計算した値と一致（**LLM が packet_id を作文していないこと**）
- 候補行の現在の `source_payload_hash` が packet 生成時と一致（**判断中に候補が改訂されていないこと**。違えば `packet_stale`）
- `requested_action` が packet の `allowed_actions` に含まれる

### 4.4 候補行の `status` は動かさない

判断が付いても `review_inbox_items.status` は `candidate` のままにします。**queue state の正本は `review_queue_state_ledger` で、`status` 列は E0 の writer が所有しているためです**（§2e）。ここを `judged` などに変えると E0 の再実行が ValueError で止まります。

「判断済みかどうか」は `canonical_decision_ledger` に当該 `inbox_id` の行があるかで引きます。E0 §4.2 が改訂判定に使っているのと同じ基準で、**2か所が同じ基準を見る**形に揃えます。

---

## 5. 台帳への書き込み

### 5.1 3表を1トランザクションで

1件の判断につき、次を**同一トランザクション**で行います。途中で失敗したら全部ロールバックすること。

| 表 | 動作 |
|---|---|
| `canonical_decision_ledger` | INSERT（`decision_id` PRIMARY KEY） |
| `review_queue_state_ledger` | upsert（`inbox_id` PRIMARY KEY、`queue_state` と `decision_id` を更新） |
| `review_hold_ledger` | hold のときだけ INSERT（`build_hold_ledger_entry` の戻りを直列化して） |
| claim 表 | 対象 claim を release |

**`hold_id` の決め方**: `stable_id("hold", decision_id)`。決定的にすることで、二重取り込みが `decision_id` の UNIQUE 制約より先に PRIMARY KEY 衝突で止まるのを防ぎ、§5.3 の冪等判定に乗せられます。

### 5.2 LLM の申告を採用しない箇所（実装の要）

- `requested_action` が `defer_for_retry` / `hold_for_user` でも、**契約へ渡す action は `hold` に正規化**します（registry に `defer_for_retry` は存在しません）。
- **`hold_mode` は `reason_code` から引きます。** LLM が `hold_for_user` と言っていても `reason_code` が `packet_stale` なら `deferred_retry` です。**逆に、LLM の申告と reason_code 由来の mode が食い違ったら、その result を捨てて medium issue を出します**（契約 §6 の「LLM の申告を採用しない」を、黙って上書きするのではなく不一致として記録する形で実装する）。
- `next_eligible_at` は `retry_candidates` から取ります。LLM が日付を書いてきても読みません。

### 5.3 冪等（二重取り込み）

同じ result ファイルを2回流したときの規則です。

| 状況 | 動作 |
|---|---|
| `decision_id` の行が既にあり、`packet_sha256` と `action` と `actor_id` が一致 | **no-op**（何も書かない。レポートの `noop` に計上） |
| `decision_id` の行が既にあり、いずれかが不一致 | **high severity で停止**（黙って上書きしない） |
| 行が無い | 通常どおり INSERT |

**`INSERT OR IGNORE` を使わないこと。** 「同じIDだが中身が違う」を握りつぶすと、あとから何が起きたか追えなくなります。

### 5.4 `--apply` と migration の境界（E0 §10.1 と同じ規律・**両方の CLI に適用**）

**この節は `apply_judgment_results.py` だけでなく `build_judgment_packets.py` にも適用されます。** packet 生成も claim 表へ書くため、書き込み先の境界は同じ規律で守る必要があります。

| モード | 動作 |
|---|---|
| dry-run（既定） | 本番DBをコピーし、コピーに対して **migration v1 → v2 → v3 をこの順で適用してよい**。書き込み（台帳・claim とも）はコピーに対して行う |
| `--apply` | **migration を一切実行しない（v1・v2・v3 のいずれも）。** 必要な表が無ければ high severity で停止し、「migration runner を内田さんの承認のもとで先に流すこと」を出力する |
| `--no-auto-migrate` | dry-run でも適用しない（台帳欠落で停止する経路のテスト用） |

**v3（`review_claim_ledger`）を dry-run の適用対象に含めるのは、両 CLI が claim 表を読み書きするためです**（§6）。v1・v2 だけを当てると claim 表が存在せず、dry-run が実行不能になります。**適用した migration は実行レポートの `migrations_applied` に必ず列挙すること**（E0 §10.1 と同じ。黙って当てない）。

dry-run の適用先が `--db` に渡した本番パスと同一なら停止すること。本番書き込みは `--apply` ＋ `operation_safety/manual_apply_guards` の確認フレーズ（新設定数 `JUDGMENT_RESULT_CONFIRMATION`）が揃ったときのみ。

**本番 `data/bon_odori_master.sqlite` への migration 適用は、このPRでも行いません。** 内田さんの承認事項として据え置きます（契約 §10 / E0 §12 と同じ）。

---

## 6. claim / lease（minimal）

### 6.1 なぜ要るか

「こと」は複数セッションが並行して動くことが実際にあり、同じ対象へ別々の指示を出す事故が起きています。同じ候補を2つのセッションが同時に判断すると、**先に入った判断で `closed` になり、後の判断が `decision_id` 衝突ではなく「closed からの再判断」で落ちます**。落ちること自体は正しいのですが、LLM に読ませた時間が丸ごと無駄になります。

### 6.2 queue_state に `claimed` を足さない

契約 v1.1 §1 は「J0-read で `claimed_agent` / `claimed_user` を追加する」と書いていますが、**queue state に足すと `TRANSITIONS`（frozenset）と遷移表を変更することになり、merge 済みの契約に手が入ります。**

そこで**別表 `review_claim_ledger` を新設**します（migration v3、additive）。claim は「いま誰が見ているか」という運用上の排他であって、判断の状態でも canonical fact でもありません。契約の不変条件（canonical mutation は typed action と lineage を伴う）にも抵触しません。

```sql
CREATE TABLE IF NOT EXISTS review_claim_ledger (
  inbox_id     TEXT PRIMARY KEY,
  claimed_by   TEXT NOT NULL,     -- actor_id
  claim_kind   TEXT NOT NULL,     -- agent | user
  claimed_at   TEXT NOT NULL,
  expires_at   TEXT NOT NULL,     -- claimed_at + lease
  batch_id     TEXT
);
```

### 6.3 claim を書く先（dry-run では排他が効かないことを明記する）

claim の読み書きは、**その実行が対象としている DB に対して行います。** つまり dry-run ではコピーに書かれ、`--apply` では本番に書かれます。

**したがって dry-run 同士は互いに排他できません。** コピーは実行ごとに作られるので、他セッションの claim はコピー作成時点のスナップショットしか見えず、こちらが取った claim も本番には残らないからです。これは制限として受け入れ、**dry-run の実行レポートに `claim_scope: "dry_run_copy"` を出して、排他が効いていないことを明示します**（`--apply` では `"production"`）。

黙って効かないより、レポートに出ているほうが安全です。実際に排他が要るのは本番へ書き込む `--apply` の側で、そこでは本番の claim 表を見るため正しく効きます。

### 6.4 lease の扱い

- lease は既定30分（`--lease-minutes`）。**期限切れの claim は無効**として扱い、行を消さずに上書きする（誰がいつ握って離さなかったかを残すため）
- packet 生成時に claim を取り、取り込み完了時に release（行を削除）する
- 他者の有効な claim が付いている候補は §3.1 の条件6で除外し、レポートに `claimed_by_other` として出す
- **`--force-claim` を用意する**（停止したセッションの claim を奪う用。使ったことをレポートに記録する）

**`claim_kind` に `user` を用意しておくのは、J0-adjudication が同じ表を使えるようにするためです。** J0-read が書くのは `agent` だけです。

---

## 7. CLI と実行レポート

### 7.1 `build_judgment_packets.py`

```
--db PATH / --out-dir DIR / --batch-size N（既定20） / --max-packets N（既定100）
--actor-id ID / --lease-minutes N（既定30） / --force-claim
--domain event（既定 event。将来 song/term）
```

出力: `data/judgment_packets/batch_*.json` と `data/judgment_packets_report.json`

### 7.2 `apply_judgment_results.py`

```
--db PATH / --results PATH（複数可） / --packets-dir DIR
--actor-id ID / --apply / --confirm PHRASE / --no-auto-migrate
```

出力: `data/judgment_results_report.json` と `.md`。内訳は `accepted` / `rejected` / `held_for_user` / `deferred_for_retry` / `noop` / `rejected_result`（照合失敗で捨てた分）/ `issues`。**各件について `inbox_id`・`decision_id`・`action`・`reason_code` を1件ずつ列挙すること**（件数だけでは何が起きたか読めない）。

終了コード: high severity issue があれば非zero。`rejected_result` は medium なので非zero にしない。

**argparse の実パースを経由するテストを必ず両方の CLI に置くこと**（PR #165 の `seed` が `AttributeError` で落ちた再発防止。関数直接呼び出しのテストだけでは検出できません）。

### 7.3 issue の severity

| 事象 | severity |
|---|---|
| packet と result の照合不一致（§4.3） | medium（その result のみ捨てる） |
| LLM 申告の hold_mode と reason_code 由来の mode が不一致 | medium（同上） |
| 未知の reason_code | medium（同上） |
| `defer_for_retry` なのに `selected_retry_candidate_id` が無い／候補外 | medium（同上） |
| `decision_id` 既存で中身が違う | **high（全体停止、§5.3）** |
| 台帳が存在しない（`--apply` 時 / `--no-auto-migrate` 時） | high（全体停止） |
| dry-run の適用先が本番DBパスと同一 | high（全体停止） |
| `actor_id` が未指定 | high（起動時に停止） |
| result の `packet_id` に対応する packet ファイルが無い | high（全体停止。照合できないまま台帳へ入れない） |

---

## 8. 次段階への申し送り（J0-adjudication が最初に踏む穴）

**(1) `adjudication_batch_id` を記録する経路が無い**（§2c）。対処案は2つあり、**後者を推奨します**。

- (a) migration で `review_hold_ledger` に列を足す → hold を開く時点でバッチは存在しないので、意味的に不自然
- (b) `build_user_decision` に `adjudication_batch_id` 引数を足す（既定 None、既存呼び出しを壊さない additive 変更）→ バッチは裁定時に決まるので自然

**(2) 裁定画面を既存コンソールに相乗りさせるか**（§2f）。**わたしの既定案は「同じプロセス（`http://127.0.0.1:8751/`）に別ページとして足すが、データ経路と保存先は完全に分離する」です。** 内田さんが開く場所を1つに保てる一方、判断待ち561件の器（`data/review_inbox.json`）とは混ざりません。E0 が `status='candidate'` で意図的に分離した設計を、画面側でも守る形です。ただし内田さんの使い勝手に関わるので、実装前に確認してください。

**(3) `awaiting_user` の hold には候補集合が凍結されています**（契約 v1.1 §7）。裁定画面の対象IDピッカーは、`candidate_set_sha256` を照合して「裁定しようとしている今、候補集合が当時と変わっていないか」を検知すること。変わっていたら裁定を通さず、候補を作り直します。

---

## 9. negative test 一覧（= 受け入れ条件）

**各件について「修正を外したら落ちる」ことを確認できる形にすること。「テスト全通過」は合格の根拠にしません。**
PR本文に、どのテストがどの修正を外すと落ちるかを1行ずつ書いてください。
**壊す位置が効く場所かも確かめること**（#172 で、hash 計算より後ろに注入して空振りした失敗があります）。

packet 生成
1. `queue_state = 'closed'` の候補が packet 化されない
2. `deferred_retry` / `awaiting_user` の候補が packet 化されない
3. `superseded_by_inbox_id` が入った候補が packet 化されない
4. 期限切れ（`expires_at` < 実行時刻）の候補が packet 化されない
5. `review_queue_state_ledger` に行が無い候補が `eligible` として扱われる（E0 §8 の規則）
6. 同じ入力で2回実行すると同じ `packet_id` になる（決定的。**ランダム化すると落ちる**）
7. 候補の proposal を1文字変えると `packet_id` が変わる
8. `targets` の候補集合だけが変わっても `packet_id` は変わらず、`packet_sha256` は変わる
9. `occurrence_candidates` が空の候補では `retry_candidates` が空配列になり、`retry_unavailable_reason` が入る
10. `allowed_actions` が registry から引かれている（registry のエントリを消すと packet の内容が変わる）
11. `--max-packets` 超過分が出力されず、レポートに待機件数が出る

取り込みと照合
12. LLM が作文した `packet_id`（式に合わない値）の result が捨てられる
13. packet と `source_payload_hash` が違う result が捨てられる（`packet_stale`）
14. 判断中に候補が改訂された場合に捨てられる
15. `allowed_actions` に無い action の result が捨てられる
16. 対応する packet ファイルが無い result で **high severity 停止**（黙って入れない）

untrusted の扱い
17. result に `actor_id: "uchida"` と書いても採用されず、`--actor-id` の値が入る
18. result に `actor_type: "user"` と書いても `agent` として扱われる（**user の terminal decision を LLM 経由で作れない**）
19. result の `decided_at` が採用されず、取り込み時刻が入る
20. `--actor-id` 未指定で起動すると停止する
21. `payload` に registry 外のキー（`rationale` など）があると拒否される

hold の正規化
22. `defer_for_retry` が action `hold` へ正規化され、registry を通る
23. `hold_for_user` と申告しつつ `reason_code = packet_stale`（`deferred_retry` 側）の result が捨てられ、medium issue が出る（**黙って mode を書き換えない**）
24. `defer_for_retry` で `selected_retry_candidate_id` が機械提示の候補外なら捨てられる
25. `deferred_retry` の hold で `next_eligible_at` が `retry_candidates` の値になり、LLM が書いた日付は無視される
26. 未知の `reason_code` が捨てられる

台帳
27. accept 1件で `canonical_decision_ledger` に1行、`review_queue_state_ledger` が `closed` に upsert される
28. hold 1件で3表すべてに整合した行ができる（`review_hold_ledger.decision_id` が canonical の `decision_id` と一致）
29. `hold_packet_json` / `allowed_actions` / `candidate_ids` が **JSON 文字列として**保存される（dict / list のまま INSERT すると落ちる）
30. 途中で失敗したとき3表とも書かれない（トランザクション。**writer の途中で例外を注入して確認する**）
31. 同じ result を2回流すと2回目が no-op（行数不変）
32. 同じ `decision_id` で `action` が違う result を流すと **high severity 停止**（上書きしない）
33. J0-read 実行の前後で canonical テーブル（E0 §7 の一覧）の `COUNT(*)` がすべて不変
34. `review_inbox_items.status` が `candidate` のまま変わらない（変えると E0 の再実行が止まる）
35. `review_inbox_items` の既存 legacy 行（`status='pending'` の561件）が1行も変わらない

claim
36. 他者の有効な claim が付いた候補が packet 化されず、レポートに `claimed_by_other` で出る
37. 期限切れ claim は無効として扱われ、新しい claim で上書きされる（行は消えない）
38. 取り込み完了で claim が release される
39. `--force-claim` で奪えるが、レポートに記録が残る

安全装置
40. dry-run 既定で本番DBの checksum が実行前後で一致する
41. `--apply` を確認フレーズ無しで拒否する
42. `--apply` では migration を実行せず、台帳が無ければ停止する
43. dry-run の適用先が本番DBパスと同一なら停止する
44. `argparse` 実パース経由で両CLIの全経路が動く（属性欠落が無い）

### v1.1 で追加（おとの仕様レビュー指摘への対応）

45. **dry-run でコピーへ migration v1→v2→v3 が適用され、`review_claim_ledger` が作られる**（v3 を適用対象から外すと、claim を書く経路が「表が無い」で落ちること。**これが v1 の仕様バグそのもの**なので必ず実測する）
46. `--apply` では v3 も実行されず、claim 表が無ければ high severity で停止する
47. **`--max-packets 100` で生成される packet が最大100件・5バッチになる**（バッチ数と取り違えていれば最大2,000件になるので落ちる）
48. 上限で切られた候補は claim されず、次の実行で対象になる（claim が残っていると次回 `claimed_by_other` で除外されてしまう）
49. 実行レポートに `migrations_applied` と `claim_scope`（dry-run なら `dry_run_copy`、`--apply` なら `production`）が出る

---

## 10. やらないこと（J0-read の範囲外）

- canonical fact write（系列・開催回・会場・日付・曲のいずれも）→ E2a 以降
- user terminal decision と裁定画面 → J0-adjudication
- 一括裁定・`adjudication_batch_id` → 同上
- `requeue` の自動実行（scheduler）→ J1
- 過去の告知実績からの `next_eligible_at` 算出 → 固定窓で代替（§3.4）
- song / term ドメインの候補生成 → E0 は event のみ
- 既存 apply スクリプト・既存レビューコンソールの削除や無効化（strangler：旧経路は残す）
- **本番 `data/bon_odori_master.sqlite` への migration 適用（v1・v2・v3 すべて。内田さんの承認を別途取る）**

---

## 11. 完了条件

1. §9 の 44件がすべて通り、かつ各件が「修正を外すと落ちる」ことを確認済み
2. E0 の dry-run 出力（`data/event_inbox_candidates_dry_run.sqlite`）に対して packet 生成を実行し、生成件数・除外内訳を PR 本文に貼る
3. その packet に対する raw judgment を fixture で作り、取り込みまで通した結果を PR 本文に貼る（**実際の LLM 判断は内田さんの承認後**。テストは fixture で完結させること）
4. §9-33 の canonical テーブル行数不変を実データで実測して PR 本文に貼る
5. 仕様書（この文書）を `docs/local-judgment-j0-read-v1.md` として同梱
6. 本番 migration は適用しない（PRにはスクリプトのみ）

**着手前に、この仕様の矛盾・実装不能点・§2 の実測との食い違いを指摘してください。** 実装より先に読んで、疑問を返してもらうところから始めます。
