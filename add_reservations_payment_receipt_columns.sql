-- reservations テーブルに支払方法・領収書ステータスを追加
ALTER TABLE reservations
ADD COLUMN IF NOT EXISTS payment_method text,
ADD COLUMN IF NOT EXISTS receipt_status text;
