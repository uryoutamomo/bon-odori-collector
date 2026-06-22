# Ph2 event occurrence apply runbook

Ph2 now uses an RDB-primary path. `data/bon_odori_master.sqlite` is the
operational source of truth for reviewed event occurrence updates. Notion is a
legacy/read-only reference for this path; do not write RDB changes back to
Notion unless Uchida-san explicitly reopens that decision.

Do not run production apply commands until the dry-run output has passed Koto
review and Uchida-san has explicitly approved the step.

## Policy

- Apply reviewed date/venue changes to the master RDB first.
- Preserve legacy Notion page ids in `external_record_links` when they already
  exist, but do not create new Notion pages just to mirror RDB changes.
- Use Notion snapshots only as input/reference material and drift evidence.
- Regenerate public JSON from the RDB and review collector/site diffs before
  any public deploy.
- Public deploy remains a separate approval step.

## Step 0: Dry-run review

For the general Ph2 plan:

```sh
python3 build_ph2_event_occurrence_apply_plan.py
python3 dry_run_ph2_event_occurrence_apply.py
python3 audit_master_rdb.py
```

For venue-change cases that need new curated venue rows, use a case-specific
dry-run plan before writing the master DB. Example:

```sh
python3 build_ph2_ebara_fifth_venue_plan.py
```

Expected current result after 荏原第一 and 品川第二 have already been applied:

- Current official auto-apply plan: `applied=0`, because the remaining current
  official candidate, 荏原第五, requires a new venue review.
- 荏原第五 venue-change dry-run: `issues=0`.
- Audit may report medium `source_snapshot_drift` until the master DB is
  refreshed from the latest Notion/source snapshots during cutover while
  preserving DB-only review state. Do not force-rebuild from snapshots after
  review queues or apply state have been recorded in the master DB.

## Step 1: RDB apply only

Apply only after the relevant dry-run plan is reviewed. The apply step should:

- create a timestamped backup under `data/backups/`,
- update only `data/bon_odori_master.sqlite`,
- avoid Notion writes,
- avoid public JSON writes,
- record enough JSON/MD output for Koto to verify the exact mutation.

For simple current-official updates, use:

```sh
python3 dry_run_ph2_event_occurrence_apply.py \
  --apply \
  --event-name '<reviewed event name>' \
  --confirm 'APPLY PH2 EVENT OCCURRENCE'
```

For new-venue cases such as 荏原第五, use a dedicated apply script matching the
reviewed dry-run plan. Do not use the generic apply path until it understands
new venue creation without Notion write-back.

For historical-reference rows, keep the default path non-writing until venue
lookup and human-review flags are cleared:

```sh
python3 dry_run_ph2_event_occurrence_apply.py \
  --mutation-type historical_reference \
  --out-db data/ph2_historical_reference_dry_run.sqlite \
  --out-json data/ph2_historical_reference_dry_run_report.json \
  --out-md data/ph2_historical_reference_dry_run_report.md
```

Reviewer-only simulations may add `--include-blocked` against the copied DB to
confirm the proposed rows insert cleanly. Historical references must insert
`occurrence_dates.date_type = 'historical_reference'` only and must not update
`event_occurrences.date_start`, `date_end`, `date_status`, or `venue_id`.

Stop after this step for Koto review.

## Step 2: Public export dry-run

After RDB review passes, regenerate local public outputs from the master RDB and
compare them against the current collector/site state. Do not deploy yet.

The exact export command depends on which Ph2 exporter is being exercised, but
the review must show:

- the intended event/date/venue change,
- no unrelated wholesale replacement of `events_public.json`,
- no reintroduction of frozen legacy song occurrence generation,
- public sync guard status and any remaining individual-review diffs.

Stop after this step for Koto review and Uchida-san approval.

## Step 3: Public deploy

Deploy only when Uchida-san explicitly approves public reflection. The normal
deployment source is the site repository and GitHub Actions path described in
the project instructions, not a local S3 sync from this machine.
