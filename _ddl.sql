drop policy if exists bobj_ins_t on storage.objects;
create policy bobj_ins_t on storage.objects for insert to authenticated with check (bucket_id='banners');
