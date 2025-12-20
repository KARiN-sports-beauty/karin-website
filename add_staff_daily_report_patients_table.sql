-- staff_daily_report_patients テーブルを新規作成
-- 日報の勤務カードに紐づく患者・予約情報を管理（1つの勤務カードに複数の患者・予約を紐付け可能）

CREATE TABLE IF NOT EXISTS public.staff_daily_report_patients (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id uuid NOT NULL REFERENCES public.staff_daily_report_items(id) ON DELETE CASCADE,
  patient_id uuid REFERENCES public.patients(id) ON DELETE SET NULL,
  reservation_id uuid REFERENCES public.reservations(id) ON DELETE SET NULL,
  course_name text,
  amount integer,  -- 金額（日報で編集可能）
  memo text,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- 検索用index
CREATE INDEX IF NOT EXISTS staff_daily_report_patients_item_id_idx ON public.staff_daily_report_patients (item_id);
CREATE INDEX IF NOT EXISTS staff_daily_report_patients_patient_id_idx ON public.staff_daily_report_patients (patient_id);
CREATE INDEX IF NOT EXISTS staff_daily_report_patients_reservation_id_idx ON public.staff_daily_report_patients (reservation_id);

