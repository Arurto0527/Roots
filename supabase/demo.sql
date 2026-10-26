-- ============================================================
-- お試し版（?demo=1）の利用状況
-- ・1行 = お試し版を1回開いたぶん（タブ1つ）
-- ・名前やメールアドレスは記録しない。visitor は端末ごとのランダムな番号
-- ・お試し版からは demo_ping() で自分の回の数字を書きこむことだけができる
-- ・見られるのは管理者だけ
-- Supabase の SQL Editor に全部はりつけて Run する（何回実行してもよい）
-- ============================================================
create table if not exists public.demo_visits (
  id             uuid primary key,
  visitor        uuid not null,
  started_at     timestamptz not null,
  last_at        timestamptz not null,
  active_seconds integer not null default 0 check (active_seconds >= 0),
  answers        integer not null default 0 check (answers >= 0)
);
create index if not exists demo_visits_time on public.demo_visits (started_at);

alter table public.demo_visits enable row level security;
-- 表を読めるのはログインした人だけ（その中でも下の決まりで管理者だけ）
revoke all on public.demo_visits from anon, authenticated;
grant select on public.demo_visits to authenticated;
drop policy if exists demo_visits_admin_read on public.demo_visits;
create policy demo_visits_admin_read on public.demo_visits
  for select to authenticated using (public.is_admin());

create or replace function public.demo_ping(
  p_id uuid, p_visitor uuid, p_started timestamptz, p_active integer, p_answers integer)
returns void
language plpgsql security definer set search_path = public
as $$
begin
  -- おかしな値は丸める（1回で1日以上・1万問以上はありえない）
  p_active  := least(greatest(coalesce(p_active,0),0),86400);
  p_answers := least(greatest(coalesce(p_answers,0),0),10000);
  if p_started is null or p_started > now() + interval '5 minutes' or p_started < now() - interval '2 days' then
    p_started := now();
  end if;
  insert into public.demo_visits (id, visitor, started_at, last_at, active_seconds, answers)
  values (p_id, p_visitor, p_started, now(), p_active, p_answers)
  on conflict (id) do update
    set last_at = now(),
        active_seconds = greatest(demo_visits.active_seconds, excluded.active_seconds),
        answers = greatest(demo_visits.answers, excluded.answers)
    where demo_visits.visitor = excluded.visitor;
end;
$$;
revoke all on function public.demo_ping(uuid, uuid, timestamptz, integer, integer) from public;
grant execute on function public.demo_ping(uuid, uuid, timestamptz, integer, integer) to anon, authenticated;
