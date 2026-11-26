-- Phase 11: cached check-worthiness decisions for internal (uncited) claims.
CREATE TABLE internal_screen (
  text_hash TEXT PRIMARY KEY,
  worthy    INTEGER NOT NULL,
  method    TEXT NOT NULL
);
