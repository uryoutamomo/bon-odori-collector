# E2-S: 曲の観測を開催回へ結びつける（同一性1問1答・第2段）v1.3

作成: 2026-08-16 / こと（Claude Code）
v1.1（同日）＝**内田さんの決定「LLMの読み取りを人のレビューと同等の根拠として扱う」を反映**（§2.5）。
v1.0 では曲マスタに無い曲を保留にしていたが、それだと実データで**1件も公開へ届かない**ことが分かったため。

**v1.2（同日）＝おとの実装前レビューで出た8件を確定した。すべて既存 helper の契約との矛盾で、
v1.1 のままでは実装できなかった。** 直した内容は §5.5（evidence の作り方）・§6（helper の拡張契約）・
§6.5（状態の置き場）・§4.5（候補集合の凍結）。**根本原因は、E2 での「既存の器がそのまま使えた」体験を、
曲でも確かめずに前提にしたこと**である。`upsert_occurrence_song` は E2 が使った helper とは契約が違った。
上位＝`x-post-extraction-songs-v1.md`（E0X-S v1.1、観測台帳を作る第1段）。
この文書は**その台帳を `occurrence_songs` まで届ける**ための仕様である。

## 0. コンセプト（設計判断に迷ったらここへ戻る）

内田さんの言葉＝「LLMの誤りは人間とほぼ同等。ただしLLMは全体像を見渡すことを見落としがち。
だからLLMの一つ一つの業務はシンプルであるべきで、全体を見渡すのは別のシーンかつ別のモデルで行う」。

E2（開催情報）で「**LLMに聞くのは同一性だけ、変更型は機械が決める**」形にして成功した。曲でも同じ形を取る。
**LLMに聞くのは2つ（この曲は曲マスタのどれか／この行事は開催回のどれか）だけで、
確率・根拠区分・書き込み先はすべて機械が決める。**

## 1. なぜ第2段が要るか（第1段だけで止めると起きること）

2026-08-16 に E0X-S が merge され（`1b7e548`）、実データで曲15件・界隈語5語が台帳に入った。
だが**台帳は誰も読んでいない**。ここで止めると `data/youtube_setlist_occurrences.json` と同じ、
構造化されたまま2年近くどのパイプラインにも消費されない孤立データになる。

同時に、**旧経路（`build_event_song_candidates.py`）を止められない**。止めると曲目が一切増えなくなるためで、
新経路が `occurrence_songs` まで届いて初めて退場の判断ができる。

## 2. 実測（この仕様の前提。2026-08-16 に master RDB の実物で確認）

**器の大部分が既にある。** E2 のときと同じで、新設が要るのは変換層だけである。

- `occurrence_songs` は823件。列に `song_id` / `song_title_raw` / `normalized_title` / `evidence_status` /
  `probability` / `confidence` / `origin` / `role` / `source_count` を持つ
- **`song_id` が null の行が210件ある。** ただし**それらは別経路（YouTubeセットリスト等）が作ったもので、
  この仕様が使う `upsert_occurrence_song` 経由では作れない**（下記）

### ★★ 実コードを読んで前提が崩れた（v1.0 執筆中に判明。ここが設計を決めた）

**`upsert_occurrence_song`（`report_apply/event_report_helpers.py:507`）は、曲名が `songs` に無ければ
必ず新規登録する。しかも `status='active'` 固定である**（532行）。つまりこの関数を通す限り、

1. `song_id` が null の行は作れない（必ず曲マスタへ登録してIDを付ける）
2. **誰もレビューしていない曲が「確認済み」として曲マスタへ入る**

`active` は `SongCatalog.resolve()` が検証済みとして返す値である（INV-SNG-003）。
これは新経路が作ったものではなく **origin/main に元からある挙動**で、
正規表現由来の粗い候補まで無審査で確定曲にしてしまう点が問題だった。

### 2.4 公開は `songs.status` を見ていない（これが判断を分けた）

`export_public_events.py` の公開クエリは **`FROM occurrence_songs` を素で読み、`songs` と JOIN していない**。
つまり**`occurrence_songs` へ書いた時点で公開に出る**。曲マスタの状態は公開の門になっていない。
唯一の防御は `is_suppressed_song()`（抑制リストとの完全一致）だけである。

したがって「曲マスタの状態で安全を担保する」という設計は成り立たない。
**書くかどうかがそのまま公開するかどうか**である。

### 2.5 ★★ 内田さんの決定（2026-08-16）＝LLMの読み取りは人のレビューと同等の根拠

実データで測ったところ、**このまま安全側へ倒すと第2段が無意味になる**ことが分かった。
X投稿30件から取れた14曲のうち、曲マスタにあるのは6曲、うちレビュー済み（`active`/`有効`）は2曲だけ。
**行事名が付いた観測5件に限ると、レビュー済みの曲は0件**——つまり1件も公開へ届かない。

そこで内田さんへ3案を出し、**「LLMの読み取りを人のレビューと同等の根拠として扱う」を選択**いただいた。
根拠は内田さんのコンセプト「LLMの誤りは人間とほぼ同等」と、同日の実測
（**LLMが書き写した15曲は全件が本文に実在し誤り0件。旧経路は3件中1件が誤抽出**）である。
**質はすでに逆転している。**

**実装上の含意**＝曲マスタに無い曲は `status='active'` で登録してよい。
これは**人のレビュー経路と同じ値**である（`apply_song_candidate_finite_actions.py` の
`_apply_register_song` も `STATUS_ACTIVE` を入れる）。同じ経路の同じ扱いにする、というだけの話になる。

**ただし条件が2つある。** ①**由来を必ず残す**（`source_url` に投稿URL、`memo` に観測IDとバッチID、
`occurrence_songs.origin='observed_x_post'`）。誤りが出たときに、どの投稿から来たかを辿って消せるようにする。
②**この決定はX投稿由来のLLM読み取りにだけ適用する。** 正規表現由来の暗黙登録（§2の既知の挙動）は
**別の宿題として残す**——質が違うものを同じ扱いにはしない。
- `evidence_status` の実値は `announced` 15 / `observed` 552 / `predicted` 256。
  **E0X-S の `origin`（`events`＝告知に載っていた曲／`observations`＝踊った記録の曲）が、
  `announced` / `observed` にそのまま対応する。** 第1段で `origin` を残しておいた判断がここで効く
- `occurrence_songs.origin` の実値は `curated` / `inherited_prediction` / `observed_matched` /
  `observed_youtube_setlist` の4つ。**X投稿由来は新しい値 `observed_x_post` を足す**（既存の意味を変えない）
- 曲の有限行動は `song_candidate_finite_actions.py` に**既にある**＝
  `register_song` / `add_song_alias` / `reject_song` / `hold`。新設不要
- `songs` は399件で **`status` の語彙が二重**（`active` 29 / `有効` 77 / `候補` 274 / `無効` 19）。
  **この仕様では触らない**（別の宿題。ここで直すと範囲が膨らむ）

## 3. 範囲

**v1で扱う**＝`data/x_song_observations.json` の観測を、LLMの同一性判定を経て
`occurrence_songs` へ反映する提案に変える。反映は既存の dry-run / backup / 監査の経路をそのまま使う。

**あわせて扱う（v1.1 で範囲に入った）**＝**曲マスタに無い曲の新規登録**。§2.5 の内田さんの決定による。
由来（投稿URL・観測ID）を必ず残す形で `status='active'` を入れる。

**v1で扱わない**
- **既存 `songs.status` の書き換え** — `候補` の曲を昇格させない（INV-SNG-008）。曲マスタ側の仕事
- `songs.status` の語彙二重（`active` 29 / `有効` 77）の統一
- **正規表現由来の暗黙登録** — `upsert_occurrence_song` は他経路からも呼ばれ、そちらは
  粗い候補を無審査で `active` にする。**質が違うので同じ扱いにしない**。別の宿題として残す
- 界隈語（`x_glossary_observations.json`）から用語集への反映 — Notionへの書き込みを伴うので別PR
- 旧経路の停止 — §8 の条件を満たしてから
- 日次workflowへの組み込み

## 4. LLMに聞くこと

観測1件につき、**同一性2つだけ**。候補集合は機械が作って見せる。

```json
{"observation_id": "...",
 "song_match": "song_8301ef2fd9b554f0",
 "occurrence_match": "none",
 "reason": "本文の『炭鉱節』は炭坑節の表記ゆれ。行事名が書かれていないので開催回は特定できない"}
```

- `song_match` — 見せた曲候補のIDか `"none"`
- `occurrence_match` — 見せた開催回候補のIDか `"none"`
- **変更型の名前を一度も書かせない。** どう反映するかは機械が決める

### 候補集合の作り方（機械の仕事。高再現率の検索器であって除外器ではない）

- 曲候補＝`songs` と `song_aliases` を正規化して引く（最大20件）。
  E0X-S と同じ正規化（NFKC・中黒・長音・空白・URL）を使う。
  **並び順は「完全一致 → 前方一致 → 部分一致」、同点は `song_id` の昇順**（v1.2 で確定）
- 候補には **`song_id` / `canonical_title` / `status` / どの別名で当たったか**を載せる。
  LLMは表記ゆれを見て選ぶので、別名で当たったことが分からないと判断できない
- 開催回候補＝観測の `event_name` から `event_series` と `event_occurrences` を引く（最大20件）。
  並びは同じ規則で、同点は `date_start` の降順 → `occurrence_id` 昇順。
  `event_name` が null の観測は**開催回候補を空で渡す**（＝必ず `"none"` になり §5 で保留になる）

### 4.5 候補集合の凍結（v1.2 で契約を確定）

**候補集合はパケット生成時に凍結し、取り込み時に照合する**（E2 #213 の教訓＝
古いコピーで作ったパケットで判定して重複を10件作る一歩手前だった事故と同型を避ける）。

- **ハッシュの対象は「候補IDの並び（ソート済み）」だけ**にする。
  `canonical_title` や `status` を混ぜない——**無関係な更新でstale扱いになり、判定がやり直しになる**ため。
  見せた選択肢の集合が変わっていないことだけを保証する
- `candidate_set_sha256` は曲候補と開催回候補で**別々に持つ**（片方だけ変わったときに切り分けられる）
- stale だったときは**反映せず** `candidate_set_stale` を issue に記録し、
  その観測は §6.5 の state で `eligible` に戻す（次のパケットで新しい候補とともに再提示される）

## 5. 機械が決めること（LLMには選ばせない）

| `song_match` | `occurrence_match` | 機械の動き |
|---|---|---|
| 既存ID | 既存ID | `occurrence_songs` へ upsert（`song_id` つき） |
| `"none"` | 既存ID | **曲マスタへ `active` で登録**（由来つき）してから upsert（§2.5） |
| 既存ID | `"none"` | **書かない。** 観測を保留のまま残す |
| `"none"` | `"none"` | **書かない。** 同上 |

**`occurrence_match` が `"none"` のとき書かないのは、書く先が無いためである。**
新しい開催回を作るのは E0→E2 の仕事で、ここで作ると同じ行事が二重にできる。
観測は台帳に残るので、**開催回が後から増えたときに再評価される**（`next_eligible_at` を30日後に置く）。

### ★ 曲マスタへ登録するときに必ず残すもの（§2.5 の条件①）

新規登録は**人のレビュー経路と同じ形**にする（`status='active'`、`song_id = stable_id("song", title)`）。
そのうえで**由来を必ず埋める**。誤りが出たときに辿って消せることが、この決定の前提だからである。

- `songs.source_url` — その曲を書き写した**投稿のURL**
- `songs.memo` — `observation_id` とバッチIDを含む系譜（`_lineage_memo` と同じ形でよい）
- `occurrence_songs.origin` — `observed_x_post` 固定。**既存の4つの値と混ぜない**

**曲マスタの状態は「候補」でも上書きしない。** 既にある行の `status` はこの経路では一切触らない
（`候補` のまま `occurrence_songs` へ書く）。昇格の判断は曲マスタ側の仕事で、ここでやると範囲が膨らむ。

### ★ 既存IDが決まったら、書く曲名は canonical_title にする（v1.2。おとの指摘7）

`occurrence_songs` の一意キーは **`(occurrence_id, normalized_title, role)`** である。
つまり同じ曲を別表記で2回観測すると、**同じ `song_id` を指す行が2つでき、公開にも2行並ぶ**。

したがって **`song_match` が既存IDのときは、`song_title_raw` に `songs.canonical_title` を入れる。**
投稿にあった生の表記（「炭鉱節」など）は **evidence 側（§5.5）に残す**ので失われない。

`song_match` が `"none"`（新規登録）のときは、投稿にあった表記がそのまま canonical になる。

## 5.5 evidence の作り方（v1.2 で新設。おとの指摘3）

**`upsert_occurrence_song` は `evidence_id` を必須で受け取り、`occurrence_song_evidence_links` へ必ず書く。
このテーブルは `evidence_items(evidence_id)` へ外部キーを持つ**（実DBで確認済み）。
だから**先に `evidence_items` へ行を作らないと、外部キー違反で落ちる。** v1.1 にはこの記述が丸ごと無かった。

観測1件につき evidence を1件、次の形で upsert する。

| 列 | 値 |
|---|---|
| `evidence_id` | `stable_id("ev", "x_song", observation_id)` |
| `platform` | `"x"` |
| `evidence_type` | 観測の `origin` から。`events`→`"announced"`／`observations`→`"observed"` |
| `source_key` | `"x_song_observation"` |
| `source_id` | `tweet_id` |
| `account_key` | 観測の `account` |
| `text_excerpt` | 投稿本文（既存行にならい先頭を切り詰める） |
| `url` | 観測の `url`。**空なら `https://x.com/i/status/<tweet_id>`**（§6.6） |
| `published_at` | 観測の `posted_at` |
| `observed_at` | 取り込み日 |
| `raw_status` | `role`（`prediction` / `result`） |
| `raw_json` | `observation_id` / `batch_id` / `song_name`（**投稿にあった生の表記**）/ `event_name` / `origin` / `score` |

**`evidence_id` が `observation_id` から決まるので、同じ観測を2回取り込んでも evidence は1件である**（冪等）。

### 機械が埋める値

- `evidence_status` — 観測の `origin` から決める。`events` → `announced`、`observations` → `observed`。
  **LLMには聞かない**
- `origin` — `observed_x_post` 固定
- `role` — `announced` なら `prediction`、`observed` なら `result`
- `probability` — 触らない（helper も NULL を入れる）。既存の `calibrate_song_probabilities_rdb.py` が
  後から計算する（手動実行のまま。自動化はここでは決めない）
- `confidence` — **一律 `high`（`uncertain=False`）。件数で変えない。**

  **★ v1.3 で訂正（内田さんの指摘）。v1.2 では「観測1件なら medium、2件以上なら high」と書いたが、
  これは設計として誤りだった。** 内田さんの問い＝「曲名として認識しているのに根拠が足りないことはあるのか。
  曲名でない何かも2つカウントしたら曲名とされてしまうのか」。**後者はそのとおりで、
  同じ誤りが2件あれば high になる。件数は質の代理にならない**（同じアカウントの2投稿でも増える）。

  加えて、**この列が表すのは「曲名かどうか」ではない**。既存の呼び出し元を読むと、
  `uncertain` は**報告者自身の自信申告**（`apply_firsthand_field_report.py` は `report.get("uncertain")`、
  `apply_official_notice_report.py` は曲ごとの申告、`build_x_review_lanes.py` は情報源が公式か）を渡している。
  つまり**「その1件の報告が信用できるか」**である。実データも `unknown` 672 / `high` 148 / `medium` 3 で、
  medium はほぼ使われていない。

  **一律 `high` にする根拠4点**＝①人のレビューを経た曲は `uncertain=False` で入るので、
  内田さんの決定「LLMの読み取りを人のレビューと同等に扱う」に沿うなら同じ値になる
  ②本文に書いてあることを機械が照合済み ③件数は正しさを表さない
  ④**E0X-S の時点で「どの行事の曲か本文から読めないときは紐づけない」約束をしている**ので、
  怪しい結びつきは第1段で既に落ちている。

  **将来、伝聞（「やるらしい」）と直接体験（「踊った」）を区別したくなったら、
  LLMへ1問足して決める。いまは足さない**——聞くことを増やすとコンセプト（一業務はシンプルに）から外れる
- `source_count` / `evidence_count` — **v1.2 で仕様から外した**（おとの指摘4）。
  helper は新規時 1 固定で更新時は動かさない。正確に保つには distinct link 数の再計算が要り、
  範囲が膨らむ。**既存の挙動のままにして、必要になったら別途直す**

## 6. 反映の経路

E2 と同じく、**planner も二相CAS も作らない**。既存の dry-run → backup → 適用 → 監査を人の操作と同じように使う。
書き込みは既存の `upsert_occurrence_song` を通す。**新しい書き込み口を作らない。**

### ★ helper を後方互換の任意引数で拡張する（v1.2 で確定。おとの指摘1・2）

`upsert_occurrence_song`（`report_apply/event_report_helpers.py:507`）の現契約は、この仕様と3点で噛み合わない。
**実コードを読んで確認した事実**は次のとおりである。

1. **`song_id` を受け取らず、`songs.normalized_title` の完全一致だけで曲を探す。`song_aliases` を見ていない。**
   したがって **LLMが別名経由で既存曲を正しく指しても、その別名で新しい曲が作られる**（重複を生む）
2. `origin` は `'curated'` のリテラル固定。新規 `songs` の `source_url` / `memo` は NULL 固定
3. `confidence` は `uncertain` から high/medium を決め、**既存行も上書きする**

**したがって、次の任意引数を足す（既定値は現在の挙動と同一にし、既存の呼び出し元は無変更）。**

| 引数 | 既定 | この仕様での値 |
|---|---|---|
| `song_id` | `None` | LLMが選んだ既存ID。**渡されたら名前検索を行わず、暗黙登録もしない** |
| `origin` | `"curated"` | `"observed_x_post"` |
| `song_source_url` | `None` | 投稿URL（新規登録時のみ使う） |
| `song_memo` | `None` | `observation_id` とバッチID（新規登録時のみ使う） |

**既存呼び出し元が3つある**（official notice / firsthand / 他）ので、
**引数を足しても既定の挙動が1ビットも変わらないこと**をテストで固定する（受け入れ条件16）。

### 6.5 状態の置き場（v1.2 で新設。おとの指摘5）

v1.1 には「30日後に再評価」と書きながら、**その状態をどこに持つかが無かった**。
`x_song_observations.json` は観測の記録であって、適用状態を混ぜると責務が増える。

**`data/x_song_identity_state.json` を新設する**（E0X が `x_extraction_state.json` を別に持つのと同じ形）。
キーは `observation_id`、値は `{issued_at, batch_id, applied_at, outcome, next_eligible_at}`。

- `outcome` — `applied`（`occurrence_songs` へ書いた）／`deferred`（`"none"` を含み保留）／
  `issue`（検査で落ちた）／`stale`（候補集合が変わっていた）
- `deferred` は `next_eligible_at` を**30日後**に置く。到達するまでパケットに出さない
- `stale` は `next_eligible_at` を置かず、**次のパケットにすぐ出す**（候補を作り直せば判定できるため）
- **dry-run では state を書かない。** 書くと本番適用の前に「処理済み」になってしまう

### 6.6 URL が空の観測（v1.2 で確定。おとの指摘6）

E0X-S は URL が空でも観測を残す（観測は正本factではないため）。一方この仕様は
新規登録する曲に `source_url` を必須にしているので、そのままでは矛盾する。

**`tweet_id` から `https://x.com/i/status/<tweet_id>` を組み立てて使う。**
保留にするより実用的で、`tweet_id` は一意なので辿れる。
**組み立てたことが分かるよう `song_memo` に注記する**（後から「これは復元したURLだ」と分かるように）。

**★ 曲マスタへ登録するのは「LLMが読んだ曲」だけであることを、テストで固定する。**
`upsert_occurrence_song` の暗黙登録分岐を通る以上、**由来の無い行が混ざらないこと**が生命線になる。
反映で増えた `songs` の行が**すべて `source_url` と `memo` を持つ**ことを確かめる（受け入れ条件4）。
ここが破れると、どの投稿から来たか分からない曲が公開に出て、誤りが見つかっても消せなくなる。

## 7. 不変条件

- **INV-SNG-004**: X投稿由来の曲は、LLMが既存開催回との同一性を示した場合にのみ `occurrence_songs` へ入る
  （`occurrence_match` が `"none"` の観測から行を作らない）
- **INV-SNG-005**: `evidence_status` は観測の `origin` から機械が決める。LLMの申告を採用しない
- **INV-SNG-006**: この経路が曲マスタ（`songs`）へ追加する行は、**必ず `source_url`（投稿URL）と
  `memo`（観測ID・バッチID）を持つ**。由来を辿れない曲を作らない
- **INV-SNG-007**: 判定に使った候補集合はパケット生成時に凍結され、取り込み時に照合される
  （候補集合が変わっていたら反映しない）
- **INV-SNG-008**: この経路は既存の `songs.status` を書き換えない（`候補` を昇格させない）
- **INV-SNG-009**（v1.2）: LLMが既存の `song_id` を指したとき、この経路は曲マスタへ行を追加しない。
  **別名で当たった場合も、その別名で新しい曲を作らない**（helper の名前検索を迂回する）

## 8. 旧経路を止める条件（E0X-S §9 から引き継ぎ）

**`build_event_song_candidates.py` を日次から外すのは、次の3つを測ってからにする。**

1. 同じ日のX投稿から、新旧それぞれ何件の曲名が取れたか
2. その曲名のうち、曲名でないものが何件混ざっているか
3. `occurrence_songs` へ届いた件数（新経路）と、レビュー待ちのまま滞留した件数（旧経路）

**2026-08-16 に30投稿で取った初回の実測**＝旧経路3件（うち誤抽出1件）に対し新経路14件（誤り0件）。
旧経路だけが取れた2件はどちらも新経路のほうが正確だった（「今となっては踊り」は曲名でない、
「新曲BENBEN音頭」は修飾語込み）。**ただし30件は少ないので、数日ぶんで確かめる。**

## 9. 受け入れ条件（negative test。各件「修正を外したら落ちる」ことを確認する）

1. `occurrence_match` が既存IDの観測から `occurrence_songs` へ1行できる
2. `occurrence_match` が `"none"` の観測からは1行もできない（INV-SNG-004）
3. `song_match` が `"none"` でも、`occurrence_match` があれば曲マスタへ登録され `occurrence_songs` へ1行できる
4. **反映で増えた `songs` の行は、すべて `source_url` と `memo` を持つ**（INV-SNG-006）
4b. 既にある曲の `status` は書き換わらない（`候補` の曲を反映しても `候補` のまま。INV-SNG-008）
4c. 同じ曲名の観測が2件あっても `songs` の行は1つしか増えない
5. `origin` が `events` の観測は `evidence_status='announced'` / `role='prediction'` になる
6. `origin` が `observations` の観測は `evidence_status='observed'` / `role='result'` になる
7. LLMが `evidence_status` を回答に含めても無視される（INV-SNG-005）
8. 候補集合に無いIDを指した回答は反映されない
9. 候補集合がパケット生成時から変わっていたら反映しない（INV-SNG-007）
10. `event_name` が null の観測には開催回候補が渡されない
11. 同じ観測を2回反映しても `occurrence_songs` の行が増えない（冪等）
12. `occurrence_songs.origin` が `observed_x_post` になる
13. dry-run では master RDB のチェックサムが変わらない
14. 反映済みの観測は次のパケットに出ない
15. `occurrence_match` が `"none"` の観測は30日後に再評価の対象になる

**v1.2 で追加（おとの指摘8件に対応）**

16. **既存の呼び出し元（official notice / firsthand）の挙動が1ビットも変わらない**
    （任意引数を足す前後で、生成される `occurrence_songs` / `songs` の行が同一。**既存テストが緑のままであることは
    根拠にしない**——新しい引数の既定値を明示的に確かめる）
17. **`song_match` が既存IDのとき、その曲が別名で当たっていても `songs` へ行が増えない**（INV-SNG-009。
    v1.1 のままなら別名で新しい曲ができる＝この経路の最大の事故）
18. `song_match` が既存IDのとき、`occurrence_songs.song_title_raw` は `canonical_title` になる
19. **同じ曲を別表記で2回観測しても `occurrence_songs` の行は1つ**（一意キーが `normalized_title` のため。
    18が守られていれば自然に満たされるが、独立に確かめる）
20. `evidence_items` へ行ができ、`occurrence_song_evidence_links` が外部キー違反にならない
21. 同じ観測を2回反映しても `evidence_items` の行は1つ（`evidence_id` が `observation_id` から決まる）
22. `evidence_items.raw_json` に**投稿にあった生の曲名表記**が残る（18で canonical に置き換えても失われない）
23. 観測の `url` が空のとき、`https://x.com/i/status/<tweet_id>` が使われ、組み立てたことが `memo` に残る
24. **`confidence` は観測の件数によらず常に `high`**（v1.3。1件でも2件でも同じ値になることを確かめる。
    件数で変える実装に戻すと落ちる）
25. `stale`（候補集合が変わっていた）の観測は `next_eligible_at` を持たず、次のパケットにすぐ出る
26. **dry-run では state ファイルが書き換わらない**（本番適用の前に「処理済み」にしない）
27. 候補集合のハッシュは候補IDの並びだけから決まる（`canonical_title` や `status` を変えても stale にならない）

## 10. 進め方

1. **まずこの仕様を読んで、矛盾や穴があれば実装前に返してほしい**（E0・E0X・E0X-S で計10件の穴が実装前に潰れた）
2. 問題なければ Draft PR まで。Ready化・merge は内田さんの承認を得てから こと が行う
3. 実装時は `docs/local-judgment-e2s-song-identity-v1.md` として同梱する
4. `docs/spec/` の更新を同じPRに含める（大原則）。L1-songs に **INV-SNG-004〜009 の6件**を足す
   （v1.1 では 008 を列挙から落としていた。おとの指摘8）。
   **`report_apply/event_report_helpers.py` にも手が入るので、`spec_index.py impact` で
   出てくる仕様（L1-master ほか）も同じPRで直す**
5. **本番RDBには書かない。** dry-run とテストだけで完結させる

---

こと（Claude Code）
