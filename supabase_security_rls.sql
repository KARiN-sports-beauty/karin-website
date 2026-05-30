-- ============================================================
-- KARiN. — Supabase セキュリティ一式（RLS / GRANT / POLICY）
-- ============================================================
--
-- 【既存 DB に実行すべきか？】
--   → はい、本番・ステージングともに実行を推奨します。
--
--   理由:
--   1. anon key はブラウザに露出しうるため、DB 側で最小権限 + RLS が必須
--   2. 下書き記事・患者情報・予約などが PostgREST 経由で読まれないよう防御
--   3. コメント機能廃止後、comments への公開 INSERT/SELECT を DB レベルで遮断
--   4. 本 SQL は IF NOT EXISTS / DROP POLICY IF EXISTS 中心で再実行可能（冪等）
--
-- 【実行前チェックリスト】
--   □ Supabase Dashboard → Database → Backups でバックアップ取得
--   □ app.py がデプロイ済み（管理 CRUD は supabase_admin / service_role 使用）
--   □ SUPABASE_SERVICE_KEY がサーバー環境変数のみ（クライアントに露出していない）
--   □ news テーブルに draft 列があること（無い場合は section 3 の POLICY をコメント参照）
--
-- 【実行後の確認】
--   □ /blog /news / トップが表示される
--   □ /admin/* が通常どおり動く
--   □ section 6 の検証クエリを SQL Editor で実行
--
-- 【アーキテクチャ】
--   anon / authenticated … 公開コンテンツ（blogs / news の公開行）SELECT のみ
--   service_role (Flask supabase_admin) … 全管理操作（RLS バイパス）
--   comments … データ保持・アーカイブ。公開ポリシーなし
-- ============================================================


-- ============================================================
-- 1. スキーマ: KARiN.NOTES article_type
-- ============================================================
ALTER TABLE public.blogs
ADD COLUMN IF NOT EXISTS article_type text NOT NULL DEFAULT 'standard';

UPDATE public.blogs
SET article_type = 'standard'
WHERE article_type IS NULL OR article_type = '';

ALTER TABLE public.blogs
DROP CONSTRAINT IF EXISTS blogs_article_type_check;

ALTER TABLE public.blogs
ADD CONSTRAINT blogs_article_type_check
CHECK (article_type IN ('standard', 'feature', 'column'));

CREATE INDEX IF NOT EXISTS idx_blogs_article_type ON public.blogs (article_type);

COMMENT ON COLUMN public.blogs.article_type IS
  'KARiN.NOTES 記事タイプ: standard | feature | column';


-- ============================================================
-- 2. 公開コンテンツ: blogs / news
--    REVOKE → 最小 GRANT → FORCE RLS → 公開 SELECT ポリシーのみ
-- ============================================================
REVOKE ALL ON TABLE public.blogs FROM anon, authenticated;
REVOKE ALL ON TABLE public.news FROM anon, authenticated;

GRANT SELECT ON TABLE public.blogs TO anon, authenticated;
GRANT SELECT ON TABLE public.news TO anon, authenticated;

ALTER TABLE public.blogs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.blogs FORCE ROW LEVEL SECURITY;

ALTER TABLE public.news ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.news FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS blogs_public_select_published ON public.blogs;
DROP POLICY IF EXISTS news_public_select_published ON public.news;

CREATE POLICY blogs_public_select_published
  ON public.blogs
  AS PERMISSIVE
  FOR SELECT
  TO anon, authenticated
  USING (draft IS NOT TRUE);

-- news に draft 列が無い場合は USING (true) に差し替え
CREATE POLICY news_public_select_published
  ON public.news
  AS PERMISSIVE
  FOR SELECT
  TO anon, authenticated
  USING (draft IS NOT TRUE);


-- ============================================================
-- 3. comments — アーカイブ保持・公開アクセスなし
-- ============================================================
REVOKE ALL ON TABLE public.comments FROM anon, authenticated;

ALTER TABLE public.comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.comments FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS comments_public_select_published ON public.comments;
DROP POLICY IF EXISTS comments_public_insert_published ON public.comments;

-- ポリシーを再作成しない = anon / authenticated は一切アクセス不可
-- service_role（Flask サーバー）のみ参照・削除可


-- ============================================================
-- 4. 管理・機密テーブル — RLS ON + ポリシー無し + REVOKE
--    （Flask supabase_admin のみアクセス）
-- ============================================================
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'contacts',
    'patients',
    'karte_logs',
    'karte_images',
    'reservations',
    'staff_daily_reports',
    'staff_daily_report_items',
    'staff_daily_report_patients',
    'staff_daily_report_transportations',
    'staff_work_shifts',
    'staff_salaries',
    'field_reports',
    'field_report_time_slots',
    'field_report_staff_details',
    'field_report_schedules',
    'field_report_staff',
    'equipment_items',
    'equipment_initial_stock',
    'equipment_takeouts',
    'equipment_orders',
    'expenses',
    'invoices',
    'invoice_items',
    'invoice_places',
    'self_care_videos',
    'staff'
  ]
  LOOP
    IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
      EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated', t);
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
      EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', t);
    END IF;
  END LOOP;
END $$;


-- ============================================================
-- 5. シーケンス（serial / identity の場合のみ GRANT）
-- ============================================================
DO $$
DECLARE
  seq_name text;
BEGIN
  FOR seq_name IN
    SELECT pg_get_serial_sequence('public.blogs', 'id')
    UNION ALL SELECT pg_get_serial_sequence('public.news', 'id')
    UNION ALL SELECT pg_get_serial_sequence('public.comments', 'id')
  LOOP
    IF seq_name IS NOT NULL THEN
      EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM anon, authenticated', seq_name);
      -- 公開 INSERT なしのため anon への USAGE は付与しない
    END IF;
  END LOOP;
END $$;


-- ============================================================
-- 6. Storage: blog-images
--    公開 read のみ anon。upload/delete は service_role（サーバー）のみ
-- ============================================================
DROP POLICY IF EXISTS "blog_images_public_read" ON storage.objects;
DROP POLICY IF EXISTS "blog_images_service_write" ON storage.objects;

CREATE POLICY "blog_images_public_read"
  ON storage.objects
  AS PERMISSIVE
  FOR SELECT
  TO anon, authenticated
  USING (bucket_id = 'blog-images');

CREATE POLICY "blog_images_service_write"
  ON storage.objects
  AS PERMISSIVE
  FOR ALL
  TO service_role
  USING (bucket_id = 'blog-images')
  WITH CHECK (bucket_id = 'blog-images');


-- ============================================================
-- 7. 実行後検証（結果を目視確認）
-- ============================================================

-- 7a. RLS が有効な public テーブル一覧
-- SELECT tablename, rowsecurity
-- FROM pg_tables
-- WHERE schemaname = 'public'
-- ORDER BY tablename;

-- 7b. blogs / news の公開ポリシー
-- SELECT tablename, policyname, roles, cmd, qual
-- FROM pg_policies
-- WHERE schemaname = 'public'
--   AND tablename IN ('blogs', 'news', 'comments')
-- ORDER BY tablename, policyname;

-- 7c. anon ロールの blogs 権限（SELECT のみであること）
-- SELECT grantee, privilege_type
-- FROM information_schema.role_table_grants
-- WHERE table_schema = 'public'
--   AND table_name IN ('blogs', 'news', 'comments', 'patients')
--   AND grantee IN ('anon', 'authenticated')
-- ORDER BY table_name, grantee, privilege_type;

-- 7d. 下書きが anon から見えないこと（0 件が正常）
-- SET ROLE anon;
-- SELECT count(*) FROM public.blogs WHERE draft IS TRUE;
-- RESET ROLE;
