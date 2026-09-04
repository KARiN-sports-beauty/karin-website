-- ============================================================
-- KARiN. RAG 基盤（ai_knowledge）
-- ============================================================
-- 既存テーブル・既存関数は変更しない。
-- 追加するもの:
--   - pgvector extension（未導入時のみ）
--   - public.ai_knowledge
--   - similarity search index
--   - public.match_ai_knowledge
--   - RLS / GRANT（anon からの直接操作を不可にする）
-- Embedding: OpenAI text-embedding-3-small / 1536 次元
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;


CREATE TABLE IF NOT EXISTS public.ai_knowledge (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title text NOT NULL,
  content text NOT NULL,
  category text NOT NULL,
  source_type text NOT NULL,
  status text NOT NULL DEFAULT 'active',
  priority integer NOT NULL DEFAULT 50,
  source_url text,
  effective_from timestamptz,
  effective_to timestamptz,
  embedding vector(1536),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ai_knowledge_category_check
    CHECK (category IN (
      'official', 'service', 'pricing', 'reservation',
      'faq', 'notes', 'health', 'safety'
    )),
  CONSTRAINT ai_knowledge_source_type_check
    CHECK (source_type IN ('official', 'notes', 'health')),
  CONSTRAINT ai_knowledge_status_check
    CHECK (status IN ('active', 'inactive'))
);

COMMENT ON TABLE public.ai_knowledge IS 'カリン RAG 用 Knowledge。公開サイトの anon からは直接操作しない。';
COMMENT ON COLUMN public.ai_knowledge.embedding IS 'OpenAI text-embedding-3-small (1536)';
COMMENT ON COLUMN public.ai_knowledge.status IS 'active のみ RAG 検索対象。削除せず inactive にする。';
COMMENT ON COLUMN public.ai_knowledge.priority IS '100=公式, 80=NOTES, 50=一般健康情報。検索は similarity と併用。';
COMMENT ON COLUMN public.ai_knowledge.effective_from IS 'NULL なら常に有効開始。';
COMMENT ON COLUMN public.ai_knowledge.effective_to IS 'NULL なら終了期限なし。';


CREATE INDEX IF NOT EXISTS ai_knowledge_embedding_hnsw_idx
  ON public.ai_knowledge
  USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS ai_knowledge_status_idx
  ON public.ai_knowledge (status);


CREATE OR REPLACE FUNCTION public.match_ai_knowledge(
  query_embedding vector(1536),
  match_count integer DEFAULT 5,
  similarity_threshold double precision DEFAULT 0.0
)
RETURNS TABLE (
  id uuid,
  title text,
  content text,
  category text,
  source_type text,
  priority integer,
  source_url text,
  similarity double precision
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    k.id,
    k.title,
    k.content,
    k.category,
    k.source_type,
    k.priority,
    k.source_url,
    (1 - (k.embedding <=> query_embedding))::double precision AS similarity
  FROM public.ai_knowledge k
  WHERE k.status = 'active'
    AND k.embedding IS NOT NULL
    AND (k.effective_from IS NULL OR k.effective_from <= now())
    AND (k.effective_to IS NULL OR k.effective_to >= now())
    AND (1 - (k.embedding <=> query_embedding)) >= similarity_threshold
  ORDER BY
    k.embedding <=> query_embedding,
    k.priority DESC
  LIMIT GREATEST(match_count, 0);
$$;

COMMENT ON FUNCTION public.match_ai_knowledge(vector(1536), integer, double precision) IS
  'active かつ有効期間内の Knowledge を cosine similarity で返す。Flask service_role からのみ実行する。';


ALTER TABLE public.ai_knowledge ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_knowledge FORCE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.ai_knowledge FROM PUBLIC;
REVOKE ALL ON TABLE public.ai_knowledge FROM anon, authenticated;
GRANT ALL ON TABLE public.ai_knowledge TO service_role;

REVOKE ALL ON FUNCTION public.match_ai_knowledge(vector(1536), integer, double precision) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.match_ai_knowledge(vector(1536), integer, double precision) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.match_ai_knowledge(vector(1536), integer, double precision) TO service_role;
