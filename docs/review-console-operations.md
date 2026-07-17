# Review Console Operations

Updated: 2026-06-26 JST
署名: おと（Codex）

## Position

The review console is a local-only operations surface for Uchida-san and oto.

It is for:

- checking whether review queues are piling up,
- reviewing candidates across existing JSON review/queue files,
- saving Uchida-san's decisions,
- exporting event/source/venue decisions,
- staging per-source decision files for deliberate downstream application.

X/RSS account candidates are a direct-decision path. Their buttons write
`registration_decision` back to `data/x_candidate_post_review.json`; they do
not need export or staging.

It is not for:

- direct Master RDB mutation,
- direct Notion writes,
- direct public JSON/S3/CloudFront deployment,
- background scheduling or login-time launch.

## Page Overview

URL:

```text
http://127.0.0.1:8751/
```

The page has four areas.

1. Header actions
   - `操作ガイド ?`
   - `更新 r`
   - `件数を保存 t`
   - `判断をまとめる e`
   - `反映準備 g`

2. Left sidebar
   - total counts: `全件 a`, `未レビュー u`, `決定済み d`, `処理済み p`
   - search field: `/`
   - next-action filters such as `日付確認待ち`, `曲候補待ち`, `根拠URL不足`, `会場確認待ち`
   - category filters such as `YouTube`, `開催日/会場`, `根拠URL`, `会場`
   - always-visible quick keyboard guide
   - source filters such as `登録済みイベント調査` and `YouTubeアクティブ動画レビュー`

3. Review list
   - each card is one review target from an existing JSON queue/review file.
   - the active card has a green outline.
   - `j` / `k` moves the active card.
   - URL chips open evidence/source pages.
   - `Google検索 s` opens a Google search for the event name in a new tab.
   - the detail grid shows the main fields extracted from the source row.

4. Decision panel
   - source-specific decision buttons such as `過去実績として採用`,
     `曲候補を再調査`, `不採用`, `保留`
   - X/RSS account buttons: `情報源にする`, `様子を見る`, `対象外`, `後で見る`
   - `メモ (n)`
   - `元に戻す z`
   - `解除 c`
   - `JSON詳細 i`

The page is keyboard-first. Button labels intentionally include their shortcut
keys because routine operation should not require using the mouse.

## Run Locally

Start the console:

```bash
cd /Users/ryotauchida/bon-odori-collector
python3 run_review_console.py
```

Open:

```text
http://127.0.0.1:8751/
```

The server refuses non-local bind addresses. Keep it on `127.0.0.1`.

Stop the console with `Ctrl-C` in the terminal that started it.

If the browser is already open and code was changed, reload the page.

## Files

Inputs are existing review and queue files under `data/`, currently including:

- `data/registered_event_investigation_queue.json`
- `data/predicted_occurrence_research_queue.json`
- `data/predicted_occurrence_date_review.json`
- `data/missing_source_url_review.json`
- `data/missing_occurrence_venue_review.json`
- `data/accepted_venue_song_missing_venue_review.json`
- `data/historical_promotion_candidate_review.json`
- `data/historical_reference_quality_review.json`
- `data/official_source_review_candidates.json`
- `data/youtube_active_video_review.json`
- `data/youtube_year_backfill_review_queue.json`
- `data/youtube_user_confirmation_queue.json`
- `data/x_candidate_post_review.json`
- `data/rare_signal_backcheck_queue.json`

根拠URL系のレビューソースは公開サイトの対象範囲に合わせる。東京23区外と分かる候補は
内田さんのレビュー対象へ出さず、必要なら生成物の skipped メタデータに監査用として残す。

Console outputs:

- `data/review_console/source_inventory.json`
- `data/review_console/source_inventory.md`
- `data/review_console/decisions.json`
- `data/review_console/exported_decisions.json`
- `data/review_console/exported_decisions.md`
- `data/review_console/staged/*_decisions.json`

Rare signalの裏どり判断は `rare_signal_backcheck` としてステージされる。
`非X根拠で確認済み` を選ぶ場合は、メモ欄に確認URLを貼る。
後続の `export_rare_signal_backcheck_reviews.py` が、そのURLを
`data/rare_signal_backcheck_reviews.json` に変換する。

## Daily Review Flow

1. Open the console.
2. Press `u` to show only `未レビュー`.
3. Check the left sidebar `次アクション` counts.
4. Start from the action that matches today's work, for example `曲候補待ち`,
   `日付確認待ち`, `根拠URL不足`, or `会場確認待ち`.
5. Use `種類` or `ソース` only when you need to narrow the list further.
6. Use `j` / `k` to move through cards.
7. Use `s` to search the event name in Google when the visible URLs are not enough.
8. Use `o` to open the first evidence/source URL when needed.
9. Use `i` to inspect the raw JSON when the card summary is not enough.
10. Use `n` to add a memo first when the decision would be unclear later.
11. Press the appropriate decision button, or use `1`-`5`. The button press
   saves that decision immediately.
11. Repeat until a coherent review batch is done.
12. For event/source/venue decisions, press `e` to export decisions.
13. For event/source/venue decisions, press `g` to stage decisions.
14. Oto or a domain-specific apply script checks the staged file before any
    operational data is changed.

For X/RSS account candidates, stop after the decision button. The decision is
already saved to the source review JSON.

Do not use `ステージ適用` as a production deployment action. It only creates
local apply packets under `data/review_console/staged/`.

## Review Card Fields

Each review card is normalized from a source JSON row.

Card labels:

- red `未レビュー`: no console decision has been saved yet.
- green `決定済み`: a console decision exists in `decisions.json`.
- gray `処理済み`: the source row already appears decided, skipped, ignored,
  or otherwise closed by upstream review data.

Common fields:

- next action: what the operator should decide next, such as `曲候補待ち` or
  `日付確認待ち`.
- source title: which JSON queue/review file the card came from.
- domain: broad operation category such as `YouTube`, `根拠URL`, or `会場`.
- priority: values such as `P0`, `P1`, `high`, `normal`, or source-specific
  priority labels.
- score: source-specific review score.
- action: suggested or detected upstream action.
- URL chips: source URL, candidate source URL, video URL, checked URLs, or
  evidence URLs found in the raw row.
- detail grid: selected scalar fields from the raw row.

The first URL chip is what `o` opens.

## Filters And Counts

`全件 a`

- Shows every normalized item from configured sources.
- Includes unreviewed, decided, and processed/closed rows.

`未レビュー u`

- Shows rows that still need a console-level decision.
- This is the default work view.

`決定済み d`

- Shows rows that have been decided in this console.
- Use this before export to review what will be handed off.

`処理済み p`

- Shows rows inferred as already decided or closed from upstream source data.
- Useful when checking why an item no longer appears in the work queue.

Search `/`

- Filters by visible fields such as title, subtitle, source title, domain,
  next-action label/reason, action, and description.
- Search does not modify files.

## Next-Action Filters

`次アクション` is the primary daily entry point. It hides internal JSON source
complexity and groups work by the operator question.

- `日付確認待ち`: current-year date or prediction needs confirmation.
- `過去実績日付再調査`: an accepted historical reference lacks reliable date or weekday.
- `曲候補待ち`: an accepted historical reference has no song candidates yet.
- `根拠URL不足`: evidence URL or official/semi-official source needs confirmation.
- `会場確認待ち`: venue is missing or needs identity confirmation.
- `同一イベント確認`: a historical or YouTube-derived occurrence may need merging.
- `YouTube候補確認`: video-derived candidates need accept/reject/hold.
- `X/RSS確認`: social/RSS-derived accounts or posts need triage.

Selecting a next-action filter clears `種類` and `ソース` filters to avoid
confusing intersections. `種類` and `ソース` remain available as secondary
diagnostic filters.

## 開催日・会場 と 根拠URL の違い

`開催日・会場` と `根拠URL` は、どちらもイベント名、日付、会場、URLが表示されるため似て見えます。
違いは、何を判断しているかです。

`開催日・会場`

- 判断する問い: このイベントは、対象年にこの日付・この会場で扱ってよいか。
- 見ているもの: イベント本体の中身。
- 例: 2026年開催として載せてよいか、日付が正しいか、会場が正しいか、過去実績から今年候補に上げてよいか、公式確認待ちにするべきか。
- 短い言い方: イベント内容確認。

`根拠URL`

- 判断する問い: その判断の根拠として、このURLを付けてよいか。
- 見ているもの: 証拠リンクの品質と妥当性。
- 例: 公式ページとして使えるか、自治体・主催・会場ページなど信頼できるURLか、既存イベントの `source_url` として入れてよいか、URLは関係あるが今年の確定情報ではないため要調査にするべきか。
- 短い言い方: 証拠リンク確認。

優先順位は、公開情報に直結する `開催日・会場` を先に見て、`根拠URL` はその判断の裏付けを整える作業として見るのが基本です。

## Decision Semantics

The four top-level decisions are console-level review states. They do not
directly mutate Master RDB, Notion, public JSON, or deployment state.

`レビュー採用`

- Use when the displayed candidate is valid enough to move forward.
- The saved value is `decision=accept`.
- It means "include this row in the next staged decision export."
- The concrete downstream action still depends on `適用値` and the source file.
  For X/RSS account candidates, the source file is updated immediately instead.

`却下`

- Use when the displayed candidate is wrong, out of scope, duplicate noise, or
  should not be applied.
- The saved value is `decision=reject`.
- It preserves the rejection reason in the console decision file so the same
  candidate can be skipped or audited later.

`保留`

- Use when the candidate is not ready to apply, but does not need immediate
  active research.
- The saved value is `decision=hold`.
- Typical cases: weak evidence, season mismatch, ambiguous event identity, or
  "not now, keep as context."

`要調査`

- Use when the candidate needs a next research action before it can be accepted
  or rejected.
- The saved value is `decision=needs_research`.
- Typical cases: official source recheck, venue identity check, date mismatch,
  or source URL quality confirmation.

Saving any of these writes only to:

```text
data/review_console/decisions.json
```

Exception: X/RSS account candidates also write the selected account decision to
`data/x_candidate_post_review.json`.

Export and stage write only to:

```text
data/review_console/exported_decisions.json
data/review_console/exported_decisions.md
data/review_console/staged/
```

The stage output is an instruction bundle for oto or a downstream apply script.
It is not itself an operational database update.

Each 反映ルート button carries the source-specific `apply_value` that downstream
apply scripts expect. Examples:

- registered event investigation: `promote_historical_reference`,
  `confirm_current_date`, `reject`, `hold`
- official source review: `official`, `hp`, `post`, `reject`, `hold`
- venue review: `会場追加`, `既存に統合`, `不採用`, `保留`
- missing source URL review: `fill_source_url`, `source_research_required`, `hold`

X/RSS account candidates use direct decisions instead:

- `情報源にする`: writes `registration_decision=登録`
- `様子を見る`: writes `registration_decision=監視`
- `対象外`: writes `registration_decision=不採用`
- `後で見る`: writes `registration_decision=保留`

## 登録済みイベント調査の反映ルート

`登録済みイベント調査` は、2026年の開催確定と過去実績採用を混同しやすいため、反映ルートを明示して扱う。

全体フロー図:

- `docs/historical-reference-review-flow.md`

`promote_historical_reference`

- 表示名: `過去実績として採用`
- 意味: 過去年の開催実績として採用する。
- 前提: 過去実績の日付があり、曜日を算出できること。
- 2026年の `date_start` は入れない。
- 公開上は `過去実績あり・今年未確認` や `日程未定` 側のルートに進む。
- 過去実績日がないカードでは選ばない。画面上も無効化され、直接入力して保存しても止まる。

`confirm_current_date`

- 表示名: `2026年日程確認済みにする`
- 意味: 今年の公式/主催/自治体情報などで、2026年開催日が確認できた場合だけ使う。
- カードに2026年日程が無い場合は保存できない。
- 過去年YouTubeや過去実績だけでは選ばない。

`reject`

- 表示名: `不採用`
- 意味: 候補として使わない。

`hold`

- 表示名: `保留`
- 意味: 今は判断しない。

`needs_research`

- 表示名: `要調査`
- 意味: 採用前に日付、曜日、根拠URL、同一イベント性、または曲候補を追加確認する。

人間に確認してほしい焦点は、カードごとに分ける。

- 過去実績日が無い場合: `日付確認待ち` として、日付・曜日を確認する。
- 過去実績日はあるが会場が不足している場合: `会場確認待ち` として、会場候補を採用するか、要調査に回すか、保留するかを確認する。日付を人間に聞く対象にはしない。ボタンも `過去実績＋会場を採用` / `会場を要調査` のように会場焦点で表示する。
- 過去実績日と会場はあるが2026年日程が無い場合: 2026年日程は未確認のまま過去実績として採用するか、追加調査に回すかを確認する。ボタンは `過去実績だけ採用` / `2026年日程を要調査` のように表示する。

根拠が十分で機械的に確信できるものは、人間に確認しない。

- 例: 京橋プラザは、公式施設ページで `京橋プラザ区民館` と住所を確認でき、複数の観測根拠で `2025-07-19`、`銀座一丁目東町会・新富町会`、`京橋プラザ` が一致する場合は `自動解決` として `closed` にする。
- この場合はレビュー画面の `未レビュー` には出さず、会場未設定の開催回レビューでは `ready_new_venue_candidate` として会場作成と開催回紐づけの適用候補に回す。
- 自動解決にできない場合だけ、`会場確認待ち` として人間に「会場を採用するか、要調査か、保留か」を聞く。

既にマスターDBへ `historical_reference` が登録済みの調査キューも、人間に確認しない。

- 例: `ゐの市盆踊り～不忍夢～` は `occurrence_dates` に `2025-08-09〜2025-08-11 / 上野恩賜公園` が登録済みなので、古い `missing_date` キューとして `自動解決` の `closed` にする。
- この場合は2026年日程を確認済みにするわけではない。あくまで `過去実績は既に登録済みなので、同じ確認を人間に聞かない` という扱い。

登録済みイベント調査カードには `確認してほしいこと` が表示される。その他のカードには `採用後に残る情報` が表示される。

- `過去実績日`: 2025年など過去年の具体日。ここが未確認なら過去実績採用しない。
- `曜日`: 日付から算出した曜日。日付がなければ確定できない。
- `証拠URL`: 採用後の根拠確認に使えるURL件数。
- `過去候補強度`: observed candidate の confidence とソース件数。
- `曲候補`: YouTube/曲実績側から見つかった曲名候補。候補があっても、このボタンだけでは曲マスタへ確定登録しない。
- `曲収集ルート`: `song_occurrences` / YouTubeバックフィル側の別工程で確認する。

重要: `過去実績として採用` は、2026年開催確定ではない。公開価値はあるが、開催確定フィルタには含めない。過去実績日・曜日・根拠URLが足りない場合は、採用より `保留` または `要調査` を優先する。

## 採用済み過去実績の品質レビュー

`採用済み過去実績品質レビュー` は、すでに公開側で過去実績扱いになっているイベントを再点検する。

対象:

- 過去実績日がない、または日付が不正。
- 日付から曜日を算出できない。
- 過去実績として残っているが曲候補がない。

現在の公開データでは、過去実績系93件のうち日付なしは0件、曲なしは65件。曲なしの65件がこのレビューソースに出る。

主な反映ルート:

- `needs_date_research`: 日付・曜日を再調査。
- `needs_song_research`: 曲候補を再調査。
- `keep_historical_reference`: 不足を把握したうえで過去実績として維持。
- `remove_historical_reference`: 公開価値が低い過去実績として外す判断へ回す。
- `hold`: 今は判断しない。

## What Each Save Does

Pressing a反映ルート button writes or updates one entry in:

```text
data/review_console/decisions.json
```

Saved fields include:

- `item_id`
- `source_id`
- `item_key`
- `decision`
- `decision_label`
- `note`
- `apply_value`
- `apply_value_label`
- `decision_route`
- `reviewer`
- `updated_at`
- `updated_by`

Pressing `元に戻す z` restores the previous `decisions.json` state for the
last saved or cleared item. Press it repeatedly to go back multiple operations.
The undo stack is local and stored in:

```text
data/review_console/decision_history.json
```

Pressing `解除 c` removes that one `item_id` from `decisions.json`.

Neither the route button nor `解除` edits the source review/queue JSON files.

## Keyboard Operation

The console is keyboard-first. Normal Tab navigation also works for every
button, input, filter, and link.

Primary review keys:

- `j` / `ArrowDown`: next item
- `k` / `ArrowUp`: previous item
- `1`-`5`: press the visible 反映ルート button and save that decision
- `z`: undo the most recent save/clear operation
- `c`: clear the active item's console decision
- `n`: focus the active item's memo field
- `s`: Google-search the active item's event name
- `i`: open JSON detail for the active item
- `o`: open the first evidence/source URL for the active item
- `/`: focus search
- `Esc`: leave an input field, close JSON detail, or re-center the active item

View and batch keys:

- `u`: show unreviewed items
- `a`: show all items
- `d`: show decided items
- `p`: show processed/closed items
- `r`: refresh
- `t`: write source inventory
- `e`: export decisions
- `g`: stage decisions

When the cursor is inside the search field, memo field, apply value field, or a
select box, typed characters are treated as input. Press `Esc` to return to card
navigation.

Open `操作ガイド ?` on the page for the same explanation without leaving the
console.

## Header Actions

`更新`

- Re-reads the current review/queue JSON files and the console decision file.
- Use when another script has regenerated review queues, or after saving/clearing
  decisions and you want to reload the current view.
- Keyboard: `r`.
- Writes: none.

`棚卸し保存`

- Saves the current source breakdown to local inventory files.
- Outputs:
  - `data/review_console/source_inventory.json`
  - `data/review_console/source_inventory.md`
- Use when you want a timestamped snapshot of how many review items are piling
  up by source and category.
- Keyboard: `t`.
- Writes: local inventory files only.

`エクスポート`

- Writes all saved console decisions into one consolidated decision export.
- Outputs:
  - `data/review_console/exported_decisions.json`
  - `data/review_console/exported_decisions.md`
- Use after saving decisions that should be handed to oto or checked before
  staging.
- Keyboard: `e`.
- Writes: local export files only.

`ステージ適用`

- Groups exported decisions by source and writes per-source staged decision
  files for downstream apply scripts.
- Outputs:
  - `data/review_console/staged/*_decisions.json`
  - `data/review_console/staged/stage_apply_result.json`
- `review_inbox` decisions are split into `change_request`, `domain_stage`,
  `research_followup`, and `no_apply` packets. The same operation also writes
  `review_inbox_decision_updates.json` for a future CAS writer; it does not
  update the Master RDB itself.
- Despite the label, this does not update Master RDB, Notion, public JSON,
  S3, CloudFront, DynamoDB, or Google Calendar.
- Use when the reviewed decisions are ready to become an explicit apply packet.
- Keyboard: `g`.
- Writes: local staged files only.

Recommended use:

- Use `更新 r` freely.
- Use `棚卸し保存 t` when you want a record of queue pressure.
- Use `エクスポート e` after a meaningful review batch.
- Use `ステージ適用 g` only when the saved decisions are ready for oto or a
  downstream apply script to inspect.

## エクスポートとステージ適用の違い

`エクスポート` は、保存済みの判断を人間が確認できる一覧と、機械が読めるJSONにまとめる操作です。レビュー結果レポートの段階です。

- 目的: 内田さんが判断した内容を確認・共有・見直しする。
- イメージ: "今回こう判断しました" の一覧。
- 出力:
  - `data/review_console/exported_decisions.json`
  - `data/review_console/exported_decisions.md`
- ソース別のapply用パケットはまだ作らない。
- Master RDB、Notion、公開JSON、S3、CloudFront、DynamoDB、Google Calendarは変更しない。

`ステージ適用` は、保存済み/エクスポート済みの判断をソース別に分け、後続のapplyスクリプトが確認できる形に箱づめする操作です。実反映前の受け渡し準備です。

- 目的: 判断をソース別に分け、apply前に確認できるパケットを作る。
- イメージ: "次の処理に渡すための作業箱づめ"。
- 出力:
  - `data/review_console/staged/*_decisions.json`
  - `data/review_console/staged/stage_apply_result.json`
- ここでもまだ Master RDB、Notion、公開JSON、S3、CloudFront、DynamoDB、Google Calendarは変更しない。
- 実データの変更は、この後に領域別applyスクリプトでdry-run確認してから明示実行する。

通常の順番:

```text
レビューする -> 保存 -> エクスポートで確認 -> 問題なければステージ適用 -> おと/個別applyが実反映
```

## 反映待ちの見落とし防止

ステージ適用後に個別applyを動かし忘れることは、設計上あり得ます。
レビューコンソールは安全のため、本番DBや公開データへの反映を自動実行しないからです。

見落とし防止として、コンソールは `data/review_console/staged/` を確認し、ステージ済みのapply用パケットがある場合に画面上部へ `反映待ちステージあり` を表示します。

表示される状態:

- `反映待ちステージあり`: `staged/*_decisions.json` が残っている。個別applyをdry-runしてから明示実行する。
- `ステージが古い可能性`: ステージ適用後に `decisions.json` が更新された。個別apply前にもう一度 `ステージ適用 g` を行う。
- `反映確認済み`: 個別applyをdry-run後に明示実行したことをローカルに記録済み。
- `反映待ちなし`: ステージ済みのapply用パケットがない。

ステージ適用をやり直すと、前回の `staged/*_decisions.json` は作り直されます。これにより、前回のステージファイルと今回の判断が混ざることを避けます。

個別applyが完了した後は、画面上部の `個別apply済みとして記録` を押します。これは実反映を実行するボタンではなく、すでに外側で個別applyを完了したことを `data/review_console/staged/stage_apply_ack.json` に記録して、反映待ちバナーを消すためのものです。

## CLI

Write a current source inventory:

```bash
python3 run_review_console.py --inventory
```

Export saved decisions:

```bash
python3 run_review_console.py --export
```

Dry-run staged application:

```bash
python3 apply_review_console_decisions.py
```

Write staged per-source decision files:

```bash
python3 apply_review_console_decisions.py --write
```

`apply_review_console_decisions.py --write` writes only under
`data/review_console/staged/`. It does not write Master RDB, Notion, public
JSON, S3, CloudFront, DynamoDB, or Google Calendar.

## Output Review Before Apply

Before applying anything outside the console, check:

```bash
python3 run_review_console.py --export
python3 apply_review_console_decisions.py --write
```

Then inspect:

```text
data/review_console/exported_decisions.md
data/review_console/exported_decisions.json
data/review_console/staged/
```

The staged files are grouped by `source_id`. A downstream script or oto should
read the source-specific staged file, verify the target source file and the
decision labels, then run the appropriate domain apply script with its own
dry-run/apply controls.

If a source has no saved decisions, no staged source file is created for it.

## Current Inventory

The latest local inventory can be regenerated at any time:

```bash
python3 run_review_console.py --inventory
```

As of the latest local inventory, the console found 13 sources and 846
pending review items. The generated breakdown is in
`data/review_console/source_inventory.md`.

The latest implementation inventory was:

| Domain | Pending |
| --- | ---: |
| YouTube | 564 |
| 開催日/会場 | 79 |
| 過去実績 | 70 |
| 根拠URL | 61 |
| X/RSS | 30 |
| 会場 | 26 |
| 開催日 | 16 |

## Adding A Source

Add a `ReviewSource` entry in `review_console/data.py`.

Minimum fields:

- `id`
- `title`
- `path`
- `rows_path`
- `domain`
- `key_fields`
- `title_fields`

Prefer stable IDs such as occurrence IDs, candidate IDs, or video IDs for
`key_fields`. Avoid using only row index when a row may move between runs.

After adding a source:

1. Run `python3 run_review_console.py --inventory`.
2. Confirm the source appears in `data/review_console/source_inventory.md`.
3. Open the console and confirm cards render with stable titles and URLs.
4. Add or update tests if the source needs special normalization.

## Production Boundary

The console is allowed to write local decision artifacts only.

If a future version directly mutates operational data, update this document and
`docs/manual-auto-operations-inventory.md` first, then add explicit dry-run,
confirmation, and backup behavior.

## Troubleshooting

Page does not load:

- Confirm the server is running.
- Start it again with `python3 run_review_console.py`.
- Check that the URL is `http://127.0.0.1:8751/`.

Shortcut does not work:

- If the cursor is inside search, memo, apply value, or the item count select,
  press `Esc` first.
- If a dialog is open, press `Esc` to close it.
- Reload the page after code changes.

Counts look stale:

- Press `更新 r`.
- If a review-generating script ran externally, press `棚卸し保存 t` afterward
  when you want a recorded count snapshot.

Oto primary research review:

- Oto may do first-pass research for `日付確認待ち`, especially when official,
  municipal, organizer, venue, or reliable local pages must be checked.
- Save decisions one item at a time. Research may be parallelized, but decision
  writes must be sequential so local decision history stays complete.
- Use 2026 direct evidence only for current-year confirmation.
- If 2026 direct evidence is found but the review row has no current-year date
  field, save `要調査` and write `日付補完apply待ち` in the note.
- If only past-year evidence or a weekday rule is found, do not confirm the
  2026 date. Save as historical reference when the row supports it, otherwise
  save `要調査` with the evidence year and URL.

Saved decision disappeared:

- Check whether `解除 c` was pressed.
- Check `data/review_console/decisions.json`.
- Confirm the source row still has the same stable key fields. If upstream
  regeneration changed the key fields, the console may see it as a new item.

Stage output changed no production data:

- This is expected. `ステージ適用 g` is intentionally local-only.
- Use a domain-specific apply script after checking the staged JSON.

## Verification

For code changes to the console, run:

```bash
python3 -m pytest tests/test_review_console.py
python3 -m py_compile review_console/data.py review_console/server.py run_review_console.py apply_review_console_decisions.py
node --check review_console/static/app.js
```
