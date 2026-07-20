# B5 consolidated review-inbox cutover runbook

## Cutover contract

The local review console starts in `inbox` mode unless the operator explicitly
sets `REVIEW_CONSOLE_READER_MODE` or passes `--reader-mode`.  The three modes are
mutually exclusive:

- `inbox`: read only `data/review_inbox.json`.
- `legacy`: read only the retained legacy source snapshots; this is the rollback entrypoint.
- `canary`: retain the historical B1 missing-venue canary behavior only.

The source writer accepts only the atomic flag pairs `legacy + writer enabled`
and `inbox + writer disabled`.  Mixed pairs fail before artifact access.  Canary
writes remain restricted to the legacy pair.

## Legacy output closure

`collect.yml` still builds fresh machine inputs inside the job because the
adapters must compare the exact current collector output.  After cutover those
files are not committed and are not console inputs.  The last committed legacy
JSON/Markdown snapshots remain available read-only for rollback.

The cutover removes these new human-facing outputs from the normal commit path:

- the two daily keyboard-review HTML files;
- daily song and term review queues;
- rare-signal backcheck queue;
- YouTube active/year legacy review queues;
- accepted venue-song and historical-quality legacy review queues.

The consolidated `data/review_inbox.json` projection remains the only committed
human-review input.

## Closure evidence

The user explicitly requested accelerated manual execution instead of waiting
for the daily cron.  These `workflow_dispatch` runs use the same `collect.yml`
job graph, variables, builders, CAS store, and artifact uploads as the scheduled
event.  They are therefore retained as the two consecutive production
observations for this cutover exception.

- YouTube observation 1: run `29716343539`, 172/172 parity, unmapped 0.
- YouTube observation 2: run `29717567678`, 172/172 parity, changed 0,
  unchanged 172, unmapped 0, Rstart=Rend
  `51a4057e2fd10ea609044f04d1f880a053fe892b7d5a6ffa378a84e72a67c00f`.
- Low-priority observation 1: run `29717567678`, 257 items
  (song 3, term 21, venue 5, historical quality 69, publication gap 159),
  all five sources parity true and unmapped 0.
- All reports above: SQLite integrity `ok`, foreign-key violations 0,
  domain-table counts unchanged, public projection unchanged, and complete CAS
  checksum continuity.
- Independent production artifact review: こと（Claude Code）, Findingなし.

The post-cutover production run must provide the second low-priority observation
and prove that no legacy queue/UI commit occurs.

## JSON fallback hard failure

`export_public_events.py` records every prediction supplied only by the legacy
JSON.  A nonzero `json_fallback_count` now raises and stops the export; it no
longer warns and continues.  This keeps the last successful public projection
instead of silently reintroducing a legacy data source.

## Rollback

1. Set the three workflow writer environments back to
   `REVIEW_INBOX_READER_MODE=legacy` and
   `REVIEW_INBOX_LEGACY_WRITER_ENABLED=true` as one reviewed change.
2. Restore the legacy queue/UI `git add` lines only if operators need fresh
   legacy files; otherwise use the retained last-good snapshots.
3. Start the console with `--reader-mode legacy`.
4. Run one full `collect.yml` execution and verify parity, CAS continuity,
   public projection invariance, and no loss of inbox decisions.
5. Do not delete or rewrite `review_inbox_items` during rollback.

— おと（Codex）
