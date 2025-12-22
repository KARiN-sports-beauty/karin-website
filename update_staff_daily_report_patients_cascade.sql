-- staff_daily_report_patients テーブルの reservation_id の CASCADE 設定を変更
-- 予約を削除したら、日報からも自動的に削除されるようにする

-- 既存の外部キー制約を削除
ALTER TABLE public.staff_daily_report_patients 
DROP CONSTRAINT IF EXISTS staff_daily_report_patients_reservation_id_fkey;

-- 新しい外部キー制約を追加（ON DELETE CASCADE）
ALTER TABLE public.staff_daily_report_patients 
ADD CONSTRAINT staff_daily_report_patients_reservation_id_fkey 
FOREIGN KEY (reservation_id) 
REFERENCES public.reservations(id) 
ON DELETE CASCADE;

-- 注意: この変更により、予約を削除すると関連する staff_daily_report_patients のレコードも自動的に削除されます
-- これにより、予約削除時に明示的に staff_daily_report_patients から削除する処理は不要になります

