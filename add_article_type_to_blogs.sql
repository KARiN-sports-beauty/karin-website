-- ============================================================
-- KARiN.NOTES: article_type 追加
-- ============================================================
-- RLS / GRANT / POLICY まで含む完全版は supabase_security_rls.sql を使用してください。
-- 本ファイルはスキーマ変更のみ（既に secure 版を実行済みなら不要）
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
