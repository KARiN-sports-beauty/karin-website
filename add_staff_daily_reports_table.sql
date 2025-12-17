-- staff_daily_reports テーブルを新規作成
-- スタッフの日々の勤務報告（日報）管理

CREATE TABLE IF NOT EXISTS public.staff_daily_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  staff_name text NOT NULL,  -- 現状は文字列（将来staff_idに置換可）
  date date NOT NULL,
  work_type text NOT NULL,   -- 'in_house' | 'visit' | 'field'
  start_time time,
  end_time time,
  break_minutes integer DEFAULT 0,
  memo text,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- work_type 制約（karte_logs.place_typeと統一）
ALTER TABLE public.staff_daily_reports
DROP CONSTRAINT IF EXISTS staff_daily_reports_work_type_check;

ALTER TABLE public.staff_daily_reports
ADD CONSTRAINT staff_daily_reports_work_type_check
CHECK (work_type IN ('in_house', 'visit', 'field'));

-- 検索用index
CREATE INDEX IF NOT EXISTS staff_daily_reports_date_idx ON public.staff_daily_reports (date);
CREATE INDEX IF NOT EXISTS staff_daily_reports_staff_name_idx ON public.staff_daily_reports (staff_name);
CREATE INDEX IF NOT EXISTS staff_daily_reports_work_type_idx ON public.staff_daily_reports (work_type);
