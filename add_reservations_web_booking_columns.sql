-- 院内Web予約（Phase 1）用カラム
ALTER TABLE public.reservations
ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'staff',
ADD COLUMN IF NOT EXISTS client_email text,
ADD COLUMN IF NOT EXISTS web_course_request text,
ADD COLUMN IF NOT EXISTS web_note text;

ALTER TABLE public.reservations
DROP CONSTRAINT IF EXISTS reservations_source_check;

ALTER TABLE public.reservations
ADD CONSTRAINT reservations_source_check
CHECK (source IN ('staff', 'web'));

-- 将来の決済用（Phase 1 では未使用・デフォルトのまま）
ALTER TABLE public.reservations
ADD COLUMN IF NOT EXISTS payment_status text NOT NULL DEFAULT 'not_required',
ADD COLUMN IF NOT EXISTS stripe_payment_intent_id text,
ADD COLUMN IF NOT EXISTS stripe_checkout_session_id text;

ALTER TABLE public.reservations
DROP CONSTRAINT IF EXISTS reservations_payment_status_check;

ALTER TABLE public.reservations
ADD CONSTRAINT reservations_payment_status_check
CHECK (payment_status IN ('unpaid', 'pending', 'paid', 'refunded', 'not_required'));

COMMENT ON COLUMN public.reservations.source IS 'staff=管理画面, web=クライアント予約';
COMMENT ON COLUMN public.reservations.client_email IS 'Web予約時のメールアドレス';
COMMENT ON COLUMN public.reservations.web_course_request IS 'Web予約の希望コース表示名';
COMMENT ON COLUMN public.reservations.web_note IS 'Web予約の要望';
