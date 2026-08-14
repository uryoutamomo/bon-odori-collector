# PR-J0-adjudication 仕様：user 裁定レーン v1（正本）

決定者: こと（Claude Code） / 2026-08-14
- **v1.1**（同日）：おとの仕様レビュー指摘2件を反映。§4.2＝台帳へ反映する API を置かない（**v1 は §0 と自己矛盾していた**）、§5.2＝`adjudications.json` に `status`（pending/applied/invalidated）と失敗理由を追加、§9-7a/7b・13a/13b/13c
- **v1.2**（同日、実装とテストの中で判明した6点を反映）：**§7.2 の対象要否の判定が誤りだった（ことの仕様バグ4件目）**、§0 に claim の例外、§3.1 の期限切れ表示を §9-3 と整合、§5.3 に検査6と失敗理由コード3つ、§5.4 に dry-run の migration（実装から抜けていた）、ショートカットを `j` から `b` へ。§9 は45条件・テスト46本
前提:
- `docs/local-judgment-contract-v1.md`（v1.1、SHA-256 `3b47f5e4e2618c209c1d8b0fb42cbaa1f5687b9a3f167719bd2939ceb4756a05`）
- `docs/local-judgment-j0-read-v1.md`（v1.4、SHA-256 `8475c53828da1920f71e683168d0168159e3d82a2a1997ec72b881ca06115b98`）
- `docs/local-judgment-e0-event-inbox-v1.md`（v1.3）
段階: 10本立ての5本目（E1・J0-contract・E0・J0-read は merge 済み）

この文書が PR-J0-adjudication の**正本**です。過去のメッセージ本文・artifact と食い違う場合はこちらが優先します。
実装時は `docs/local-judgment-j0-adjudication-v1.md` としてPRに含め、コードと一緒に version 管理してください。

**この仕様は origin/main の実コード（2026-08-14 時点 `8e7de2a`）を読んで書いています。** 食い違いを見つけたら実装前に指摘してください（黙って仕様に寄せない）。

---

## 0. 不変条件（これを壊す実装は不合格）

> **内田さんが裁けるのは、agent が `awaiting_user` の hold を開いた候補だけである。**
> user の経路は全 pending への並行入口ではなく、**agent hold 専用の後段レーン**（契約 v1.1 §0）。

> **画面のボタン操作は master RDB の判断台帳を変更しない。**
> 裁定はいったん console 側のファイルへ記録し、明示的な反映操作を経て台帳へ入る。

**v1.2 の訂正：唯一の例外は claim（作業中の札）です。** §8 の claim は `review_claim_ledger`（master RDB 内）へリース行を書きます。v1 は「1バイトも変えない」と書いていましたが、それでは §8 と両立しません。**正しくは「判断の3台帳（canonical / queue / hold）は画面操作では1行も動かない。動くのは claim のリース行だけ」** です。claim は判断ではなく、二重作業を防ぐための札なので、この線引きにしました（§9-7 と §9-7c の2本で固定します）。

> **裁定時に候補集合が当時と変わっていたら、その裁定を通さない。**
> hold に凍結された `candidate_set_sha256` と照合する（契約 v1.1 §7）。

導かれる帰結を3つ明記します。

1. **J0-adjudication も canonical な正本事実を1行も書かない。** 書くのは判断の台帳だけで、master RDB への反映は E2a 以降。
2. **裁定の書き込み口は J0-read と同じ builder / validator を通る。** console 専用の抜け道を作らない。
3. **既存の判断待ち561件（`data/review_inbox.json`）とは経路が交わらない。**

---

## 1. 範囲

### 入れるもの

| 工程 | 実体 |
|---|---|
| `awaiting_user` の hold を読み出す | `review_console/data.py` に追加（master RDB を読む新関数） |
| 裁定画面（既存コンソールへ**あいのり**） | `review_console/static/` に5つ目のタブ |
| 裁定の記録（console 側ファイル） | `review_console/adjudications.json`（新設） |
| 台帳への反映 | 新設 `review_inbox_adapters/apply_user_adjudications.py` |
| 一括裁定（`grouping_fingerprint` で束ねる） | 画面と反映 CLI の両方 |
| user レーンの claim | 既存 `review_claim_ledger` の `claim_kind='user'` |

### 入れないもの（意図的な先送り）

- **`requeue` の自動実行（scheduler）** → J1。`deferred_retry` の hold は画面に出しません（§3.1）
- **canonical fact write** → E2a 以降。**裁定で「採用」しても、イベントは1件も増えません**
- song / term ドメイン。E0 が event しか作っていないため入力がありません
- 既存レビュー画面（判断待ち561件）の改修・統合

---

## 2. 実コードで確認した前提（実装者はここを読んでから書く）

すべて origin/main で実測した事実です。変わっていたら報告してください。

**(a) 既存コンソールは「ボタンで master RDB を変更しない」を明示的な設計原則にしています。** `docs/review-console-operations.md` の "It is not for:" に `direct Master RDB mutation from a button press` と書かれています。**この原則は J0-adjudication でも守ります**（§5 の2段構え）。

**(b) 既存コンソールは JSON ファイルだけを読み書きします。** `review_console/data.py` の `DECISIONS_PATH = review_console/decisions.json`、`EXPORT_PATH`、`STAGED_DIR` など。**master RDB（SQLite）を読む経路は現状ありません。** J0-adjudication が最初に足します。

**(c) 画面はタブ4つ**（`review_console/static/index.html:15-20`）＝ホーム `h` / 取得状況 `q` / メトリクス `m` / レビュー `v`。**5つ目として「裁定」を足します**。

**ショートカットは `b` にしました（v1.2 で訂正。当初 `j` としていました）。** レビュー画面では `j` が既にカーソル移動（`moveActive(1)`）に割り当てられていて、`reviewActions` が `sharedActions` を上書きします。`j` のままだと、いちばん長く開いているレビュー画面から裁定タブへ飛べません。`b` はどちらの表にも無い空きキーです。

**(d) サーバは `BaseHTTPRequestHandler` の素朴な実装**（`review_console/server.py`、240行）で、`do_GET` / `do_POST` にパスを1つずつ足す形です。フレームワークはありません。同じ流儀で追加してください。

**(e) `build_user_decision` は `adjudication_batch_id` を `open_hold` から取りますが、`review_hold_ledger` にその列がありません**（`local_judgment_contract.py:299`、DDL・契約 §8 の両方に無い）。**現状は必ず null になります。** §6 で対処します。

**(f) J0-read が `review_claim_ledger` を新設済み**（migration v3）。`claim_kind` に `user` を入れる想定で作ってあります（J0-read 仕様 §6.2）。**列追加は不要です。**

**(g) 「台帳に行が無い＝eligible」は J0-read が実装済み。** hold の有無は `review_hold_ledger` の `status='open'` で引きます。

---

## 3. hold の読み出し

### 3.1 対象

`review_hold_ledger` から次を満たす行だけを画面に出します。

1. `status = 'open'`
2. `hold_mode = 'awaiting_user'`（**`deferred_retry` は出さない**。時刻到達で自動復帰するもので、人の作業キューではありません＝契約 v1.1 §6）
3. `expires_at` は絞り込みに使わない（**v1.2 で訂正**。v1 は「未来、または null」と書いていましたが、§9-3 の「期限切れは隠さずに理由を出す」と矛盾していました。**期限切れも一覧に出し、操作だけを止めます**）
4. 有効な `user` claim が他に無い（§8）。これも隠さず「他の画面で裁定中」と理由を出します

**実測（v1.2）：現状 hold の `expires_at` は必ず null です。** `judgment_ledger_writer.write_decision` が `build_hold_ledger_entry` を `expires_at` なしで呼ぶためで、期限切れの経路は実データではまだ発生しません。テストは列を直接埋めて確かめています。期限を実際に入れるのは J1 以降の宿題です。

`deferred_retry` を画面に出さないのは、**内田さんの作業キューを「本当に人でないと決まらないもの」だけに保つ**ためです。ここを緩めると判断待ち561件の再演になります。

### 3.2 1件あたりに見せるもの

裁定に必要な材料を、**hold と packet ファイルの両方**から集めます。

- hold から: `hold_id` / `reason_code` / `reason_detail` / `required_resolution_type` / `allowed_actions` / `candidate_ids` / `candidate_set_sha256` / `opened_at` / `expires_at` / `grouping_fingerprint`
- `canonical_decision_ledger`（`prior_agent_attempt_id` で引く）から: agent が何を根拠に hold にしたか（`payload.reason_detail`）
- `review_inbox_items` から: `title` / `event_name` / `venue` / `event_year` / `source_url`
- **packet ファイル（`data/judgment_packets/batch_*.json`）から: `proposal` と `targets`**

**packet ファイルを読むのは、候補集合が台帳に残っていないためです**（J0-read 仕様 v1.4 §3.2）。ファイルが見つからない hold は、**候補集合を照合できないので裁定させません**。画面には出しますが「packet が見つからないため裁定できない」と表示し、操作を無効にします。黙って隠すと、なぜ消えたか分からなくなります。

### 3.3 並び順

`expires_at` の昇順、次に `opened_at` の昇順。**期限が近いものから裁く**ためです。

---

## 4. 画面（あいのり）

### 4.1 あいのりの方針（2026-08-14 内田さん決定）

**同じプロセス・同じ URL（`http://127.0.0.1:8751/`）に5つ目のタブとして足します。** 開く場所を増やさないためです。

**ただしデータ経路と保存先は完全に分けます。**

| | 既存4タブ | 裁定タブ |
|---|---|---|
| 読む先 | `data/review_inbox.json` ほか JSON | **master RDB の `review_hold_ledger`** ＋ packet ファイル |
| 書く先 | `review_console/decisions.json` | **`review_console/adjudications.json`**（新設） |
| 反映 | `export` → `stage-apply` | **`apply_user_adjudications.py`** |

**同じファイル・同じ関数を共用しないでください。** `save_decision` / `load_decisions` / `export_decisions` を裁定に流用すると、561件の器と混ざります。E0 が `status='candidate'` で分けた設計を、画面側でも守ります。

### 4.2 API

`server.py` に足すパス（既存の流儀に合わせ、`do_GET` / `do_POST` に1つずつ）。

```
GET  /api/adjudication/holds          … §3 の一覧（claim 込み）
GET  /api/adjudication/hold/<hold_id> … 1件の詳細（proposal・targets・agent の理由）
POST /api/adjudication/claim          … user claim の取得・解放
POST /api/adjudication/decide         … 1件の裁定を adjudications.json へ記録
POST /api/adjudication/decide-batch   … grouping_fingerprint 単位の一括裁定
GET  /api/adjudication/status         … 未反映件数・最終反映時刻・**実行すべきコマンド文字列**
```

**台帳へ反映する API は置きません**（v1.1 で訂正。**おとの指摘どおり、v1 は自己矛盾していました**）。`POST /api/adjudication/apply` を置くと、UI のボタンから master RDB を書くことになり、§0 と §2(a) の「ボタン押下で master RDB を直接変更しない」を破ります。**反映は CLI だけの経路にします。**

そのかわり `GET /api/adjudication/status` が、**そのまま貼って実行できるコマンド文字列**を返します。画面には未反映件数と一緒にこれを表示し、コピーできるようにしてください。

```
python3 review_inbox_adapters/apply_user_adjudications.py --apply --confirm "APPLY USER ADJUDICATIONS" --actor-id uchida
```

**手数が1つ増えますが、確認フレーズを UI のボタンで形骸化させないための意図的な設計です。** 内田さんは日々 iTerm を開いて作業されるので、コマンドを1本貼る負担は小さいと判断しました。

### 4.3 画面に必ず出すもの

- **agent がなぜ人へ回したか**（`reason_code` の日本語ラベルと `reason_detail`）
- **何を選べるか**（`allowed_actions` から。ボタンをハードコードしない）
- **候補集合**（`candidate_ids` を、packet の `targets` から名前つきで表示）
- **期限**（`expires_at` までの残り日数。過ぎたものは操作不可）
- **未反映の裁定がいくつあるか**（反映を忘れると台帳に入りません）

`reason_code` の日本語ラベルは画面表示だけに使い、**保存値は必ず英語**にしてください（契約 v1.1 §5）。

---

## 5. 裁定の記録と台帳への反映（2段構え）

### 5.1 なぜ2段にするか

既存コンソールの原則（§2a）を守るためです。**ボタン押下で master RDB へ書かず、いったん `review_console/adjudications.json` へ記録します。** そのうえで明示的な「台帳へ反映」操作を通します。

**副産物として、J0-read と同じ形（判断ファイル → 検証 → 台帳）に揃います。** LLM の判断も人の裁定も、同じ2段を通ることになり、経路が1本になります。

### 5.2 `adjudications.json` の形

```jsonc
{
  "schema_version": 1,
  "adjudications": [
    {"hold_id": "hold_xxxxxxxxxxxxxxxx",
     "inbox_id": "inbox_xxxxxxxxxxxxxxxx",
     "action": "accept",                      // accept | reject
     "target_id": "occ_xxxxxxxxxxxxxxxx",     // 対象を選んだ場合。null 可
     "reason_detail": "内田さんのメモ",
     "candidate_set_sha256": "<hold から写した値>",
     "decided_by": "uchida",
     "recorded_at": "2026-08-14T22:30:00+09:00",
     "batch_id": "batch_xxxxxxxxxxxx",        // 一括裁定のときだけ。単発は null
     "status": "pending",                      // pending | applied | invalidated
     "applied_at": null,                       // applied のとき時刻
     "decision_id": null,                      // applied のとき台帳の ID
     "invalidated_at": null,                   // invalidated のとき時刻
     "invalid_reason": null}                   // invalidated のとき理由コード
  ]
}
```

**`status` の3値は v1.1 で追加しました（おとの指摘2）。** v1 は `applied_at` の null だけで未反映を判定していたため、**検証に失敗した裁定が永久に `applied_at=null` のまま残り、反映のたびに同じ issue を出し続けます。** かといって行を消すと、内田さんが裁いた事実そのものが消えて監査証跡を失います。

- **反映 CLI が処理する対象は `status='pending'` の行だけ**
- 検証に失敗した行は **`status='invalidated'`** にし、`invalidated_at` と `invalid_reason`（§5.3 の失敗理由コード）を書く。**行は消さない**
- 成功した行は `status='applied'`

**`invalidated` になった hold は `status='open'` のままなので、画面に再び現れます。** 内田さんは改めて裁定でき、それは**別の行**として記録されます。古い行は理由つきで残るので、「なぜ最初の裁定が通らなかったか」を後から追えます。

**`recorded_at` は「画面で裁いた時刻」で、契約の `decided_at` ではありません。** 契約の `decided_at` は反映 CLI が stamp します（§5.3）。混同しないよう別名にしています。

### 5.3 反映（`apply_user_adjudications.py`）

**`status='pending'` の裁定だけ**を順に台帳へ入れます。**1件ごとに次を確認し、1つでも欠ければその件を `invalidated` にして medium issue を出します**（バッチ全体は止めない）。`invalid_reason` には失敗した検査に対応するコードを入れてください（`hold_not_open` / `inbox_mismatch` / `candidate_set_changed` / `action_not_allowed` / `hold_expired`）。

1. `hold_id` の hold が実在し、`status='open'` かつ `hold_mode='awaiting_user'`
2. `inbox_id` が hold と一致
3. **`candidate_set_sha256` が hold の値と一致**（候補集合が変わっていたら裁定を通さない＝§0）
4. `action` が hold の `allowed_actions` に含まれる
5. hold が期限切れでない
6. **対象IDは凍結された候補集合の中にある（v1.2 で追加）。** `accept` で候補集合が空でないのに `target_id` が無ければ `missing_target_id`、候補集合の外の ID なら `target_not_in_candidate_set`。**画面の外で作られた対象を通さないため**で、これが無いと §0 の「候補集合を凍結する」意味が反映の段で消えます

失敗理由コードは `hold_not_open` / `inbox_mismatch` / `candidate_set_changed` / `action_not_allowed` / `hold_expired` / `missing_target_id` / `target_not_in_candidate_set` / `invalid_decision` / `prior_attempt_missing` の9つです（後半4つは v1.2 で追加）。**`invalid_decision` は契約側で弾かれた場合**、**`prior_attempt_missing` は hold の `prior_agent_attempt_id` に対応する canonical decision が見つからない場合**に使います。v1.1 は5つしか用意しておらず、契約違反を `action_not_allowed` と記録することになっていました＝実際の失敗理由と食い違うので分けました。

**`adjudications.json` に保存する `invalid_reason` と、report の `issue_type` には同じコードを入れてください。** 2つの語彙に割れると、あとから「どの理由で何件通らなかったか」を数えられなくなります（おとの独立レビューで実際に割れているのが見つかりました）。

**ただし `decision_id_conflict`（同じ ID で中身が違う）だけは invalidated にせず、バッチ全体を止めます。** 台帳の履歴が壊れている合図で、1件の記録として流すと気づけないためです（J0-read の `apply_judgment_results.py` と同じ扱い）。

そのうえで契約の `build_user_decision` を呼び、`judgment_ledger_writer.write_decision` で書きます。**J0-read の writer をそのまま使ってください。** console 専用の書き込み口を作らないこと（§0 の帰結2）。

**lineage は反映 CLI が stamp します。** 画面やファイルの自己申告を採用しません（J0-read §4.2 と同じ規律）。

```
actor_type = "user"（固定）
actor_id   = --actor-id 引数、無ければ環境変数、無ければ停止
decision_channel = "console"（固定。ACTOR_CHANNELS が強制する）
decided_at = 反映の実行時刻（tz付き）
```

**hold を閉じること。** 反映が成功したら `review_hold_ledger` の `status='resolved'`、`closed_at`、`resolved_by_decision_id` を更新します。**J0-read はここに触っていないので、hold を閉じる実装は J0-adjudication が最初です。**

### 5.4 `--apply` と migration の境界

J0-read §5.4 と同じ規律です。dry-run（既定）は本番DBをコピーして v1→v2→v3 を当ててよい。`--apply` は migration を実行せず、必要な表が無ければ high severity で停止。確認フレーズ（新設定数 `APPLY_USER_ADJUDICATIONS_CONFIRMATION`）が揃ったときだけ本番へ書く。

**v1.2 で明記：dry-run のコピーへ migration を当てる処理は必須です。** 最初の実装ではここが抜けていて、コピーを作るだけで migration を当てていませんでした。**本番 `data/bon_odori_master.sqlite` にはまだ J0 の台帳が無いので、この状態では実データでの dry-run が一度も成立しません**（`judgment_ledger_missing` で必ず止まる）。E0 で一度潰したのと同じ形の穴です。`--no-auto-migrate` を用意し、台帳が無いときに止まることをテストできるようにします。適用した migration 名は report の `migrations_applied` に出します。

**本番 `data/bon_odori_master.sqlite` への migration 適用は、このPRでも行いません。**

---

## 6. `adjudication_batch_id` の穴を塞ぐ（§2e）

**`build_user_decision` に `adjudication_batch_id` 引数を足します**（既定 `None`、additive）。`review_hold_ledger` へ列を足す案は採りません。**バッチは裁定時に決まるので、hold を開く時点では存在しないから**です。

```python
def build_user_decision(raw, *, open_hold, adjudication_batch_id=None):
    ...
    packet["adjudication_batch_id"] = adjudication_batch_id or open_hold.get("adjudication_batch_id")
```

既存の呼び出し（引数なし）は壊れません。**契約 v1.1 の遷移表・registry・validator には手を入れないこと。**

`batch_id` の決め方: `stable_id("adjbatch", grouping_fingerprint, recorded_at, length=12)`（`master_rdb.master_db.stable_id`。結果は `adjbatch_` + 12桁）。**自前で sha256 を組まないでください**。単発の裁定では null のままにします。

---

## 7. 一括裁定

### 7.1 束ね方

**`grouping_fingerprint` が同じ hold だけを束ねます。** `reason_code` だけで group 化してはいけません（契約 v1.1 §8）。同じ曖昧さでも、許可 action や必要な対象の型が違えば、まとめて裁いてはいけないためです。

### 7.2 展開

**画面上は1回の操作でも、`adjudications.json` には item ごとの行を書きます。** 反映 CLI も1件ずつ検証します（§5.3 の5項目を各件について）。

**「1位候補へまとめて」のような暗黙の対象選択を作らないこと**（契約 v1.1 §8）。一括で選べるのは `target_id` を伴わない裁定だけです。対象IDが要る hold は、**一括の対象から外して1件ずつ裁かせます。**

### 7.3 対象が要るかどうかの判定（v1.2 で訂正。ことの仕様バグ4件目）

**v1.1 は「`required_resolution_type` が対象を求めるもの」と書いていましたが、これは誤りです。** 実コード（`local_judgment_contract.build_hold_ledger_entry`）を読み直したところ、この列は hold_mode から機械的に決まる2値でした。

```
awaiting_user  → "user_terminal_decision"
deferred_retry → "scheduled_requeue"
```

つまり**画面に出るすべての hold で必ず `"user_terminal_decision"` になり、「対象IDが要るか」は1件も区別しません。** v1.1 のまま実装すると、**すべての単発裁定が対象IDを要求し、すべての hold が一括の対象から外れます**＝一括裁定が永久に成立しません。最初の実装は実際にそうなっていました。

**正しい判定材料は `candidate_ids` です。** agent が候補集合を凍結した hold（＝人が選ぶべき選択肢がある）だけが対象IDを要します。

- `accept` かつ `candidate_ids` が空でない → **`target_id` 必須**。値は候補集合の中のものに限る
- `reject` → 対象IDは不要（「どれでもない」と決める判断なので、選ばせる意味がない）
- `candidate_ids` が空 → 対象IDを付けること自体を拒否（凍結されていない対象を持ち込ませない）
- **一括の対象は `candidate_ids` が空の hold だけ**

`required_resolution_type` は「どのレーンで解決するか」を表す列であって、対象の要否ではありません。同じ轍を踏まないよう、判定に使わないでください。

---

## 8. user レーンの claim

J0-read が作った `review_claim_ledger` を `claim_kind='user'` で使います。

- 画面で hold を開いたときに claim を取り、閉じたら解放
- lease は既定30分。期限切れは無効（行は消さず上書き）
- **`agent` claim とは別扱い**。同じ `inbox_id` に agent claim があっても user は裁けます（agent は既に hold を開いて手を離しているため）
- **ただし他の user セッションが握っている hold は開かせません**（内田さんが2つの画面を開いた場合）

---

## 9. negative test 一覧（= 受け入れ条件）

**各件について「修正を外したら落ちる」ことを確認できる形にすること。「テスト全通過」は合格の根拠にしません。**
**壊す位置が効く場所かも確かめてください。** J0-read では3回空振りしました（別の検査が先に弾く／言語のしくみが肩代わりする／件数は同じで理由が違う）。詳細は `docs/local-judgment-j0-read-test-coverage.md` の「落とし穴」。

**§9 の全件について対応表（条件番号 → テスト名、未カバーはそう明記）を作り、PR 本文とリポジトリに置いてください。** 合計テスト数を充足件数として報告しないこと。

読み出し
1. `deferred_retry` の hold が画面に出ない
2. `status != 'open'` の hold が出ない
3. 期限切れの hold が操作不可になる（隠さずに理由を出す）
4. packet ファイルが無い hold は裁定不可として表示される（黙って消えない）
5. 他の user が claim 中の hold は開けない
6. agent claim があっても user は裁ける

裁定の記録
7. 画面の裁定操作で master RDB が1バイトも変わらない（**§0 の核。checksum で確認**）
7c. **claim は `review_claim_ledger` のリース行だけを書き、判断の3台帳は行の中身まで含めて動かない**（v1.2 で追加。§0 の例外の線引き。**件数だけを比べると UPDATE を見逃す**ので、行の内容ごと比べること）
7a. **台帳へ反映する HTTP API が存在しない**（`server.py` に `/api/adjudication/apply` のパスが無いことを構造検査で固定する。UI から本番へ書く経路を作らない）
7b. `GET /api/adjudication/status` が未反映件数と実行コマンド文字列を返す
8. `adjudications.json` が `decisions.json` と別ファイルで、既存の `load_decisions` から見えない
9. `allowed_actions` に無い action を記録しようとすると拒否される
9a. **凍結された候補集合の外の `target_id` を記録できない。候補集合があるのに `target_id` なしの `accept` も記録できない**（v1.2 で追加＝§7.3）
10. 対象IDが要る hold を一括裁定の対象にできない（**理由まで確かめること。**「対象IDが無い」で弾かれても素通りするため）

反映
11. `candidate_set_sha256` が hold と違う裁定は `invalidated` になり、medium issue が出る
11a. **候補集合の外の `target_id` を持つ裁定は反映でも `invalidated` になる**（v1.2 で追加。画面を通さず `adjudications.json` を直接書かれた場合の砦）
12. `status != 'open'` の hold への裁定が `invalidated` になる
13. 期限切れ hold への裁定が `invalidated` になる
13a. **`invalidated` の行は消えずに残り、`invalid_reason` が入る**（監査証跡）
13b. **`invalidated` の行は次回以降の反映で再処理されない**（同じ issue を出し続けない）
13c. **`invalidated` になった hold は画面に再び現れ、裁き直すと別の行として記録される**（古い行は残る）
13d. **hold の `prior_agent_attempt_id` に対応する decision が無いとき、保存する `invalid_reason` と report の `issue_type` が同じコードになる**（v1.2 で追加。監査の語彙を割らない）
14. 反映で `canonical_decision_ledger` / `review_queue_state_ledger` / `review_hold_ledger` が整合して更新される（queue が `closed`、hold が `resolved`、`resolved_by_decision_id` が入る）
15. 反映が J0-read の `write_decision` を経由している（構造検査。console 専用の書き込み口が無い）
16. 途中で失敗したら3表とも書かれない（トランザクション）
17. 同じ裁定を2回反映しても台帳の行が増えない（冪等）
18. `applied_at` と `decision_id` が `adjudications.json` に書き戻される

lineage
19. ファイルに `decided_by: "koto"` と書いても採用されず、`--actor-id` の値が入る
20. `actor_type` が `user`、`decision_channel` が `console` で固定される
21. `decided_at` が反映の実行時刻になる（画面の `recorded_at` ではない）
22. **`eligible` の候補に user が直接 terminal decision を出せない**（agent hold を経ていないもの。契約 v1.1 §0）
23. `deferred_retry` の hold に user が terminal decision を出せない

一括
24. `grouping_fingerprint` が違う hold が同じバッチに入らない
25. 一括でも item ごとに canonical decision が作られ、各件が個別に検証される
26. `adjudication_batch_id` が canonical decision に記録される（**現状 null になる穴が塞がっている**）
27. 単発の裁定では `adjudication_batch_id` が null

canonical 不変
28. J0-adjudication 実行の前後で canonical fact 表10表の `COUNT(*)` が不変
29. J0-adjudication のモジュールが canonical fact writer 5関数を import していない（構造検査）
30. `review_inbox_items.status` が `candidate` のまま変わらない
31. 既存の判断待ち561件（`status='pending'`）が1行も変わらない

安全装置
32. dry-run 既定で本番DBの checksum が実行前後で一致する
33. `--apply` を確認フレーズ無しで拒否する
34. `--apply` では migration を実行せず、台帳が無ければ停止する
34a. **dry-run はコピーにだけ migration を当てる**（v1.2 で追加。当てないと実データで一度も走らない＝§5.4。`migrations_applied` に3本が並び、元DBには台帳が生えていないこと）
34b. **`--no-auto-migrate` を付けた dry-run は台帳が無ければ止まる**（v1.2 で追加。34a の裏返しで、migration の有無を切り替えられること）
35. dry-run の適用先が本番DBパスと同一なら停止する
36. `argparse` 実パース経由で全経路が動く（属性欠落が無い）

---

## 10. やらないこと（J0-adjudication の範囲外）

- canonical fact write（系列・開催回・会場・日付・曲のいずれも）→ E2a 以降
- `requeue` の自動実行 → J1
- 既存レビュー画面（561件）の改修・統合・削除（strangler：旧経路は残す）
- song / term ドメイン
- **本番 `data/bon_odori_master.sqlite` への migration 適用（内田さんの承認事項）**

---

## 11. 完了条件

1. §9 の46件（v1.2 時点）がすべて通り、かつ各件が「修正を外すと落ちる」ことを確認済み
2. 対応表（条件番号 → テスト名）を作り、未カバーがあれば正直に明記
3. §9-7（画面操作で master RDB が変わらない）と §9-28（canonical 不変）を実データで実測して PR 本文に貼る
4. 仕様書（この文書）を `docs/local-judgment-j0-adjudication-v1.md` として同梱
5. `docs/spec/L1/03-review.md` に user 裁定レーンを追記し、不変条件を立てる（**同じPRで。別PRにしない**）
6. 本番 migration は適用しない

**着手前に、この仕様の矛盾・実装不能点・§2 の実測との食い違いを指摘してください。** 実装より先に読んで、疑問を返してもらうところから始めます。J0-read では、この往復で仕様バグが実装前に1件、実装後にテストで3件見つかりました。
