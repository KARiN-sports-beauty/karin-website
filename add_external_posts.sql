-- KARiN.NOTES / サービス紹介の外部投稿状態
-- 投稿先: GBP東京 / GBP福岡 / Instagram / Facebook
-- blogs に媒体別フラグは追加しない
-- status = posted は、媒体の受付IDと投稿日時があるときだけ

CREATE TABLE IF NOT EXISTS public.external_posts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_kind text NOT NULL,
  blog_id text,
  service_key text,
  channel text NOT NULL,
  gbp_profile text,
  status text NOT NULL DEFAULT 'draft',
  body text NOT NULL DEFAULT '',
  link_url text,
  image_url text,
  angle_label text,
  external_id text,
  error_message text,
  posted_at timestamptz,
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT external_posts_source_kind_check
    CHECK (source_kind IN ('notes_article', 'service')),
  CONSTRAINT external_posts_channel_check
    CHECK (channel IN ('gbp', 'instagram', 'facebook')),
  CONSTRAINT external_posts_profile_check
    CHECK (
      (channel = 'gbp' AND gbp_profile IN ('tokyo', 'fukuoka'))
      OR (channel <> 'gbp' AND gbp_profile IS NULL)
    ),
  CONSTRAINT external_posts_status_check
    CHECK (status IN ('draft', 'ready', 'posting', 'posted', 'failed', 'unknown')),
  CONSTRAINT external_posts_posted_requires_receipt
    CHECK (
      status <> 'posted'
      OR (
        posted_at IS NOT NULL
        AND external_id IS NOT NULL
        AND length(btrim(external_id)) > 0
      )
    ),
  CONSTRAINT external_posts_source_shape_check
    CHECK (
      (source_kind = 'notes_article' AND blog_id IS NOT NULL AND service_key IS NULL)
      OR (source_kind = 'service' AND service_key IS NOT NULL AND blog_id IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS external_posts_notes_gbp_uidx
  ON public.external_posts (blog_id, gbp_profile)
  WHERE source_kind = 'notes_article' AND channel = 'gbp';

CREATE UNIQUE INDEX IF NOT EXISTS external_posts_notes_social_uidx
  ON public.external_posts (blog_id, channel)
  WHERE source_kind = 'notes_article' AND channel IN ('instagram', 'facebook');

CREATE INDEX IF NOT EXISTS external_posts_service_idx
  ON public.external_posts (service_key, gbp_profile, updated_at DESC)
  WHERE source_kind = 'service';

COMMENT ON TABLE public.external_posts IS
  '外部投稿の現在状態。GBP東京とGBP福岡は別行。posted は媒体の成功応答があるときだけ。';

CREATE TABLE IF NOT EXISTS public.external_post_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  external_post_id uuid NOT NULL REFERENCES public.external_posts (id) ON DELETE CASCADE,
  event text NOT NULL,
  body_snapshot text,
  link_url text,
  image_url text,
  detail text,
  actor_staff_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT external_post_events_event_check
    CHECK (event IN (
      'generated', 'edited', 'confirmed',
      'submit_started', 'succeeded', 'failed', 'unknown'
    ))
);

CREATE INDEX IF NOT EXISTS external_post_events_post_idx
  ON public.external_post_events (external_post_id, created_at DESC);

COMMENT ON TABLE public.external_post_events IS
  '外部投稿の履歴。成功イベントは、媒体の成功応答を受け取った処理だけが書く。';

REVOKE ALL ON TABLE public.external_posts FROM anon, authenticated;
REVOKE ALL ON TABLE public.external_post_events FROM anon, authenticated;

ALTER TABLE public.external_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.external_posts FORCE ROW LEVEL SECURITY;
ALTER TABLE public.external_post_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.external_post_events FORCE ROW LEVEL SECURITY;
