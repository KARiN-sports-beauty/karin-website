-- 帯同予約など、患者未紐付けの予約を許可する
-- Supabase SQL Editor で実行してください。
ALTER TABLE public.reservations
  ALTER COLUMN patient_id DROP NOT NULL;
