grant select on public.event_daily to authenticated;
grant select on public.banners to anon;
grant select on public.notices to anon;
grant select,insert,update,delete on public.banners to authenticated;
grant select,insert,update,delete on public.notices to authenticated;
grant usage,select on sequence public.banners_id_seq to authenticated;
grant usage,select on sequence public.notices_id_seq to authenticated;
