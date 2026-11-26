-- Phase 10/11: claim scope (previous sentence, paragraph) and claim origin.
ALTER TABLE claims ADD COLUMN prev_norm TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN para_norm TEXT NOT NULL DEFAULT '';
-- cited | internal ; role: '' | abstract | conclusion
ALTER TABLE claims ADD COLUMN origin TEXT NOT NULL DEFAULT 'cited';
ALTER TABLE claims ADD COLUMN role TEXT NOT NULL DEFAULT '';
