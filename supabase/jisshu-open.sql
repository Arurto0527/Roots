-- ============================================================
-- 教育実習の予定表（jisshu/）を「パスワードなし」で使えるようにする（2026-10-09）
--
-- jisshu/index.html の NEED_PASSWORD=false とセットで使う。先に jisshu.sql（意見箱の表まで）を実行しておくこと。
-- ログインしていない人（anon）にも、予定・フィードバック・資料の読み書きを許す。
-- つまり URL を知っている人ならだれでも見る・書く・消すことができる。
-- jisshu.sql で作った「共有アカウントだけ」の決まりはそのまま残してある。
--
-- パスワードありに戻すとき：いちばん下の「もとに戻す」を実行して、
--   jisshu/index.html の NEED_PASSWORD を true にする。
-- ============================================================

drop policy if exists jisshu_lessons_open on public.jisshu_lessons;
create policy jisshu_lessons_open on public.jisshu_lessons
  for all to anon using (true) with check (true);
drop policy if exists jisshu_feedback_open on public.jisshu_feedback;
create policy jisshu_feedback_open on public.jisshu_feedback
  for all to anon using (true) with check (true);
drop policy if exists jisshu_files_open on public.jisshu_files;
create policy jisshu_files_open on public.jisshu_files
  for all to anon using (true) with check (true);

drop policy if exists jisshu_ideas_open on public.jisshu_ideas;
create policy jisshu_ideas_open on public.jisshu_ideas
  for all to anon using (true) with check (true);

drop policy if exists jisshu_notices_open on public.jisshu_notices;
create policy jisshu_notices_open on public.jisshu_notices
  for all to anon using (true) with check (true);

grant select, insert, update, delete on public.jisshu_lessons  to anon;
grant select, insert, update, delete on public.jisshu_feedback to anon;
grant select, insert, update, delete on public.jisshu_files    to anon;
grant select, insert, update, delete on public.jisshu_ideas    to anon;
grant select, insert, update, delete on public.jisshu_notices  to anon;

drop policy if exists jisshu_storage_open_read on storage.objects;
create policy jisshu_storage_open_read on storage.objects
  for select to anon using (bucket_id = 'jisshu');
drop policy if exists jisshu_storage_open_insert on storage.objects;
create policy jisshu_storage_open_insert on storage.objects
  for insert to anon with check (bucket_id = 'jisshu');
drop policy if exists jisshu_storage_open_delete on storage.objects;
create policy jisshu_storage_open_delete on storage.objects
  for delete to anon using (bucket_id = 'jisshu');

-- ------------------------------------------------------------
-- もとに戻す（パスワードありにする）ときは、下の行の「-- 」を外して実行する
-- ------------------------------------------------------------
-- drop policy if exists jisshu_lessons_open  on public.jisshu_lessons;
-- drop policy if exists jisshu_feedback_open on public.jisshu_feedback;
-- drop policy if exists jisshu_files_open    on public.jisshu_files;
-- drop policy if exists jisshu_ideas_open    on public.jisshu_ideas;
-- drop policy if exists jisshu_notices_open  on public.jisshu_notices;
-- revoke select, insert, update, delete on public.jisshu_lessons  from anon;
-- revoke select, insert, update, delete on public.jisshu_feedback from anon;
-- revoke select, insert, update, delete on public.jisshu_files    from anon;
-- revoke select, insert, update, delete on public.jisshu_ideas    from anon;
-- revoke select, insert, update, delete on public.jisshu_notices  from anon;
-- drop policy if exists jisshu_storage_open_read   on storage.objects;
-- drop policy if exists jisshu_storage_open_insert on storage.objects;
-- drop policy if exists jisshu_storage_open_delete on storage.objects;
