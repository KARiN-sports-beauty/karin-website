-- 収支管理テーブル作成

-- 1. 経費テーブル
CREATE TABLE IF NOT EXISTS expenses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    expense_date DATE NOT NULL,  -- 経費発生日
    year INTEGER NOT NULL,  -- 年（集計用）
    month INTEGER NOT NULL,  -- 月（集計用）
    category TEXT NOT NULL,  -- カテゴリ: salary（給与）, transportation（交通費）, tax（税金）, supplies（消耗品）, other（その他）
    amount DECIMAL(10, 2) NOT NULL,  -- 金額
    description TEXT,  -- 説明
    staff_id UUID,  -- スタッフID（給与・交通費の場合）
    staff_name TEXT,  -- スタッフ名（給与・交通費の場合）
    linked_type TEXT,  -- 紐付けタイプ: equipment_order（備品発注）, manual（手動入力）
    linked_id UUID,  -- 紐付け先ID（備品発注IDなど）
    memo TEXT,  -- メモ
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. スタッフ給与テーブル
CREATE TABLE IF NOT EXISTS staff_salaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    year INTEGER NOT NULL,  -- 年
    month INTEGER NOT NULL,  -- 月
    staff_id UUID NOT NULL,  -- スタッフID
    staff_name TEXT NOT NULL,  -- スタッフ名
    base_salary DECIMAL(10, 2) DEFAULT 0,  -- 基本給
    commission DECIMAL(10, 2) DEFAULT 0,  -- 歩合
    transportation DECIMAL(10, 2) DEFAULT 0,  -- 交通費
    tax DECIMAL(10, 2) DEFAULT 0,  -- 税金
    social_insurance DECIMAL(10, 2) DEFAULT 0,  -- 社会保険
    other_deduction DECIMAL(10, 2) DEFAULT 0,  -- その他控除
    total_salary DECIMAL(10, 2) DEFAULT 0,  -- 総支給額
    net_salary DECIMAL(10, 2) DEFAULT 0,  -- 手取り額
    memo TEXT,  -- メモ
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(year, month, staff_id)  -- 同じ年月の同じスタッフは1つだけ
);

-- インデックス作成
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_expenses_year_month ON expenses(year, month);
CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category);
CREATE INDEX IF NOT EXISTS idx_expenses_staff ON expenses(staff_id);
CREATE INDEX IF NOT EXISTS idx_staff_salaries_year_month ON staff_salaries(year, month);
CREATE INDEX IF NOT EXISTS idx_staff_salaries_staff ON staff_salaries(staff_id);

-- コメント追加
COMMENT ON TABLE expenses IS '経費テーブル';
COMMENT ON TABLE staff_salaries IS 'スタッフ給与テーブル';

