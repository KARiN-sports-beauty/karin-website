-- フィールド報告書テーブル
CREATE TABLE IF NOT EXISTS public.field_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  site_name text NOT NULL,
  report_date date NOT NULL,
  location text,
  staff_name text NOT NULL,
  column_count int4 NOT NULL CHECK (column_count >= 3 AND column_count <= 5) DEFAULT 3,
  special_notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid,
  updated_by uuid
);

-- フィールド報告書時間スケジュールテーブル
CREATE TABLE IF NOT EXISTS public.field_report_schedules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id uuid REFERENCES public.field_reports(id) ON DELETE CASCADE,
  time_hour int4 NOT NULL CHECK (time_hour >= 7 AND time_hour <= 26),
  column_index int4 NOT NULL CHECK (column_index >= 1 AND column_index <= 5),
  staff_name text,
  treatment_content text,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- フィールド報告書対応者テーブル
CREATE TABLE IF NOT EXISTS public.field_report_staff (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id uuid REFERENCES public.field_reports(id) ON DELETE CASCADE,
  staff_name text NOT NULL,
  condition text,
  treatment_content text,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_field_reports_date ON public.field_reports(report_date);
CREATE INDEX IF NOT EXISTS idx_field_reports_site_name ON public.field_reports(site_name);
CREATE INDEX IF NOT EXISTS idx_field_report_schedules_report_id ON public.field_report_schedules(report_id);
CREATE INDEX IF NOT EXISTS idx_field_report_staff_report_id ON public.field_report_staff(report_id);

