# local judgment contract v1（PR-J0-contract の正本仕様）

決定者: こと（Claude Code） / 2026-08-10（v1.1 追記 同日）
根拠: 内田さんの決定3件（2026-08-10）と、おと・こと間で合意した設計（スレッド `20260810-local-judgment-unification`）

この文書が J0-contract の**正本**です。過去のメッセージ本文と食い違う場合はこちらが優先します。
実装後は `docs/local-judgment-contract-v1.md` としてPRに含め、コードと一緒にversion管理してください。

---

## 0. 不変条件（これを壊す実装は不合格）

> canonical な正本事実の変更は、すべて **typed finite action** と **decision lineage** を伴う。
> 判断者は agent（こと／おと）either user（内田さん）。
> **全候補はまず agent の判断を通る。agent が hold にしたものだけ、user が同じ contract で terminal decision を出せる。**

ここから導かれる、実装が満たすべき2点。

1. **agent は terminal decision（accept / reject）を出せなければならない。** agent が hold しか出せない契約は、全件が内田さんの裁定待ちに積み上がることを意味し、この設計の目的そのものに反する。
2. **user は agent hold を経ていない候補に手を出せない。** user の経路は全 pending への並行入口ではなく、`awaiting_user` 専用の後段レーン。

---

## 1. queue state

```
eligible | deferred_retry | awaiting_user | closed
```

`claimed` は **J0-contract には入れない。** claim/lease は J0-read/adjudication で minimal 版を足す。これは意図的な先送りで、抜け漏れではない。J0-read で `claimed_agent` / `claimed_user` を追加したとき、既存の遷移表を壊さずに差し込めるようにしておくこと（= 状態の集合を定数で持ち、遷移表をデータとして持つ）。

### 1.1 publication scope router（実装前の契約）

23区外であることは候補そのものを棄却する理由ではない。scope router は候補の真偽を裁定せず、
**現在の公開方針で処理対象かだけ**を次の属性として記録する。

| field | value / rule |
|---|---|
| `publication_scope` | `current_scope` / `outside_current_scope` / `undetermined` |
| `decision` | `route_within_scope` / `hold_outside_scope` / `hold_for_scope_resolution` |
| `scope_policy_version` | 判定に使った方針の不変な版。必須 |
| `eligible_regions` | その版で公開対象だった地域の正規化済み集合 |
| `evaluated_at` | scope 判定時刻。timezone 必須 |
| `first_seen_at` | 元candidateを最初に観測した時刻。再評価でも維持 |
| `source_payload_hash` | 元candidateの入力bytesに対するSHA-256。再評価でも同じ入力なら維持 |

`outside_current_scope` の `decision` は **`hold_outside_scope` のみ**で、`accept` / `reject` や
`closed` へ遷移させてはならない。このholdは `deferred_retry`（時刻による再試行）とも
`awaiting_user`（人の裁定待ち）とも別の **reopenable scope hold** である。

- candidateの `status` とpayloadを変えない。新しいcandidate revisionも作らない。
- venue / series / occurrence / song などのcanonical factを変更しない。
- `scope_policy_version` または `eligible_regions` が変わったとき、同じcandidate IDを再評価する。
- 再評価で対象内になった場合だけ、systemがholdを解放して通常のagent判断へ戻す。
- 旧scope判定はlineageとして残す。新判定で上書きして履歴を失わない。

これにより、23区外を現在は公開しない方針と、将来の全国化で同じ観測を再利用することを両立する。
J0-readが正本factを変えないこと（INV-RVW-005）とcandidateを消費しないこと（INV-RVW-007）は、
scope routerにもそのまま適用する。

`publication_scope_needed` は、地域が判別不能で本当に方針判断が要る場合の `awaiting_user` として残す。
明確に `outside_current_scope` と判定できた候補を、人へ送るために使ってはならない。

## 2. 遷移表（これが全部。ここに無い遷移は validator が必ず拒否する）

| # | before → after | actor_type | action | 必須のもの |
|---|---|---|---|---|
| T1 | `eligible` → `closed` | `agent` | `accept` / `reject` | `decided_at`。hold系フィールドは全て null |
| T2 | `eligible` → `deferred_retry` | `agent` | `hold` | `reason_code`（mode=deferred_retry）、凍結済み `hold_packet`、`next_eligible_at` |
| T3 | `eligible` → `awaiting_user` | `agent` | `hold` | `reason_code`（mode=awaiting_user）、`next_eligible_at = null`、`hold_packet = null` |
| T4 | `deferred_retry` → `eligible` | `system` | `requeue` | `released_at >= next_eligible_at` の証拠、対象 `hold_id` |
| T5 | `awaiting_user` → `closed` | `user` | `accept` / `reject` | `open_hold_id`、`prior_agent_attempt_id` |

**明示的に禁止（それぞれ negative test を持つこと）**

- `eligible` → user の terminal decision（agent hold を経ていない）
- `deferred_retry` → user の terminal decision
- `closed` からの再判断（agent / user のどちらからも）
- `awaiting_user` → `eligible`（人待ちの候補が勝手に agent の列へ戻る）
- open hold が無い、または `status != "open"` の console decision
- `system` レーンからの `accept` / `reject` / `hold`
- `agent` / `user` レーンからの `requeue`

### T4 に `system` を足す理由

時刻到達による復帰は「判断」ではないが、**状態は変わる**。これを台帳に残さないと「誰も判断していないのに候補が動いた」記録が消え、あとから追えなくなる。そこで actor を3種類にする。

```
actor_type   : agent | user | system
decision_channel: llm | console | scheduler
```

対応は固定で、`(agent, llm)` `(user, console)` `(system, scheduler)` の3組だけを許可する。`system` レーンができる action は `requeue` **のみ**。逆に `requeue` は `system` にしかできない。

復帰を実際に走らせる scheduler の実装は J1 で構わない。**J0 の担当は「その遷移が正当かどうかを判定できること」。**

### validator と builder の責任分界（v1.1 で追記）

`requeue` の検査は2か所に分かれる。どちらが持つかを明示しておく。

- **validator が単独で持つもの**（packet だけで判定できるので、builder を通らない手作り packet も弾けなければならない）
  - `payload.released_at >= payload.next_eligible_at`
- **builder が持つもの**（open hold を参照しないと判定できない）
  - `payload.hold_id` が実在し、`status = "open"` かつ `hold_mode = "deferred_retry"` であること
  - `payload.next_eligible_at` が、その hold の `next_eligible_at` と一致すること

**「packet だけで判定できる検査は必ず validator にも置く」** を原則とする。validator が最後の関門である以上、builder にしか無い検査は迂回できる。

---

## 3. canonical decision の必須フィールド

すべての canonical decision が持つ。null 可のものは「null という値を持つ」ことを要求する（キー自体の欠落は拒否）。

### 識別と由来
- `schema_version` : int、現在 `1`
- `decision_id` : §4 の式で機械生成
- `packet_id` : str
- `packet_sha256` : str（凍結 packet 全体の SHA-256）
- `inbox_id` : str
- `domain` : `event | song | term`
- `lane` : `event_create | event_update | song | term`
- `source_id` : str
- `source_key` : str
- `source_payload_hash` : str（`review_inbox_items` に既にある同名列と同じ値）

### 判断そのもの
- `action` : registry に載っている値のみ
- `queue_state_before` / `queue_state_after`
- `reason_code` : hold のとき必須、それ以外 null
- `hold_mode` : hold のとき必須（reason_code から導出）、それ以外 null
- `next_eligible_at` : `deferred_retry` のとき必須、それ以外 null
- `hold_packet` : `deferred_retry` のとき必須、それ以外 null
- `payload` : dict。**dict でなければ `{}` に直さず拒否する**

### lineage（ローカルの entrypoint が stamp する。入力JSONの自己申告は採用しない）
- `actor_type` / `actor_id` / `decision_channel`
- `decided_at` : ISO-8601、timezone 必須
- `prior_agent_attempt_id` : user の terminal decision で必須、それ以外 null
- `open_hold_id` : user の terminal decision で必須、それ以外 null
- `adjudication_batch_id` : null 可

`domain` `source_payload_hash` `decided_at` は `review_inbox_items` に既に存在する列。**新しい台帳が正本で既存が写像**という関係にする以上、正本のほうが情報が少ない状態は許さない。

---

## 4. decision_id の決め方

```
decision_id = "decision:" + sha256_hex(canonical_json({
    "schema_version": …, "domain": …, "inbox_id": …,
    "packet_id": …, "actor_type": …, "action": …,
    "source_payload_hash": …,
}))
```

`canonical_json` は キーsort・区切り文字固定・`ensure_ascii=False` の決定的な直列化。

満たすべき性質は2つ。**同じ判断のやり直しは同じ ID になる**（冪等な no-op として扱える）。**agent の hold と user の terminal decision は別 ID になる**（`actor_type` と `action` が違うため、同じ `packet_id` を使い回しても衝突しない）。

`decision:{packet_id}` のような packet_id だけの式は禁止。console が hold の packet_id をそのまま使うのは異常系ではなく通常経路で、実測で `UNIQUE constraint failed` を確認済み。

---

## 5. action registry

キーは **`(domain, lane, action)` の3つ組**。ドメイン共通の平坦な辞書にしない。

各エントリが持つもの。

- `label_ja` : 表示用。**保存値は必ず英語。日本語ラベルは durable protocol の一部にしない**
- `terminal` : bool
- `allowed_actor_types` : set
- `required_target_type` : `series | occurrence | venue | song | term | null`
- `allowed_payload_fields` : set。payload のキーがこの集合を超えたら拒否

### J0 で登録するもの（lifecycle actions のみ）

| action | terminal | allowed_actor_types | label_ja |
|---|---|---|---|
| `accept` | true | agent, user | 採用 |
| `reject` | true | agent, user | 却下 |
| `hold` | false | agent | 保留 |
| `requeue` | false | system | 再投入 |

これを `event/event_create`・`event/event_update`・`song/song`・`term/term` の4レーンすべてに登録する。

**ドメイン固有の finite action（`register_event_series_occurrence`、`add_song_evidence`、`add_term_alias` など）は J0 では登録しない。** それぞれ E2a / T2 が同じ registry へ追加する。J0 の仕事は「後から追加できる形を先に決める」ことなので、registry は**データとして持ち、追加時にコードを書き換えなくてよい形**にすること。

**registry に載っているのに到達できない action があってはならない。** これを固定するテストを置くこと（registry の全エントリについて、その actor_type から実際に canonical decision を作れる）。

---

## 6. reason code と hold_mode の固定対応表

LLM に mode を選ばせない。reason_code から一意に決まる。未知の code、対応表と違う mode、必要フィールドの欠落は validator が拒否する。

| reason_code | hold_mode | 意味 |
|---|---|---|
| `awaiting_official_announcement` | `deferred_retry` | 公式発表がまだ存在しない。証拠不足とは別物 |
| `source_temporarily_unavailable` | `deferred_retry` | 情報源が一時的に読めない |
| `packet_stale` | `deferred_retry` | 候補集合か対象の状態が変わった。作り直して再判断 |
| `insufficient_announcement_history` | `awaiting_user` | 再試行日を算出する履歴が足りない。**根拠のない日付を作らず人へ回す** |
| `requires_policy_judgment` | `awaiting_user` | 方針判断が要る |
| `ambiguous_event_series` | `awaiting_user` | どのシリーズか意味的に決まらない |
| `ambiguous_occurrence` | `awaiting_user` | どの開催回か決まらない |
| `ambiguous_venue` | `awaiting_user` | どの会場か決まらない |
| `missing_target_id` | `awaiting_user` | 既存対象のIDが解決できない |
| `conflicting_sources` | `awaiting_user` | 情報源が食い違う |
| `insufficient_evidence` | `awaiting_user` | 証拠が足りない（存在はする） |
| `distinct_event_uncertain` | `awaiting_user` | 別イベントか同一かが決まらない |
| `publication_scope_needed` | `awaiting_user` | 公開してよい範囲の判断が要る |

LLM が返す raw action も単一の `hold` ではなく `defer_for_retry` / `hold_for_user` に分けてよいが、**その選択は検証時に reason_code 由来の mode と一致しなければ拒否**する（LLM の申告を採用しない）。

---

## 7. deferred_retry の hold packet

`next_eligible_at` は機械が算出し、**LLM は提示された候補から選ぶだけ**。範囲外は拒否。

凍結する内容。

- `candidate_id`
- `next_eligible_at`, `window_start`, `window_end`（`window_start <= next_eligible_at <= window_end`）
- `occurrence_ids`（1件以上）, `evidence_ids`（1件以上）
- `retrieved_at`
- `calculation_version`
- `input_hash`

履歴が足りず候補を作れないときは、**推測の日付を作らない。** `insufficient_announcement_history` で `awaiting_user` へ送る。

### awaiting_user の候補集合も凍結する（v1.1 で追記）

これは v1 で書き漏らしていた。`deferred_retry` の再試行日候補だけでなく、**`awaiting_user` の hold が内田さんへ提示する候補集合（曖昧なシリーズ・開催回・会場の一覧）も凍結する。**

- `candidate_ids` : 提示した候補の **全件**。選ばれた1件だけではない
- `candidate_set_sha256` : その全件集合に対する SHA-256

理由は、J0-read で作る対象IDの picker が「裁定しようとしている今、候補集合が当時と変わっていないか」を照合できるようにするため。選択済みの1件しか残っていないと、新しい候補が現れたことを検知できず、古い前提のまま裁定が通る。提示すべき候補が無い hold（方針判断だけを問うものなど）は空配列と null で構わない。

---

## 8. hold ledger の列

```
hold_id                  TEXT PRIMARY KEY
decision_id              TEXT NOT NULL UNIQUE   -- hold を開いた decision
inbox_id                 TEXT NOT NULL
domain                   TEXT NOT NULL
lane                     TEXT NOT NULL
hold_mode                TEXT NOT NULL          -- deferred_retry | awaiting_user
reason_code              TEXT NOT NULL
reason_detail            TEXT
required_resolution_type TEXT
allowed_actions          TEXT NOT NULL          -- JSON配列。sort済み
candidate_ids            TEXT                   -- JSON配列
candidate_set_sha256     TEXT
prior_agent_attempt_id   TEXT NOT NULL
grouping_fingerprint     TEXT NOT NULL
status                   TEXT NOT NULL          -- open | resolved | expired
queue_state              TEXT NOT NULL
next_eligible_at         TEXT                   -- deferred_retry のみ
hold_packet_json         TEXT
opened_at                TEXT NOT NULL
expires_at               TEXT
closed_at                TEXT
resolved_by_decision_id  TEXT
```

### grouping_fingerprint

一括裁定の単位。**reason_code だけで group 化しない。** 同じ曖昧さでも許可 action や必要な対象の型が違えば、まとめて裁いてはいけない。

```
grouping_fingerprint = sha256_hex(canonical_json({
    "domain": …, "lane": …, "reason_code": …,
    "registry_version": …,
    "allowed_actions": sorted([...]),
    "required_target_type": …,
    "evidence_class": …,
}))
```

一括操作が画面上1回でも、builder は item ごとの canonical decision へ展開し、各 item の対象ID・source hash・候補集合を個別に検証する。「1位候補へまとめて」のような暗黙の対象選択は作らない。

---

## 9. validator が拒否すべきケース（= negative test の一覧）

**修正を外したら落ちること**を各件について確認できる形にすること。「テスト全通過」は合格の根拠にしない。

遷移
1. `eligible` から user の terminal decision
2. `deferred_retry` から user の terminal decision
3. `closed` からの再判断（agent / user 両方）
4. `awaiting_user` → `eligible`
5. open hold が無い console decision
6. `status != "open"` の hold を参照した console decision
7. 別 inbox_id の hold を参照した console decision
8. `system` レーンからの accept / reject / hold
9. agent / user レーンからの requeue
10. `released_at < next_eligible_at` の requeue

hold
11. 未知の reason_code
12. reason_code と hold_mode の不一致
13. `awaiting_user` なのに `next_eligible_at` が入っている
14. `deferred_retry` なのに `next_eligible_at` か `hold_packet` が欠けている
15. 候補 window の外の `next_eligible_at`
16. 機械が提示していない candidate_id の選択
17. `occurrence_ids` か `evidence_ids` が空の retry packet

lineage と identity
18. 入力JSONの `actor_type` / `actor_id` 自己申告が採用されない（`actor_id: uchida` と書いても無視される）
19. `decided_at` の欠落、timezone 無しの `decided_at`
20. user の terminal decision で `prior_agent_attempt_id` か `open_hold_id` が欠落
21. **同一 packet_id の agent hold と user final が別 decision_id になり、台帳へ両方INSERTできる**
22. 同一内容の再判断が同じ decision_id になる（冪等）

registry と payload
23. registry に無い `(domain, lane, action)` の組み合わせ
24. `allowed_payload_fields` を超えるキーを持つ payload
25. dict でない payload（`{}` に直さず拒否）
26. registry の全エントリが、その `allowed_actor_types` から実際に到達できる

migration
27. 冪等（2回流して差分なし）
28. 既存 `review_inbox_items` の行と列が変わらない

v1.1 で追加
29. **builder を通さず組んだ `requeue` packet で `released_at < payload.next_eligible_at` のものを、`validate_canonical_decision` **単独で** 拒否する**（builder 側の N10 とは別に、validator だけを呼んで確認すること）
30. `awaiting_user` の hold ledger に、提示した候補の全件と `candidate_set_sha256` が凍結される（1件だけ・null にならない）

---

## 10. やらないこと（J0-contract の範囲外）

- domain write（event / song / term のいずれも）
- claim / lease（J0-read/adjudication）
- scheduler の実装（J1）
- console UI（J0-read/adjudication）
- ドメイン固有 finite action の登録（E2a / T2）
- legacy 日本語 option_values の整理（別PR）
- **本番 `data/bon_odori_master.sqlite` への migration 適用**（別途、内田さんの承認を取る）
