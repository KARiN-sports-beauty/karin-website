-- staff_salaries に特別給カラムを追加
ALTER TABLE staff_salaries
ADD COLUMN IF NOT EXISTS special_bonus numeric DEFAULT 0;

-- 既存データのNULLを0で補正
UPDATE staff_salaries
SET special_bonus = 0
WHERE special_bonus IS NULL;
