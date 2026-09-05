-- Sign-In & AI Limits plan, Phase 2 - public.profiles (username for password accounts).
--
-- auth.users is Supabase-managed and not exposed through the API, and it has no username
-- field. This is the standard Supabase pattern for adding one: a public.profiles table,
-- one row per user, created automatically by a trigger on auth.users insert - see
-- https://supabase.com/docs/guides/auth/managing-user-data.
--
-- HOW TO APPLY: paste this whole file into the Supabase SQL Editor for this project
-- (Dashboard -> SQL Editor -> New query) and run it once. Not applied automatically -
-- this app's own Alembic migrations are a separate database (Railway's Postgres, app
-- data only); auth.users only exists in Supabase's own Postgres.
--
-- Safe to re-run accidentally: every statement is idempotent (create-if-not-exists /
-- create-or-replace / drop-then-create for the one trigger that doesn't support OR REPLACE).

create table if not exists public.profiles (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  username   text,
  created_at timestamptz not null default now(),
  constraint profiles_username_format check (
    username is null or username ~ '^[A-Za-z0-9_]{3,32}$'
  )
);

-- Case-insensitive uniqueness ("Alice" and "alice" collide). A NULL username (every
-- Google / magic-link signup - see the trigger below) is never treated as a duplicate of
-- another NULL or of anything else, so those signups are never blocked by this index.
create unique index if not exists profiles_username_unique_idx
  on public.profiles (lower(username))
  where username is not null;

alter table public.profiles enable row level security;

-- Private by default - this is a research terminal, not a social app with public profile
-- pages, so (unlike Supabase's own docs example) there is no "viewable by everyone"
-- policy here. A user can only ever see or change their OWN row. The signup trigger
-- below runs as `security definer` and bypasses RLS entirely for its own insert, so
-- nothing here is required for signup to work - these two policies exist for a future
-- "change my username" feature; no code shipped in this phase calls them.
drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
  on public.profiles for select
  using ( auth.uid() = user_id );

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
  on public.profiles for update
  using ( auth.uid() = user_id );

grant select, update on public.profiles to authenticated;

-- Creates the profile row the moment a new auth.users row is inserted - covers every
-- signup path (password, Google, magic link), not just the new password one. A password
-- signup passes a username via signUp()'s `options.data.username`; Google/magic-link
-- signups don't, so their row is created with username = null - the frontend already
-- falls back to showing the account's email whenever a username isn't set.
--
-- NOTE: not verified against a live signup - this session had no SQL-execution access to
-- run it. In particular, the exact error text `supabase.auth.signUp()` surfaces to the
-- client when this trigger raises (a duplicate username racing the unique index) is
-- unconfirmed; `auth_provider.tsx`'s signUpWithPassword pattern-matches "username_taken"
-- in the error message and falls back to showing Supabase's own message otherwise. Try a
-- real duplicate-username signup after applying this migration and adjust the frontend's
-- match if the message shape differs from what's expected.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
declare
  requested_username text := nullif(trim(new.raw_user_meta_data ->> 'username'), '');
begin
  begin
    insert into public.profiles (user_id, username) values (new.id, requested_username);
  exception
    when unique_violation then
      raise exception 'username_taken';
  end;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();
