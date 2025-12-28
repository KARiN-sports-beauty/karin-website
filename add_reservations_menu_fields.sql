-- 予約テーブルにメニュー選択・指名料・割引のカラムを追加

-- 選択されたメニュー（JSON配列）
ALTER TABLE public.reservations
ADD COLUMN IF NOT EXISTS selected_menus JSONB DEFAULT '[]'::jsonb;

-- 指名料（本指名・枠指名の合計）
ALTER TABLE public.reservations
ADD COLUMN IF NOT EXISTS nomination_fee INTEGER DEFAULT 0;

-- 割引額
ALTER TABLE public.reservations
ADD COLUMN IF NOT EXISTS discount INTEGER DEFAULT 0;

-- コメント追加
COMMENT ON COLUMN public.reservations.selected_menus IS '選択されたメニュー（本指名、枠指名、割引など）';
COMMENT ON COLUMN public.reservations.nomination_fee IS '指名料（本指名・枠指名の合計）';
COMMENT ON COLUMN public.reservations.discount IS '割引額';

