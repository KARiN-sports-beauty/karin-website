-- ============================================================
-- KARiN.NOTES / NEWS — RLS・GRANT（Supabase SQL Editor）
-- ============================================================
-- 実行前:
--   1. 本番 DB のバックアップを取得
--   2. Flask は server-side のみ service_role（SUPABASE_SERVICE_KEY）を使用
--      → blogs / news の管理 CRUD は supabase_admin 経由
--   3. anon key（supabase）は公開 read のみ（comments テーブルは非公開・データは保持）
--
-- 実行後:
--   - /blog /news / トップの公開記事取得は draft=false でフィルタされること
-- ============================================================


-- ============================================================
-- 1. スキーマ: article_type（KARiN.NOTES）
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
-- 2. 権限（最小権限 GRANT）
--    service_role は RLS をバイパス（サーバー専用・クライアントに露出禁止）
-- ============================================================
REVOKE ALL ON TABLE public.blogs FROM anon, authenticated;
REVOKE ALL ON TABLE public.comments FROM anon, authenticated;
REVOKE ALL ON TABLE public.news FROM anon, authenticated;

GRANT SELECT ON TABLE public.blogs TO anon, authenticated;
GRANT SELECT ON TABLE public.news TO anon, authenticated;

-- シーケンス（id が serial / identity の場合）
DO $$
DECLARE
  seq_name text;
BEGIN
  FOR seq_name IN
    SELECT pg_get_serial_sequence('public.blogs', 'id')
    UNION ALL
    SELECT pg_get_serial_sequence('public.comments', 'id')
    UNION ALL
    SELECT pg_get_serial_sequence('public.news', 'id')
  LOOP
    IF seq_name IS NOT NULL THEN
      EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO anon, authenticated', seq_name);
    END IF;
  END LOOP;
END $$;


-- ============================================================
-- 3. RLS 有効化
-- ============================================================
ALTER TABLE public.blogs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.blogs FORCE ROW LEVEL SECURITY;

ALTER TABLE public.comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.comments FORCE ROW LEVEL SECURITY;

ALTER TABLE public.news ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.news FORCE ROW LEVEL SECURITY;


-- ============================================================
-- 4. 既存ポリシー削除（再実行用）
-- ============================================================
DROP POLICY IF EXISTS blogs_public_select_published ON public.blogs;
DROP POLICY IF EXISTS comments_public_select_published ON public.comments;
DROP POLICY IF EXISTS comments_public_insert_published ON public.comments;
DROP POLICY IF EXISTS news_public_select_published ON public.news;


-- ============================================================
-- 5. blogs — 公開記事のみ anon/authenticated が SELECT 可
-- ============================================================
CREATE POLICY blogs_public_select_published
  ON public.blogs
  AS PERMISSIVE
  FOR SELECT
  TO anon, authenticated
  USING (draft IS NOT TRUE);


-- ============================================================
-- 6. comments — 公開アクセスなし（テーブル・データは保持、service_role のみ）
--    既存の公開ポリシーは削除のみ（再作成しない）
-- ============================================================


-- ============================================================
-- 7. news — 公開のみ SELECT 可
--     ※ draft 列が無い場合は USING (true) に変更してください
-- ============================================================
CREATE POLICY news_public_select_published
  ON public.news
  AS PERMISSIVE
  FOR SELECT
  TO anon, authenticated
  USING (draft IS NOT TRUE);


-- ============================================================
-- 8. Storage: blog-images（任意・バケット名が blog-images の場合）
--    公開 read のみ anon、upload/delete は service_role（サーバー）のみ
-- ============================================================
-- 既存ポリシーがある場合は Dashboard で確認のうえ調整してください。
/*
DROP POLICY IF EXISTS "blog_images_public_read" ON storage.objects;
DROP POLICY IF EXISTS "blog_images_service_write" ON storage.objects;

CREATE POLICY "blog_images_public_read"
  ON storage.objects
  FOR SELECT
  TO anon, authenticated
  USING (bucket_id = 'blog-images');

CREATE POLICY "blog_images_service_write"
  ON storage.objects
  FOR ALL
  TO service_role
  USING (bucket_id = 'blog-images')
  WITH CHECK (bucket_id = 'blog-images');
*/
