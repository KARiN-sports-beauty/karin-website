-- ============================================================
-- KARiN.chatbot 利用分析ログ（最小）
-- ============================================================
-- 既存テーブルは変更しない。追加するもの:
--   - public.chatbot_usage_logs
-- 会話全文・氏名・電話・メール・住所は保存しない。
-- Flask は service_role からのみ INSERT する。anon は不可。
-- ============================================================

CREATE TABLE IF NOT EXISTS public.chatbot_usage_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  intent text,
  choice_set text,
  shown_choices jsonb,
  selected_choice text,
  input_type text,
  next_intent text,
  booking_started boolean NOT NULL DEFAULT false,
  booking_completed boolean NOT NULL DEFAULT false,
  CONSTRAINT chatbot_usage_logs_input_type_check
    CHECK (input_type IS NULL OR input_type IN ('choice', 'free_text', 'other'))
);

COMMENT ON TABLE public.chatbot_usage_logs IS
  'KARiN.chatbot 利用分析。会話全文・個人情報は保存しない。chatbot本体より優先度が低い。';
COMMENT ON COLUMN public.chatbot_usage_logs.conversation_id IS
  '既存チャットの conversation_id（C3 短期状態のIDを再利用）';
COMMENT ON COLUMN public.chatbot_usage_logs.intent IS
  '直前ターンの primary_intent。既存 intent 名を使う。';
COMMENT ON COLUMN public.chatbot_usage_logs.next_intent IS
  'このターンで判定した primary_intent。';
COMMENT ON COLUMN public.chatbot_usage_logs.choice_set IS
  'このターンで表示した CHOICE_SETS のキー';
COMMENT ON COLUMN public.chatbot_usage_logs.shown_choices IS
  'このターンで実際に表示した選択肢';
COMMENT ON COLUMN public.chatbot_usage_logs.selected_choice IS
  '直前に表示した選択肢からの選択。自由入力本文は入れない。';
COMMENT ON COLUMN public.chatbot_usage_logs.input_type IS
  'choice / free_text / other';
COMMENT ON COLUMN public.chatbot_usage_logs.booking_started IS
  'このターンで予約フローに入ったとき true';
COMMENT ON COLUMN public.chatbot_usage_logs.booking_completed IS
  'このターンで予約確定が成功したときだけ true';

CREATE INDEX IF NOT EXISTS chatbot_usage_logs_conversation_id_idx
  ON public.chatbot_usage_logs (conversation_id);

CREATE INDEX IF NOT EXISTS chatbot_usage_logs_created_at_idx
  ON public.chatbot_usage_logs (created_at);

CREATE INDEX IF NOT EXISTS chatbot_usage_logs_intent_idx
  ON public.chatbot_usage_logs (intent);

CREATE INDEX IF NOT EXISTS chatbot_usage_logs_choice_set_idx
  ON public.chatbot_usage_logs (choice_set);

ALTER TABLE public.chatbot_usage_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chatbot_usage_logs FORCE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.chatbot_usage_logs FROM PUBLIC;
REVOKE ALL ON TABLE public.chatbot_usage_logs FROM anon, authenticated;
GRANT ALL ON TABLE public.chatbot_usage_logs TO service_role;
