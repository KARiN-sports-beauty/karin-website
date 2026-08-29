"""予約確認メール（Resend）のコード上チェック。APIキーは表示しない。"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import app as app_module


def main():
    key = (os.getenv("RESEND_API_KEY") or "").strip()
    print("RESEND_API_KEY:", "設定済み" if key else "未設定")
    print("BOOKING_FROM_EMAIL:", os.getenv("BOOKING_FROM_EMAIL") or "info@karin-sb.jp (default)")

    src = inspect.getsource(app_module.send_booking_confirmation_email)
    assert "RESEND_API_KEY" in src
    assert "SENDGRID" not in src
    assert "api.resend.com" in src
    assert "/form" in src
    print("send_booking_confirmation_email: Resend 実装 OK")

    src2 = inspect.getsource(app_module.api_book_create)
    assert "send_booking_confirmation_email" in src2
    assert src2.index("send_booking_confirmation_email") > src2.index("atomic_create_web_reservation")
    print("api_book_create: DB登録後にメール送信 OK")

    ok = app_module.send_booking_confirmation_email(
        "",
        "山田",
        "太郎",
        "2026-09-01",
        "10:00",
        90,
        "tokyo",
        "テスト",
        "トータル 90分",
        "",
        place_type="in_house",
    )
    assert ok is False
    print("空メール時スキップ OK")

    print("OK: コード上の確認完了")


if __name__ == "__main__":
    main()
