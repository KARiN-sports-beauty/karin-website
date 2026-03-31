-- 支払期限カラム due_date を invoices に用意する（未入力で保存できるようにする）
-- Supabase SQL Editor で実行してください。
--
-- エラー「column due_date does not exist」は、テーブルに列そのものが無い状態です。
-- その場合はまず ADD COLUMN が必要で、DROP NOT NULL だけでは足りません。
--
-- 1) 列が無ければ追加（NULL 可）
ALTER TABLE public.invoices
  ADD COLUMN IF NOT EXISTS due_date date;

-- 2) 既に列があり NOT NULL のときだけ制約を外す（1 で作った列は通常不要だが害はない）
ALTER TABLE public.invoices
  ALTER COLUMN due_date DROP NOT NULL;
