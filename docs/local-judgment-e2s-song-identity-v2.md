# E2-S v2 — X曲claimの同定・反映契約

署名: おと（Codex）

## 目的と境界

E0X-S v2 が `data/x_song_observations.json` に残した曲単位claimを、曲マスタと年次開催回へ安全に結ぶ。
LLMの判断取込は同定台帳までで、`songs` / `event_occurrences` / `occurrence_songs` / evidence表を変更しない。
正本factの書き込みは、曲と開催回の両方が解決した後のmaterializer一箇所だけが行う。

公開可能なclaimは `announced` と `observed` だけである。`mentioned` / `unknown` / conflict / legacy /
行事名欠落・行事名本文不一致 / 根拠引用不正 / source identity欠落はpacketにもfactにもならない。`origin=events|observations` は回答経路であり、
告知・実測の意味には使わない。

## 1. 曲同定を二段階に分ける

### retrieval

`build_x_song_resolution_packets.py --phase retrieval` は、全 `songs` と `song_aliases` を採点してtop 20を出す。
許可回答は `match_song` / `candidate_missing` / `unresolved` だけで、`new_song` は禁止する。
検索結果が空・不十分であることは新曲の証明ではない。

### novelty

`candidate_missing` のactive retrieval決定を持つ観測だけを `--phase novelty` へ出す。
ここではtop 20ではなく、title・alias・statusを含む全曲カタログを凍結して見せる。
許可回答は `match_song` / `new_song` / `unresolved`。`new_song` のtitleはLLMに再記述させず、
観測の `song_name` を機械的に使う。

両phaseとも観測全体SHA、候補行全体SHA、全catalog snapshot SHA、allowed actionをpacket SHAへ含める。
回答取込時に現在値を再計算し、title・alias・status・観測のどれかが変わっていれば台帳へ書かない。
別ファイルに同じpacket IDがあれば、同一内容でもfail closedにする。

同じpacket IDにdecisionが既にある場合、その観測を再びpacketへ出さない。`unresolved` は時間経過で再試行せず、
観測またはcatalog snapshotが変わりpacket IDが変わったときだけ再eligibleになる。
`candidate_missing` だけは同じretrieval decisionを依存先にしてnoveltyへ一度進める。

## 2. 開催回同定を曲同定から分ける

`event_dependency_key` があるclaimは、LLMへ開催回候補を出さない。E0のrevision familyで最大revisionの
`review_inbox_items` を選び、そのinboxのaccepted/closed event decisionだけを見る。

```text
event_dependency_key
  → 最新 review_inbox_items.revision_family_key
  → canonical_decision_ledger
  → occurrence_match
  → noneなら change-request evidence link
  → occurrence_id または dependency_pending
```

最新revisionが未判断・reject・未反映なら、旧revisionのacceptへ戻らず `dependency_pending` にする。
dependencyが無いclaimだけを別packetにし、本文照合済みevent nameと、日付または会場を必須にする。
候補には年・日付・会場・系列別名・statusを含める。許可回答は `match_occurrence` / `unresolved` だけで、
`new_occurrence` は存在しない。地域・wardは候補順位の文脈であり、E2-Sの保存gateではない。

開催回側も同じpacket IDのdecisionを再提示しない。direct `unresolved` は観測または開催回snapshotが変わったときだけ、
`dependency_pending` はE0 revision familyの最新inbox・decision・適用evidenceの状態が変わったときだけ再eligibleになる。
30日タイマーなど、同じ入力を期限だけで繰り返す経路は置かない。

## 3. 台帳とactor provenance

schema migration 4 (`x_song_identity_v2`) は次のappend-only表を追加する。

- `x_song_resolution_decisions` — retrieval/noveltyの曲同定とsupersede
- `x_occurrence_resolution_decisions` — report dependency/direct candidatesの開催回同定
- `x_song_materializations` — どの2決定から、どのsong/occurrence/fact/evidenceを作ったか
- `x_song_retractions` — 削除せずに閉じた証拠とcleanup結果

同定result内のactor/model/prompt申告は信用しない。`actor_id` / `model_id` / `prompt_sha256` / 時刻は
ローカルentrypointの引数でstampする。modelとprompt SHAは必須である。

## 4. materializer

`report_apply/materialize_x_song_resolutions.py` は次をすべて満たす観測だけを書く。

- current observation SHAが曲・開催回decisionと一致
- 選択した曲・開催回の凍結行が現在値と一致（無関係な別entityの追加だけでは再判断しない）
- claim typeが `announced` / `observed` でconflictなし
- 曲のfinal active decisionと `match_occurrence` がある
- 選択開催回が存在し、`merged`でない
- active/有効曲、同transactionで有限昇格できる候補曲、またはnoveltyで確定した新曲
- 同じ観測のactive materializationが無い

対応値は固定する。

| claim_type | role | evidence_status |
| --- | --- | --- |
| `announced` | `setlist` | `announced` |
| `observed` | `result` | `observed` |

既存 `occurrence_songs` と同じidentityなら証拠linkだけを追加し、song ID・title・origin・confidenceを
上書きしない。ただし旧経路の同一rowで `song_id` だけが `NULL` の場合に限り、`WHERE song_id IS NULL` の
CAS的な補完で解決済みsong IDだけを埋める。origin・生タイトル・evidence status・confidence・件数・notes・時刻は
変更しない。既に別の非NULL song IDがある、またはidentity/evidence statusが異なる場合はbatch全体をrollbackする。

## 5. retractと公開安全柵

X materializer所有のfactは `origin='observed_x_post'` とする。公開exporterはこのoriginだけについて、
曲statusが `active/有効`、role/evidence mappingが上表どおり、accepted evidence linkが1件以上、の全条件を要求する。
`x_song_claim_v2` evidenceは、同じfact・evidence・song・occurrence・roleを指すactive materializationも必須にする。
証跡台帳のないX風の行へaccepted linkだけを足しても公開しない。別経路のaccepted evidenceが同じfactを支える場合は、
その非X evidenceを根拠に公開を維持できる。
年次の `inherited_prediction` は `origin='observed_x_post'` のfactを継承元にせず、acceptedかつ
`x_song_claim_v2` ではない根拠だけを計算に使う。active materializationを持てない派生predictionへ
X claimを移し替えて公開gateを迂回させない。
したがって最後のaccepted linkを `retracted` にした時点で行を削除せず公開から消える。

retractはmaterialization IDを明示し、次を同じtransactionで行う。

1. 対象evidence linkを `retracted` にする
2. materializationを `retracted` にし、retraction台帳をappendする
3. 他のaccepted evidenceがあればfactと曲を保持する
4. Xだけで作った孤立曲は `無効` にする
5. Xが昇格した候補曲は、他参照なし・`updated_at` CAS一致時だけ元の `候補` へ戻す

cleanup ownerは現在retractしている行ではなく、同じ曲のCAS timestampに一致する元のcreate/promotionを探す。
そのため複数claimの撤回順に依存しない。evidence item、decision、fact行は監査のため削除しない。

## 6. 運用安全

schema migration、両decision apply、materializer、retractorはすべてdry-run既定で、実行には完全一致confirmを要する。
正本writeは最初にDB複製で同じ操作をpreflightし、成功後にbackupを作る。実DBでもtransactionを開いたまま
`integrity_check` と `foreign_key_check` を行い、両方が通ってからcommitする。検査失敗時はrollbackし、backupを残す。

この工程はpublic JSONの生成・GitHub push・公開deployを行わない。

DB transactionの失敗はcommit前rollbackで戻す。backupは監査・手動復旧用であり、自動restoreには使わない。
誤判断を後から取り消す業務操作はretractorだけを使い、DBファイル差し戻しと混同しない。

## 7. negative acceptance conditions

各条件は、対応する防御を外すとテストが落ちる粒度で固定する。

1. `mentioned` / `unknown` / legacy / claim conflict / 行事名欠落・本文不一致は曲・開催回packetを作らず、materializeしない。
2. retrieval top 20に無いことだけでは`new_song`を選べず、`candidate_missing`決定なしにnoveltyへ進めない。
3. noveltyは全catalog snapshotを持ち、同じnormalized title/aliasが現在存在すれば新曲を作らない。
4. 同じsnapshotで決着済みの`unresolved` / `dependency_pending`を再packet化しない。
5. 未解決はcatalog・開催回・観測・E0 revision/evidenceが変わった場合だけ、新しいpacket IDで再eligibleになる。
   解決済みidentityは選択行が変わらない限り、無関係なentity追加で再提示しない。
6. E0の最新revisionがpendingなら、旧revisionのacceptを再利用しない。
7. report dependency解決済みの開催回をLLM回答で上書きできない。
8. 曲decisionと開催回decisionのobservation SHAが違えばmaterializeしない。
9. 無効曲、merged開催回、stale snapshot、retracted/superseded decisionはmaterializeしない。
10. 既存curated factへX根拠を足してもorigin・song ID・title・confidenceを変更しない。
11. 同じunique identityに別song IDが衝突したらbatch全体をrollbackする。
12. `origin='observed_x_post'` でもactive materializationのない`x_song_claim_v2`根拠は公開しない。
13. active materializationでもfact・evidence・song・occurrence・roleのどれかが違えば公開しない。
14. 最後のaccepted根拠をretractすると非公開になり、別経路のaccepted根拠があれば公開を維持する。
15. Xだけで作った孤立曲は撤回で無効化し、共有曲やCAS不一致の曲を巻き戻さない。
16. schema migration・decision apply・materializer・retractorはdry-run既定、confirm不一致・FK/integrity失敗で正本不変。
17. shadow実行ではmaster DB・state・public JSON・Git差分を一切変更せず、除外理由とhold年齢をartifactへ出す。
18. 同一 `(occurrence_id, normalized_title, role)` の既存factで `song_id` がNULLなら、その列だけをCAS的に補完し、
    origin・title・evidence status・confidence・件数・notes・時刻を変更しない。別の非NULL song IDなら証拠linkも追加せず
    batchをrollbackする。

## 8. 日次shadowの次工程

最初の日次配線は、観測台帳の読取、eligible判定、packet生成、materializer plan、件数・候補rank・保留理由の
artifact出力までに限定する。RDB/state/public JSON/S3/Gitは書かない。旧抽出器の候補生成停止と、
旧review/public reader停止は別gate・別判断にする。

workflow変更はこの実装差分には含めず、保護操作として別の明示承認後に行う。

## 9. コマンド順

```text
run_x_song_identity_migration.py
build_x_song_resolution_packets.py --phase retrieval
apply_x_song_resolution_results.py
build_x_song_resolution_packets.py --phase novelty
apply_x_song_resolution_results.py
build_x_occurrence_resolution_packets.py
apply_x_occurrence_resolution_results.py
python3 -m report_apply.materialize_x_song_resolutions
python3 -m report_apply.retract_x_song_materializations
```

各writerはdry-runレポートを確認してから、同じ入力へ `--execute --confirm '<完全一致文字列>'` を付ける。
