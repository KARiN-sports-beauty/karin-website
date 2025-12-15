-- patients テーブルに visibility カラムを追加（将来の可視性制御用）
ALTER TABLE public.patients
ADD COLUMN IF NOT EXISTS visibility text NOT NULL DEFAULT 'all';

-- 既存レコードの矯正（空文字/NULL を all に寄せる）
UPDATE public.patients
SET visibility = 'all'
WHERE visibility IS NULL OR visibility = '';

-- CHECK 制約を付け直す（all / internal_only のみ許可）
ALTER TABLE public.patients
DROP CONSTRAINT IF EXISTS patients_visibility_check;

ALTER TABLE public.patients
ADD CONSTRAINT patients_visibility_check
CHECK (visibility IN ('all', 'internal_only'));
