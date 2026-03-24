-- VIPフラグに「⭐️と☘️の両方」を許可（star,clover）
-- 既存の patients_vip_level_check を更新

ALTER TABLE public.patients
DROP CONSTRAINT IF EXISTS patients_vip_level_check;

ALTER TABLE public.patients
ADD CONSTRAINT patients_vip_level_check
CHECK (vip_level IN ('none', 'star', 'clover', 'star,clover', 'clover,star'));
