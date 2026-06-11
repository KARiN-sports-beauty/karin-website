CREATE TABLE IF NOT EXISTS staff_work_shifts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shift_date DATE NOT NULL,
    staff_name TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    is_off BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (shift_date, staff_name)
);

CREATE INDEX IF NOT EXISTS idx_staff_work_shifts_date ON staff_work_shifts (shift_date);
CREATE INDEX IF NOT EXISTS idx_staff_work_shifts_staff ON staff_work_shifts (staff_name);

-- Security Advisor の "unrestricted" 対策
ALTER TABLE staff_work_shifts ENABLE ROW LEVEL SECURITY;
ALTER TABLE staff_work_shifts ADD COLUMN IF NOT EXISTS is_off BOOLEAN NOT NULL DEFAULT FALSE;

-- 勤務時間は各スタッフが予定管理画面で入力するまで未設定（CLOSE）とする。
-- 過去に system-init で投入した 10:00-19:00 データがある場合は
-- update_staff_work_shifts_remove_system_init.sql を実行してください。
