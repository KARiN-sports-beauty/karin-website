-- staff_work_shifts: 日単位の勤務モード（clinic / field / off / unset）
-- Supabase SQL Editor で実行してください。

ALTER TABLE staff_work_shifts
ADD COLUMN IF NOT EXISTS work_mode text;

-- 既存行の backfill
UPDATE staff_work_shifts
SET work_mode = 'off'
WHERE work_mode IS NULL AND is_off = TRUE;

UPDATE staff_work_shifts
SET work_mode = 'clinic'
WHERE work_mode IS NULL
  AND is_off = FALSE
  AND start_time IS NOT NULL
  AND end_time IS NOT NULL
  AND start_time <> ''
  AND end_time <> '';

UPDATE staff_work_shifts
SET work_mode = 'unset'
WHERE work_mode IS NULL;

ALTER TABLE staff_work_shifts
ALTER COLUMN work_mode SET DEFAULT 'unset';

ALTER TABLE staff_work_shifts
ALTER COLUMN work_mode SET NOT NULL;

-- 制約（既存制約名があれば先に DROP）
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'staff_work_shifts_work_mode_check'
  ) THEN
    ALTER TABLE staff_work_shifts DROP CONSTRAINT staff_work_shifts_work_mode_check;
  END IF;
END $$;

ALTER TABLE staff_work_shifts
ADD CONSTRAINT staff_work_shifts_work_mode_check
CHECK (work_mode IN ('unset', 'clinic', 'field', 'off'));

COMMENT ON COLUMN staff_work_shifts.work_mode IS
  'unset=未設定 / clinic=通常出勤(area必須) / field=帯同 / off=休み';
