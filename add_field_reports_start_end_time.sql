-- field_reportsテーブルに開始時間・終了時間カラムを追加
ALTER TABLE public.field_reports 
ADD COLUMN IF NOT EXISTS start_time time DEFAULT '07:00'::time,
ADD COLUMN IF NOT EXISTS end_time time DEFAULT '26:00'::time;

-- field_report_time_slotsテーブルにtime_minuteカラムを追加（既にある場合はスキップ）
ALTER TABLE public.field_report_time_slots 
ADD COLUMN IF NOT EXISTS time_minute text;

