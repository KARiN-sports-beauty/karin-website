-- reservations / staff_daily_reports に監査用カラムを追加
-- アプリの reservation_audit_* / staff_daily_report_audit_* と対応
-- Supabase SQL Editor で実行してください（Table Editor でも可）

-- reservations
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'reservations' AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE public.reservations ADD COLUMN updated_at timestamptz;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'reservations' AND column_name = 'created_by'
    ) THEN
        ALTER TABLE public.reservations ADD COLUMN created_by text;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'reservations' AND column_name = 'updated_by'
    ) THEN
        ALTER TABLE public.reservations ADD COLUMN updated_by text;
    END IF;
END $$;

-- staff_daily_reports（updated_at は既存の場合が多い）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'staff_daily_reports' AND column_name = 'created_by'
    ) THEN
        ALTER TABLE public.staff_daily_reports ADD COLUMN created_by text;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'staff_daily_reports' AND column_name = 'updated_by'
    ) THEN
        ALTER TABLE public.staff_daily_reports ADD COLUMN updated_by text;
    END IF;
END $$;
