-- セルフケア動画テーブル作成

CREATE TABLE IF NOT EXISTS self_care_videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,  -- 種目名
    video_url TEXT NOT NULL,  -- 動画URL（Supabase Storageまたは外部URL）
    purpose TEXT,  -- 目的
    method TEXT,  -- 方法
    recommended_for TEXT,  -- このような方におすすめ
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス作成
CREATE INDEX IF NOT EXISTS idx_self_care_videos_name ON self_care_videos(name);

-- コメント追加
COMMENT ON TABLE self_care_videos IS 'セルフケア動画テーブル';
COMMENT ON COLUMN self_care_videos.name IS '種目名';
COMMENT ON COLUMN self_care_videos.video_url IS '動画URL';
COMMENT ON COLUMN self_care_videos.purpose IS '目的';
COMMENT ON COLUMN self_care_videos.method IS '方法';
COMMENT ON COLUMN self_care_videos.recommended_for IS 'このような方におすすめ';

