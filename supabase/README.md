# Supabase migrations

SQL that runs against **this project's Supabase Postgres instance** — `auth.users` and
anything referencing it (like `public.profiles`). This is a *separate* database from the
app's own Postgres (Railway, migrated via `backend/alembic/`) — Supabase is used here only
as the identity provider, and `auth.users` only exists on Supabase's side.

**No Supabase CLI project is set up here** (no `config.toml`, no linked project) and this
session had no SQL-execution tool for the connected Supabase project, so there's no
automatic "apply on deploy" path yet. Apply each migration once, by hand:

1. Open the project's [SQL Editor](https://supabase.com/dashboard/project/_/sql/new)
   (Dashboard → SQL Editor → New query).
2. Paste the whole migration file's contents and run it.

Every migration here is written to be safe to re-run (`create table if not exists`,
`create or replace function`, `drop policy/trigger if exists` before recreating) in case
you're ever unsure whether it already applied.

| File | What it does |
|---|---|
| `migrations/0001_profiles.sql` | `public.profiles` (username for password accounts) + the `on_auth_user_created` trigger that creates a profile row for every signup path. |
