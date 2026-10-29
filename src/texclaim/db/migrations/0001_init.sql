-- 0001_init: per-paper state schema (PLAN §9). Never edit once shipped.
CREATE TABLE runs (
  run_id            TEXT PRIMARY KEY,
  started_at        TEXT NOT NULL,
  finished_at       TEXT,
  status            TEXT NOT NULL,
  settings_json     TEXT NOT NULL,
  force_epoch       TEXT,
  tool_version      TEXT NOT NULL,
  model             TEXT,
  llm_calls         INTEGER NOT NULL DEFAULT 0,
  llm_cost_usd      REAL NOT NULL DEFAULT 0,
  openalex_cost_usd REAL NOT NULL DEFAULT 0
);

CREATE TABLE source_files (
  path        TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,
  sha256      TEXT NOT NULL,
  size_bytes  INTEGER NOT NULL
);

CREATE TABLE claims (
  claim_pk      INTEGER PRIMARY KEY,
  claim_hash    TEXT NOT NULL,
  file_path     TEXT NOT NULL,
  line_start    INTEGER NOT NULL,
  line_end      INTEGER NOT NULL,
  char_start    INTEGER NOT NULL,
  char_end      INTEGER NOT NULL,
  section_path  TEXT,
  unit_kind     TEXT NOT NULL,
  raw_latex     TEXT NOT NULL,
  text_norm     TEXT NOT NULL,
  context_norm  TEXT NOT NULL
);
CREATE INDEX claims_by_hash ON claims(claim_hash);

CREATE TABLE citations (
  citation_pk     INTEGER PRIMARY KEY,
  claim_pk        INTEGER NOT NULL REFERENCES claims(claim_pk) ON DELETE CASCADE,
  bib_key         TEXT NOT NULL,
  cite_command    TEXT NOT NULL,
  prenote         TEXT,
  postnote        TEXT,
  group_keys      TEXT NOT NULL,
  attributed_span TEXT NOT NULL,
  unit_key        TEXT NOT NULL
);
CREATE INDEX citations_by_unit ON citations(unit_key);
CREATE INDEX citations_by_key  ON citations(bib_key);

CREATE TABLE references_catalog (
  bib_key           TEXT PRIMARY KEY,
  bib_file          TEXT,
  entry_type        TEXT,
  bib_entry_hash    TEXT,
  title             TEXT,
  authors_json      TEXT,
  year              TEXT,
  doi               TEXT,
  arxiv_id          TEXT,
  pmid              TEXT,
  openalex_id       TEXT,
  openalex_title    TEXT,
  openalex_year     INTEGER,
  is_retracted      INTEGER,
  source_status     TEXT NOT NULL,
  source_provider   TEXT,
  source_version    TEXT,
  blob_sha256       TEXT,
  tei_sha256        TEXT,
  text_sha256       TEXT,
  source_language   TEXT,
  lookup_trail_json TEXT NOT NULL,
  resolved_at       TEXT NOT NULL
);

CREATE TABLE source_pages (
  text_sha256  TEXT NOT NULL,
  page_index   INTEGER NOT NULL,
  page_label   TEXT,
  text         TEXT NOT NULL,
  PRIMARY KEY (text_sha256, page_index)
);

CREATE TABLE chunks (
  chunk_id        TEXT PRIMARY KEY,
  text_sha256     TEXT NOT NULL,
  page_start      INTEGER NOT NULL,
  page_end        INTEGER NOT NULL,
  char_start      INTEGER NOT NULL,
  char_end        INTEGER NOT NULL,
  section_hint    TEXT,
  is_bibliography INTEGER NOT NULL DEFAULT 0,
  is_suspicious   INTEGER NOT NULL DEFAULT 0,
  text            TEXT NOT NULL
);
CREATE INDEX chunks_by_source ON chunks(text_sha256);
CREATE VIRTUAL TABLE chunk_fts USING fts5(
  chunk_id UNINDEXED, text_sha256 UNINDEXED, text,
  tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE verification_results (
  result_id         INTEGER PRIMARY KEY,
  unit_key          TEXT NOT NULL,
  run_id            TEXT NOT NULL REFERENCES runs(run_id),
  created_at        TEXT NOT NULL,
  origin            TEXT NOT NULL,
  verdict           TEXT NOT NULL,
  reason_code       TEXT NOT NULL,
  citation_function TEXT,
  evidence_scope    TEXT NOT NULL,
  claim_scope       TEXT,
  analysis          TEXT,
  what_is_wrong     TEXT,
  what_source_says  TEXT,
  suggested_fix     TEXT,
  confidence        TEXT,
  evidence_json     TEXT NOT NULL,
  needs_review      INTEGER NOT NULL DEFAULT 0,
  model             TEXT,
  prompt_version    TEXT,
  input_tokens      INTEGER,
  output_tokens     INTEGER,
  cost_usd          REAL,
  raw_response      TEXT
);
CREATE INDEX results_by_unit ON verification_results(unit_key, result_id);

CREATE VIEW current_results AS
SELECT r.* FROM verification_results r
WHERE r.result_id = (SELECT MAX(result_id) FROM verification_results WHERE unit_key = r.unit_key);

CREATE TABLE run_errors (
  run_id      TEXT NOT NULL REFERENCES runs(run_id),
  unit_key    TEXT,
  stage       TEXT NOT NULL,
  error_class TEXT NOT NULL,
  message     TEXT NOT NULL,
  at          TEXT NOT NULL
);

CREATE TABLE integrity_issues (
  issue_id   TEXT PRIMARY KEY,
  code       TEXT NOT NULL,
  severity   TEXT NOT NULL,
  bib_key    TEXT,
  file_path  TEXT,
  line       INTEGER,
  detail     TEXT NOT NULL
);
