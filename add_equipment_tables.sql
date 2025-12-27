-- 備品管理テーブル作成

-- 1. 備品マスタテーブル
CREATE TABLE IF NOT EXISTS equipment_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,  -- 備品名
    unit TEXT,  -- 単位（個、本、セットなど）
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 年初備品在庫テーブル
CREATE TABLE IF NOT EXISTS equipment_initial_stock (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    year INTEGER NOT NULL,  -- 年
    equipment_item_id UUID NOT NULL REFERENCES equipment_items(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 0,  -- 数量
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(year, equipment_item_id)  -- 同じ年の同じ備品は1つだけ
);

-- 3. 持ち出し備品テーブル
CREATE TABLE IF NOT EXISTS equipment_takeouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    takeout_date DATE NOT NULL,  -- 持ち出し日
    equipment_item_id UUID NOT NULL REFERENCES equipment_items(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 0,  -- 数量
    memo TEXT,  -- メモ（どこに持ち出したかなど）
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. 発注備品テーブル
CREATE TABLE IF NOT EXISTS equipment_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_date DATE NOT NULL,  -- 発注日
    equipment_item_id UUID NOT NULL REFERENCES equipment_items(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 0,  -- 数量
    amount DECIMAL(10, 2),  -- 金額
    status TEXT NOT NULL DEFAULT 'pending',  -- ステータス: pending（未発注）, ordered（発注済み）, arrived（到着済み）
    arrival_date DATE,  -- 到着日（到着済みの場合）
    memo TEXT,  -- メモ
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス作成
CREATE INDEX IF NOT EXISTS idx_equipment_initial_stock_year ON equipment_initial_stock(year);
CREATE INDEX IF NOT EXISTS idx_equipment_initial_stock_item ON equipment_initial_stock(equipment_item_id);
CREATE INDEX IF NOT EXISTS idx_equipment_takeouts_date ON equipment_takeouts(takeout_date);
CREATE INDEX IF NOT EXISTS idx_equipment_takeouts_item ON equipment_takeouts(equipment_item_id);
CREATE INDEX IF NOT EXISTS idx_equipment_orders_date ON equipment_orders(order_date);
CREATE INDEX IF NOT EXISTS idx_equipment_orders_item ON equipment_orders(equipment_item_id);
CREATE INDEX IF NOT EXISTS idx_equipment_orders_status ON equipment_orders(status);

-- コメント追加
COMMENT ON TABLE equipment_items IS '備品マスタテーブル';
COMMENT ON TABLE equipment_initial_stock IS '年初備品在庫テーブル';
COMMENT ON TABLE equipment_takeouts IS '持ち出し備品テーブル';
COMMENT ON TABLE equipment_orders IS '発注備品テーブル';

