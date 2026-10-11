-- Parquet tiers: derived, rebuildable copies of audit tables in a separate private bucket.
-- Originals stay immutable in sentra-originals; only tier objects may be replaced.
begin;
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('sentra-tiers','sentra-tiers',false,52428800,array['application/vnd.apache.parquet','application/json']);
create policy sentra_tiers_read on storage.objects for select to authenticated
 using (bucket_id='sentra-tiers' and public.sentra_storage_access('read'));
create policy sentra_tiers_insert on storage.objects for insert to authenticated
 with check (bucket_id='sentra-tiers' and public.sentra_storage_access('write'));
create policy sentra_tiers_replace on storage.objects for update to authenticated
 using (bucket_id='sentra-tiers' and public.sentra_storage_access('write'))
 with check (bucket_id='sentra-tiers' and public.sentra_storage_access('write'));
commit;
