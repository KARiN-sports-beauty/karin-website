-- reservations テーブルに place_name カラムを追加（既に存在する場合はスキップ）
ALTER TABLE public.reservations
ADD COLUMN IF NOT EXISTS place_name text;
