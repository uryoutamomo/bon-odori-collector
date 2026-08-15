# PR-E0b 仕様 v1 — レビューコンソール由来の変更提案を候補器へ付け替える

- 版: v1.0
- 書いた人: こと（Claude Code）
- 前提とする正本: `docs/local-judgment-contract-v1.md`（v1.1）、`docs/local-judgment-e0-event-inbox-v1.md`（v1.3）
- 位置: 10段階の E0 と E2a の間。**canonical fact write は1行も行わない。**

---

## 0. なぜこのPRが要るか

E0 は「イベント候補の入り口を1本にする」PRだったが、範囲を意図的に狭め、公式お知らせレポートと現地報告の
`new_event` だけを候補器へ通した。E0 仕様書 §1 は、残した2つを **E0b（E2a の直前）** で扱うと明記している。

残っていたのは次の2つで、どちらも `report_apply/apply_change_requests.py` がそのまま食える JSON を作れる。
つまり **判断台帳を1行も経由せずに master RDB の正本factへ到達できる経路**である。E2a はこの先で
「正本factを書く型」を作る段なので、その前に入口を塞いでおかないと、型付き経路と素通し経路が並走する。

1. `review_inbox_adapters/build_change_requests_from_review_inbox.py`（レビューコンソールの橋渡し）
2. `public_export_support/build_public_historical_reference_change_requests.py`（E1 の既知の不整合とされていたもの）

---

## 1. 実コードで確認した前提（origin/main `aaeecb7` で実測）

仕様の根拠なので、変わっていたら実装前に報告すること。

### (a) 橋渡しは死んだ経路ではない。レビューコンソールの生きた出口である

`review_console/data.py` は `confirm_current_date` / `promote_historical_reference` / `fill_venue` を
実際の選択肢（`option_values`）として出している。内田さんがコンソールでこれらを選ぶと、
`review_inbox_adapters/decision_stage.py` の `CHANGE_REQUEST_TYPES`（3種の写像）を通って
`data/review_console/staged/review_inbox_change_request_decisions.json` に落ち、橋渡しがそれを
`apply_change_requests` 用の JSON に翻訳する。

```
コンソールの選択 → decision_stage → staged decisions
  → build_change_requests_from_review_inbox.py → rdb_change_requests.json
  → apply_change_requests.py --apply → master RDB（★ 判断台帳を通らない）
```

`.github/workflows/` からの参照はゼロで、呼び出しは手動のみ。テスト以外に import 元は無い。

### (b) 「E1 が残した不整合」は**実在しなかった**

E1 の PR 本文とメモリは「`build_public_historical_reference_change_requests.py` が ID 未解決時に
`match_hint`-only request を出し続けるので、`scripts/run_public_projection_readiness.py` の dry-run が
`requires occurrence_id` で停止しうる」と書いていた。**これは誤りである。**

`build_payload()` は `build_request()` を呼んだ直後に `if not occurrence_id:` で `issues` へ回して
`continue` しており、**未解決のリクエストは `requests` に一度も追加されない**（`origin/main` の
`public_export_support/build_public_historical_reference_change_requests.py:259-272`）。よって
出力ファイルに `match_hint` が載ることはなく、readiness の dry-run が止まる経路は存在しない。
`match_hint` を組み立てる分岐（同 `:210-215`）は**出力に到達しない死んだコード**である。

またリポジトリ全体で `apply_change_requests.py` に `match_hint` の参照は1つも無い（E1 で除去済み）。
生きている fuzzy `match_hint` 解決は `report_apply/apply_official_notice_report.py:75,119` と
`song_processing/song_evidence_adapters.py:289` に残っているが、**これは E0b の範囲外**（宿題「match_hint ID必須化」）。

### (c) `dry_run_only` は既に効いている安全機構である

`apply_change_requests.py:160-167` の `validate_apply_allowed()` は、`dry_run_only` が付いたリクエストが
1件でもあれば `--apply` を拒否する。解除できるのは `scripts/promote_change_requests_for_review.py` だけで、
これは `dry_run_only is True` を要求し、剥がすと同時に `reviewed_by` / `reviewed_at` を刻む。
**新しい仕組みを作らずに、既存の人の関門を橋渡しへ差し込める。**

### (d) `_proposal()` のキー集合を変えると既存候補の hash が動く

E0 の `_candidate()` は `payload_hash = sha256_hex(proposal)` で改訂を判定する。`_proposal()` の戻り値に
キーを足すと、**公式お知らせ由来の既存 family がすべて「内容が変わった」と判定され、無意味な revision が
一斉に増える**。よって新しいキーは review console 由来の entry のときだけ足すこと。

---

## 2. このPRの範囲

### 入れるもの

| 対象 | やること |
|---|---|
| `build_event_inbox_candidates.py` | 新しい `report_type = "review_console_change_request"` を受理し、`event_update` レーンの候補にする |
| `build_change_requests_from_review_inbox.py` | 既定で候補レポートを書く。従来の change request も引き続き書くが、全件 `dry_run_only: true` を刻む |
| `build_public_historical_reference_change_requests.py` | 到達しない `match_hint` 分岐を削り、`occurrence_id` 必須を実装で強制する |

### 入れないもの（意図的な先送り）

- **canonical fact write**（系列・開催回・会場・日付・曲のいずれも）→ E2a / E2b
- **公開 historical reference の未解決分を候補化すること。** 現状は `skipped:unresolved_occurrence` として
  issues に積まれるだけで候補にならない。これは「fuzzy を決定器にせず候補生成器にする」という設計方針
  （E2a 以降）そのものなので、E2a で lane と finite action が決まってから扱う。E0b で先に器へ流すと、
  受け取り先の型が未定のまま候補だけが増える。
- **`apply_official_notice_report.py` / `song_evidence_adapters.py` の `match_hint` 除去** → 宿題「match_hint ID必須化」
- **本番 `data/bon_odori_master.sqlite` への migration 適用**（内田さんの承認事項。E0 から持ち越し）

---

## 3. 新しいレポート形式 `review_console_change_request`

橋渡しが書き、`build_event_inbox_candidates.py` が読む中間形式。**判断ではなく提案として渡す**のが要点で、
コンソールで内田さんが選んだ行為（`apply_value`）は `action` として運ぶが、それは「採用済みの決定」ではなく
「こういう変更が要ると人が観測した」という提案に格下げされる。理由は契約 v1.1 §0 で、user の terminal decision は
agent hold を経た候補にしか出せないため、コンソールの選択をそのまま決定として台帳へ入れられないからである。

```json
{
  "report_type": "review_console_change_request",
  "source": {
    "report_id": "<staged ファイル名の stem>",
    "raw_text": "<コンソールのメモ、無ければイベント名>",
    "source_url": "<source_item 由来>",
    "title": "<source_item 由来>"
  },
  "events": [
    {
      "action": "confirm_current_year_date | add_historical_reference | update_venue",
      "occurrence_id": "occ_...",            // 必須
      "inbox_id": "<元の review_inbox_items.inbox_id>",
      "event_name_hint": "...",
      "event_year": 2026,
      "date_start": "2026-07-19",            // confirm_current_year_date のみ
      "date_end": "2026-07-20",
      "historical_year": 2025,               // add_historical_reference のみ
      "historical_date": "2025-07-20",
      "venue": {"name": "..."},              // update_venue のみ
      "detail_addendum": "<note>",
      "source_url": "..."
    }
  ]
}
```

### 契約への写像

| 項目 | 値 | 理由 |
|---|---|---|
| `contract_domain` | `event` | |
| `contract_lane` | `event_update` | 3種とも既存の開催回を対象にする提案なので、E0 の「何を生じさせる提案か」で update |
| `status` | `candidate` | E0 と同じ。`pending` にすると判断待ち561件の器へ合流する |
| `source_id` | `review_console:<report_id>` | 公式（`official_notice:`）・現地（`firsthand:`）と区別する第3の接頭辞 |
| `explicit_occurrence_id` | entry の `occurrence_id` | 3種すべてで必須 |
| entry key の suffix | `:<action>` | 同じ開催回に対する日付確定と会場補完が同一 family に潰れるのを防ぐ |

---

## 4. 変更の詳細

### 4.1 `build_event_inbox_candidates.py`

1. `_report_entries()` に `review_console_change_request` を追加する。`source.report_id` と `events` の
   リストを要求し、欠けていれば `ValueError`（＝ `invalid_report` / severity high で1行も書かない）。
2. `source_id` の接頭辞を決めている3か所（`_candidate()`、`:create` の依存解決、jobs ループ）を
   **1つのヘルパーへ寄せる**。返す文字列は既存2種について現状と同一であること。
3. `_proposal()` に review console 用の分岐を足す。`explicit_occurrence_id` は action に依らず entry の
   `occurrence_id` を入れる（従来は `confirm_existing` のときだけ）。`historical_year` / `historical_date` の
   2キーは **review console 由来のときだけ** 足す（§1(d)）。
4. lane は `event_update` 固定。suffix は `:<action>`。
5. entry に `occurrence_id` が無ければ `invalid_report`。**候補にしてはならない**（E1 の ID 必須化を候補器側でも守る）。

### 4.2 `build_change_requests_from_review_inbox.py`

1. 既定で候補レポートを `--out-candidate-report`（既定
   `data/review_console/staged/event_inbox_report_review_console.json`）へ書く。`--no-candidate-report` で抑止できる。
2. 従来の change request 出力は残す。ただし `build_requests()` が返す全リクエストに `dry_run_only: True` を刻む。
   これにより `apply_change_requests --apply` は拒否し、`promote_change_requests_for_review.py` による
   人の昇格を必ず1回挟む。**経路は消さない（strangler）が、素通しはできなくする。**
3. 候補レポートに入れるのは `occurrence_id` が解決できた行だけ。unresolved は従来どおり unresolved 出力へ。

### 4.3 `build_public_historical_reference_change_requests.py`

1. `build_request()` の `occurrence_id` を必須引数にし、falsy なら `ValueError("occurrence_id is required")`。
   `match_hint` を組み立てる分岐を削除する。
2. `build_payload()` は未解決を先に判定して `continue` する（`build_request` を呼ぶ前へ移す）。
   出力の内容は変わらない＝**解決済みリクエストは1件も変化しない**。

---

## 5. 不変条件（docs/spec へ追加する）

### INV-RVW-011 コンソール由来の変更提案は、人の昇格なしに適用JSONへ落ちない

- **内容**: `build_change_requests_from_review_inbox.build_requests()` が返すリクエストは全件
  `dry_run_only: True` を持つ。
- **なぜ**: この経路はレビューコンソールの選択を直接 master RDB へ運べる唯一の口で、判断台帳を経由しない。
  昇格を挟むことで、適用の直前に人の確認が1回必ず入る。
- **破れたときの症状**: コンソールで押した選択が、誰の確認も経ずに正本factへ反映される。
- **守っているコード**: `review_inbox_adapters/build_change_requests_from_review_inbox.py` の `build_requests()`
- **守っているテスト**: `tests/test_e0b_bridge.py::test_every_built_request_is_dry_run_only`

### INV-PUB-007 公開historical referenceのchange requestは、対象IDなしでは作られない

- **内容**: `build_request()` は `occurrence_id` が無ければ例外を投げ、出力に `match_hint` を含めない。
- **なぜ**: E1 で反映層の fuzzy 解決を塞いだのに、生成側が hint だけのリクエストを作れると、
  名寄せが反映時点で再びあいまいになる。
- **破れたときの症状**: 対象未確定のリクエストが適用経路へ流れ、別の開催回へ実績が付く。
- **守っているコード**: `public_export_support/build_public_historical_reference_change_requests.py` の `build_request()`
- **守っているテスト**: `tests/test_e0b_bridge.py::test_historical_reference_request_requires_occurrence_id`

---

## 6. 受け入れ条件（すべてテストを書き、「修正を外したら落ちる」ことを確認する）

**新レポートと候補器**

1. `review_console_change_request` を読むと `contract_domain='event'` / `contract_lane='event_update'` /
   `status='candidate'` の行ができる
2. 3種の action すべてが候補になる
3. `occurrence_id` の無い entry があると `invalid_report`（high）になり、**1行も書かれない**
4. 同じ開催回に対する別 action は別 family になる（`entry_key_collision` にならない）
5. 同じ内容の2回目の取り込みは `noop` で revision が増えない
6. 実在しない `occurrence_id` は `occurrence_id_not_found`（medium）で候補化されない
7. `source_id` が `review_console:` で始まる
8. **公式お知らせ由来の `source_payload_hash` が E0b の前後で変わらない**（既知値との一致で固定する）
9. dry-run で canonical 10表と台帳3表の件数が変わらない

**橋渡し**

10. 既定で候補レポートが書かれ、`--no-candidate-report` で書かれない
11. `build_requests()` の全リクエストに `dry_run_only: True` が付く（INV-RVW-011）
12. その出力を `apply_change_requests --apply` に渡すと `refusing --apply` で止まる
13. `promote_change_requests_for_review` を通せば `dry_run_only` が外れ、従来どおり適用できる（経路が残っている）
14. `occurrence_id` 未解決の行は候補レポートにも change request にも入らず、unresolved に出る

**公開historical reference**

15. `build_request()` を `occurrence_id=None` で呼ぶと `ValueError`
16. 出力 payload に `match_hint` キーが存在しない
17. 解決済みリクエストの内容が従来と一致する（回帰）

---

## 7. 完了条件

- 上記17件すべてにテストがあり、各件について「修正を外すと落ちる」ことを実測している
- `python3 -m pytest tests/ -q` が origin/main と同じ緑（1551 passed / 0 failed が基準）
- `python3 scripts/spec_index.py check` が終了コード0
- `docs/spec/L1/03-review.md` と `docs/spec/L1/05-publication.md` に不変条件2件を追記し、閲覧版を再生成
- 本番 master RDB を触っていないこと（dry-run のコピーのみ）

---

署名: こと（Claude Code）
