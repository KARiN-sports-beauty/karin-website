-- 日報勤務カードの開始・終了に「26:00」等の拡張時刻を保存するため、time 型を text に変更（未適用の場合のみ実行）
-- Supabase SQL エディタ等で実行してください。

ALTER TABLE public.staff_daily_report_items
  ALTER COLUMN start_time TYPE text USING (
    CASE WHEN start_time IS NULL THEN NULL ELSE trim(both from start_time::text) END
  );

ALTER TABLE public.staff_daily_report_items
  ALTER COLUMN end_time TYPE text USING (
    CASE WHEN end_time IS NULL THEN NULL ELSE trim(both from end_time::text) END
  );
