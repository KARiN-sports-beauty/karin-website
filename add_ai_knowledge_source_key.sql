-- ============================================================
-- ai_knowledge.source_key（公式Knowledgeの論理ID）
-- ============================================================
-- RAG再構築ではない。match_ai_knowledge / embedding / 検索条件は変更しない。
-- 既存行の title / content / category / source_type / status / embedding 等は
-- source_key 以外いじらない。
-- 再実行しても安全（IF NOT EXISTS / 冪等 UPDATE）。
-- ============================================================

ALTER TABLE public.ai_knowledge
  ADD COLUMN IF NOT EXISTS source_key text NULL;

COMMENT ON COLUMN public.ai_knowledge.source_key IS
  '①公式Knowledgeの論理ID。titleではない。UUIDの代替でもない。activeかつ非NULLは一意。②③はNULL可。';

CREATE UNIQUE INDEX IF NOT EXISTS ai_knowledge_active_source_key_uidx
  ON public.ai_knowledge (source_key)
  WHERE source_key IS NOT NULL AND status = 'active';


UPDATE public.ai_knowledge
SET source_key = 'basic_info'
WHERE title = 'KARiN.基本情報'
  AND source_type = 'official'
  AND status = 'active'
  AND source_key IS DISTINCT FROM 'basic_info';

UPDATE public.ai_knowledge
SET source_key = 'treatment_policy'
WHERE title = '施術について'
  AND source_type = 'official'
  AND status = 'active'
  AND source_key IS DISTINCT FROM 'treatment_policy';

UPDATE public.ai_knowledge
SET source_key = 'in_house_status'
WHERE title = '現在の院内施術'
  AND source_type = 'official'
  AND status = 'active'
  AND source_key IS DISTINCT FROM 'in_house_status';

UPDATE public.ai_knowledge
SET source_key = 'first_visit_discount'
WHERE title = '初回30%OFFについて'
  AND source_type = 'official'
  AND status = 'active'
  AND source_key IS DISTINCT FROM 'first_visit_discount';
