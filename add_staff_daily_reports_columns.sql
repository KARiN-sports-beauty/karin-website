-- staff_daily_reports テーブルに必要なカラムを追加
-- memo と updated_at カラムを追加
-- report_date カラムが存在しない場合は date カラムを report_date にリネーム

-- memo カラムを追加（存在しない場合のみ）
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'staff_daily_reports' 
        AND column_name = 'memo'
    ) THEN
        ALTER TABLE public.staff_daily_reports ADD COLUMN memo text;
    END IF;
END $$;

-- updated_at カラムを追加（存在しない場合のみ）
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'staff_daily_reports' 
        AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE public.staff_daily_reports ADD COLUMN updated_at timestamptz DEFAULT now();
    END IF;
END $$;

-- report_date カラムが存在しない場合、date カラムを report_date にリネーム
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'staff_daily_reports' 
        AND column_name = 'report_date'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'staff_daily_reports' 
            AND column_name = 'date'
        ) THEN
            ALTER TABLE public.staff_daily_reports RENAME COLUMN date TO report_date;
        ELSE
            -- date カラムも存在しない場合は新規作成
            ALTER TABLE public.staff_daily_reports ADD COLUMN report_date date NOT NULL;
        END IF;
    END IF;
END $$;

-- インデックスを追加（存在しない場合のみ）
CREATE INDEX IF NOT EXISTS staff_daily_reports_report_date_idx ON public.staff_daily_reports (report_date);

