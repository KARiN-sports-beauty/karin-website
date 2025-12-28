-- スタッフ給与テーブルに指名料カラムを追加

ALTER TABLE staff_salaries
ADD COLUMN IF NOT EXISTS nomination_fee DECIMAL(10, 2) DEFAULT 0;

COMMENT ON COLUMN staff_salaries.nomination_fee IS '指名料（本指名・枠指名の合計）';

