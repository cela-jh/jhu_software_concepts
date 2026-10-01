-- least_privilege.sql
-- Creates (or re-tightens) the login role the application connects as,
-- with only the privileges it needs: read the applicants table for the
-- analysis page, and insert/update rows for Pull Data, Update Analysis,
-- and load_data. Safe to run more than once.
--
-- Run as the table owner or a superuser, from module_5, once per database:
--     psql -d cam_db -f least_privilege.sql
-- Optionally choose another role name with: -v app_role=some_name
--
-- The role is created without a password; nothing secret lives in this
-- file. Set one interactively afterward (psql prompts and sends only a
-- hash), then put it in your untracked .env as DB_PASSWORD:
--     psql -d cam_db -c "\password gradcafe_app"

\set ON_ERROR_STOP on
\if :{?app_role}
\else
    \set app_role gradcafe_app
\endif

-- Create the role only if it doesn't exist yet. Roles are shared by
-- every database on the server, so the second database skips this.
SELECT format('CREATE ROLE %I LOGIN', :'app_role')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role')
\gexec

-- Explicitly not a superuser and unable to create databases or roles,
-- replicate, or bypass row-level security, even if it existed before
-- with broader attributes.
ALTER ROLE :"app_role" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

-- Ordinary roles must not create objects in the public schema. This is
-- already the default on PostgreSQL 15 and later; it is stated here so
-- it also holds on older servers.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Connect to this database and look up objects in its public schema.
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app_role')
\gexec
GRANT USAGE ON SCHEMA public TO :"app_role";

-- Start from nothing on the table, then grant exactly what the app uses:
--   SELECT  every analysis query, A3, and the upsert's conflict check
--   INSERT  new scraped results (load_data upsert)
--   UPDATE  existing results on conflict, and the score/nationality cleanup
-- No DELETE, TRUNCATE, REFERENCES, or TRIGGER. The role does not own the
-- table, so it cannot DROP or ALTER it either.
REVOKE ALL ON TABLE applicants FROM PUBLIC;
REVOKE ALL ON TABLE applicants FROM :"app_role";
GRANT SELECT, INSERT, UPDATE ON TABLE applicants TO :"app_role";

-- Show the resulting role attributes and table privileges.
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
FROM pg_roles
WHERE rolname = :'app_role';

SELECT grantee, table_name, string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges
FROM information_schema.role_table_grants
WHERE grantee = :'app_role'
GROUP BY grantee, table_name;
