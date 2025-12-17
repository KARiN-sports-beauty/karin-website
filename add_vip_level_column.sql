-- patients テーブルに vip_level カラムを追加
-- 手動VIPフラグ（将来の会員優先制に備える）

ALTER TABLE public.patients
ADD COLUMN IF NOT EXISTS vip_level text NOT NULL DEFAULT 'none';

-- CHECK制約で 'none' / 'star' / 'clover' のみ許可
ALTER TABLE public.patients
DROP CONSTRAINT IF EXISTS patients_vip_level_check;

ALTER TABLE public.patients
ADD CONSTRAINT patients_vip_level_check
CHECK (vip_level IN ('none', 'star', 'clover'));

-- 既存データの vip_level が NULL の場合は 'none' に設定
UPDATE public.patients
SET vip_level = 'none'
WHERE vip_level IS NULL;
