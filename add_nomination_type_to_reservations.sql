-- reservations テーブルに指名区分を追加
-- nomination_type は日本語値：'本指名','枠指名','希望','フリー' のみ使用
ALTER TABLE public.reservations
ADD COLUMN IF NOT EXISTS nomination_type text DEFAULT '本指名';

-- CHECK制約（日本語値のみ許可）
ALTER TABLE public.reservations
DROP CONSTRAINT IF EXISTS reservations_nomination_type_check;

ALTER TABLE public.reservations
ADD CONSTRAINT reservations_nomination_type_check
CHECK (nomination_type IN ('本指名', '枠指名', '希望', 'フリー'));

-- 既存データの nomination_type を日本語値に変換
UPDATE public.reservations
SET nomination_type = CASE
  WHEN nomination_type = 'main' THEN '本指名'
  WHEN nomination_type = 'frame' THEN '枠指名'
  WHEN nomination_type = 'hope' THEN '希望'
  WHEN nomination_type = 'free' THEN 'フリー'
  ELSE '本指名'
END
WHERE nomination_type IS NOT NULL;

-- NULL の場合は '本指名' に設定
UPDATE public.reservations
SET nomination_type = '本指名'
WHERE nomination_type IS NULL;
