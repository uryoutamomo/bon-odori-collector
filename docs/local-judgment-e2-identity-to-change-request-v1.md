# PR-E2 仕様 v1 — LLMは「同じか違うか」だけを答え、機械が変更要求へ変換する

- 版: v1.0
- 書いた人: こと（Claude Code）
- 前提とする正本: `docs/local-judgment-contract-v1.md`（v1.1）、`docs/local-judgment-e0-event-inbox-v1.md`（v1.1）、`docs/local-judgment-j0-read-v1.md`（v1.4）、`docs/local-judgment-j0-adjudication-v1.md`（v1.2）、`docs/local-judgment-e0b-bridge-v1.md`（v1.0）
- 位置: 10段階の7本目。**当初案の E2a（型付きアクション5つ＋planner）と E2b（二相CAS consumer）を1本に統合したもの。旧 E2a 仕様 v1.0 は破棄した。**

---

## 0. コンセプト（2026-08-15 内田さん）

> LLMの判断には誤りが含まれるが、これは人間もほぼ同等である。一方で **LLMは人間と比べて全体像を見渡すことを見落としがち**である。
> そのため、LLMの判断に置き換えてプログラムを減らす業務フローを作るなら、**LLMの一つ一つの業務はシンプルであるべき**。
> 全体を見渡すのは別のシーンかつ別のLLMのモデルで行う。

**旧 E2a 仕様はこの原則に反していた。** LLM に「新しい系列を作るのか、既存系列に足すのか」を選ばせ、重複候補を全件見たうえで新規だと宣言させ、11項目の payload を返させる設計だった。これは全部「全体像を見渡す」仕事である。

**E2 では、LLM に聞くのは同一性だけにする。** 「この候補は、いま提示した既存候補のどれと同じか。どれとも違うか」——これだけを3つの軸（開催回・系列・会場）について答えさせる。
**どの変更型を使うかは機械が決める。** LLM は変更型の名前を一度も口にしない。

あわせて、「LLMの誤りは人間と同等」という前提から、**LLM専用の重い検証機構（planner／expected delta／二相CAS）は作らない**。既存の `apply_change_requests.py` が持つ dry-run・バックアップ・監査・ロールバックを、人の操作と同じように使う。

---

## 1. 実コードで確認した前提（origin/main `cd8eb13` で実測）

変わっていたら実装前に報告すること。

### (a) 作ろうとしていたものの大部分は、既にあって既にID必須だった

旧 E2a 仕様が「新設する」と書いた5つのアクションのうち、**4つは `report_apply/apply_change_requests.py` に既に存在する**。

| 旧E2aのアクション案 | 既存の change_type | 状態 |
|---|---|---|
| `add_occurrence_to_event_series` | `create_current_year_occurrence` | `series_id` 必須・`status='active'` 検査・`occurrence_sequence != 1` を拒否・`date_start` が `event_year` 内かを検査（`:104-120`） |
| `confirm_current_year_date` | 同名 | E1 で `occurrence_id` 必須 |
| `add_historical_reference` | 同名 | 同上 |
| `update_venue` | 同名 | 同上 |
| `register_event_series_occurrence` | **無し** | ← ここだけが穴 |

**穴は1つだけ**＝「本当に新しい系列を作る」型付き経路。いまは `apply_official_notice_report.py` の `register_new` にしかなく、その実体 `ensure_series_and_occurrence`（`report_apply/event_report_helpers.py:160`）は
series_key の完全一致があれば黙って既存を再利用し（`:186-189`）、同 series 同年の occurrence があれば
`ON CONFLICT ... DO UPDATE` で venue/date を上書きする（`:228-236`）。

### (b) 会場は名前でしか渡せない

`apply_update_venue`（`apply_change_requests.py:488`）は `venue["name"]` を `ensure_venue` に渡す。
`ensure_venue`（`event_report_helpers.py:110`）は `normalized_name` ＋ `COALESCE(address,'')` の完全一致だけを再利用し、
無ければ即 INSERT する。**`venue_id` で「この会場だ」と指定する道が無い。** 8/7 の鹿骨中学校の二重化はこれ。

### (c) 候補検索は系列IDも会場IDも返している

`find_occurrence_candidates`（同 `:73`）の戻り行には `occurrence_id` / `series_id` / `event_year` / `series_name` /
`venue_id` / `venue_name` が入り、`lifecycle_status='merged'` は除外済み。
つまり**LLMへ提示する候補の中に、開催回・系列・会場の3つの識別子がそろっている**。

### (d) パケットの `allowed_actions` は既に registry 駆動

`build_judgment_packets.allowed()`（`:17`）は `ACTION_REGISTRY` から引いている。
**registry に行為を足すと、その瞬間からLLMへ「選んでよい」と告げられる。** E2 では行為を足さないので、ここは動かない。

### (e) `awaiting_user` hold の候補集合と一括裁定の関係

`apply_judgment_results.py:65` は awaiting_user hold のとき `candidate_ids` に候補の `occurrence_id` を凍結する。
一方 `review_console/data.py:789` の一括裁定は、**候補集合を持つ hold を一括から除外する**（1位候補へ暗黙に寄せるのを防ぐため）。
また `adjudication_target_required`（同 `:751`）は `action == "accept" and bool(candidate_ids)` なので、
**候補集合が空なら対象IDは不要になり、一括裁定もできる。**

---

## 2. LLM に渡すもの・返させるもの

### 渡すもの（機械が作る。E0 の候補と既存の検索結果）

いまの `build_judgment_packets.make_packet` が作るパケットをそのまま使う。中身は E0 の `proposal`（抽出済みのイベント名・年・日付・会場名）と `targets`（開催回候補8件まで・会場候補8件まで）と証拠。**新しいパケット形式は作らない。**

### 返させるもの（3つの同一性 + 理由）

```json
{"occurrence_match": "occ_xxx" | "none",
 "series_match":     "ser_xxx" | "none",
 "venue_match":      "ven_xxx" | "none",
 "reason_detail":    "..."}
```

**LLM が書くのはこれだけ。** イベント名も日付も会場名も書かない（E0 の `proposal` に既にあるので、機械がそこから取る）。
決めきれないときは従来どおり `hold_for_user` / `defer_for_retry` と理由コードを返す。

**行為（action）は `accept` / `reject` / `hold_for_user` / `defer_for_retry` のまま**で、registry に新しい行為を足さない。
したがって `TRANSITIONS`・`build_agent_terminal_decision`・`build_user_decision`・`build_hold_ledger_entry` には**一切触らない**。

### 機械が検査すること（LLMの負担にしない）

- `occurrence_match` が候補集合の中にあるか（無いIDは拒否）
- `occurrence_match` が実在するなら、`series_match` はその開催回の `series_id` と一致するか（不一致は拒否）
- `venue_match` が候補集合の中にあるか
- 「どれとも違う」は文字列 `"none"` のみ。空文字や省略は拒否

---

## 3. `"none"` の扱い（人の裁定を挟む）

**方針（2026-08-15 内田さん承認）＝ none のときは人の確認を挟む。**

ただし「どの none か」で危険度が違うので、次のように絞る。

| 状況 | 危険度 | 扱い |
|---|---|---|
| `series_match = "none"`（新しい系列ができる） | **高**。系列の重複は統合（merge）の仕組みがまだ無く、回復できない | `awaiting_user` hold |
| `venue_match = "none"`（新しい会場ができる） | **高**。実際に二重化事故が起きている（8/7 鹿骨中学校）。いま裏取りキューで人が見ている領域 | `awaiting_user` hold |
| `occurrence_match = "none"` だが `series_match` は既存 | 低。既存系列へ今年の開催回を足すだけ。間違えても `occurrence_id` で後から直せる | **そのまま進める** |

**hold への落とし方は機械が行う。** LLM には「none なら hold を返せ」と指示しない——LLM は素直に
`accept` ＋ 3つの同一性を返し、`apply_judgment_results.py` の正規化段（既に `hold_for_user` → `hold` の
書き換えをしている場所）で、ポリシーに従って hold へ落とす。

**理由**＝「人を挟むかどうか」は判断の内容ではなく運用の都合だからである。merge が実装されたらポリシーだけ外せばよく、
LLMへの指示文を書き換えずに済む。LLMの生の判断は payload に残るので、台帳から「LLMは新規と判断し、ポリシーにより人へ回した」と辿れる。

**新設する reason code は2つ**（`REASON_CODE_HOLD_MODE` へデータとして追加。どちらも `awaiting_user`）。

- `new_series_requires_confirmation` — 新しい系列ができるので確認が要る
- `new_venue_requires_confirmation` — 新しい会場ができるので確認が要る

両方が none なら series 側を採る（hold 1件に reason code 1つ）。

**この2つの hold では `candidate_ids` を凍結しない（空にする）。** 理由は3つある。
①対象を選ぶための hold ではない（選ぶべき対象が無いから hold している）。
②空にすれば `adjudication_target_required` が偽になり、内田さんは対象IDを要求されない。
③空にすれば**一括裁定ができる**ので、「新規ですね、はい」を1件ずつ押さずに済む。
LLM が何を見て none と言ったかは `data/judgment_packets/batch_*.json` に残るので追跡できる。

**副次的な効果**＝`review_console/data.py` と `apply_user_adjudications.py` の対象ID判定は**変更不要**になる。
どちらも `candidate_ids` の有無で決めているためである。

**代わりに失うもの**＝裁定画面で内田さんが「実はこれと同じだった」と気づいても、その場で対象IDを指定できない。
その場合は**却下**して、正しい判断をやり直す運用にする。

---

## 4. 機械の変換規則

台帳の accept された判断（`canonical_decision_ledger`）と、その `inbox_id` の候補（`review_inbox_items.payload_json` の `proposal`）から、変更要求を組み立てる。

| `occurrence_match` | `series_match` | 生成する change_type | 対象 |
|---|---|---|---|
| `occ_x` | （その開催回の系列） | 元の提案の意図で決まる（下記） | `occurrence_id = occ_x` |
| `none` | `ser_y` | `create_current_year_occurrence` | `series_id = ser_y` |
| `none` | `none` | **`create_event_series`（新設）** | なし |

`occurrence_match` が既存のときの change_type は、E0 の `proposal.legacy_action` から決める。

- `confirm_existing` / コンソール由来の `confirm_current_year_date` → `confirm_current_year_date`
- コンソール由来の `add_historical_reference` → `add_historical_reference`
- コンソール由来の `update_venue` → `update_venue`
- `register_new`（新規のつもりだったが既存だった）→ `confirm_current_year_date`

会場は、`venue_match` が既存IDならその `venue_id` を渡す。`none` なら `proposal.venue` の名前で新規作成を明示する。

変換の出力は既存の `rdb_change_requests` 形式（`data/change_requests/from_judgment_<日付>.json`）。
**`dry_run_only` は付けない。** 判断台帳を経ており、none の場合は既に内田さんの裁定を通っているためである
（コンソール直通の E0b 経路とはここが違う）。適用は従来どおり `apply_change_requests.py` の確認フレーズ付き手動実行。

---

## 5. 触る箇所（6つ。契約の検証コードには触らない）

1. **`REASON_CODE_HOLD_MODE`** に reason code 2つを追加（データ1行×2）
2. **`ACTION_REGISTRY`** の **event レーンの `accept` だけ** に payload 3項目（`occurrence_match` / `series_match` / `venue_match`）を許す。
   いまの辞書内包は全レーン共通の `COMMON_PAYLOAD_FIELDS` を配っているので、レーン別に持てる形へ変える。
   **他レーン（song / term）の payload 集合が現状と一致することをテストで固定する**
3. **`apply_judgment_results.py`** — ①3つの同一性の機械検査 ②none のポリシー適用（accept → hold への落とし込み）
   ③新規確認 hold では `candidate_ids` を空にする
4. **`apply_change_requests.py`** に `create_event_series` を追加。**INSERT のみ**で、既存行の UPDATE を一切含まない。
   `series_key` が既にあれば `series_key_already_exists` で止める（その場合は `create_current_year_occurrence` を使うべき）。
   `ensure_series_and_occurrence` は呼ばない
5. **`apply_change_requests.py`** の会場を `venue_id` でも渡せるようにする。`venue_id` があれば `ensure_venue` を経由せず、
   実在確認だけして使う。既存の名前渡しは残す（strangler）
6. **変換層**（新規・`review_inbox_adapters/build_change_requests_from_judgment.py` あたり）

---

## 6. 不変条件（docs/spec の既存の採番へ続ける）

- **INV-RVW-012（LLMは同一性だけを答え、事実を書かない）**: event レーンの `accept` / `hold` の payload に許すのは
  3つの同一性と共通項目だけ。イベント名・日付・会場名・IDの新規値・状態値が現れたら拒否する。
  song / term レーンの payload 集合は変えない。
  **破れたときの症状**＝候補と判断で名前や日付が食い違い、どちらが正しいか分からなくなる。
- **INV-RVW-013（新しい系列・会場は人の確認を経る）**: `series_match` または `venue_match` が `"none"` の判断は
  `awaiting_user` hold になり、裁定を経ないと変更要求へ変換されない。開催回だけ `"none"` なら止めない。
  **破れたときの症状**＝重複した系列や会場が、誰も見ないまま増える（統合の仕組みがまだ無い）。
- **INV-RVW-014（同一性は候補集合の中からしか選べない）**: 3つの答えは提示した候補に含まれるIDか `"none"` に限り、
  `occurrence_match` を指したなら `series_match` はその開催回の系列と一致する。新規確認の hold では候補集合を凍結しない。
  **破れたときの症状**＝候補の外のIDを指して無関係の開催回が書き換わる。裁定画面で選べない対象を要求される。
- **INV-MST-008（新しい系列の作成は追加だけ）**: `create_event_series` は既存行を更新せず、`series_key` の
  完全一致があれば止める。`series_id` の同梱を受け付けない。会場は `venue_id` で指せ、IDが渡されたときは
  `ensure_venue()` を経由しない。
  **破れたときの症状**＝「新規追加」が既存の開催回を黙って上書きする（現行 `register_new` の挙動）。同じ会場が2行に増える。

---

## 7. 受け入れ条件（すべてテストを書き、「修正を外したら落ちる」ことを実測する）

**LLMの返答の検査**

1. 3つの同一性を返す `accept` が受理される
2. 候補集合の外の `occurrence_match` は拒否される（INV-RVW-014）
3. `occurrence_match` と `series_match` が食い違うと拒否される
4. `"none"` 以外の空表現（空文字・null・キー省略）は拒否される
5. payload にイベント名・日付・会場名・`series_id` の新規値・`status` があると拒否される（INV-RVW-012）
6. **song / term レーンの `allowed_payload_fields` が現状と完全一致する**（他ドメインを巻き込まない証明）
7. `TRANSITIONS` が E2 の前後で同一（契約の検証コードに触っていない証明）

**none のポリシー**

8. `series_match="none"` は `awaiting_user` hold になり、reason code が `new_series_requires_confirmation`
9. `venue_match="none"` は `new_venue_requires_confirmation`
10. 両方 none なら series 側の reason code になる
11. `occurrence_match="none"` でも `series_match` が既存なら hold にならず accept のまま進む
12. 新規確認 hold の `candidate_ids` が空である
13. その結果、裁定画面で対象IDを要求されない（`adjudication_target_required` が偽）
14. その結果、同じ reason code の新規確認 hold を**一括裁定できる**
15. LLM の生の判断（3つの同一性）が hold の payload に残る

**変換**

16. `occurrence_match` が既存 → 元の提案の意図に応じた change_type になる（4通り）
17. `occurrence_match="none"` かつ `series_match` 既存 → `create_current_year_occurrence`（`series_id` 付き）
18. 両方 none かつ内田さんの裁定済み → `create_event_series`
19. **裁定を経ていない none は変換されない**（INV-RVW-013）
20. `venue_match` が既存 → `venue_id` で渡り、`ensure_venue` を経由しない
21. 変換の出力に `dry_run_only` が付かない
22. 同じ判断を2回変換しても同じ内容（決定的）・二重に出さない

**`create_event_series`**

23. 系列・開催回・日付が新規 INSERT され、UPDATE が1件も無い（INV-MST-008）
24. `series_key` の完全一致があると `series_key_already_exists` で止まる
25. `event_year` と `date_start` の年が違うと止まる
26. `ensure_series_and_occurrence` を呼んでいない（構造検査）

**全体**

27. 実 argv 経由で走る（`--help` だけのテストにしない）
28. 変換層は master RDB を読み取りにしか使わない
29. 本番 master RDB の checksum が変換の前後で不変

---

## 8. やらないこと

- **planner / expected delta / 二相CAS consumer**（旧 E2a・E2b 案）。既存 `apply_change_requests.py` の
  dry-run・バックアップ・監査・ロールバックを使う
- **registry への新しい行為の追加**。したがって `TRANSITIONS` の一般化も不要
- **`merge_existing_series` / 改名 / 削除**。後段の保護コマンドとして別途
- **曲（`add_song_evidence`）**。`songs.status` の語彙二重（候補274／有効77／active 29／無効19）の決着が先。別段階で扱う
- **旧 apply 経路の遮断**（strangler なので残す）
- **同年に複数回開催する構造**（`occurrence_sequence` は 1 固定）
- **本番 `data/bon_odori_master.sqlite` への migration 適用**（内田さんの承認事項）

---

## 9. 完了条件

- 受け入れ条件29件すべてにテストがあり、各件について「修正を外すと落ちる」ことを実測している
- `python3 -m pytest tests/ -q` が origin/main と同じ緑（**1573 passed / 0 failed** が基準）
- `python3 scripts/spec_index.py check` が終了コード0
- `docs/spec/` に不変条件4件を追記し、`index.json` を再生成
- 本番 master RDB を触っていないこと（checksum 不変を実測）
- `docs/local-judgment-e2-identity-to-change-request-v1.md` として同じ内容をリポジトリへ同梱

---

## 10. これが終わると何ができるか

**内田さんの目に見える変化が、ここで初めて起きる。**

E0 が候補を作り、LLM が「既存のどれと同じか」を判断し、新しい系列や会場になるものだけ内田さんが裁定し、
変換層が変更要求を組み立て、既存の適用経路が master RDB へ書く。**イベントが実際に増える。**

そのうえで次は、シンプル化の本体である**意味判定層の退場**（`collect.py` の意味判定ほか、解釈・判定 18,595行）に移る。

---

署名: こと（Claude Code）
