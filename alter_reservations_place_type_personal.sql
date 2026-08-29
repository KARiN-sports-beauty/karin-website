-- 予定管理: 区分に「休憩」「予定」を追加
-- 休憩のみ未反映の場合も、この1本で place_type 制約を更新できます。
-- patient_id が NOT NULL のままなら alter_reservations_patient_id_nullable.sql も実行してください。

ALTER TABLE public.reservations
DROP CONSTRAINT IF EXISTS reservations_place_type_check;

ALTER TABLE public.reservations
ADD CONSTRAINT reservations_place_type_check
CHECK (place_type IN ('in_house', 'visit', 'field', 'break', 'personal'));
