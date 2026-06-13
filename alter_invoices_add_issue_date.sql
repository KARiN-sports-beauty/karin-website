-- invoices テーブルに issue_date（発行日）列を追加
-- エラー PGRST204: Could not find the 'issue_date' column of 'invoices'
-- → Supabase SQL Editor でこのファイルを実行してください。
--
-- 前提: public.invoices テーブルは既に存在するが、issue_date 列が無い状態
-- （add_invoices_table.sql を実行していない、または古いスキーマのまま）

ALTER TABLE public.invoices
  ADD COLUMN IF NOT EXISTS issue_date date;

-- 既存行があれば year/month から月末日を補完
UPDATE public.invoices
SET issue_date = (
  make_date(year::int, month::int, 1) + interval '1 month' - interval '1 day'
)::date
WHERE issue_date IS NULL
  AND year IS NOT NULL
  AND month IS NOT NULL;

-- それでも NULL の行は今日の日付
UPDATE public.invoices
SET issue_date = current_date
WHERE issue_date IS NULL;

-- due_date も無い環境向け（alter_invoices_due_date_nullable.sql と同等・未実行ならここで追加）
ALTER TABLE public.invoices
  ADD COLUMN IF NOT EXISTS due_date date;

ALTER TABLE public.invoices
  ALTER COLUMN due_date DROP NOT NULL;
