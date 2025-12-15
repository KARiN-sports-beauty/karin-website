-- reservations テーブル作成
CREATE TABLE IF NOT EXISTS public.reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
  reserved_at timestamptz NOT NULL,
  duration_minutes int NOT NULL DEFAULT 60,
  place_type text NOT NULL,
  place_name text,
  staff_name text,
  status text NOT NULL DEFAULT 'reserved',
  memo text,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- place_type 制約（karte_logsと揃える）
ALTER TABLE public.reservations
DROP CONSTRAINT IF EXISTS reservations_place_type_check;

ALTER TABLE public.reservations
ADD CONSTRAINT reservations_place_type_check
CHECK (place_type IN ('in_house','visit','field'));

-- status 制約
ALTER TABLE public.reservations
DROP CONSTRAINT IF EXISTS reservations_status_check;

ALTER TABLE public.reservations
ADD CONSTRAINT reservations_status_check
CHECK (status IN ('reserved','visited','completed','canceled'));

-- 検索用index
CREATE INDEX IF NOT EXISTS reservations_reserved_at_idx ON public.reservations (reserved_at);
CREATE INDEX IF NOT EXISTS reservations_patient_id_idx ON public.reservations (patient_id);
CREATE INDEX IF NOT EXISTS reservations_staff_name_idx ON public.reservations (staff_name);
