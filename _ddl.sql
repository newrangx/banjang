drop policy if exists bobj_read on storage.objects;
create policy bobj_read on storage.objects for select to authenticated using(bucket_id='banners');
