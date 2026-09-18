-- Roots のデータベース設計
-- Supabase の SQL Editor に全部貼り付けて「Run」を押す。
-- 何度実行してもこわれないように書いてある。

-- ============================================================
-- 0. roster：先生が登録する名簿（メールアドレス ⇔ 生徒ID）
--    ここにないメールアドレスではログインできない
-- ============================================================
create table if not exists public.roster (
  email        text primary key,          -- 小文字で登録する
  student_code text not null unique,      -- 例：S001
  role         text not null default 'student' check (role in ('student','admin')),
  created_at   timestamptz not null default now()
);

-- ============================================================
-- 1. profiles：だれか
-- ============================================================
create table if not exists public.profiles (
  user_id      uuid primary key references auth.users(id) on delete cascade,
  student_code text not null unique,
  role         text not null default 'student' check (role in ('student','admin')),
  created_at   timestamptz not null default now()
);

-- ============================================================
-- 2. progress：同期する学習データ（localStorage の中身をそのまま）
-- ============================================================
create table if not exists public.progress (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  words      jsonb,
  stats      jsonb,
  badges     jsonb,
  settings   jsonb,
  updated_at timestamptz not null default now()
);

-- ============================================================
-- 3. study_logs：1回答ごとの記録
--    id はアプリ側で作る（オフライン後の送り直しで二重にならないように）
-- ============================================================
create table if not exists public.study_logs (
  id          uuid primary key,
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  word_id     text not null,
  mode        text not null,              -- 'card' / 'quiz' など
  grade       smallint,                   -- 0=知らなかった 1=あいまい 2=思い出せた 3=完璧
  correct     boolean,                    -- 4択の正解・不正解
  answered_at timestamptz not null
);
alter table public.study_logs add column if not exists first_try boolean;  -- その回で最初の出題か
alter table public.study_logs add column if not exists hint_used boolean;  -- 語源ヒントを見たか
create index if not exists study_logs_user_time on public.study_logs (user_id, answered_at);

-- ============================================================
-- 4. study_sessions：使った時間
-- ============================================================
create table if not exists public.study_sessions (
  id             uuid primary key,
  user_id        uuid not null default auth.uid() references auth.users(id) on delete cascade,
  started_at     timestamptz not null,
  ended_at       timestamptz not null,
  active_seconds integer not null default 0 check (active_seconds >= 0)
);
create index if not exists study_sessions_user_time on public.study_sessions (user_id, started_at);

-- ============================================================
-- 管理者かどうかを調べる関数
-- ============================================================
create or replace function public.is_admin()
returns boolean
language sql stable security definer set search_path = public
as $$
  select exists (select 1 from public.profiles where user_id = auth.uid() and role = 'admin');
$$;

-- ============================================================
-- 新しい人がログインしたとき：名簿にあれば profiles を作る、なければ断る
-- ============================================================
create or replace function public.handle_new_user()
returns trigger
language plpgsql security definer set search_path = public
as $$
declare r public.roster;
begin
  select * into r from public.roster where email = lower(new.email);
  if not found then
    raise exception 'この メールアドレス は 名簿に ありません';
  end if;
  insert into public.profiles (user_id, student_code, role)
  values (new.id, r.student_code, r.role)
  on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ============================================================
-- RLS：生徒は自分の分だけ、管理者は全員分を読むだけ
-- ============================================================
alter table public.roster         enable row level security;
alter table public.profiles       enable row level security;
alter table public.progress       enable row level security;
alter table public.study_logs     enable row level security;
alter table public.study_sessions enable row level security;

-- roster：管理者だけ見られる（登録は Supabase の画面から行う）
drop policy if exists roster_admin_read on public.roster;
create policy roster_admin_read on public.roster
  for select to authenticated using (public.is_admin());

-- profiles：自分の分を読む／管理者は全員分を読む（書きかえは不可）
drop policy if exists profiles_read on public.profiles;
create policy profiles_read on public.profiles
  for select to authenticated using (user_id = auth.uid() or public.is_admin());

-- progress：自分の分を読み書き／管理者は読むだけ
drop policy if exists progress_read on public.progress;
create policy progress_read on public.progress
  for select to authenticated using (user_id = auth.uid() or public.is_admin());
drop policy if exists progress_insert on public.progress;
create policy progress_insert on public.progress
  for insert to authenticated with check (user_id = auth.uid());
drop policy if exists progress_update on public.progress;
create policy progress_update on public.progress
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

-- study_logs：自分の分を追加・読む／管理者は読むだけ（消す・変えるは不可）
drop policy if exists logs_read on public.study_logs;
create policy logs_read on public.study_logs
  for select to authenticated using (user_id = auth.uid() or public.is_admin());
drop policy if exists logs_insert on public.study_logs;
create policy logs_insert on public.study_logs
  for insert to authenticated with check (user_id = auth.uid());

-- study_sessions：自分の分を追加・更新・読む／管理者は読むだけ
drop policy if exists sessions_read on public.study_sessions;
create policy sessions_read on public.study_sessions
  for select to authenticated using (user_id = auth.uid() or public.is_admin());
drop policy if exists sessions_insert on public.study_sessions;
create policy sessions_insert on public.study_sessions
  for insert to authenticated with check (user_id = auth.uid());
drop policy if exists sessions_update on public.study_sessions;
create policy sessions_update on public.study_sessions
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ============================================================
-- ログインした人に表を使ってよい許可を出す（新しいプロジェクトでは自動で付かない）
-- 何を見られるかは、上の RLS でしぼっている
-- ============================================================
grant select                 on public.roster         to authenticated;
grant select                 on public.profiles       to authenticated;
grant select, insert, update on public.progress       to authenticated;
grant select, insert         on public.study_logs     to authenticated;
grant select, insert, update on public.study_sessions to authenticated;

-- ============================================================
-- だれでもログインできるようにする（名簿にない人は student として登録）
-- ID番号（student_code）は生徒が設定画面で自分で入力する。重なってもよい
-- ============================================================
alter table public.profiles alter column student_code drop not null;
alter table public.profiles drop constraint if exists profiles_student_code_key;
alter table public.profiles add column if not exists email text;
update public.profiles p set email = lower(u.email) from auth.users u where u.id = p.user_id and p.email is null;

create or replace function public.handle_new_user()
returns trigger
language plpgsql security definer set search_path = public
as $$
declare r public.roster;
begin
  select * into r from public.roster where email = lower(new.email);
  insert into public.profiles (user_id, student_code, role, email)
  values (new.id, r.student_code, coalesce(r.role, 'student'), lower(new.email))
  on conflict (user_id) do nothing;
  return new;
end;
$$;

-- 自分のID番号だけを変える（role は変えられない）
create or replace function public.set_student_code(code text)
returns void
language sql security definer set search_path = public
as $$
  update public.profiles
     set student_code = nullif(left(trim(code), 40), '')
   where user_id = auth.uid();
$$;
revoke all on function public.set_student_code(text) from public, anon;
grant execute on function public.set_student_code(text) to authenticated;
