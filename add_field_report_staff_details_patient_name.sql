-- field_report_staff_details に patient_name カラムを追加
ALTER TABLE field_report_staff_details
ADD COLUMN IF NOT EXISTS patient_name text;
