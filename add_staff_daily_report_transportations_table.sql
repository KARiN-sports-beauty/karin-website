-- staff_daily_report_transportations テーブルを新規作成
-- 交通費申請用テーブル

CREATE TABLE IF NOT EXISTS public.staff_daily_report_transportations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  daily_report_id UUID REFERENCES public.staff_daily_reports(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL,
  date DATE NOT NULL,
  transport_type TEXT NOT NULL,
  route TEXT,
  amount INT4 NOT NULL CHECK (amount >= 0),
  memo TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 検索用index
CREATE INDEX IF NOT EXISTS idx_staff_daily_report_transportations_daily_report_id ON public.staff_daily_report_transportations(daily_report_id);
CREATE INDEX IF NOT EXISTS idx_staff_daily_report_transportations_staff_id ON public.staff_daily_report_transportations(staff_id);
CREATE INDEX IF NOT EXISTS idx_staff_daily_report_transportations_date ON public.staff_daily_report_transportations(date);

