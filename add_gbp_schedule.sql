-- GBPスケジュール投稿と営業時間更新の状態
-- 記事・サービス用の external_posts には入れない
-- このファイルは自動では適用しない

CREATE TABLE IF NOT EXISTS public.gbp_schedule_posts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  period_key text NOT NULL,
  gbp_profile text NOT NULL,
  status text NOT NULL DEFAULT 'draft',
  body text NOT NULL DEFAULT '',
  link_url text,
  image_url text,
  external_id text,
  error_message text,
  posted_at timestamptz,
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT gbp_schedule_posts_profile_check
    CHECK (gbp_profile IN ('tokyo', 'fukuoka')),
  CONSTRAINT gbp_schedule_posts_status_check
    CHECK (status IN ('draft', 'ready', 'posting', 'posted', 'failed', 'unknown')),
  CONSTRAINT gbp_schedule_posts_posted_requires_receipt
    CHECK (
      status <> 'posted'
      OR (
        posted_at IS NOT NULL
        AND external_id IS NOT NULL
        AND length(btrim(external_id)) > 0
      )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS gbp_schedule_posts_period_profile_uidx
  ON public.gbp_schedule_posts (period_key, gbp_profile);

COMMENT ON TABLE public.gbp_schedule_posts IS
  'GBPスケジュール投稿。半月と東京/福岡の組は1行。posted は媒体の成功確認があるときだけ。';

CREATE TABLE IF NOT EXISTS public.gbp_schedule_post_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  schedule_post_id uuid NOT NULL REFERENCES public.gbp_schedule_posts (id) ON DELETE CASCADE,
  event text NOT NULL,
  body_snapshot text,
  link_url text,
  image_url text,
  detail text,
  actor_staff_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT gbp_schedule_post_events_event_check
    CHECK (event IN (
      'generated', 'edited', 'confirmed',
      'submit_started', 'succeeded', 'failed', 'unknown'
    ))
);

CREATE INDEX IF NOT EXISTS gbp_schedule_post_events_post_idx
  ON public.gbp_schedule_post_events (schedule_post_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.gbp_hours_syncs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  period_key text NOT NULL,
  gbp_profile text NOT NULL,
  status text NOT NULL DEFAULT 'preview',
  payload text,
  error_message text,
  applied_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT gbp_hours_syncs_profile_check
    CHECK (gbp_profile IN ('tokyo', 'fukuoka')),
  CONSTRAINT gbp_hours_syncs_status_check
    CHECK (status IN ('preview', 'applied', 'failed', 'unknown'))
);

CREATE UNIQUE INDEX IF NOT EXISTS gbp_hours_syncs_period_profile_uidx
  ON public.gbp_hours_syncs (period_key, gbp_profile);

COMMENT ON TABLE public.gbp_hours_syncs IS
  'GBP営業時間更新の成否。投稿成功とは別記録。unknown のときは自動再実行しない。';

REVOKE ALL ON TABLE public.gbp_schedule_posts FROM anon, authenticated;
REVOKE ALL ON TABLE public.gbp_schedule_post_events FROM anon, authenticated;
REVOKE ALL ON TABLE public.gbp_hours_syncs FROM anon, authenticated;

ALTER TABLE public.gbp_schedule_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gbp_schedule_posts FORCE ROW LEVEL SECURITY;
ALTER TABLE public.gbp_schedule_post_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gbp_schedule_post_events FORCE ROW LEVEL SECURITY;
ALTER TABLE public.gbp_hours_syncs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gbp_hours_syncs FORCE ROW LEVEL SECURITY;
