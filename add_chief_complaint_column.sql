-- karte_logs テーブルに chief_complaint カラムを追加
ALTER TABLE public.karte_logs
ADD COLUMN IF NOT EXISTS chief_complaint text;
