-- ============================================================
-- 教育実習の予定表（jisshu/）用の表とファイル置き場（2026-10 追加）
--
-- 入り方：5人共通のパスワード＝「共有アカウント」（下の SHARED_EMAIL）のパスワード。
--   共有アカウントは Supabase の Authentication → Users → Add user で作る
--   （Auto Confirm User にチェック）。パスワードはそこで決める。
-- 共有アカウントでログインしている人だけが、下の表とファイルを読み書きできる。
-- Roots 本体の生徒・管理者のアカウントからは見えない。
-- ============================================================

create or replace function public.is_jisshu()
returns boolean
language sql stable
as $$
  select lower(coalesce(auth.jwt() ->> 'email', '')) = 'roots-jisshu@example.com';
$$;

-- 授業（時間割表の1コマに入る1つの授業）
create table if not exists public.jisshu_lessons (
  id           uuid primary key default gen_random_uuid(),
  day          date not null,
  period       text not null check (period in ('shr','1','2','3','4','5','hr')),
  teacher      text not null check (char_length(teacher) between 1 and 20),
  room         text check (room is null or char_length(room) <= 40),
  class_name   text check (class_name is null or char_length(class_name) <= 40),
  subject      text check (subject is null or char_length(subject) <= 40),
  unit         text check (unit is null or char_length(unit) <= 100),
  is_research  boolean not null default false,
  mentor       text check (mentor is null or char_length(mentor) <= 40),
  observe_memo text check (observe_memo is null or char_length(observe_memo) <= 500),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists jisshu_lessons_day on public.jisshu_lessons (day, period);

-- フィードバック（1つの授業に、1人1枚）
create table if not exists public.jisshu_feedback (
  id         uuid primary key default gen_random_uuid(),
  lesson_id  uuid not null references public.jisshu_lessons(id) on delete cascade,
  author     text not null check (char_length(author) between 1 and 20),
  good       text not null default '' check (char_length(good) <= 3000),
  improve    text not null default '' check (char_length(improve) <= 3000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (lesson_id, author)
);

-- 資料（PDF・画像・Word・PowerPoint）。lesson_id が null なら「共有」タブに出る
-- 本体は Storage の jisshu バケットに path の名前で置く（日本語のファイル名は name に残す）
create table if not exists public.jisshu_files (
  id          uuid primary key default gen_random_uuid(),
  lesson_id   uuid references public.jisshu_lessons(id) on delete cascade,
  path        text not null unique,
  name        text not null check (char_length(name) between 1 and 200),
  kind        text not null default 'その他' check (kind in ('指導案','プリント','その他')),
  size        bigint not null default 0,
  mime        text,
  uploaded_by text not null check (char_length(uploaded_by) between 1 and 20),
  created_at  timestamptz not null default now()
);
create index if not exists jisshu_files_lesson on public.jisshu_files (lesson_id, created_at);

alter table public.jisshu_lessons  enable row level security;
alter table public.jisshu_feedback enable row level security;
alter table public.jisshu_files    enable row level security;

drop policy if exists jisshu_lessons_all on public.jisshu_lessons;
create policy jisshu_lessons_all on public.jisshu_lessons
  for all to authenticated using (public.is_jisshu()) with check (public.is_jisshu());
drop policy if exists jisshu_feedback_all on public.jisshu_feedback;
create policy jisshu_feedback_all on public.jisshu_feedback
  for all to authenticated using (public.is_jisshu()) with check (public.is_jisshu());
drop policy if exists jisshu_files_all on public.jisshu_files;
create policy jisshu_files_all on public.jisshu_files
  for all to authenticated using (public.is_jisshu()) with check (public.is_jisshu());

grant select, insert, update, delete on public.jisshu_lessons  to authenticated;
grant select, insert, update, delete on public.jisshu_feedback to authenticated;
grant select, insert, update, delete on public.jisshu_files    to authenticated;

-- だれかが書きこんだら、開いているほかの人の画面にすぐ届くようにする
do $$
begin
  begin alter publication supabase_realtime add table public.jisshu_lessons;  exception when duplicate_object then null; end;
  begin alter publication supabase_realtime add table public.jisshu_feedback; exception when duplicate_object then null; end;
  begin alter publication supabase_realtime add table public.jisshu_files;    exception when duplicate_object then null; end;
end $$;

-- ファイル置き場（非公開・1ファイル 50MB まで）
insert into storage.buckets (id, name, public, file_size_limit)
values ('jisshu', 'jisshu', false, 52428800)
on conflict (id) do update set public = false, file_size_limit = 52428800;

drop policy if exists jisshu_storage_read on storage.objects;
create policy jisshu_storage_read on storage.objects
  for select to authenticated using (bucket_id = 'jisshu' and public.is_jisshu());
drop policy if exists jisshu_storage_insert on storage.objects;
create policy jisshu_storage_insert on storage.objects
  for insert to authenticated with check (bucket_id = 'jisshu' and public.is_jisshu());
drop policy if exists jisshu_storage_delete on storage.objects;
create policy jisshu_storage_delete on storage.objects
  for delete to authenticated using (bucket_id = 'jisshu' and public.is_jisshu());

-- 意見箱（予定表ページへの「ここを直してほしい」）（2026-10-09 追加）
create table if not exists public.jisshu_ideas (
  id         uuid primary key default gen_random_uuid(),
  author     text not null check (char_length(author) between 1 and 20),
  body       text not null check (char_length(body) between 1 and 2000),
  done       boolean not null default false,
  created_at timestamptz not null default now()
);
alter table public.jisshu_ideas enable row level security;
drop policy if exists jisshu_ideas_all on public.jisshu_ideas;
create policy jisshu_ideas_all on public.jisshu_ideas
  for all to authenticated using (public.is_jisshu()) with check (public.is_jisshu());
grant select, insert, update, delete on public.jisshu_ideas to authenticated;
do $$
begin
  begin alter publication supabase_realtime add table public.jisshu_ideas; exception when duplicate_object then null; end;
end $$;
