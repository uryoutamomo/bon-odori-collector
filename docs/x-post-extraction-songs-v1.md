# E0X-S: X投稿の曲claim観測台帳 v2.0

作成: 2026-08-16 / おと（Codex）

上位は `docs/x-post-extraction-e0x-v1.md`。この段はX投稿から本文由来の曲claimを写し、
`data/x_song_observations.json` へ止める。曲マスタとの同一性、開催回との同一性、公開可否は決めない。

## 0. 設計判断の基準

- LLMの一業務は単純にする。この段で聞くのは、本文にある曲名・関係する行事・claim種別・根拠引用の書き写しだけ。
- 採点は抽出のついでであり、点数の不整合を理由に本文由来の曲claimを捨てない。
- 回答JSON内の置き場所である `origin` を、告知・実測などの意味に使わない。
- 公開可能な関係factは後段で作る。この段は `songs`、`song_aliases`、`event_occurrences`、
  `occurrence_songs` を読まず、書かない。

## 1. v1.1から直す問題

v1.1は `events[].songs` を告知、`observations[].songs` を実測として扱う前提を後段へ渡していた。
しかし `observations` には願望・思い出・一般的な言及も入るため、
「来年はマツケンサンバをやってほしい」を実績曲として公開できてしまう。

また、同じ行事について実績曲と願望曲が一投稿に混在する。したがって `claim_type` は行事グループではなく
曲ごとに持たせる。開催回は年ごとのentityなので、5点イベントが既に持つ日付・会場・E0レポート系譜も捨てない。

## 2. 回答契約（採点基準 v3.3）

4点など、開催情報レポートを作らない投稿は次の形を使う。

```json
{
  "no": 12,
  "s": 4,
  "observations": [
    {
      "event_name": "上野ゐの市盆踊り",
      "event_date_start": "2026-08-15",
      "event_date_end": null,
      "venue_name": "上野恩賜公園",
      "ward": "台東区",
      "event_quote": "上野ゐの市盆踊りで",
      "song_claims": [
        {
          "song_name": "東京音頭",
          "claim_type": "observed",
          "evidence_quote": "東京音頭を踊った"
        },
        {
          "song_name": "マツケンサンバ",
          "claim_type": "mentioned",
          "evidence_quote": "マツケンサンバもやってほしい"
        }
      ]
    }
  ],
  "glossary": ["盆オドラー"]
}
```

5点は既存 `events[]` の各要素へ同じ `song_claims` を追加する。

```json
{
  "event_name": "試験盆踊り",
  "date_start": "2026-08-20",
  "date_end": "2026-08-21",
  "venue_name": "試験公園",
  "ward": "足立区",
  "quote": "8月20日・21日に試験公園で試験盆踊りを開催",
  "song_claims": [
    {
      "song_name": "東京音頭",
      "claim_type": "announced",
      "evidence_quote": "曲目は東京音頭です"
    }
  ]
}
```

### claim_type

| 値 | 意味 |
|---|---|
| `announced` | その開催回で流す予定・選曲済みだと本文が述べる |
| `observed` | その開催回で実際に流れた・踊ったと本文が述べる |
| `mentioned` | 願望・一般論・開催回不明の思い出など、開催回の予定・実績ではない |
| `unknown` | 本文から区別できない |

迷ったら `unknown` にする。後段で公開候補になれるのは `announced` と `observed` だけである。

### 書き写しの約束

- `song_name`、observations側の `event_name`、会場名、quoteは本文にある表記のまま。正式名へ直さない。
- 5点events側の `event_name` だけは、従来E0契約どおり本文に固有名がなくても短い識別名を付けてよい。
  この場合も `event_name_in_text=false` として区別され、E0系譜なしには開催回手がかりとして使わない。
- `evidence_quote` は本文の連続した部分文字列で、必ず曲名を含む。
- `event_quote` は任意だが、付ける場合は本文の連続した部分文字列である。
- 行事が本文から分からなければ `event_name: null`。推測で補わない。
- 4点の日時・会場は本文に明示され、書き写せる場合だけ付ける。投稿時刻から開催年を推測しない。
- `glossary` は従来どおり本文表記を文字列で返す。

## 3. 後方互換

採点基準 v3.3 は `song_claims` を正規形とする。ただし取り込みは既存回答を失わない。

- 旧 `songs: ["東京音頭"]` は受け入れ、`claim_type="unknown"`、quoteなしとして記録する。
- claim_typeの欠落・不正値・型不正は `invalid_claim_type` issueを残し、`unknown` にする。
- 曲名やquoteの型不正、本文照合失敗はその曲だけを落とし、兄弟曲・glossary・採点・E0レポートを続ける。
- v1の既存観測はIDを変えず、欠落 `claim_type` を読み取り時に `unknown` と扱う。再判定はしない。

## 4. 本文照合

NFKC、空白・改行・URL・中黒・長音の除去後に照合する。ひらがなとカタカナは同一視しない。

- `song_name` は本文に存在しなければ `song_not_in_text`。
- `evidence_quote` は本文に存在しなければ `claim_quote_not_in_text`。
- v2のquoteは正規化後に `song_name` を含まなければ `song_not_in_claim_quote`。
- `event_quote` は本文に存在しなければ `event_quote_not_in_text` とし、開催回手がかりだけ無効化する。
- 日付はISO日付かつpacketの `machine_extracted_dates` に存在すること、日付範囲が逆転しないことを検査する。
- 会場とwardを付ける場合は本文に存在することを検査する。
- `event_context_valid=true` には、本文内の行事名に加えて日付・会場・event quoteのいずれかの
  検証済みanchorが必要である。空contextはvalidにしない。
- observations側の `event_name` は本文に存在しない場合も曲claim自体は残すが、
  `event_name_in_text=false` として後段の開催回候補生成には使わせない。

## 5. E0レポート系譜

5点イベントがE0検査を通り、実際にレポートが生成または再利用された場合だけ、曲観測へ次を残す。

- `event_report_id`: レポートの `source.report_id`
- `report_event_id`: レポート内イベント要素の安定ID
- `event_dependency_key`: E0受信箱の revision family key

E0レポート側のイベントにも `entry_id=report_event_id` を書く。受信箱アダプタは既存どおり `entry_id` を
最優先キーに使うので、後段は `event_dependency_key` から同じイベント要素のE2判断・適用結果を追跡できる。
ただしv1で既に生成済みのレポートに `entry_id` が無い場合は、E0が従来使っていた
行事名・年・会場由来の `entry_*` を補う。新しい `xrevent_*` へ変えて既存revision familyを分裂させない。

過去日、URL欠落、quote・日付・会場の検査失敗では曲claimは残すが、存在しないレポート系譜を付けない。
曲観測を先に作って架空IDを付けないため、イベント検証結果を確定してから材料台帳を組み立てる。

## 6. 出力契約

```json
{
  "schema_version": 2,
  "generated_by": "apply_x_extraction_results.py",
  "updated_at": "...",
  "observations": [
    {
      "observation_schema_version": 2,
      "observation_id": "xsong2_...",
      "claim_family_id": "xsclaim_...",
      "tweet_id": "...",
      "url": "...",
      "posted_at": "...",
      "account": "@...",
      "officiality": "...",
      "event_name": "試験盆踊り",
      "event_name_in_text": true,
      "event_report_verified": true,
      "song_name": "東京音頭",
      "claim_type": "announced",
      "evidence_quote": "曲目は東京音頭です",
      "origin": "events",
      "event_date_start": "2026-08-20",
      "event_date_end": "2026-08-21",
      "event_venue_name": "試験公園",
      "event_ward": "足立区",
      "event_context_valid": true,
      "event_report_id": "x_event_...",
      "report_event_id": "xrevent_...",
      "event_dependency_key": "official_notice:x_event_...#xrevent_...",
      "batch_id": "...",
      "score": 5,
      "text": "...",
      "first_seen_at": "..."
    }
  ]
}
```

`origin` は `events` / `observations` という系譜だけを表す。evidence_statusやroleへ変換しない。

`event_name_in_text` は行事名が本文にあったか、`event_report_verified` は実在するE0レポート系譜が付いたかを
別々に表す。後段はこの2つを混同しない。

`claim_family_id` は投稿・行事文脈・曲名・根拠quoteから作る。`observation_id` はそこへclaim_typeを加える。
同じ回答の再取り込みは同じIDになり、claim_typeだけが食い違う再回答は同じfamilyの競合として残る。
同一familyに複数のclaim_typeがある場合、後段は自動公開せず `claim_type_conflict` にする。

## 7. 既存15件

既存行は再採番・再判定しない。台帳読込時に次の既定を補う。

- `observation_schema_version=1`
- `claim_type=unknown`
- 新しいevent context／report lineageはnull

必要なら明示的な一回限りmigrationを用意し、件数と既存IDが不変であることをテストする。

## 8. 旧経路の退場条件

旧抽出器の新規候補生成停止と、旧レビュー／公開経路の停止は別gateにする。

1. 同じ投稿集合で曲名precision/recall、複数曲、表記ゆれ、一般語を層別比較する。
2. 新経路で候補recall、開催回解決率、重複新曲率、保留期間、positive dry-run、retract試験を測る。
3. 最初は日次shadowだけを動かし、RDBとstateは書かない。

## 9. negative acceptance conditions

既存25条件を維持し、v2では少なくとも次を追加する。

1. 同じ行事グループの実測曲と願望曲を別claimとして保持する。
2. `origin` を入れ替えてもclaim_typeは変わらない。
3. 欠落・不正claimはunknownになり、曲・兄弟材料を失わない。
4. evidence_quoteが本文に無い、または曲名を含まないclaimだけを落とす。
5. events由来の日時・会場・wardを同じイベント要素から保持する。
6. observations由来へ別イベントのcontextを推測コピーしない。
7. 実在するレポートだけがreport ID・entry ID・dependency keyを持つ。
8. 過去日・URL欠落・不正イベントでも曲claimは残り、dangling dependencyは作られない。
9. 同じ投稿・行事・曲でも別開催回文脈なら別観測になる。
10. v2回答の再取り込みは冪等である。
11. 旧文字列形式はunknownとして受理される。
12. v1既存行のID・件数は不変で、claim_type欠落はunknownになる。
13. 同一familyでclaim_typeが競合した場合、後段公開不可になる。
14. 点数とeventsの形が不整合でも曲claimを救い、E0レポートだけ5点に限定する。
15. `results` が配列でなくてもクラッシュしない。
16. 取り込みレポートにclaim_type別の追加件数・累計を出す。
17. claim追加後も既存E0のreport、bundling、state outcomeは変わらない。
18. この段に `songs` / `event_occurrences` / `occurrence_songs` の読み書き口が無い。

---

おと（Codex）
