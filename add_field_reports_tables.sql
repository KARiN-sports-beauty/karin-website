-- ===================================================
-- 報告書機能のデータベーステーブル作成
-- ===================================================
-- このSQLファイルは、報告書機能（/admin/reports）で使用する
-- データベーステーブルを作成するためのものです。
-- SupabaseのSQL Editorで実行してください。
-- ===================================================

-- 報告書テーブル（基本情報）
CREATE TABLE IF NOT EXISTS public.field_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  field_name text NOT NULL, -- 現場名
  report_date date NOT NULL, -- 報告日
  place text, -- 場所（任意）
  staff_names text[], -- 対応スタッフ（配列）
  column_count int4 NOT NULL DEFAULT 3 CHECK (column_count >= 3 AND column_count <= 5), -- 時間軸表の列数（3〜5列）
  start_time time, -- 開始時間（例：07:00）
  end_time time, -- 終了時間（例：22:00）
  special_notes text, -- 特記事項
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- 報告書時間スロットテーブル（左側の時間軸表）
CREATE TABLE IF NOT EXISTS public.field_report_time_slots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id uuid NOT NULL REFERENCES public.field_reports(id) ON DELETE CASCADE,
  time text NOT NULL, -- "7", "8", "9" などの時間（7時〜26時）
  time_minute text, -- "00", "30" （30分単位）
  column_index int4 NOT NULL CHECK (column_index >= 0 AND column_index < 5), -- 列インデックス（0〜4）
  content text, -- スケジュール内容
  created_at timestamptz NOT NULL DEFAULT now()
);

-- 報告書スタッフ詳細テーブル（右側の対応者情報）
CREATE TABLE IF NOT EXISTS public.field_report_staff_details (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id uuid NOT NULL REFERENCES public.field_reports(id) ON DELETE CASCADE,
  staff_name text NOT NULL, -- スタッフ名
  status text, -- 今日の状態（karte_logs.body_stateから自動反映）
  treatment_content text, -- 施術内容（karte_logs.treatmentから自動反映）
  created_at timestamptz NOT NULL DEFAULT now()
);

-- インデックス（検索パフォーマンス向上のため）
CREATE INDEX IF NOT EXISTS idx_field_reports_date ON public.field_reports(report_date);
CREATE INDEX IF NOT EXISTS idx_field_report_time_slots_report_id ON public.field_report_time_slots(report_id);
CREATE INDEX IF NOT EXISTS idx_field_report_staff_details_report_id ON public.field_report_staff_details(report_id);

