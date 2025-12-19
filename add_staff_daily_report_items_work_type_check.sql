-- staff_daily_report_items テーブルの work_type CHECK制約を追加
-- staff_daily_reports テーブルと同じ値（in_house, visit, field）を許可

ALTER TABLE public.staff_daily_report_items
DROP CONSTRAINT IF EXISTS staff_daily_report_items_work_type_check;

ALTER TABLE public.staff_daily_report_items
ADD CONSTRAINT staff_daily_report_items_work_type_check
CHECK (work_type IN ('in_house', 'visit', 'field'));
