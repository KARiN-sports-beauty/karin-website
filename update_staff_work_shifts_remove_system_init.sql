-- 勤務時間の自動投入データ（10:00-19:00）を削除し、未設定＝CLOSE 状態に戻す
DELETE FROM staff_work_shifts
WHERE updated_by = 'system-init';
