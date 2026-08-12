CREATE INDEX idx_event_investigation_tasks_priority ON event_investigation_tasks(priority_label, priority_score)

CREATE INDEX idx_evidence_platform ON evidence_items(platform)

CREATE INDEX idx_historical_promotion_candidates_target ON historical_promotion_candidates(target_occurrence_id)

CREATE INDEX idx_observed_occurrence_songs_match ON observed_occurrence_songs(match_status)

CREATE INDEX idx_observed_occurrences_match ON observed_occurrences(match_status)

CREATE INDEX idx_occurrence_songs_occurrence ON occurrence_songs(occurrence_id)

CREATE INDEX idx_occurrences_year ON event_occurrences(event_year)

CREATE INDEX idx_predicted_occurrence_dates_target ON predicted_occurrence_dates(target_occurrence_id, predicted_year)

CREATE INDEX idx_series_key ON event_series(series_key)

CREATE INDEX idx_songs_title ON songs(normalized_title)

CREATE INDEX idx_venues_name ON venues(normalized_name)

CREATE INDEX idx_place_nodes_parent ON place_nodes(parent_place_id)

CREATE INDEX idx_place_nodes_name ON place_nodes(normalized_name)

CREATE INDEX idx_place_aliases_name ON place_aliases(normalized_alias)

CREATE TABLE event_investigation_tasks (
  task_id TEXT PRIMARY KEY,
  occurrence_id TEXT,
  notion_page_id TEXT NOT NULL,
  event_name TEXT NOT NULL,
  event_year INTEGER NOT NULL,
  status TEXT NOT NULL,
  missing_date INTEGER NOT NULL DEFAULT 0,
  missing_venue INTEGER NOT NULL DEFAULT 0,
  known_venue_names_json TEXT NOT NULL DEFAULT '[]',
  source_url TEXT,
  observed_candidate_count INTEGER NOT NULL DEFAULT 0,
  observed_candidate_confidence TEXT,
  priority_score INTEGER NOT NULL DEFAULT 0,
  priority_label TEXT NOT NULL,
  recommended_action TEXT NOT NULL,
  reason_codes_json TEXT NOT NULL DEFAULT '[]',
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (occurrence_id) REFERENCES event_occurrences(occurrence_id)
)

CREATE TABLE event_occurrences (
  occurrence_id TEXT PRIMARY KEY,
  origin TEXT NOT NULL DEFAULT 'curated',
  series_id TEXT NOT NULL,
  event_year INTEGER NOT NULL,
  occurrence_sequence INTEGER NOT NULL DEFAULT 1,
  display_name TEXT NOT NULL,
  venue_id TEXT,
  date_start TEXT,
  date_end TEXT,
  date_status TEXT NOT NULL DEFAULT 'unknown',
  lifecycle_status TEXT NOT NULL DEFAULT 'draft',
  current_event_state TEXT NOT NULL DEFAULT 'predicted',
  date_certainty_tier TEXT NOT NULL DEFAULT 'historical_reference',
  confidence TEXT NOT NULL DEFAULT 'unknown',
  source_kind TEXT,
  source_url TEXT,
  inherited_from_occurrence_id TEXT,
  public_intro_override TEXT,
  detail TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(series_id, event_year, occurrence_sequence),
  FOREIGN KEY (series_id) REFERENCES event_series(series_id),
  FOREIGN KEY (venue_id) REFERENCES venues(venue_id),
  FOREIGN KEY (inherited_from_occurrence_id) REFERENCES event_occurrences(occurrence_id)
)

CREATE TABLE event_series (
  series_id TEXT PRIMARY KEY,
  origin TEXT NOT NULL DEFAULT 'curated',
  series_key TEXT NOT NULL UNIQUE,
  canonical_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  usual_venue_id TEXT,
  area TEXT,
  program_type TEXT,
  annual_months_json TEXT NOT NULL DEFAULT '[]',
  schedule_rule_type TEXT,
  schedule_rule_detail TEXT,
  public_intro TEXT,
  source_url TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (usual_venue_id) REFERENCES venues(venue_id)
)

CREATE TABLE evidence_items (
  evidence_id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  source_key TEXT,
  source_id TEXT,
  account_key TEXT,
  title TEXT,
  text_excerpt TEXT,
  url TEXT,
  published_at TEXT,
  observed_at TEXT,
  detected_event_date TEXT,
  raw_status TEXT,
  raw_json TEXT NOT NULL DEFAULT '{}'
)

CREATE TABLE external_record_links (
  system TEXT NOT NULL,
  source_key TEXT NOT NULL,
  external_id TEXT NOT NULL,
  master_table TEXT NOT NULL,
  master_id TEXT NOT NULL,
  relation_kind TEXT NOT NULL DEFAULT 'primary',
  last_seen_at TEXT,
  last_synced_at TEXT,
  source_checksum TEXT,
  read_only_after_cutover INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (system, source_key, external_id, master_table, master_id)
)

CREATE TABLE historical_promotion_candidates (
  candidate_id TEXT PRIMARY KEY,
  target_series_id TEXT NOT NULL,
  target_occurrence_id TEXT NOT NULL,
  target_event_name TEXT NOT NULL,
  source_types_json TEXT NOT NULL DEFAULT '[]',
  historical_years_json TEXT NOT NULL,
  exact_dates_json TEXT NOT NULL DEFAULT '{}',
  year_only_evidence_json TEXT NOT NULL DEFAULT '{}',
  prediction_json TEXT NOT NULL DEFAULT '{}',
  source_occurrence_ids_json TEXT NOT NULL DEFAULT '[]',
  evidence_url_count INTEGER NOT NULL DEFAULT 0,
  song_title_count INTEGER NOT NULL DEFAULT 0,
  match_score INTEGER NOT NULL DEFAULT 0,
  promotion_confidence TEXT NOT NULL,
  auto_promote_eligible INTEGER NOT NULL DEFAULT 0,
  recommended_action TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (target_series_id) REFERENCES event_series(series_id),
  FOREIGN KEY (target_occurrence_id) REFERENCES event_occurrences(occurrence_id)
)

CREATE TABLE master_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
)

CREATE TABLE notion_sync_jobs (
  job_id TEXT PRIMARY KEY,
  direction TEXT NOT NULL,
  target_table TEXT NOT NULL,
  target_id TEXT NOT NULL,
  notion_source_key TEXT NOT NULL,
  notion_page_id TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  requested_by TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  applied_at TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}'
)

CREATE TABLE observed_occurrence_songs (
  observed_occurrence_song_id TEXT PRIMARY KEY,
  observed_occurrence_id TEXT NOT NULL,
  occurrence_song_id TEXT,
  raw_song_title TEXT NOT NULL,
  normalized_title TEXT NOT NULL,
  matched_song_id TEXT,
  match_status TEXT NOT NULL DEFAULT 'unmatched',
  role TEXT NOT NULL,
  evidence_status TEXT NOT NULL,
  probability REAL,
  evidence_count INTEGER NOT NULL DEFAULT 0,
  speaker_count INTEGER NOT NULL DEFAULT 0,
  setlist_complete INTEGER NOT NULL DEFAULT 0,
  prediction_reliability_json TEXT NOT NULL DEFAULT '[]',
  evidence_urls_json TEXT NOT NULL DEFAULT '[]',
  source_payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (observed_occurrence_id) REFERENCES observed_occurrences(observed_occurrence_id),
  FOREIGN KEY (occurrence_song_id) REFERENCES occurrence_songs(occurrence_song_id),
  FOREIGN KEY (matched_song_id) REFERENCES songs(song_id)
)

CREATE TABLE observed_occurrences (
  observed_occurrence_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_occurrence_id TEXT,
  raw_event_name TEXT NOT NULL,
  raw_venue_name TEXT,
  normalized_event_name TEXT NOT NULL,
  normalized_venue_name TEXT,
  event_year INTEGER NOT NULL,
  matched_occurrence_id TEXT,
  match_status TEXT NOT NULL DEFAULT 'unmatched',
  quality_status TEXT NOT NULL DEFAULT 'review',
  quality_flags_json TEXT NOT NULL DEFAULT '[]',
  source_payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (matched_occurrence_id) REFERENCES event_occurrences(occurrence_id)
)

CREATE TABLE occurrence_dates (
  occurrence_date_id TEXT PRIMARY KEY,
  occurrence_id TEXT NOT NULL,
  date_start TEXT NOT NULL,
  date_end TEXT,
  date_type TEXT NOT NULL,
  confidence TEXT NOT NULL,
  source_evidence_id TEXT,
  basis TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (occurrence_id) REFERENCES event_occurrences(occurrence_id)
)

CREATE TABLE occurrence_evidence_links (
  occurrence_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  target TEXT NOT NULL,
  link_status TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  notes TEXT,
  PRIMARY KEY (occurrence_id, evidence_id, target),
  FOREIGN KEY (occurrence_id) REFERENCES event_occurrences(occurrence_id),
  FOREIGN KEY (evidence_id) REFERENCES evidence_items(evidence_id)
)

CREATE TABLE occurrence_song_evidence_links (
  occurrence_song_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  link_status TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  notes TEXT,
  PRIMARY KEY (occurrence_song_id, evidence_id),
  FOREIGN KEY (occurrence_song_id) REFERENCES occurrence_songs(occurrence_song_id),
  FOREIGN KEY (evidence_id) REFERENCES evidence_items(evidence_id)
)

CREATE TABLE occurrence_songs (
  occurrence_song_id TEXT PRIMARY KEY,
  origin TEXT NOT NULL DEFAULT 'curated',
  occurrence_id TEXT NOT NULL,
  song_id TEXT,
  song_title_raw TEXT NOT NULL,
  normalized_title TEXT NOT NULL,
  role TEXT NOT NULL,
  evidence_status TEXT NOT NULL,
  probability REAL,
  confidence TEXT NOT NULL DEFAULT 'unknown',
  source_count INTEGER NOT NULL DEFAULT 0,
  evidence_count INTEGER NOT NULL DEFAULT 0,
  inherited_from_year INTEGER,
  first_observed_at TEXT,
  last_observed_at TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(occurrence_id, normalized_title, role),
  FOREIGN KEY (occurrence_id) REFERENCES event_occurrences(occurrence_id),
  FOREIGN KEY (song_id) REFERENCES songs(song_id)
)

CREATE TABLE predicted_occurrence_dates (
  predicted_date_id TEXT PRIMARY KEY,
  historical_candidate_id TEXT NOT NULL,
  target_series_id TEXT NOT NULL,
  target_occurrence_id TEXT,
  target_event_name TEXT NOT NULL,
  predicted_year INTEGER NOT NULL,
  date_start TEXT NOT NULL,
  date_end TEXT,
  date_status TEXT NOT NULL DEFAULT 'predicted',
  basis_type TEXT NOT NULL,
  basis_type_label TEXT NOT NULL,
  rule_type TEXT NOT NULL,
  basis TEXT,
  confidence TEXT NOT NULL,
  score REAL,
  application_status TEXT NOT NULL DEFAULT 'candidate_for_2026_occurrence',
  source TEXT NOT NULL,
  source_payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (historical_candidate_id) REFERENCES historical_promotion_candidates(candidate_id),
  FOREIGN KEY (target_series_id) REFERENCES event_series(series_id),
  FOREIGN KEY (target_occurrence_id) REFERENCES event_occurrences(occurrence_id)
)

CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL
)

CREATE TABLE song_aliases (
  song_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'manual',
  PRIMARY KEY (song_id, normalized_alias),
  FOREIGN KEY (song_id) REFERENCES songs(song_id)
)

CREATE TABLE songs (
  song_id TEXT PRIMARY KEY,
  canonical_title TEXT NOT NULL,
  normalized_title TEXT NOT NULL UNIQUE,
  category TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  prior_tier TEXT,
  target_area TEXT,
  evidence_count REAL,
  source_url TEXT,
  memo TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)

CREATE TABLE venue_aliases (
  venue_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'manual',
  PRIMARY KEY (venue_id, normalized_alias),
  FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
)

CREATE TABLE place_nodes (
  place_id TEXT PRIMARY KEY,
  place_type TEXT NOT NULL CHECK(place_type IN ('prefecture', 'municipality', 'locality', 'site')),
  canonical_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  parent_place_id TEXT,
  latitude REAL,
  longitude REAL,
  memo TEXT,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'official',
  review_status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(parent_place_id, normalized_name),
  FOREIGN KEY (parent_place_id) REFERENCES place_nodes(place_id)
)

CREATE TABLE place_aliases (
  place_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'manual',
  PRIMARY KEY (place_id, normalized_alias),
  FOREIGN KEY (place_id) REFERENCES place_nodes(place_id)
)

CREATE TABLE venues (
  venue_id TEXT PRIMARY KEY,
  origin TEXT NOT NULL DEFAULT 'curated',
  canonical_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  area TEXT,
  address TEXT,
  access TEXT,
  scale TEXT,
  public_intro TEXT,
  past_memo TEXT,
  source_url TEXT,
  latitude REAL,
  longitude REAL,
  review_status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(normalized_name, address)
)

CREATE TABLE write_batches (
  batch_id TEXT PRIMARY KEY,
  actor TEXT NOT NULL,
  operation TEXT NOT NULL,
  dry_run INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL,
  input_checksum TEXT,
  output_checksum TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  summary_json TEXT NOT NULL DEFAULT '{}'
)

CREATE TRIGGER validate_event_state_axes_insert
BEFORE INSERT ON event_occurrences
WHEN NEW.current_event_state NOT IN ('predicted', 'announced', 'confirmed', 'ended', 'cancelled')
  OR NEW.date_certainty_tier NOT IN ('confirmed', 'rule_predicted', 'historical_slide', 'season_hint', 'historical_reference')
  OR (NEW.current_event_state IN ('confirmed', 'ended') AND NEW.date_certainty_tier != 'confirmed')
  OR (NEW.current_event_state IN ('predicted', 'announced') AND NEW.date_certainty_tier = 'confirmed')
BEGIN
  SELECT RAISE(ABORT, 'invalid event state axes');
END

CREATE TRIGGER validate_event_state_axes_update
BEFORE UPDATE OF current_event_state, date_certainty_tier ON event_occurrences
WHEN NEW.current_event_state NOT IN ('predicted', 'announced', 'confirmed', 'ended', 'cancelled')
  OR NEW.date_certainty_tier NOT IN ('confirmed', 'rule_predicted', 'historical_slide', 'season_hint', 'historical_reference')
  OR (NEW.current_event_state IN ('confirmed', 'ended') AND NEW.date_certainty_tier != 'confirmed')
  OR (NEW.current_event_state IN ('predicted', 'announced') AND NEW.date_certainty_tier = 'confirmed')
BEGIN
  SELECT RAISE(ABORT, 'invalid event state axes');
END
