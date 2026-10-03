-- AI read-only database access.
-- Run this manually as the database owner/superuser in Adminer/psql.
--
-- Goal:
-- - Create a dedicated read-only role for AI analysis.
-- - Grant SELECT only.
-- - Exclude sensitive tables such as users/token/auth/session tables.
-- - Exclude sensitive columns such as password/token columns from every granted table.
--
-- Replace the password before running in production.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'budimas_ai_reader') THEN
        CREATE ROLE budimas_ai_reader LOGIN PASSWORD 'CHANGE_THIS_STRONG_PASSWORD';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE budimas_dev TO budimas_ai_reader;
GRANT USAGE ON SCHEMA public TO budimas_ai_reader;

-- Start from a clean permission state.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM budimas_ai_reader;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM budimas_ai_reader;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM budimas_ai_reader;
GRANT USAGE ON SCHEMA public TO budimas_ai_reader;

DO $$
DECLARE
    rec RECORD;
    column_list TEXT;
BEGIN
    FOR rec IN
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type IN ('BASE TABLE', 'VIEW')
          AND table_name NOT ILIKE '%user%'
          AND table_name NOT ILIKE '%token%'
          AND table_name NOT ILIKE '%auth%'
          AND table_name NOT ILIKE '%session%'
          AND table_name NOT ILIKE '%password%'
        ORDER BY table_name
    LOOP
        SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position)
        INTO column_list
        FROM information_schema.columns
        WHERE table_schema = rec.table_schema
          AND table_name = rec.table_name
          AND column_name NOT ILIKE '%password%'
          AND column_name NOT ILIKE '%token%'
          AND column_name NOT ILIKE '%secret%'
          AND column_name NOT ILIKE '%key%'
          AND column_name NOT ILIKE '%otp%'
          AND column_name NOT ILIKE '%pin%';

        IF column_list IS NOT NULL AND length(column_list) > 0 THEN
            EXECUTE format(
                'GRANT SELECT (%s) ON TABLE %I.%I TO budimas_ai_reader',
                column_list,
                rec.table_schema,
                rec.table_name
            );
        END IF;
    END LOOP;
END
$$;

-- Optional sanity check: list tables/columns accessible by this role.
SELECT
    table_schema,
    table_name,
    column_name,
    privilege_type
FROM information_schema.column_privileges
WHERE grantee = 'budimas_ai_reader'
ORDER BY table_schema, table_name, column_name, privilege_type;
