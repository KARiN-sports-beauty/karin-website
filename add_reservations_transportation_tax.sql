-- reservationsテーブルに出張費と消費税カラムを追加

ALTER TABLE public.reservations
ADD COLUMN IF NOT EXISTS transportation_fee INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS tax INTEGER DEFAULT 0;

COMMENT ON COLUMN public.reservations.transportation_fee IS '出張費（5km圏内: 1000円、10km圏内: 2000円、15km圏内: 3000円）';
COMMENT ON COLUMN public.reservations.tax IS '消費税（料金の10%）';

