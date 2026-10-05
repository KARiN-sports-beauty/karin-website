-- patients.vip_level
-- none / star / clover / 両方（star,clover と clover,star）

ALTER TABLE public.patients
ADD COLUMN IF NOT EXISTS vip_level text NOT NULL DEFAULT 'none';

ALTER TABLE public.patients
DROP CONSTRAINT IF EXISTS patients_vip_level_check;

ALTER TABLE public.patients
ADD CONSTRAINT patients_vip_level_check
CHECK (vip_level IN ('none', 'star', 'clover', 'star,clover', 'clover,star'));
