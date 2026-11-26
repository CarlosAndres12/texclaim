-- Phase 14b: cached entity extraction for the knowledge graph.
CREATE TABLE entity_cache (
  claim_hash TEXT NOT NULL,
  method     TEXT NOT NULL,   -- model name or "heuristic"
  json       TEXT NOT NULL,
  PRIMARY KEY (claim_hash, method)
);
