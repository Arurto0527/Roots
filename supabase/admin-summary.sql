-- 管理画面の「集計係」（2026-11 追加）
-- Supabase の SQL Editor に全部貼り付けて「Run」を押す。何度実行してもこわれない。
--
-- 前は管理画面を開くたびに、直近28日の回答記録を1件ずつ全部と、全員の単語データ（progress.words）を
-- まるごとダウンロードしていた。生徒が使うほど重くなるので、サーバーで先に数えて、まとめた数字だけを返す。
-- 返す形は index.html の adminAggregate() と同じ（そちらは、この関数が使えないときの予備）。
--
-- Supabase（無料プラン）は1回の処理が8秒をこえると止められるので、2つに分けてある。
--   admin_summary_logs     … 回答記録と学習時間（since〜until の期間ぶん。index.html が1週間ずつに分けて同時に呼ぶ）
--   admin_summary_progress … 単語データ（off 番目から lim 人ずつ。index.html が何回かに分けて同時に呼ぶ）

-- 日付で範囲をしぼるための索引（今ある索引は「人→日付」の順なので、全員分を日付で取るときに使えない）
create index if not exists study_logs_time     on public.study_logs (answered_at);
create index if not exists study_sessions_time on public.study_sessions (started_at);

-- 最初に作った1つにまとめた版（8秒をこえて止められた）は消す
drop function if exists public.admin_summary(timestamptz, text, numeric);
drop function if exists public.roots_num(jsonb);
drop function if exists public.admin_summary_logs(timestamptz, text);

-- since 以降・until より前の記録を数える（until が null なら終わりなし）／tz：日付・時刻の区切りに使うタイムゾーン（例 Asia/Tokyo）
-- 返すもの（どれも user_id ごと）
--   d    : [[日付, 時, 回答数, 正解数, ヒント数], ...]   … 回答記録を日・時間ごとに数えたもの
--   w    : [[単語ID, 回答数, 正解数, 最後に答えた時刻(ms)], ...]
--   last : 最後に答えた時刻(ms)
--   s    : [[日付, 学習秒数], ...]                       … study_sessions を日ごとに足したもの
create or replace function public.admin_summary_logs(since timestamptz, until timestamptz default null, tz text default 'Asia/Tokyo')
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
begin
  if not public.is_admin() then
    raise exception 'admin only';
  end if;
  return (
    with l as materialized (
      select user_id, word_id, correct, hint_used, answered_at,
             answered_at at time zone tz lt
      from public.study_logs where answered_at >= since and (until is null or answered_at < until)
    ), dh as (
      select user_id, lt::date dy, extract(hour from lt)::int hr,
             count(*) n, count(*) filter (where correct) ok, count(*) filter (where hint_used) hint
      from l group by 1, 2, 3
    ), uw as (
      select user_id, word_id, count(*) n, count(*) filter (where correct) ok,
             floor(extract(epoch from max(answered_at)) * 1000) last
      from l group by 1, 2
    ), ss as (
      select user_id, (started_at at time zone tz)::date dy, sum(active_seconds) sec
      from public.study_sessions where started_at >= since and (until is null or started_at < until) group by 1, 2
    )
    select jsonb_build_object(
      'd', (select coalesce(jsonb_object_agg(user_id, a), '{}'::jsonb) from (
        select user_id, jsonb_agg(jsonb_build_array(dy::text, hr, n, ok, hint) order by dy, hr) a
        from dh group by user_id) y),
      'w', (select coalesce(jsonb_object_agg(user_id, a), '{}'::jsonb) from (
        select user_id, jsonb_agg(jsonb_build_array(word_id, n, ok, last) order by word_id) a
        from uw group by user_id) y),
      'last', (select coalesce(jsonb_object_agg(user_id, last), '{}'::jsonb) from (
        select user_id, max(last) last from uw group by user_id) y),
      's', (select coalesce(jsonb_object_agg(user_id, a), '{}'::jsonb) from (
        select user_id, jsonb_agg(jsonb_build_array(dy::text, sec) order by dy) a
        from ss group by user_id) y)
    )
  );
end;
$$;

-- off 番目から lim 人分の単語データをまとめる（user_id の順）。master は「習得」とみなす復習間隔（MASTER_INTERVAL）
-- 返すもの：{n: この回に読んだ人数, p: {user_id: {at:更新時刻(ms), st:[学習した語のID], ma:[習得した語のID],
--           due:復習待ちの数, wn:苦手な語の数, wk:[[ID, 見出し語, まちがい数, 正解数], ...上位10]}}}
-- 数は数値として入っている前提（アプリが数値で保存している）。数値でないものは 0 とみなす
create or replace function public.admin_summary_progress(off int, lim int, master numeric default 21)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare
  now_ms numeric := floor(extract(epoch from now()) * 1000);
begin
  if not public.is_admin() then
    raise exception 'admin only';
  end if;
  return (
    with pr as (
      select user_id, words, updated_at from public.progress order by user_id offset off limit lim
    ), el as (
      select pr.user_id, t.i, t.e -> 'id' id, t.e -> 'w' w,
             coalesce((t.e -> 'manualPass') = 'true'::jsonb, false) mp,
             case when jsonb_typeof(t.e -> 'reps') = 'number' then (t.e -> 'reps')::numeric else 0 end reps,
             case when jsonb_typeof(t.e -> 'lapses') = 'number' then (t.e -> 'lapses')::numeric else 0 end lapses,
             case when jsonb_typeof(t.e -> 'correctCount') = 'number' then (t.e -> 'correctCount')::numeric else 0 end okc,
             case when jsonb_typeof(t.e -> 'incorrectCount') = 'number' then (t.e -> 'incorrectCount')::numeric else 0 end ngc,
             case when jsonb_typeof(t.e -> 'interval') = 'number' then (t.e -> 'interval')::numeric else 0 end iv,
             case when jsonb_typeof(t.e -> 'due') = 'number' then (t.e -> 'due')::numeric end due
      from pr
      cross join lateral jsonb_array_elements(case when jsonb_typeof(pr.words) = 'array' then pr.words else '[]'::jsonb end)
           with ordinality t(e, i)
    ), z as (
      select user_id,
             coalesce(jsonb_agg(id order by i) filter (where reps > 0 or lapses > 0 or okc > 0 or ngc > 0), '[]'::jsonb) st,
             coalesce(jsonb_agg(id order by i) filter (where mp or iv >= master), '[]'::jsonb) ma,
             count(*) filter (where not mp and due <= now_ms) due,
             count(*) filter (where ngc + lapses > 0) wn,
             jsonb_path_query_array(coalesce(jsonb_agg(jsonb_build_array(id, w, ngc + lapses, okc)
               order by ngc + lapses desc, okc asc, i) filter (where ngc + lapses > 0), '[]'::jsonb), '$[0 to 9]') wk
      from el group by user_id
    )
    select jsonb_build_object(
      'n', (select count(*) from pr),
      'p', coalesce((select jsonb_object_agg(pr.user_id, jsonb_build_object(
             'at', floor(extract(epoch from pr.updated_at) * 1000),
             'st', coalesce(z.st, '[]'::jsonb), 'ma', coalesce(z.ma, '[]'::jsonb),
             'due', coalesce(z.due, 0), 'wn', coalesce(z.wn, 0), 'wk', coalesce(z.wk, '[]'::jsonb)))
           from pr left join z on z.user_id = pr.user_id), '{}'::jsonb)
    )
  );
end;
$$;

revoke all on function public.admin_summary_logs(timestamptz, timestamptz, text) from public, anon;
grant execute on function public.admin_summary_logs(timestamptz, timestamptz, text) to authenticated;
revoke all on function public.admin_summary_progress(int, int, numeric) from public, anon;
grant execute on function public.admin_summary_progress(int, int, numeric) to authenticated;
