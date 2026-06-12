-- 日別勤務のエリア（東京出張など。未設定時は user_metadata.area を使用）
ALTER TABLE staff_work_shifts
ADD COLUMN IF NOT EXISTS area text CHECK (area IS NULL OR area IN ('tokyo', 'fukuoka'));
