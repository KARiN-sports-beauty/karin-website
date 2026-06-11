-- 予定管理: 現場区分に「休憩」を追加
ALTER TABLE public.reservations
DROP CONSTRAINT IF EXISTS reservations_place_type_check;

ALTER TABLE public.reservations
ADD CONSTRAINT reservations_place_type_check
CHECK (place_type IN ('in_house', 'visit', 'field', 'break'));
