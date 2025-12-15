-- karte_images テーブルを作成（将来の画像機能用）
CREATE TABLE IF NOT EXISTS public.karte_images (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  log_id uuid NOT NULL REFERENCES public.karte_logs(id) ON DELETE CASCADE,
  image_url text NOT NULL,
  storage_path text,
  created_at timestamptz DEFAULT now()
);

-- log_id にインデックスを追加（検索性能向上）
CREATE INDEX IF NOT EXISTS idx_karte_images_log_id ON public.karte_images(log_id);
