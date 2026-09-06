"""C5 チャットUI。本番Knowledgeは変更しない。UI側に予約・医療判定を作らない。

  python scripts/test_karin_chat_c5.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from karin_chat import EMERGENCY_REPLY  # noqa: E402
from karin_chat_memory import reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)

ICON_PATH = "/static/images/chatbotfaceicon.png"
USER_SAFE_ERROR = "申し訳ありません。現在うまくご案内できないようです。少し時間をおいてもう一度お試しください。"
SECRET_MARKERS = (
    "OPENAI",
    "sk-",
    "SUPABASE",
    "traceback",
    "Traceback",
    "SELECT *",
    "api_key",
    "API_KEY",
)


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return len(rows), digest


def read_text(*parts: str) -> str:
    path = os.path.join(ROOT, *parts)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def leaks_secret(text: str) -> bool:
    return any(marker in (text or "") for marker in SECRET_MARKERS)


def main() -> int:
    print("OPENAI_API_KEY:", "設定済み" if (os.getenv("OPENAI_API_KEY") or "").strip() else "未設定")
    failures: list[str] = []

    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print(f"Knowledge snapshot before: n={before_n} hash={before_h[:16]}...")

    js = read_text("static", "js", "karin_chat.js")
    css = read_text("static", "css", "karin_chat.css")
    widget = read_text("templates", "_karin_chat.html")
    chat_page = read_text("templates", "chat.html")

    reset_store_for_tests()
    from app import app

    with app.test_client() as client:
        print("\n===== Test 1 初回チャット =====")
        first = client.post("/api/chat", json={"message": "腰が痛いです。"})
        first_body = first.get_json(silent=True) or {}
        first_id = first_body.get("conversation_id")
        first_reply = first_body.get("reply") or ""
        print("status:", first.status_code)
        print("has_conversation_id:", bool(first_id))
        print("has_reply:", bool(first_reply))
        if first.status_code != 200 or not first_reply:
            failures.append("Test1: 初回 /api/chat で reply がない")
        if not isinstance(first_id, str) or not first_id:
            failures.append("Test1: conversation_id を受け取れない")
        if leaks_secret(json.dumps(first_body, ensure_ascii=False)):
            failures.append("Test1: 応答に秘密情報の疑い")

        print("\n===== Test 2 2ターン目 =====")
        second = client.post(
            "/api/chat",
            json={
                "message": "特に座っているときがつらいです。",
                "conversation_id": first_id,
            },
        )
        second_body = second.get_json(silent=True) or {}
        second_id = second_body.get("conversation_id")
        second_reply = second_body.get("reply") or ""
        print("status:", second.status_code)
        print("same_conversation_id:", second_id == first_id)
        if second.status_code != 200 or not second_reply:
            failures.append("Test2: 2ターン目の reply がない")
        if second_id != first_id:
            failures.append("Test2: conversation_id が継続していない")
        if "conversation_id" not in js or "payload.conversation_id" not in js:
            failures.append("Test2: UIが conversation_id を送信する実装になっていない")

        print("\n===== Test 3 新しいチャット =====")
        third = client.post("/api/chat", json={"message": "初めてなんですが、どんな施術がありますか？"})
        third_body = third.get_json(silent=True) or {}
        third_id = third_body.get("conversation_id")
        print("new_conversation_id:", bool(third_id) and third_id != first_id)
        if not third_id or third_id == first_id:
            failures.append("Test3: IDなし送信で新しい会話を開始できない")
        if "conversationId = null" not in js and "conversationId=null" not in js:
            failures.append("Test3: 新しく相談する で conversation_id を破棄していない")
        if "data-karin-reset" not in widget or "新しく相談する" not in widget:
            failures.append("Test3: 新しく相談する 操作がない")

        print("\n===== Test 4 APIエラー =====")
        bad = client.post("/api/chat", json={})
        bad_body = bad.get_json(silent=True) or {}
        print("empty_status:", bad.status_code)
        if bad.status_code == 200 and bad_body.get("reply"):
            failures.append("Test4: 空メッセージで reply が返った")
        if USER_SAFE_ERROR not in js:
            failures.append("Test4: ユーザー向け安全メッセージがない")
        if re.search(r"body\.error", js) or re.search(r"result\.body\.error", js):
            failures.append("Test4: API error 本文をUIに出す実装がある")
        if "traceback" in js.lower() or "sk-" in js:
            failures.append("Test4: UIソースに内部情報がある")

        print("\n===== Test 5 緊急症状 =====")
        emergency_msg = "急に右半身に力が入らなくなりました"
        emergency = client.post("/api/chat", json={"message": emergency_msg})
        emergency_body = emergency.get_json(silent=True) or {}
        emergency_reply = emergency_body.get("reply") or ""
        print("status:", emergency.status_code)
        print("matches_c1_gate:", emergency_reply == EMERGENCY_REPLY)
        if emergency.status_code != 200 or emergency_reply != EMERGENCY_REPLY:
            failures.append("Test5: C1安全ゲートの応答を表示できない")
        ui_medical = (
            "強い胸痛" in js
            or "呼吸困難" in js
            or "_EMERGENCY_PATTERNS" in js
            or "is_emergency_message" in js
        )
        if ui_medical:
            failures.append("Test5: UI側で独自の医療判定がある")
        if "ご予約はこちら" in emergency_reply:
            failures.append("Test5: 緊急応答に予約誘導がある")

        print("\n===== Test 6 予約枠 =====")
        slot_logic = any(
            token in js
            for token in (
                "/api/book/slots",
                "list_web_booking_slots",
                "duration_minutes",
                "place_type",
                "selectable",
            )
        )
        invented_slots = any(
            token in js
            for token in ('"20:00"', "'20:00'", '"18:00"', "'18:00'", "[60, 90, 120]")
        )
        print("ui_slot_api:", slot_logic)
        print("ui_invented_times:", invented_slots)
        if slot_logic:
            failures.append("Test6: UIが予約API/枠算出を持っている")
        if invented_slots:
            failures.append("Test6: UIが時刻を独自追加している")
        if "renderSafeText" not in js:
            failures.append("Test6: C4の reply をテキスト表示する経路がない")

        print("\n===== Test 7 予約ページ =====")
        chat_html = client.get("/chat")
        book_html = client.get("/book")
        chat_text = chat_html.get_data(as_text=True)
        print("/chat:", chat_html.status_code, "/book:", book_html.status_code)
        if chat_html.status_code != 200:
            failures.append("Test7: /chat が開けない")
        if book_html.status_code != 200:
            failures.append("Test7: /book が開けない")
        if 'href="/book"' not in chat_text and "url_for('book_page')" not in chat_page:
            failures.append("Test7: /book への導線がない")
        if "Web予約ページへ進む" not in js and "ご予約" not in widget:
            failures.append("Test7: 予約ページへのUI導線がない")

        print("\n===== Test 8 XSS =====")
        if "innerHTML" in js:
            failures.append("Test8: innerHTML を使っており XSS のリスクがある")
        if "textContent" not in js:
            failures.append("Test8: テキストとして安全に表示していない")
        if "createElement(\"script\")" in js or "dangerouslySetInnerHTML" in js:
            failures.append("Test8: 危険なHTML挿入がある")

        print("\n===== Test 9 顔アイコン =====")
        icon = client.get(ICON_PATH)
        print("icon_status:", icon.status_code, "content_type:", icon.content_type)
        if icon.status_code != 200:
            failures.append("Test9: chatbotfaceicon.png が静的パスから読めない")
        if "png" not in (icon.content_type or "").lower():
            failures.append(f"Test9: 画像の Content-Type が不正: {icon.content_type}")
        if "chatbotfaceicon.png" not in chat_text or "chatbotfaceicon.png" not in widget:
            failures.append("Test9: テンプレートが顔アイコンを参照していない")
        if 'img.alt = "KARiN.chatbot"' not in js:
            failures.append("Test9: AIアイコンの alt がない")
        if "karin-chat-row--user" not in js:
            failures.append("Test9: ユーザー行の実装がない")
        if re.search(r"row--user[\s\S]{0,400}chatbotfaceicon", js):
            failures.append("Test9: ユーザー側に顔アイコンを付ける実装がある")

        print("\n===== Test 10 レスポンシブ =====")
        if "overflow-wrap" not in css:
            failures.append("Test10: 長文の折り返し指定がない")
        if "min-height: 44px" not in css:
            failures.append("Test10: タップ領域の確保がない")
        if "@media (max-width: 767px)" not in css:
            failures.append("Test10: スマホ幅の調整がない")
        if "100dvh" not in css and "100svh" not in css:
            failures.append("Test10: モバイル画面高の考慮がない")
        if "karin-chat-bubble" not in css or "karin-chat-input" not in css:
            failures.append("Test10: 吹き出しまたは入力欄のスタイルがない")
        if "isMobile" not in js or "Enter" not in js:
            failures.append("Test10: スマホでの誤送信防止がない")

    after_n, after_h = snapshot_knowledge(admin)
    print(f"\nKnowledge snapshot after: n={after_n} hash={after_h[:16]}...")
    if (after_n, after_h) != (before_n, before_h):
        failures.append("Knowledge DB snapshot がテスト前後で変化した")

    if failures:
        print("\nFAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nC5 UIテスト: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
