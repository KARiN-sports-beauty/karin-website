-- ===================================================
-- 請求書機能のデータベーステーブル作成
-- ===================================================
-- このSQLファイルは、請求書機能（/admin/invoices）で使用する
-- データベーステーブルを作成するためのものです。
-- SupabaseのSQL Editorで実行してください。
-- ===================================================

-- 請求先情報テーブル（現場ごとの請求先情報を保持）
CREATE TABLE IF NOT EXISTS public.invoice_places (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  place_name text UNIQUE NOT NULL, -- 現場名（一意制約）
  address text, -- 住所
  phone text, -- 電話番号
  contact_person text, -- 担当者名
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- 請求書テーブル（基本情報）
CREATE TABLE IF NOT EXISTS public.invoices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_number text UNIQUE NOT NULL, -- 請求書番号（例：INV-2025-01-001）
  place_name text NOT NULL, -- 請求先（現場名）
  place_address text, -- 請求先住所
  place_phone text, -- 請求先電話番号
  place_contact_person text, -- 請求先担当者名
  year int4 NOT NULL, -- 請求対象年
  month int4 NOT NULL, -- 請求対象月
  issue_date date NOT NULL, -- 発行日（基本は月末）
  due_date date NOT NULL, -- 支払期限（基本は翌月末）
  subtotal_amount int4 NOT NULL CHECK (subtotal_amount >= 0), -- 小計（税抜）
  tax_amount int4 NOT NULL DEFAULT 0 CHECK (tax_amount >= 0), -- 消費税額（外税）
  total_amount int4 NOT NULL CHECK (total_amount >= 0), -- 請求合計金額（税込）
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sent', 'paid')), -- 状態（draft: 未作成/発送前, sent: 発送済み, paid: 入金済み）
  sent_at date, -- 発送日
  paid_at date, -- 入金日
  notes text, -- 備考・メモ
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- 請求書明細テーブル
CREATE TABLE IF NOT EXISTS public.invoice_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id uuid NOT NULL REFERENCES public.invoices(id) ON DELETE CASCADE,
  daily_report_item_id uuid, -- 日報の勤務カードID（紐付け用、任意）
  report_date date NOT NULL, -- 日付
  description text, -- 内容・説明
  amount int4 NOT NULL CHECK (amount >= 0), -- 金額
  created_at timestamptz NOT NULL DEFAULT now()
);

-- インデックス（検索パフォーマンス向上のため）
CREATE INDEX IF NOT EXISTS idx_invoice_places_place_name ON public.invoice_places(place_name);
CREATE INDEX IF NOT EXISTS idx_invoices_year_month ON public.invoices(year, month);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON public.invoices(status);
CREATE INDEX IF NOT EXISTS idx_invoices_place_name ON public.invoices(place_name);
CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice_id ON public.invoice_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_invoice_items_daily_report_item_id ON public.invoice_items(daily_report_item_id);

-- ===================================================
-- 備考：
-- - 請求書番号は自動生成（INV-YYYY-MM-XXX形式）
-- - 状態：draft（未作成/発送前）、sent（発送済み）、paid（入金済み）
-- - 請求書は月ごとに現場ごとに作成される
-- - 明細は日報の帯同データから自動生成される
-- - 発行日は基本月末、支払期限は基本翌月末（編集可）
-- - 消費税は外税（税率10%）
-- - 請求先情報（住所、電話番号、担当者）はinvoice_placesテーブルで管理され、
--   同じ現場名の場合は次回も自動反映される
-- ===================================================

