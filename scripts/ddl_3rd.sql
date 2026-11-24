-- =============================================================
-- 글반장 아카이브 3차 고도화 — Supabase 적용 SQL (2026-11-24)
-- project: geulbanjang / ref ecwrolumnuajrkqmzeds
-- 다시 실행해도 안전하도록 if not exists / drop ... if exists 형태
-- =============================================================

-- 1) 댓글 답글(1단계) -------------------------------------------
alter table public.quote_comments add column if not exists parent_id bigint;

do $do$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'quote_comments_parent_id_fkey'
      and conrelid = 'public.quote_comments'::regclass
  ) then
    alter table public.quote_comments
      add constraint quote_comments_parent_id_fkey
      foreign key (parent_id) references public.quote_comments(id) on delete cascade;
  end if;
end $do$;

create index if not exists quote_comments_quote_idx on public.quote_comments(quote_num, created_at desc);
create index if not exists quote_comments_parent_idx on public.quote_comments(parent_id);

-- add_comment: p_parent 추가. 기존 5인자 함수와 공존하면 PostgREST가 고르지 못하므로 교체한다.
create or replace function public.add_comment_v2(
  p_quote integer,
  p_nick text,
  p_body text,
  p_hp text default '',
  p_token text default '',
  p_parent bigint default null
) returns public.quote_comments
language plpgsql security definer set search_path to 'public' as $function$
declare
  v_nick text; v_body text; v_row public.quote_comments; v_token text; v_parent bigint;
begin
  if coalesce(btrim(p_hp), '') <> '' then raise exception 'spam'; end if;
  if p_quote is null or p_quote <= 0 then raise exception 'invalid quote'; end if;
  v_nick := left(coalesce(nullif(btrim(coalesce(p_nick,'')), ''), '익명'), 20);
  v_body := btrim(coalesce(p_body, ''));
  if char_length(v_body) < 2 or char_length(v_body) > 300 then raise exception 'length'; end if;
  if v_body ~* '(https?://|www\.|\.com|\.net|\.kr|카톡|카카오톡|텔레그램|t\.me/)' then raise exception 'link'; end if;

  v_parent := null;
  if p_parent is not null then
    select coalesce(c.parent_id, c.id) into v_parent
      from public.quote_comments c
     where c.id = p_parent and c.quote_num = p_quote;
    if v_parent is null then raise exception 'parent'; end if;
  end if;

  if exists (
    select 1 from public.quote_comments c
     where c.quote_num = p_quote and c.body = v_body
       and c.created_at > now() - interval '15 seconds'
  ) then raise exception 'duplicate'; end if;

  insert into public.quote_comments(quote_num, nickname, body, parent_id)
  values (p_quote, v_nick, v_body, v_parent)
  returning * into v_row;

  v_token := btrim(coalesce(p_token, ''));
  if char_length(v_token) >= 16 then
    insert into public.comment_tokens(comment_id, token) values (v_row.id, v_token)
    on conflict (comment_id) do update set token = excluded.token;
  end if;
  return v_row;
end $function$;

grant execute on function public.add_comment_v2(integer, text, text, text, text, bigint) to anon, authenticated;
drop function if exists public.add_comment(integer, text, text, text, text);
alter function public.add_comment_v2(integer, text, text, text, text, bigint) rename to add_comment;

-- 2) 카드 댓글 수 일괄 조회 + 최근 댓글 ------------------------------
create or replace function public.quote_comment_counts(p_nums integer[] default null)
returns table(quote_num integer, cnt bigint)
language sql stable security definer set search_path to 'public' as $fn$
  select c.quote_num, count(*)::bigint
    from public.quote_comments c
   where p_nums is null or c.quote_num = any(p_nums)
   group by c.quote_num;
$fn$;
grant execute on function public.quote_comment_counts(integer[]) to anon, authenticated;

create or replace function public.recent_comments(p_limit integer default 8)
returns table(id bigint, quote_num integer, nickname text, body text, created_at timestamptz, parent_id bigint)
language sql stable security definer set search_path to 'public' as $fn$
  select c.id, c.quote_num, c.nickname, c.body, c.created_at, c.parent_id
    from public.quote_comments c
   order by c.created_at desc
   limit greatest(1, least(coalesce(p_limit, 8), 20));
$fn$;
grant execute on function public.recent_comments(integer) to anon, authenticated;

-- 3) 텔레그램 새 글 (t.me/s/banjang9) -------------------------------
create table if not exists public.telegram_posts (
  id bigint generated always as identity primary key,
  msg_id bigint not null unique,
  kind text not null default 'text' check (kind in ('text','photo','album','video')),
  body text not null default '',
  media jsonb not null default '[]'::jsonb,
  duration text,
  post_url text not null,
  posted_at timestamptz,
  published boolean not null default true,
  synced_at timestamptz not null default now()
);
alter table public.telegram_posts enable row level security;
drop policy if exists tg_read on public.telegram_posts;
create policy tg_read on public.telegram_posts for select using (published);
drop policy if exists tg_admin on public.telegram_posts;
create policy tg_admin on public.telegram_posts for all to authenticated
  using (auth.jwt() ->> 'email' = 'newrangx@gmail.com')
  with check (auth.jwt() ->> 'email' = 'newrangx@gmail.com');
grant select on public.telegram_posts to anon;
grant select, insert, update, delete on public.telegram_posts to authenticated;
grant usage, select on sequence public.telegram_posts_id_seq to authenticated;

-- 동기화 스크립트용 키 (RLS 정책 없음 = 관리자(authenticated 정책상 아님) 외 접근 불가, RPC만 검증)
create table if not exists public.sync_keys (
  name text primary key,
  key text not null,
  updated_at timestamptz not null default now()
);
alter table public.sync_keys enable row level security;
-- 동기화 키는 저장소에 두지 않는다. 대시보드 SQL 에디터에서 아래를 값만 바꿔 1회 실행한다.
--   insert into public.sync_keys(name, key) values ('telegram', '<새 키>')
--   on conflict (name) do update set key = excluded.key, updated_at = now();

create or replace function public.ingest_telegram_posts(p_key text, p_posts jsonb)
returns integer language plpgsql security definer set search_path to 'public' as $fn$
declare v_n integer := 0;
begin
  if not exists (select 1 from public.sync_keys where name = 'telegram' and key = p_key) then
    raise exception 'unauthorized';
  end if;
  if p_posts is null or jsonb_typeof(p_posts) <> 'array' then raise exception 'invalid'; end if;
  insert into public.telegram_posts(msg_id, kind, body, media, duration, post_url, posted_at, synced_at)
  select (x->>'msg_id')::bigint,
         coalesce(nullif(x->>'kind',''), 'text'),
         coalesce(x->>'body',''),
         coalesce(x->'media', '[]'::jsonb),
         nullif(x->>'duration',''),
         x->>'post_url',
         nullif(x->>'posted_at','')::timestamptz,
         now()
    from jsonb_array_elements(p_posts) x
  on conflict (msg_id) do update
     set kind = excluded.kind, body = excluded.body, media = excluded.media,
         duration = excluded.duration, post_url = excluded.post_url,
         posted_at = excluded.posted_at, synced_at = now();
  get diagnostics v_n = row_count;
  return v_n;
end $fn$;
grant execute on function public.ingest_telegram_posts(text, jsonb) to anon, authenticated;

-- 4) 문장 총 개수 동적 카운트 ---------------------------------------
create table if not exists public.archive_quotes (
  id bigint generated always as identity primary key,
  quote_num integer,
  body text not null,
  author text,
  source text not null default 'manual' check (source in ('drive','admin','telegram','manual')),
  note text,
  published boolean not null default true,
  created_at timestamptz not null default now()
);
alter table public.archive_quotes enable row level security;
drop policy if exists aq_read on public.archive_quotes;
create policy aq_read on public.archive_quotes for select using (published);
drop policy if exists aq_admin on public.archive_quotes;
create policy aq_admin on public.archive_quotes for all to authenticated
  using (auth.jwt() ->> 'email' = 'newrangx@gmail.com')
  with check (auth.jwt() ->> 'email' = 'newrangx@gmail.com');
grant select on public.archive_quotes to anon;
grant select, insert, update, delete on public.archive_quotes to authenticated;
grant usage, select on sequence public.archive_quotes_id_seq to authenticated;

create or replace view public.archive_stats with (security_invoker = true) as
  select 2888 as base,
         (select count(*)::int from public.archive_quotes where published) as added,
         2888 + (select count(*)::int from public.archive_quotes where published) as total;
grant select on public.archive_stats to anon, authenticated;
