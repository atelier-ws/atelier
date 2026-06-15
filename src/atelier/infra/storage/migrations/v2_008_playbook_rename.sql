-- v2_008: rename the legacy ReasonBlock schema to the Playbook schema.
--
-- Existing v2 databases were created with tables named ``reasonblocks`` /
-- ``block_applications`` (column ``reasonblock_id``). The v3 greenfield schema
-- uses ``playbooks`` / ``playbook_applications`` (column ``playbook_id``) and
-- creates them with ``CREATE TABLE IF NOT EXISTS``. Without this migration an
-- upgraded database keeps the old tables and gets a *second*, empty set of new
-- tables -- orphaning every existing row. This migration renames the legacy
-- objects in place so the data survives the upgrade.
--
-- This is the POSTGRES variant. It is registered as a pre-schema migration
-- (run BEFORE the greenfield CREATE TABLE IF NOT EXISTS) so the rename targets
-- are still free. Every step is guarded so it is a safe no-op on a fresh
-- database (where ``reasonblocks`` never existed) and on an already-migrated
-- database (where ``playbooks`` already exists), making the whole script
-- idempotent. SQLite databases are migrated by an equivalent guarded helper in
-- ``ContextStore`` (SQLite cannot express these guards in plain SQL).

DO $$
BEGIN
    -- 1. reasonblocks -> playbooks (+ indexes), only if the legacy table
    --    exists and the new table has not already been created.
    IF to_regclass('reasonblocks') IS NOT NULL
       AND to_regclass('playbooks') IS NULL THEN
        ALTER TABLE reasonblocks RENAME TO playbooks;
        IF to_regclass('idx_rb_domain_status') IS NOT NULL THEN
            ALTER INDEX idx_rb_domain_status RENAME TO idx_playbook_domain_status;
        END IF;
        IF to_regclass('idx_rb_slug') IS NOT NULL THEN
            ALTER INDEX idx_rb_slug RENAME TO idx_playbook_slug;
        END IF;
        IF to_regclass('idx_rb_metadata') IS NOT NULL THEN
            ALTER INDEX idx_rb_metadata RENAME TO idx_playbook_metadata;
        END IF;
        IF to_regclass('idx_rb_embedding') IS NOT NULL THEN
            ALTER INDEX idx_rb_embedding RENAME TO idx_playbook_embedding;
        END IF;
    END IF;

    -- 2. block_applications -> playbook_applications (+ column rename), only if
    --    the legacy table exists and the new table has not been created.
    IF to_regclass('block_applications') IS NOT NULL
       AND to_regclass('playbook_applications') IS NULL THEN
        ALTER TABLE block_applications RENAME TO playbook_applications;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'playbook_applications'
              AND column_name = 'reasonblock_id'
              AND table_schema = current_schema()
        ) THEN
            ALTER TABLE playbook_applications RENAME COLUMN reasonblock_id TO playbook_id;
        END IF;
    END IF;
END $$;
