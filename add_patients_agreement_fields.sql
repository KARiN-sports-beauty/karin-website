-- patientsテーブルに同意書関連のカラムを追加（既に存在する場合はスキップ）

ALTER TABLE public.patients
ADD COLUMN IF NOT EXISTS agreement_confirmed BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS agreed_at DATE;

COMMENT ON COLUMN public.patients.agreement_confirmed IS '同意書確認チェックボックス（署名の代わり）';
COMMENT ON COLUMN public.patients.agreed_at IS '同意書確認日（送信日時で自動設定）';

