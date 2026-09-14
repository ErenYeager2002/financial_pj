-- Online guard for file-center retirement. No financial tables are rewritten.
SET LOCAL lock_timeout = '2s';
CREATE TABLE IF NOT EXISTS file_retention_receipts (
    file_id varchar(36) PRIMARY KEY,
    stored_path text NOT NULL,
    retired_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_file_retention_receipts_path ON file_retention_receipts(stored_path);
CREATE OR REPLACE FUNCTION file_retention_strings(payload text) RETURNS text[]
LANGUAGE sql IMMUTABLE AS $fn$
WITH RECURSIVE nodes(value) AS (
 SELECT COALESCE(NULLIF(payload, ''), '{}')::jsonb
 UNION ALL
 SELECT child.value FROM nodes n CROSS JOIN LATERAL (
   SELECT value FROM jsonb_each(CASE WHEN jsonb_typeof(n.value)='object' THEN n.value ELSE '{}'::jsonb END)
   UNION ALL
   SELECT value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(n.value)='array' THEN n.value ELSE '[]'::jsonb END)
 ) child
)
SELECT COALESCE(array_agg(value #>> '{}'), ARRAY[]::text[]) FROM nodes WHERE jsonb_typeof(value)='string'
$fn$;
CREATE OR REPLACE FUNCTION file_retention_reference_guard() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE field text; new_refs text[]; old_refs text[]; reactivating boolean;
BEGIN
 PERFORM pg_advisory_xact_lock_shared(7816091001);
 reactivating := TG_OP='UPDATE' AND (to_jsonb(OLD)->>'state') IN ('succeeded','failed','cancelled','canceled','timed_out','expired','superseded','submitted') AND (to_jsonb(NEW)->>'state') NOT IN ('succeeded','failed','cancelled','canceled','timed_out','expired','superseded','submitted');
 FOREACH field IN ARRAY TG_ARGV LOOP
   IF TG_OP='UPDATE' AND NOT reactivating AND (to_jsonb(NEW)->>field) IS NOT DISTINCT FROM (to_jsonb(OLD)->>field) THEN CONTINUE; END IF;
   new_refs := file_retention_strings(to_jsonb(NEW)->>field);
   old_refs := CASE WHEN TG_OP='UPDATE' AND NOT reactivating THEN file_retention_strings(to_jsonb(OLD)->>field) ELSE ARRAY[]::text[] END;
   IF EXISTS (SELECT 1 FROM file_retention_receipts WHERE file_id=ANY(new_refs) AND NOT file_id=ANY(old_refs)) THEN
     RAISE EXCEPTION 'Selected input has been superseded; select a current file' USING ERRCODE='23503';
   END IF;
 END LOOP;
 RETURN NEW;
END
$fn$;
CREATE OR REPLACE FUNCTION file_retention_storage_guard() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
 PERFORM pg_advisory_xact_lock_shared(7816091001);
 IF EXISTS (SELECT 1 FROM file_retention_receipts WHERE file_id=NEW.id OR stored_path=NEW.stored_path) THEN
   RAISE EXCEPTION 'Retired file identity or storage path cannot be reused' USING ERRCODE='23503';
 END IF;
 RETURN NEW;
END
$fn$;
DROP TRIGGER IF EXISTS file_retention_refs ON task_drafts;
CREATE TRIGGER file_retention_refs BEFORE INSERT OR UPDATE OF files_json, parameters_json, state ON task_drafts FOR EACH ROW EXECUTE FUNCTION file_retention_reference_guard('files_json', 'parameters_json');
DROP TRIGGER IF EXISTS file_retention_refs ON runs;
CREATE TRIGGER file_retention_refs BEFORE INSERT OR UPDATE OF files_json, parameters_json, state ON runs FOR EACH ROW EXECUTE FUNCTION file_retention_reference_guard('files_json', 'parameters_json');
DROP TRIGGER IF EXISTS file_retention_refs ON workflow_batches;
CREATE TRIGGER file_retention_refs BEFORE INSERT OR UPDATE OF files_json, state ON workflow_batches FOR EACH ROW EXECUTE FUNCTION file_retention_reference_guard('files_json');
DROP TRIGGER IF EXISTS file_retention_refs ON workflow_sessions;
CREATE TRIGGER file_retention_refs BEFORE INSERT OR UPDATE OF files_json, context_json, state ON workflow_sessions FOR EACH ROW EXECUTE FUNCTION file_retention_reference_guard('files_json', 'context_json');
DROP TRIGGER IF EXISTS file_retention_refs ON workflow_actions;
CREATE TRIGGER file_retention_refs BEFORE INSERT OR UPDATE OF input_json, state ON workflow_actions FOR EACH ROW EXECUTE FUNCTION file_retention_reference_guard('input_json');
DROP TRIGGER IF EXISTS file_retention_storage ON files;
CREATE TRIGGER file_retention_storage BEFORE INSERT OR UPDATE ON files FOR EACH ROW EXECUTE FUNCTION file_retention_storage_guard();

-- The already-running legacy collector and manual deletion also participate.
CREATE OR REPLACE FUNCTION file_retention_delete_guard() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE referenced boolean;
BEGIN
 IF NOT pg_try_advisory_xact_lock(7816091001) THEN
   RAISE EXCEPTION 'File references are being edited; postpone deletion' USING ERRCODE='55P03';
 END IF;
 IF EXISTS (SELECT 1 FROM file_retention_receipts WHERE file_id=OLD.id AND stored_path=OLD.stored_path) THEN RETURN OLD; END IF;
 IF OLD.kind='output' THEN
   RAISE EXCEPTION 'Output deletion requires a verified successful replacement' USING ERRCODE='23503';
 END IF;
 IF EXISTS (SELECT 1 FROM files WHERE stored_path=OLD.stored_path AND id<>OLD.id) THEN
   RAISE EXCEPTION 'Shared file storage cannot be retired' USING ERRCODE='23503';
 END IF;
 SELECT EXISTS (
   SELECT 1 FROM task_drafts WHERE OLD.id=ANY(file_retention_strings(files_json)) OR OLD.id=ANY(file_retention_strings(parameters_json))
   UNION ALL SELECT 1 FROM runs WHERE OLD.id=ANY(file_retention_strings(files_json)) OR OLD.id=ANY(file_retention_strings(parameters_json))
   UNION ALL SELECT 1 FROM workflow_batches WHERE OLD.id=ANY(file_retention_strings(files_json))
   UNION ALL SELECT 1 FROM workflow_sessions WHERE OLD.id=ANY(file_retention_strings(files_json)) OR OLD.id=ANY(file_retention_strings(context_json))
   UNION ALL SELECT 1 FROM workflow_actions WHERE OLD.id=ANY(file_retention_strings(input_json))
 ) INTO referenced;
 IF referenced THEN
   RAISE EXCEPTION 'Referenced file requires the unified retention policy' USING ERRCODE='23503';
 END IF;
 INSERT INTO file_retention_receipts(file_id,stored_path) VALUES (OLD.id,OLD.stored_path);
 RETURN OLD;
END
$fn$;
DROP TRIGGER IF EXISTS file_retention_delete ON files;
CREATE TRIGGER file_retention_delete BEFORE DELETE ON files FOR EACH ROW EXECUTE FUNCTION file_retention_delete_guard();
