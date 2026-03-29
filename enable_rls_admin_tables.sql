-- ============================================================
-- 管理系テーブル: RLS 有効化（Supabase SQL Editor で実行）
-- ============================================================
-- 前提:
--   - Flask は supabase_admin（service_role）を使用 → RLS をバイパスするため
--     ポリシーを追加しなくてもサーバーからの読み書きは従来どおり動く。
--   - anon / authenticated 用のポリシーを付けない = クライアント直接アクセスは拒否。
-- 注意:
--   - テーブル名が Supabase 上で異なる場合は該当行だけ修正・スキップすること。
--   - 帯同レポートの時間スロットは field_report_time_slots（field_report_staff_slots は無い）。
-- ============================================================

-- 共通: 各テーブルで RLS を ON（ポリシー無し = anon はデフォルト拒否）
ALTER TABLE IF EXISTS public.equipment_initial_stock ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.equipment_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.equipment_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.equipment_takeouts ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.expenses ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.field_report_staff_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.field_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.field_report_time_slots ENABLE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS public.invoice_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.invoice_places ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.karte_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.karte_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.self_care_videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.staff_daily_report_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.staff_daily_report_patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.staff_daily_report_transportations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.staff_daily_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.staff_salaries ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- （任意）明示的に「anon / authenticated には何もさせない」ポリシー
-- ※ RLS ON でポリシー 0 件でも通常は anon はアクセスできないが、
--    ダッシュボードで挙動をはっきりさせたい場合のみ有効化する。
--    実行前に同じ名前のポリシーが無いか確認すること。
-- ============================================================
/*
-- 例: patients テーブルだけ明示拒否（全テーブルに繰り返し可能）
CREATE POLICY "no_access_for_anon"
  ON public.patients
  FOR ALL
  TO anon, authenticated
  USING (false)
  WITH CHECK (false);
*/
