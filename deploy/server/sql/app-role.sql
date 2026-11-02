-- Least-privilege application role for the backend and the Telegram bot (ADR-032).
--
-- Why: the backend and bot used to connect as POSTGRES_USER, which on the official
-- Postgres image is a SUPERUSER and the owner of every table. A compromise of either
-- service could then DISABLE or DROP the append-only audit trigger (migration 0010) and
-- rewrite history. This role connects with only the DML the app needs and owns nothing,
-- so it can neither touch the trigger nor run DDL. Migrations keep running as the owner.
--
-- Idempotent. Run as the Postgres superuser/owner. Variables (psql -v):
--   app_user  = the app role name           (identifier)
--   app_pw    = the app role password        (literal)
--   db_name   = the database to grant CONNECT (identifier)
--   owner     = the role that owns/creates tables, i.e. POSTGRES_USER (identifier)

\set ON_ERROR_STOP on

-- Create the role only if missing; always (re)assert its flags and password.
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
              :'app_user', :'app_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

ALTER ROLE :"app_user" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'app_pw';

GRANT CONNECT ON DATABASE :"db_name" TO :"app_user";
GRANT USAGE ON SCHEMA public TO :"app_user";

-- Data access the app needs: full DML on the tables, use of the identity sequences.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_user";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_user";

-- Audit is append-only for the app: it may write and read events, never rewrite them.
-- (The 0010 trigger also blocks UPDATE/DELETE, but the grant must not even offer it, and
-- the role is not the owner, so it cannot disable or drop that trigger.)
REVOKE UPDATE, DELETE ON audit_events FROM :"app_user";

-- Tables created by FUTURE migrations (run as the owner) get the same grants automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";

-- The app role must never be able to create objects in the schema (would make it an owner).
REVOKE CREATE ON SCHEMA public FROM :"app_user";
