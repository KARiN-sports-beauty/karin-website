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

-- 初期投入（一括・本日〜365日先、承認済み・非管理者スタッフを 10:00-19:00）
INSERT INTO staff_work_shifts (
    shift_date,
    staff_name,
    start_time,
    end_time,
    is_off,
    updated_by
)
SELECT
    d.shift_date,
    TRIM(
        COALESCE(u.raw_user_meta_data->>'last_name', '') || ' ' ||
        COALESCE(u.raw_user_meta_data->>'first_name', '')
    ) AS staff_name,
    '10:00' AS start_time,
    '19:00' AS end_time,
    FALSE AS is_off,
    'system-init' AS updated_by
FROM auth.users u
CROSS JOIN (
    SELECT generate_series(CURRENT_DATE, CURRENT_DATE + INTERVAL '365 days', INTERVAL '1 day')::date AS shift_date
) d
WHERE COALESCE((u.raw_user_meta_data->>'approved')::boolean, false) = true
  AND COALESCE((u.raw_user_meta_data->>'is_admin')::boolean, false) = false
  AND TRIM(
        COALESCE(u.raw_user_meta_data->>'last_name', '') || ' ' ||
        COALESCE(u.raw_user_meta_data->>'first_name', '')
      ) <> ''
ON CONFLICT (shift_date, staff_name) DO UPDATE
SET
    start_time = EXCLUDED.start_time,
    end_time = EXCLUDED.end_time,
    is_off = EXCLUDED.is_off,
    updated_by = EXCLUDED.updated_by,
    updated_at = NOW();
