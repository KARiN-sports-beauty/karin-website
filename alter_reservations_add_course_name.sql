-- reservations テーブルに course_name（コース表示名）列を追加
-- エラー PGRST204: Could not find the 'course_name' column of 'reservations'
-- → Supabase SQL Editor で実行してください。
--
-- 管理画面の予約作成・Web予約（/api/book）の両方で使用します。

ALTER TABLE public.reservations
  ADD COLUMN IF NOT EXISTS course_name text;

COMMENT ON COLUMN public.reservations.course_name IS 'コース表示名（例: トータルコンディショニング 60分）';
