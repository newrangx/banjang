-- 글반장 2차 고도화 DDL
create table if not exists public.event_daily(day date not null,event text not null,quote_num int not null default 0,cnt int not null default 0,primary key(day,event,quote_num));
alter table public.event_daily enable row level security;
drop policy if exists ev_read on public.event_daily;
create policy ev_read on public.event_daily for select to authenticated using(auth.jwt()->>'email'='newrangx@gmail.com');
create or replace function public.log_event(p_event text,p_quote int default 0) returns void language plpgsql security definer set search_path=public as $fn$begin
if p_event in('view_quote','view_image','copy_quote','share_kakao','share_copy','like_quote','comment_quote') then
insert into public.event_daily(day,event,quote_num,cnt) values((now() at time zone 'Asia/Seoul')::date,p_event,coalesce(p_quote,0),1) on conflict(day,event,quote_num) do update set cnt=event_daily.cnt+1;
end if;end$fn$;
grant execute on function public.log_event(text,int) to anon,authenticated;
create table if not exists public.banners(id bigint generated always as identity primary key,title text,pc_url text not null,mobile_url text,link_url text,active boolean not null default false,sort_order int not null default 0,created_at timestamptz not null default now());
alter table public.banners enable row level security;
drop policy if exists bn_read on public.banners;
create policy bn_read on public.banners for select using(active);
drop policy if exists bn_admin on public.banners;
create policy bn_admin on public.banners for all to authenticated using(auth.jwt()->>'email'='newrangx@gmail.com') with check(auth.jwt()->>'email'='newrangx@gmail.com');
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types) values('banners','banners',true,2097152,array['image/webp','image/png','image/jpeg']) on conflict(id) do update set public=true,file_size_limit=2097152;
drop policy if exists bobj_ins on storage.objects;
create policy bobj_ins on storage.objects for insert to authenticated with check(bucket_id='banners' and auth.jwt()->>'email'='newrangx@gmail.com');
drop policy if exists bobj_upd on storage.objects;
create policy bobj_upd on storage.objects for update to authenticated using(bucket_id='banners' and auth.jwt()->>'email'='newrangx@gmail.com') with check(bucket_id='banners' and auth.jwt()->>'email'='newrangx@gmail.com');
drop policy if exists bobj_del on storage.objects;
create policy bobj_del on storage.objects for delete to authenticated using(bucket_id='banners' and auth.jwt()->>'email'='newrangx@gmail.com');
create table if not exists public.notices(id bigint generated always as identity primary key,title text not null,body text not null default '',is_pinned boolean not null default false,published boolean not null default true,created_at timestamptz not null default now(),updated_at timestamptz not null default now());
alter table public.notices enable row level security;
drop policy if exists nt_read on public.notices;
create policy nt_read on public.notices for select using(published);
drop policy if exists nt_admin on public.notices;
create policy nt_admin on public.notices for all to authenticated using(auth.jwt()->>'email'='newrangx@gmail.com') with check(auth.jwt()->>'email'='newrangx@gmail.com');
