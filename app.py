from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, jsonify, flash
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))

def to_jst(dt_str):
    if not dt_str:
        return ""

    try:
        # SupabaseのISO形式 → JST変換
        dt = datetime.fromisoformat(dt_str.replace("Z", ""))
        return dt.astimezone(JST).strftime("%Y/%m/%d %H:%M")
    except Exception:
        return dt_str


import json, os
import mimetypes
from dotenv import load_dotenv
import requests
from supabase import create_client, Client
import uuid
import sendgrid
from sendgrid.helpers.mail import Mail as SGMail



# =====================================
# ▼ .envを読み込む
# =====================================
load_dotenv()


# ===============================
# Supabase 接続設定
# ===============================
SUPABASE_URL = "https://pmuvlinhusxesmhwsxtz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBtdXZsaW5odXN4ZXNtaHdzeHR6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM3OTA1ODAsImV4cCI6MjA3OTM2NjU4MH0.efXpBSYXAqMqvYnQQX1CUSnaymft7j_HzXZX6bHCXHA"
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)



def now_iso():
    """JST の ISO8601 文字列を返す"""
    return datetime.now(JST).isoformat()

def today():
    """JST の YYYY-MM-DD 文字列を返す"""
    return datetime.now(JST).strftime("%Y-%m-%d")

# =========================
# slug生成関数
# =========================
import re

def generate_slug_base(title: str) -> str:
    """
    タイトルから slug のベース文字列を生成（日本語タイトルにも対応する簡易版）。
    日本語や記号は '-' に置き換え、a-z0-9 と - だけを残す。
    """
    s = title.strip()
    # 全角スペースを半角に
    s = s.replace("　", " ")
    # 非ASCIIを一旦ハイフンに
    s_ascii = "".join(ch if ord(ch) < 128 else "-" for ch in s)
    s_ascii = s_ascii.lower()
    # 許可文字以外をハイフンに
    s_ascii = re.sub(r"[^a-z0-9\-]+", "-", s_ascii)
    # 連続ハイフンを1つに
    s_ascii = re.sub(r"-{2,}", "-", s_ascii)
    # 先頭末尾のハイフン除去
    s_ascii = s_ascii.strip("-")

    if not s_ascii:
        # タイトルが全部日本語などで slug が空になった場合のフォールバック
        s_ascii = datetime.now(JST).strftime("post-%Y%m%d-%H%M%S")

    return s_ascii

def generate_unique_slug(table: str, title: str, current_id=None) -> str:
    """
    blogs/news テーブル用の slug を生成。
    既に同じ slug が存在する場合、-2, -3... を付与してユニークにする。
    current_id が指定されている場合、その記事自身は除外してチェックする。
    """
    base = generate_slug_base(title)
    slug = base
    counter = 2

    while True:
        query = supabase_admin.table(table).select("id, slug").eq("slug", slug)
        if current_id is not None:
            query = query.neq("id", current_id)
        res = query.execute()
        if not res.data:
            break
        slug = f"{base}-{counter}"
        counter += 1

    return slug

# ===============================
# LINE通知（Messaging API）
# ===============================

def send_line_message(text: str):
    """
    LINE Messaging API の pushメッセージ送信用（正しい版）
    """
    try:
        line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        user_id = os.getenv("LINE_USER_ID")

        if not line_token:
            print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
            return

        if not user_id:
            print("❌ LINE_USER_ID が設定されていません")
            return

        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {line_token}"
        }

        payload = {
            "to": user_id,
            "messages": [
                {"type": "text", "text": text}
            ]
        }

        response = requests.post(url, headers=headers, json=payload)
        print("📩 LINE送信結果:", response.status_code, response.text)

    except Exception as e:
        print("❌ LINE通知エラー:", e)




# =====================================
# ▼ Flaskアプリ初期化
# =====================================
app = Flask(__name__, template_folder="templates")

@app.template_filter("to_jst")
def to_jst_filter(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return value

app.jinja_env.filters["to_jst"] = to_jst_filter


def calc_age(birthday_str):
    if not birthday_str:
        return None
    birthday = datetime.strptime(birthday_str, "%Y-%m-%d").date()
    today = datetime.now(JST).date()
    return today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))

@app.template_filter("age_from_birthday")
def age_from_birthday_filter(value):
    age = calc_age(value)
    return age if age is not None else ""

app.secret_key = os.getenv("FLASK_SECRET_KEY", "super-secret-key")


# =====================================
# スタッフログインが必要なページ制御
# =====================================
def staff_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "staff" not in session:
            return redirect("/staff/login")
        return f(*args, **kwargs)
    return wrapper


# =====================================
# 管理者が必要なページ制御
# =====================================
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        staff = session.get("staff")
        if not staff or staff.get("is_admin") != True:
            return "権限がありません", 403
        return f(*args, **kwargs)
    return wrapper



# =====================================
# SendGrid 設定（Render からのメール送信）
# =====================================
# Render の環境変数に SENDGRID_API_KEY を設定済み想定
sg = sendgrid.SendGridAPIClient(api_key=os.getenv("SENDGRID_API_KEY"))

FROM_ADDRESS = "info@karin-sb.jp"  # 送信元は共通で info@ に統一


def send_email(from_addr, to_addr, subject, content, reply_to=None):
    """
    SendGrid 経由でプレーンテキストメールを送信するユーティリティ
    """
    try:
        email = SGMail(
            from_email=from_addr,
            to_emails=to_addr,
            subject=subject,
            plain_text_content=content
        )
        if reply_to:
            email.reply_to = reply_to

        response = sg.send(email)
        print("✅ SendGrid response:", response.status_code)
        return response.status_code
    except Exception as e:
        print("❌ SendGrid メール送信エラー:", e)
        return None



# スタッフ承認メール送信用
def send_staff_approved_email(to_addr, name):
    body = f"""
{name} 様

スタッフアカウントが承認されました。

以下よりログインしてご利用いただけます。

https://www.karin-sb.jp/staff/login

KARiN. ~ Sports & Beauty ~
"""

    try:
        send_email(
            from_addr="info@karin-sb.jp",
            to_addr=to_addr,
            subject="【KARiN.】スタッフアカウント承認のお知らせ",
            content=body
        )
        print("📨 承認メール送信完了:", to_addr)
    except Exception as e:
        print("❌ 承認メール送信エラー:", e)





# =====================================
# ▼ ユーティリティ関数
# =====================================
def calc_age(birthday_str):
    if not birthday_str:
        return None
    birthday = datetime.strptime(birthday_str, "%Y-%m-%d").date()
    today = datetime.now(JST).date()
    age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
    return age


def normalize_datetime(dt):
    """
    入力された日時文字列を PostgreSQL が受け取れる ISO8601 に統一する。
    日本語形式（2025年12月31日 23:59）なども吸収。
    """
    if not dt:
        return None

    dt = dt.strip()

    # すでに ISO（2025-12-31T23:59）ならそのまま
    if "T" in dt and "-" in dt:
        return dt

    # 日本語やスラッシュ形式を yyyy-mm-dd hh:mm に揃える
    dt = (
        dt.replace("年", "-")
          .replace("月", "-")
          .replace("日", "")
          .replace("/", "-")
    )

    # "2025-12-31 23:59" → "2025-12-31T23:59"
    if " " in dt:
        parts = dt.split(" ")
        if len(parts) == 2:
            date_part, time_part = parts
            return f"{date_part}T{time_part}"

    return None



def load_schedule():
    try:
        with open("static/data/schedule.json", encoding="utf-8") as f:
            all_schedule = json.load(f)
        today = datetime.today()
        ten_days = today + timedelta(days=10)
        return [s for s in all_schedule if today <= datetime.strptime(s["date"], "%Y-%m-%d") <= ten_days]
    except Exception as e:
        print("❌ schedule.json 読み込みエラー:", e)
        return []

def load_blogs():
    with open("static/data/blogs.json", encoding="utf-8") as f:
        blogs = json.load(f)
    blogs.sort(key=lambda x: datetime.strptime(x["date"], "%Y-%m-%d"), reverse=True)
    return blogs


def load_json_safely(path, default):
    """JSONを安全に読み込む（エラー時は default を返す）"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ JSON読み込みエラー: {path}", e)
        return default


def save_json_safely(path, data):
    """JSONを安全に書き込む"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ JSON書き込みエラー: {path}", e)


def sort_key(p):
    last = p.get("last_visit_date")
    return (last is None, last or "")

# =====================================
# ▼ 各ページルート定義
# =====================================

@app.route("/treatment")
def treatment():
    items = [
        ("鍼灸治療", "腰痛・肩こり・頭痛・関節痛などの慢性痛をはじめ、自律神経のバランス調整による不眠や胃腸・呼吸器系の不調にも対応。", "treatment1.jpg"),
        ("美容鍼", "内側から美しさを引き出す自然派美容法。血行促進・ターンオーバー促進・肌質改善が期待できます。", "treatment2.jpg"),
        ("整体", "スポーツマッサージの手技を中心に身体のバランスを整え、姿勢の改善や自然治癒力を引き出します。", "treatment3.jpg"),
        ("ストレッチ", "筋肉を伸ばして血行促進、疲労回復に効果的。", "treatment4.jpg"),
        ("リコンディショニング", "動きや姿勢を本来の状態に戻し、慢性不調を改善します。", "treatment5.jpg"),
        ("トレーニング", "筋力向上・姿勢改善・ストレス軽減に効果的。", "treatment6.jpg"),
        ("テクニカ・ガビラン", "金属ツールを使った筋膜リリース。癒着の緩和や可動域向上に。", "treatment7.jpg"),
        ("アクティベーター", "軽い刺激で安全に神経を整える調整法。", "treatment8.jpg"),
        ("カッピング（吸玉）", "血流促進・デトックス・自然治癒力を高める伝統療法。", "treatment9.jpg"),
        ("コンプレフロス", "筋膜や関節を圧迫しながら動かして柔軟性を改善。", "treatment10.jpg"),
        ("オイルトリートメント", "リンパの流れを促し、心身のリラックスに◎。", "treatment11.jpg"),
        ("トレーナー帯同", "施術・トレーニング・コンディショニングまで一貫対応。", "treatment12.jpg"),
    ]
    return render_template("treatment.html", items=items)

@app.route("/price")
def price():
    return render_template("price.html")

@app.route("/form", methods=["GET"])
def form():
    years = list(range(datetime.now().year, datetime.now().year - 5, -1))
    months = list(range(1, 13))
    days = list(range(1, 32))
    schedule = load_schedule()
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("form.html", years=years, months=months, days=days, schedule=schedule, today=today)


# ===================================================
# 初診フォーム送信
# ===================================================
@app.route("/submit_form", methods=["POST"])
def submit_form():
    try:
        # フォームデータ取得（姓名分離）
        last_name = request.form.get("last_name", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_kana = request.form.get("last_kana", "").strip()
        first_kana = request.form.get("first_kana", "").strip()
        
        # name / kana を自動生成（半角スペース1つで結合）
        name = f"{last_name} {first_name}".strip()
        kana = f"{last_kana} {first_kana}".strip()
        
        birthday = request.form.get("birthday")
        gender = request.form.get("gender", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        postal_code = request.form.get("postal_code", "").strip()
        address = request.form.get("address", "").strip()
        introducer = request.form.get("introducer", "").strip()
        chief_complaint = request.form.get("chief_complaint", "").strip()
        onset = request.form.get("onset", "").strip()
        pain_level = request.form.get("pain_level", "").strip()
        shinkyu_pref = request.form.get("shinkyu_pref", "").strip()
        electric_pref = request.form.get("electric_pref", "").strip()
        pressure_pref = request.form.get("pressure_pref", "").strip()
        heart = request.form.get("heart", "").strip()
        pregnant = request.form.get("pregnant", "").strip()
        chronic = request.form.get("chronic", "").strip()
        surgery = request.form.get("surgery", "").strip()
        under_medical = request.form.get("under_medical", "").strip()
        signature = request.form.get("signature", "").strip()
        
        # 希望日をフォーマット
        preferred_date1 = normalize_datetime(request.form.get("preferred_date1"))
        preferred_date2 = normalize_datetime(request.form.get("preferred_date2"))
        preferred_date3 = normalize_datetime(request.form.get("preferred_date3"))

        
        # agreed_atをYYYY-MM-DD形式で作成
        agree_year = request.form.get("agree_year", "").strip()
        agree_month = request.form.get("agree_month", "").strip()
        agree_day = request.form.get("agree_day", "").strip()
        agreed_at = f"{agree_year}-{agree_month}-{agree_day}" if agree_year and agree_month and agree_day else None
        
        # Supabase patientsテーブルに保存（DBスキーマと完全同期）
        patient_data = {
            "last_name": last_name,
            "first_name": first_name,
            "last_kana": last_kana,
            "first_kana": first_kana,
            "name": name,
            "kana": kana,
            "birthday": birthday,
            "gender": gender,
            "phone": phone,
            "email": email,
            "postal_code": postal_code,
            "address": address,
            "introducer": introducer,
            "chief_complaint": chief_complaint,
            "onset": onset,
            "pain_level": pain_level,
            "shinkyu_pref": shinkyu_pref,
            "electric_pref": electric_pref,
            "pressure_pref": pressure_pref,
            "heart": heart,
            "pregnant": pregnant,
            "chronic": chronic,
            "surgery": surgery,
            "under_medical": under_medical,
            "preferred_date1": preferred_date1,
            "preferred_date2": preferred_date2,
            "preferred_date3": preferred_date3,
            "signature": signature,
            "agreed_at": agreed_at,
            "note": "",  # 空でも入れる
            "visibility": "all",  # 可視性制御（将来のstaff_role対応用、現時点では'all'固定）
            "created_at": now_iso(),
        }
        
        res = supabase_admin.table("patients").insert(patient_data).execute()
        
        # 保存したデータを取得（JSON用）
        saved_patient = res.data[0] if res.data else patient_data

        # 🟢 LINE通知（introducerも追記）
        age_display = calc_age(birthday) if birthday else "未入力"
        line_message = f"""
【初診フォーム】
お名前：{name}
ふりがな：{kana}
生年月日：{birthday if birthday else '未入力'}
年齢：{age_display}
性別：{gender}
電話番号：{phone}
メール：{email}
住所：{address}
紹介者：{introducer if introducer else 'なし'}
第1希望：{to_jst(preferred_date1) if preferred_date1 else "未入力"}
主訴：{chief_complaint}
"""
        send_line_message(line_message)

        # 📨 メール通知（patientsに保存した内容をJSONで）
        send_email(
            from_addr=FROM_ADDRESS,
            to_addr="form@karin-sb.jp",
            subject="【KARiN.】初診フォーム送信",
            content=json.dumps(saved_patient, ensure_ascii=False, indent=2)
        )

        return redirect(url_for(
            "thanks",
            message="初診受付フォームを送信しました。<br>担当者よりご連絡いたします。"
        ))

    except Exception as e:
        print("❌ 初診フォーム送信エラー:", e)
        return f"サーバーエラー: {str(e)}", 500
    


# ===================================================
# ✅ お問い合わせページ（GET表示用）
# ===================================================
@app.route("/contact")
def contact():
    schedule = load_schedule()
    return render_template("contact.html", schedule=schedule)


# ===================================================
# ✅ お問い合わせフォーム送信
# ===================================================
@app.route("/submit_contact", methods=["POST"])
def submit_contact():
    try:
        name = request.form.get("name")
        phone = request.form.get("phone")
        email = request.form.get("email")
        message = request.form.get("message")
        timestamp = datetime.now(JST).strftime("%Y/%m/%d %H:%M")

        data = {
            "name": name,
            "phone": phone,
            "email": email,
            "message": message,
            "timestamp": timestamp
        }


        # 🟢 LINE通知
        line_message = f"""
【お問い合わせ】
お名前：{name}
電話番号：{phone}
メール：{email}
内容：
{message}
"""
        send_line_message(line_message)

                # 📨 メール通知（SendGrid）
        body_text = (
            f"名前: {name}\n"
            f"電話: {phone}\n"
            f"メール: {email}\n"
            f"日時: {timestamp}\n"
            f"内容:\n{message}"
        )

        send_email(
            from_addr=FROM_ADDRESS,
            to_addr="contact@karin-sb.jp",
            subject="【KARiN.】お問い合わせ",
            content=body_text
        )

        # ▼ Supabase に保存
        supabase_admin.table("contacts").insert({
            "id": str(uuid.uuid4()),
            "name": name,
            "email": email,
            "phone": phone,
            "message": message,
            "created_at": datetime.utcnow().isoformat(),
            "processed": False
        }).execute()



        return redirect(url_for(
            "thanks",
            message="ご予約・お問い合わせありがとうございました。<br>内容を確認のうえ、24時間以内にご連絡いたします。"
        ))

    except Exception as e:
        print("❌ お問い合わせエラー:", e)
        return f"サーバーエラー: {str(e)}", 500


# ===================================================
# ✅ お問い合わせスタッフページ（未返信一覧、返信済み一覧、お問い合わせ詳細、返信済みにするボタン）
# ===================================================
@app.route("/admin/contacts")
@admin_required
def admin_contacts():
    res = supabase_admin.table("contacts") \
        .select("*") \
        .eq("processed", False) \
        .order("created_at", desc=True) \
        .execute()

    return render_template("admin_contacts.html", items=res.data or [])


@app.route("/admin/contacts/replied")
@admin_required
def admin_contacts_replied():
    res = supabase_admin.table("contacts") \
        .select("*") \
        .eq("processed", True) \
        .order("created_at", desc=True) \
        .execute()

    return render_template("admin_contacts_replied.html", items=res.data or [])


@app.route("/admin/contact/<contact_id>")
@admin_required
def admin_contact_detail(contact_id):
    res = supabase_admin.table("contacts").select("*").eq("id", contact_id).execute()
    if not res.data:
        return "お問い合わせが見つかりません", 404
    contact = res.data[0]
    return render_template("admin_contact_detail.html", contact=contact)


@app.route("/admin/contact/<contact_id>/done", methods=["POST"])
@admin_required
def admin_contact_done(contact_id):
    supabase_admin.table("contacts") \
        .update({"processed": True}) \
        .eq("id", contact_id) \
        .execute()

    return redirect("/admin/contacts")




# ===================================================
# ✅ thanks.html
# ===================================================
@app.route("/thanks")
def thanks():
    message = request.args.get("message", "送信ありがとうございました。内容を確認のうえ、24時間以内にご連絡いたします。")
    return render_template("thanks.html", message=message)


# ===================================================
# ✅ スタッフログイン
# ===================================================
@app.route("/staff/register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not name or not phone or not email or not password:
            return render_template("staff_register.html", error="全ての項目を入力してください。")

        # Supabase Auth にユーザー作成（未承認）
        try:
            user = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": {
                        "name": name,
                        "phone": phone,
                        "approved": False
                    }
                }
            })

        except Exception as e:
            print("STAFF REGISTER ERROR:", e)
            return render_template("staff_register.html", error="登録に失敗しました。")

        # 成功画面
        return render_template("staff_register.html", success=True)

    # GETメソッド → 登録画面表示
    return render_template("staff_register.html")


# ===================================================
# パスワードリセット（メール送信）
# ===================================================
@app.route("/staff/forgot-password", methods=["GET", "POST"])
def staff_forgot_password():
    if request.method == "GET":
        return render_template("forgot_password.html")

    email = request.form.get("email")

    try:
        # Supabase のパスワードリセットメール送信
        supabase.auth.reset_password_email(email)

        return render_template(
            "forgot_password.html",
            message="パスワード再設定メールを送信しました。メールをご確認ください。"
        )

    except Exception as e:
        print("RESET PASS ERROR:", e)
        return render_template(
            "forgot_password.html",
            error="メール送信に失敗しました。メールアドレスをご確認ください。"
        )


@app.route("/auth")
def auth_handler():
    return render_template("auth.html")



# ============================
# スタッフ一覧（承認/停止管理）
# ============================
@app.route("/admin/staff")
@admin_required
def admin_staff():
    try:
        # SDK によっては list_users() が「リスト」を返す
        users = supabase_admin.auth.admin.list_users()
        print("USERS RAW:", users)  # ← デバッグ用
    except Exception as e:
        print("❌ STAFF LIST ERROR:", e)
        users = []

    staff_list = []

    # ここが重要！ users は「そのままリストなので」 users.users ではない
    for u in users:
        meta = u.user_metadata or {}

        staff_list.append({
            "id": u.id,
            "email": u.email,
            "name": meta.get("name", "未設定"),
            "phone": meta.get("phone", "未登録"),
            "approved": meta.get("approved", False),
            "created_at": str(u.created_at)[:10],
        })

    return render_template("admin_staff.html", staff=staff_list)




# 承認
@app.route("/admin/staff/approve/<user_id>", methods=["POST"])
@admin_required
def admin_staff_approve(user_id):

    try:
        # ユーザー情報の取得
        users = supabase_admin.auth.admin.list_users()
        user = next((u for u in users if u.id == user_id), None)

        if not user:
            flash("ユーザーが見つかりません", "error")
            return redirect("/admin/staff")

        meta = user.user_metadata or {}

        # 承認処理
        supabase_admin.auth.admin.update_user_by_id(
            user_id,
            {"user_metadata": {"approved": True}}
        )

        # 承認メール送信
        send_staff_approved_email(user.email, meta.get("name", ""))

        flash("スタッフを承認しました（メール送信済み）", "success")

    except Exception as e:
        print("❌ APPROVE ERROR:", e)
        flash("承認処理に失敗しました。", "error")

    return redirect("/admin/staff")




# 承認解除（停止）
@app.route("/admin/staff/disable/<user_id>", methods=["POST"])
@admin_required
def admin_staff_disable(user_id):
    try:
        supabase_admin.auth.admin.update_user_by_id(
            user_id,
            {
                "user_metadata": { "approved": False }
            }
        )

        flash("スタッフを停止しました。", "success")
    except Exception as e:
        print("❌ DISABLE ERROR:", e)
        flash("停止処理に失敗しました。", "error")
    return redirect("/admin/staff")


# スタッフ削除
@app.route("/admin/staff/delete/<user_id>", methods=["POST"])
@admin_required
def admin_staff_delete(user_id):
    try:
        supabase_admin.auth.admin.delete_user(user_id)
        print("🗑️ STAFF DELETED:", user_id)
    except Exception as e:
        print("❌ DELETE STAFF ERROR:", e)

    return redirect("/admin/staff")



@app.route("/staff/profile", methods=["GET"])
@staff_required
def staff_profile():
    staff = session.get("staff")

    return render_template(
        "staff_profile.html",
        staff=staff,
        message=request.args.get("message")
    )


@app.route("/staff/profile", methods=["POST"])
@staff_required
def staff_profile_update():
    try:
        staff = session.get("staff")
        user_id = staff["id"]

        new_name = request.form.get("name")
        new_phone = request.form.get("phone", "")

        # Supabase Auth メタデータ更新
        result = supabase_admin.auth.admin.update_user_by_id(
            uid=user_id,
            attributes={
                "user_metadata": {
                    "name": new_name,
                    "phone": new_phone
                }
            }
        )

        # セッション情報を更新（ここ重要）
        session["staff"]["name"] = new_name
        session["staff"]["phone"] = new_phone

        return redirect(url_for(
            "staff_profile",
            message="プロフィールを更新しました"
        ))

    except Exception as e:
        print("PROFILE UPDATE ERROR:", e)
        return f"エラーが発生しました: {e}", 500



@app.route("/staff/login", methods=["GET"])
def staff_login_page():
    return render_template("stafflogin.html")


# スタッフログイン処理
@app.route("/staff/login", methods=["POST"])
def staff_login():
    email = request.form.get("email")
    password = request.form.get("password")

    try:
        data = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
    except Exception as e:
        print("STAFF LOGIN ERROR:", e)
        return render_template("stafflogin.html", error="ログインに失敗しました")

    # ログイン失敗チェック
    if not getattr(data, "user", None):
        return render_template("stafflogin.html", error="メールまたはパスワードが違います")

    user = data.user
    metadata = getattr(user, "user_metadata", {}) or {}

    # 🔥 承認チェック（ここが正しい位置）
    if not metadata.get("approved", False):
        return render_template("stafflogin.html", error="まだ管理者の承認が必要です")

    # 🔹 表示名を決定
    full_name = (
        metadata.get("name")
        or metadata.get("full_name")
        or email
    )

    is_admin = metadata.get("is_admin", False)

    # 🔹 セッション保存（承認後）
    session["staff"] = {
        "id": user.id,
        "email": user.email,
        "name": full_name,
        "is_admin": is_admin
    }

    return redirect("/admin/dashboard")



@app.route("/staff/logout")
def staff_logout():
    session.pop("staff", None)
    return redirect("/staff/login")



@app.route("/admin/dashboard")
@staff_required
def admin_dashboard():
    """
    スタッフログイン後に表示する管理ダッシュボード。
    - 未返信コメント数（comments.reply IS NULL）
    - 未処理お問い合わせ数（contacts.processed = False）
    を Supabase から取得してテンプレートに渡す。
    """

    # ---------- 未返信コメント数 ----------
    try:
        res_unreplied = (
            supabase
            .table("comments")
            .select("id", count="exact")
            .is_("reply", None)
            .execute()
        )
        unreplied_comments = res_unreplied.count or 0
    except Exception as e:
        print("❌ 未返信コメント数取得エラー:", e)
        unreplied_comments = 0

    # ---------- 未処理お問い合わせ数（contacts） ----------
    try:
        res_unprocessed = (
            supabase_admin
            .table("contacts")  # ★ contacts テーブルを使用
            .select("id", count="exact")
            .eq("processed", False)
            .execute()
        )
        unprocessed_contacts = res_unprocessed.count or 0
    except Exception as e:
        print("❌ 未処理お問い合わせ数取得エラー:", e)
        unprocessed_contacts = 0

    # ---------- スタッフ名（フルネーム） ----------
    staff = session.get("staff", {})
    staff_name = staff.get("name") or staff.get("email") or "スタッフ"

    # ---------- テンプレートへ ----------
    return render_template(
        "admin_dashboard.html",
        unreplied_comments=unreplied_comments,
        unprocessed_contacts=unprocessed_contacts,
        staff_name=staff_name,
    )





# ===================================================
# ✅ ログイン・登録・マイページ
# ===================================================
@app.route("/login")
def login():
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        # save_user_to_db(name, email, password)
        return redirect(url_for(
            'thanks',
            message=( 
                "会員登録が完了しました。<br>"
                "ログインページよりお進みください。<br><br>"
                "<a href='/login' class='btn-link'>▶ ログインページへ</a>")
        ))
    return render_template('register.html')

@app.route("/mypage")
def mypage():
    return render_template("mypage.html")

# ===================================================
# ✅ ブログ・ニュース
# ===================================================
@app.route("/test_supabase")
def test_supabase():
    try:
        response = supabase.table("blogs").select("*").execute()
        return {"status": "ok", "data": response.data}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.route("/blog")
def blog():
    query = request.args.get("q")
    category = request.args.get("category")

    sb = supabase.table("blogs").select("*")

    if category:
        sb = sb.eq("category", category)

    if query:
        sb = sb.ilike("title", f"%{query}%")

    res = sb.order("created_at", desc=True).execute()
    blogs = res.data

    # ★ ここでブログの中身をログに出す（確認用）
    print("BLOGS_FROM_DB:", blogs)

    return render_template("blog.html", blogs=blogs, current_category=category, query=query)



# ===========================
# ブログ詳細（slug 版）
# ===========================
@app.route("/blog/<slug>")
def show_blog(slug):
    # 対象ブログ取得（slug で検索）
    res = supabase.table("blogs").select("*").eq("slug", slug).execute()
    data = res.data

    if not data:
        return render_template("404.html"), 404

    blog = data[0]
    blog_id = blog["id"]  # ← コメント・いいね取得用に必要

    # コメント取得（新しい順）
    comments_res = (
        supabase
        .table("comments")
        .select("*")
        .eq("blog_id", blog_id)
        .order("created_at", desc=True)
        .execute()
    )
    comments = comments_res.data or []

    print("💬 COMMENTS_DEBUG:", comments)  # ← これ追加

    # いいね数取得
    like_res = (
        supabase
        .table("likes")
        .select("liked", count="exact")
        .eq("blog_id", blog_id)
        .eq("liked", True)
        .execute()
    )
    like_count = like_res.count or 0

    return render_template(
        "blog_detail.html",
        blog=blog,
        comments=comments,
        like_count=like_count
    )


# ===================================================
# ✅ ブログ管理（/admin/blogs）
# ===================================================
@app.route("/admin/blogs")
@staff_required
def admin_blogs():
    """ブログ一覧（新しい順）"""
    try:
        res = supabase_admin.table("blogs").select("*").order("created_at", desc=True).execute()
        blogs = res.data or []
        return render_template("admin_blogs.html", blogs=blogs)
    except Exception as e:
        print("❌ ブログ一覧取得エラー:", e)
        return "ブログ一覧の取得に失敗しました", 500


@app.route("/admin/blogs/new", methods=["GET", "POST"])
@staff_required
def admin_blog_new():
    """新規ブログ作成"""
    if request.method == "GET":
        return render_template("admin_blog_new.html")
    
    # POST処理
    title = request.form.get("title", "").strip()
    if not title:
        flash("タイトルを入力してください", "error")
        return render_template("admin_blog_new.html")
    
    slug_input = request.form.get("slug", "").strip()
    if slug_input:
        slug = generate_unique_slug("blogs", slug_input)
    else:
        slug = generate_unique_slug("blogs", title)

    excerpt = request.form.get("excerpt", "").strip()
    image = request.form.get("image", "").strip()
    category = request.form.get("category", "").strip()
    tags_raw = request.form.get("tags", "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    body_raw = request.form.get("body", "").strip()
    body_html = body_raw.replace("\n", "<br>") if body_raw else "<p>(本文未入力)</p>"
    draft = request.form.get("draft") == "on"
    
    insert_data = {
        "title": title,
        "slug": slug,
        "excerpt": excerpt,
        "image": image,
        "category": category,
        "tags": tags,
        "body": body_html,
        "draft": draft,
        "date": today(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    
    try:
        res = supabase_admin.table("blogs").insert(insert_data).execute()
        blog_id = res.data[0]["id"]
        flash("ブログを作成しました", "success")
        return redirect(f"/admin/blogs/edit/{blog_id}")
    except Exception as e:
        print("❌ ブログ作成エラー:", e)
        flash(f"ブログの作成に失敗しました: {e}", "error")
        return render_template("admin_blog_new.html")


@app.route("/admin/blogs/edit/<blog_id>", methods=["GET", "POST"])
@staff_required
def admin_blog_edit(blog_id):
    """ブログ編集"""
    if request.method == "GET":
        try:
            res = supabase_admin.table("blogs").select("*").eq("id", blog_id).execute()
            if not res.data:
                flash("ブログが見つかりません", "error")
                return redirect("/admin/blogs")
            blog = res.data[0]
            # bodyの<br>を\nに戻す
            if blog.get("body"):
                blog["body"] = blog["body"].replace("<br>", "\n")
            return render_template("admin_blog_edit.html", blog=blog)
        except Exception as e:
            print("❌ ブログ取得エラー:", e)
            flash("ブログの取得に失敗しました", "error")
            return redirect("/admin/blogs")
    
    # POST処理
    title = request.form.get("title", "").strip()
    if not title:
        flash("タイトルを入力してください", "error")
        return redirect(f"/admin/blogs/edit/{blog_id}")
    
    slug_input = request.form.get("slug", "").strip()
    if slug_input:
        slug = generate_unique_slug("blogs", slug_input, current_id=blog_id)
    else:
        slug = generate_unique_slug("blogs", title, current_id=blog_id)
    
    excerpt = request.form.get("excerpt", "").strip()
    image = request.form.get("image", "").strip()
    category = request.form.get("category", "").strip()
    tags_raw = request.form.get("tags", "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    body_raw = request.form.get("body", "").strip()
    body_html = body_raw.replace("\n", "<br>") if body_raw else "<p>(本文未入力)</p>"
    draft = request.form.get("draft") == "on"
    
    update_data = {
        "title": title,
        "slug": slug,
        "excerpt": excerpt,
        "image": image,
        "category": category,
        "tags": tags,
        "body": body_html,
        "draft": draft,
        "updated_at": now_iso(),
    }
    
    try:
        supabase_admin.table("blogs").update(update_data).eq("id", blog_id).execute()
        flash("ブログを更新しました", "success")
        return redirect(f"/admin/blogs/edit/{blog_id}")
    except Exception as e:
        print("❌ ブログ更新エラー:", e)
        flash(f"ブログの更新に失敗しました: {e}", "error")
        return redirect(f"/admin/blogs/edit/{blog_id}")


@app.route("/admin/blogs/delete/<blog_id>", methods=["POST"])
@staff_required
def admin_blog_delete(blog_id):
    """ブログ削除"""
    try:
        supabase_admin.table("blogs").delete().eq("id", blog_id).execute()
        flash("ブログを削除しました", "success")
    except Exception as e:
        print("❌ ブログ削除エラー:", e)
        flash(f"ブログの削除に失敗しました: {e}", "error")
    return redirect("/admin/blogs")


# ===================================================
# ✅ ニュース管理（/admin/news）
# ===================================================
@app.route("/admin/news")
@staff_required
def admin_news():
    """ニュース一覧（新しい順）"""
    try:
        res = supabase_admin.table("news").select("*").order("created_at", desc=True).execute()
        news_list = res.data or []
        return render_template("admin_news.html", news_list=news_list)
    except Exception as e:
        print("❌ ニュース一覧取得エラー:", e)
        return "ニュース一覧の取得に失敗しました", 500


@app.route("/admin/news/new", methods=["GET", "POST"])
@staff_required
def admin_news_new():
    """新規ニュース作成"""
    if request.method == "GET":
        return render_template("admin_news_new.html")
    
    # POST処理
    title = request.form.get("title", "").strip()
    if not title:
        flash("タイトルを入力してください", "error")
        return render_template("admin_news_new.html")
    
    slug_input = request.form.get("slug", "").strip()
    if slug_input:
        slug = generate_unique_slug("news", slug_input)
    else:
        slug = generate_unique_slug("news", title)

    excerpt = request.form.get("excerpt", "").strip()
    image = request.form.get("image", "").strip()
    category = request.form.get("category", "").strip()
    tags_raw = request.form.get("tags", "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    body_raw = request.form.get("body", "").strip()
    body_html = body_raw.replace("\n", "<br>") if body_raw else "<p>(本文未入力)</p>"
    draft = request.form.get("draft") == "on"
    
    insert_data = {
        "title": title,
        "slug": slug,
        "excerpt": excerpt,
        "image": image,
        "category": category,
        "tags": tags,
        "body": body_html,
        "draft": draft,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    
    try:
        res = supabase_admin.table("news").insert(insert_data).execute()
        news_id = res.data[0]["id"]
        flash("ニュースを作成しました", "success")
        return redirect(f"/admin/news/edit/{news_id}")
    except Exception as e:
        print("❌ ニュース作成エラー:", e)
        flash(f"ニュースの作成に失敗しました: {e}", "error")
        return render_template("admin_news_new.html")


@app.route("/admin/news/edit/<news_id>", methods=["GET", "POST"])
@staff_required
def admin_news_edit(news_id):
    """ニュース編集"""
    if request.method == "GET":
        try:
            res = supabase_admin.table("news").select("*").eq("id", news_id).execute()
            if not res.data:
                flash("ニュースが見つかりません", "error")
                return redirect("/admin/news")
            news = res.data[0]
            # bodyの<br>を\nに戻す
            if news.get("body"):
                news["body"] = news["body"].replace("<br>", "\n")
            return render_template("admin_news_edit.html", news=news)
        except Exception as e:
            print("❌ ニュース取得エラー:", e)
            flash("ニュースの取得に失敗しました", "error")
            return redirect("/admin/news")
    
    # POST処理
    title = request.form.get("title", "").strip()
    if not title:
        flash("タイトルを入力してください", "error")
        return redirect(f"/admin/news/edit/{news_id}")
    
    slug_input = request.form.get("slug", "").strip()
    if slug_input:
        slug = generate_unique_slug("news", slug_input, current_id=news_id)
    else:
        slug = generate_unique_slug("news", title, current_id=news_id)
    
    excerpt = request.form.get("excerpt", "").strip()
    image = request.form.get("image", "").strip()
    category = request.form.get("category", "").strip()
    tags_raw = request.form.get("tags", "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    body_raw = request.form.get("body", "").strip()
    body_html = body_raw.replace("\n", "<br>") if body_raw else "<p>(本文未入力)</p>"
    draft = request.form.get("draft") == "on"
    
    update_data = {
        "title": title,
        "slug": slug,
        "excerpt": excerpt,
        "image": image,
        "category": category,
        "tags": tags,
        "body": body_html,
        "draft": draft,
        "updated_at": now_iso(),
    }
    
    try:
        supabase_admin.table("news").update(update_data).eq("id", news_id).execute()
        flash("ニュースを更新しました", "success")
        return redirect(f"/admin/news/edit/{news_id}")
    except Exception as e:
        print("❌ ニュース更新エラー:", e)
        flash(f"ニュースの更新に失敗しました: {e}", "error")
        return redirect(f"/admin/news/edit/{news_id}")


@app.route("/admin/news/delete/<news_id>", methods=["POST"])
@staff_required
def admin_news_delete(news_id):
    """ニュース削除"""
    try:
        supabase_admin.table("news").delete().eq("id", news_id).execute()
        flash("ニュースを削除しました", "success")
    except Exception as e:
        print("❌ ニュース削除エラー:", e)
        flash(f"ニュースの削除に失敗しました: {e}", "error")
    return redirect("/admin/news")


# ===================================================
# ✅ カルテ管理（/admin/karte）【IN句 最適化 完全版】
# ===================================================
@app.route("/admin/karte/new", methods=["GET", "POST"])
@staff_required
def admin_karte_new():
    if request.method == "GET":
        # 全患者一覧を取得（姓名分離、生年月日、紹介者、紹介者数も取得）
        try:
            # まず基本情報を取得
            res_all = supabase_admin.table("patients").select("id, last_name, first_name, last_kana, first_kana, name, kana, birthday, introducer").order("name").execute()
            all_patients = res_all.data or []
            
            # 各患者の紹介者数を取得
            for patient in all_patients:
                res_introduced = supabase_admin.table("patients").select("id", count="exact").eq("introduced_by_patient_id", patient["id"]).execute()
                patient["introduced_count"] = res_introduced.count or 0
        except Exception as e:
            print("❌ 患者一覧取得エラー:", e)
            all_patients = []
        
        return render_template("admin_karte_new.html", all_patients=all_patients)

    # POST処理
    try:
        # 姓名分離フィールドを取得
        last_name = request.form.get("last_name", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_kana = request.form.get("last_kana", "").strip()
        first_kana = request.form.get("first_kana", "").strip()
        
        # name / kana を自動生成（半角スペース1つで結合）
        name = f"{last_name} {first_name}".strip()
        kana = f"{last_kana} {first_kana}".strip()
        
        data = {
            "last_name": last_name,
            "first_name": first_name,
            "last_kana": last_kana,
            "first_kana": first_kana,
            "name": name,
            "kana": kana,
            "birthday": request.form.get("birthday", "").strip() or None,
            "gender": request.form.get("gender", "").strip(),
            "category": request.form.get("category", "").strip(),
            "introducer": request.form.get("introducer", "").strip(),
            "introduced_by_patient_id": request.form.get("introduced_by_patient_id", "").strip() or None,
            "visibility": "all",  # 可視性制御（将来のstaff_role対応用、現時点では'all'固定）
            "created_at": now_iso()
        }
        
        supabase_admin.table("patients").insert(data).execute()
        flash("カルテを作成しました", "success")
        return redirect("/admin/karte")
    except Exception as e:
        print("❌ カルテ作成エラー:", e)
        flash(f"カルテの作成に失敗しました: {e}", "error")
        # エラー時も患者一覧を取得して再表示
        try:
            res_all = supabase_admin.table("patients").select("id, name, kana").order("name").execute()
            all_patients = res_all.data or []
        except:
            all_patients = []
        return render_template("admin_karte_new.html", all_patients=all_patients)


@app.route("/admin/karte")
@staff_required
def admin_karte():
    """カルテ一覧（高速化IN句対応版）"""
    try:
        # ✅ patients 全件取得
        res_patients = supabase_admin.table("patients").select("*").execute()
        patients = res_patients.data or []

        # ✅ karte_logs 最終来院日取得
        res_logs = supabase_admin.table("karte_logs").select("patient_id, date").execute()
        logs = res_logs.data or []

        # ✅ 最終来院日マップ作成
        last_visit_map = {}
        for log in logs:
            pid = log.get("patient_id")
            date = log.get("date")
            if pid:
                if pid not in last_visit_map or (date and date > last_visit_map[pid]):
                    last_visit_map[pid] = date

        # ✅ 紹介者IDだけを一括収集
        introducer_ids = list({
            p.get("introduced_by_patient_id")
            for p in patients
            if p.get("introduced_by_patient_id")
        })

        introducer_map = {}

        # ✅ IN句で紹介者を一括取得（ここが最重要：姓名分離フィールドも取得）
        if introducer_ids:
            res_intro = (
                supabase_admin
                .table("patients")
                .select("id, last_name, first_name, last_kana, first_kana, name")
                .in_("id", introducer_ids)
                .execute()
            )
            if res_intro.data:
                introducer_map = {
                    p["id"]: p for p in res_intro.data
                }

        # ✅ 紹介された人数を一括取得（各患者が紹介した人数）
        # introduced_by_patient_idをキーにして紹介人数をCOUNTするmapをPython側で作成
        introduced_count_map = {}
        if patients:
            patient_ids = [p.get("id") for p in patients if p.get("id")]
            if patient_ids:
                # introduced_by_patient_idがpatient_idsに含まれる患者を一括取得
                res_introduced_patients = supabase_admin.table("patients").select("introduced_by_patient_id").in_("introduced_by_patient_id", patient_ids).execute()
                if res_introduced_patients.data:
                    # 紹介者IDごとにカウント（Python側で集計）
                    for patient_record in res_introduced_patients.data:
                        intro_id = patient_record.get("introduced_by_patient_id")
                        if intro_id:
                            introduced_count_map[intro_id] = introduced_count_map.get(intro_id, 0) + 1

        # ✅ patients に 最終来院日・紹介者情報・紹介者数 を合成
        for patient in patients:
            pid = patient.get("id")

            patient["last_visit_date"] = last_visit_map.get(pid)
            intro_id = patient.get("introduced_by_patient_id")
            introducer_info = introducer_map.get(intro_id)
            if introducer_info:
                # 紹介者の紹介者数を追加
                introducer_info["introduced_count"] = introduced_count_map.get(introducer_info.get("id"), 0)
            patient["introducer_info"] = introducer_info
            # 現在の患者が紹介した人数
            patient["introduced_count"] = introduced_count_map.get(pid, 0)

        # ✅ 並び順（最後に来た人が上）
        patients.sort(key=sort_key, reverse=True)
        
        # ✅ 紹介者ランキング取得（上位10名）
        introducer_ranking = []
        if introduced_count_map:
            # 紹介人数でソート（降順）
            sorted_introducers = sorted(
                introduced_count_map.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]  # 上位10名のみ
            
            # 各紹介者の情報を取得
            for introducer_id, count in sorted_introducers:
                introducer_info = introducer_map.get(introducer_id)
                if introducer_info:
                    # 名前を結合
                    name = f"{introducer_info.get('last_name', '')} {introducer_info.get('first_name', '')}".strip()
                    if not name:
                        name = introducer_info.get('name', '不明')
                    
                    introducer_ranking.append({
                        "patient_id": introducer_id,
                        "name": name,
                        "count": count
                    })

        return render_template("admin_karte.html", patients=patients, introducer_ranking=introducer_ranking)

    except Exception as e:
        print("❌ カルテ一覧取得エラー:", e)
        return "カルテ一覧の取得に失敗しました", 500


@app.route("/admin/karte/<patient_id>")
@staff_required
def admin_karte_detail(patient_id):
    """カルテ詳細"""
    try:
        # 患者情報取得
        res_patient = supabase_admin.table("patients").select("*").eq("id", patient_id).execute()
        if not res_patient.data:
            flash("患者が見つかりません", "error")
            return redirect("/admin/karte")
        patient = res_patient.data[0]
        
        # デバッグ: heart と under_medical の値を確認
        print(f"🔍 DEBUG - patient.heart: {patient.get('heart')} (type: {type(patient.get('heart'))})")
        print(f"🔍 DEBUG - patient.under_medical: {patient.get('under_medical')} (type: {type(patient.get('under_medical'))})")
        
        # 紹介者情報取得（姓名分離フィールドも取得）
        introducer_info = None
        if patient.get("introduced_by_patient_id"):
            res_intro = supabase_admin.table("patients").select("id, last_name, first_name, last_kana, first_kana").eq("id", patient.get("introduced_by_patient_id")).execute()
            if res_intro.data:
                introducer_info = res_intro.data[0]
                introducer_id = introducer_info.get("id")
                # 紹介者の紹介者数を一括取得（N+1を避けるため）
                if introducer_id:
                    res_introducer_count = supabase_admin.table("patients").select("id", count="exact").eq("introduced_by_patient_id", introducer_id).execute()
                    introducer_info["introduced_count"] = res_introducer_count.count or 0
        patient["introducer_info"] = introducer_info
        
        # 現在の患者が紹介した人数を取得（表示用）
        res_introduced = supabase_admin.table("patients").select("id", count="exact").eq("introduced_by_patient_id", patient_id).execute()
        patient["introduced_count"] = res_introduced.count or 0
        
        # この患者が紹介した患者一覧を取得
        res_introduced_patients = supabase_admin.table("patients").select("id, last_name, first_name, last_kana, first_kana, name, kana, birthday").eq("introduced_by_patient_id", patient_id).order("created_at", desc=True).execute()
        patient["introduced_patients"] = res_introduced_patients.data or []
        
        # karte_logs取得（IN句で高速化）
        res_logs = supabase_admin.table("karte_logs").select("*").eq("patient_id", patient_id).order("date", desc=True).execute()
        logs = res_logs.data or []
        
        # ログIDを収集して画像を一括取得（karte_imagesテーブルが存在しない場合でもエラーにしない）
        log_ids = [log.get("id") for log in logs if log.get("id")]
        log_images_map = {}
        if log_ids:
            try:
                res_images = supabase_admin.table("karte_images").select("*").in_("log_id", log_ids).execute()
                if res_images.data:
                    for img in res_images.data:
                        log_id = img.get("log_id")
                        if log_id not in log_images_map:
                            log_images_map[log_id] = []
                        log_images_map[log_id].append(img)
            except Exception as e:
                # karte_imagesテーブルが存在しない場合など、エラーが発生しても処理を続行
                print(f"⚠️ WARNING - karte_images取得エラー（テーブルが存在しない可能性）: {e}")
                # log_images_mapは空のまま（画像なしとして扱う）
        
        # ログに画像を追加
        for log in logs:
            log["images"] = log_images_map.get(log.get("id"), [])
        
        # 最終来院日を取得
        last_visit_date = None
        if logs:
            last_visit_date = logs[0].get("date")
        patient["last_visit_date"] = last_visit_date
        
        # staff_nameは既にDBから取得されているため、追加処理は不要
        # ログからstaff_idなどの不要な参照を削除（staff_nameのみを使用）
        for log in logs:
            # staff_idなどの不要なキーを削除（将来のstaff_id導入まで）
            if "staff_id" in log:
                del log["staff_id"]
            if "staff" in log:
                del log["staff"]
        
        # 管理者チェック
        staff = session.get("staff", {})
        is_admin = staff.get("is_admin") == True
        
        return render_template("admin_karte_detail.html", patient=patient, logs=logs, is_admin=is_admin)
    except Exception as e:
        print("❌ カルテ詳細取得エラー:", e)
        flash("カルテ詳細の取得に失敗しました", "error")
        return redirect("/admin/karte")


@app.route("/admin/karte/<patient_id>/edit", methods=["GET", "POST"])
@staff_required
def admin_karte_edit(patient_id):
    """基本情報編集"""
    if request.method == "GET":
        try:
            res = supabase_admin.table("patients").select("*").eq("id", patient_id).execute()
            if not res.data:
                flash("患者が見つかりません", "error")
                return redirect("/admin/karte")
            patient = res.data[0]
            
            # 紹介者候補を取得（検索用：姓名分離、生年月日、紹介者も取得）
            res_all = supabase_admin.table("patients").select("id, last_name, first_name, last_kana, first_kana, birthday, introducer").order("name").execute()
            all_patients = res_all.data or []
            
            return render_template("admin_karte_edit.html", patient=patient, all_patients=all_patients)
        except Exception as e:
            print("❌ 患者取得エラー:", e)
            flash("患者の取得に失敗しました", "error")
            return redirect("/admin/karte")
    
    # POST処理
    try:
        # 姓名分離フィールドを取得
        last_name = request.form.get("last_name", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_kana = request.form.get("last_kana", "").strip()
        first_kana = request.form.get("first_kana", "").strip()
        
        # name / kana を自動生成（半角スペース1つで結合）
        name = f"{last_name} {first_name}".strip()
        kana = f"{last_kana} {first_kana}".strip()
        
        update_data = {
            "last_name": last_name,
            "first_name": first_name,
            "last_kana": last_kana,
            "first_kana": first_kana,
            "name": name,
            "kana": kana,
            "birthday": request.form.get("birthday", "").strip() or None,
            "gender": request.form.get("gender", "").strip(),
            "category": request.form.get("category", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "email": request.form.get("email", "").strip(),
            "postal_code": request.form.get("postal_code", "").strip(),
            "address": request.form.get("address", "").strip(),
            "introduced_by_patient_id": request.form.get("introduced_by_patient_id", "").strip() or None,
            "chief_complaint": request.form.get("chief_complaint", "").strip(),
            "heart": request.form.get("heart", "").strip(),
            "pregnant": request.form.get("pregnant", "").strip(),
            "chronic": request.form.get("chronic", "").strip(),
            "surgery": request.form.get("surgery", "").strip(),
            "under_medical": request.form.get("under_medical", "").strip(),
            "shinkyu_pref": request.form.get("shinkyu_pref", "").strip(),
            "electric_pref": request.form.get("electric_pref", "").strip(),
            "pressure_pref": request.form.get("pressure_pref", "").strip(),
            "signature": request.form.get("signature", "").strip(),
            "agreed_at": request.form.get("agreed_at", "").strip() or None,
            "note": request.form.get("note", "").strip(),
        }
        
        supabase_admin.table("patients").update(update_data).eq("id", patient_id).execute()
        flash("基本情報を更新しました", "success")
        return redirect(f"/admin/karte/{patient_id}")
    except Exception as e:
        print("❌ 基本情報更新エラー:", e)
        flash(f"基本情報の更新に失敗しました: {e}", "error")
        return redirect(f"/admin/karte/{patient_id}/edit")


@app.route("/admin/karte/<patient_id>/log/new", methods=["GET", "POST"])
@staff_required
def admin_karte_new_log(patient_id):
    """新規施術ログ作成"""
    if request.method == "GET":
        try:
            # 同一日付のログが存在するかチェック（指示⑤）
            today = datetime.now(JST).strftime("%Y-%m-%d")
            res_existing = supabase_admin.table("karte_logs").select("id").eq("patient_id", patient_id).eq("date", today).execute()
            if res_existing.data:
                # 既存のログがあれば編集画面へリダイレクト
                log_id = res_existing.data[0]["id"]
                return redirect(f"/admin/karte/log/{log_id}/edit")
            
            res = supabase_admin.table("patients").select("id, name").eq("id", patient_id).execute()
            if not res.data:
                flash("患者が見つかりません", "error")
                return redirect("/admin/karte")
            patient = res.data[0]
            
            staff = session.get("staff", {})
            staff_name = staff.get("name", "スタッフ")
            
            # スタッフリストを取得（承認済みスタッフのみ）
            staff_list = []
            try:
                # まずstaffテーブルから取得を試みる
                try:
                    res_staff = supabase_admin.table("staff").select("id, name").execute()
                    if res_staff.data:
                        staff_list = [{"name": s.get("name", "不明"), "id": s.get("id")} for s in res_staff.data]
                except:
                    # staffテーブルがない場合は、現在のスタッフのみ
                    staff_list = [{"name": staff_name, "id": staff.get("id")}]
                
                # 現在のスタッフがリストに含まれていない場合は追加
                current_staff_in_list = any(s.get("id") == staff.get("id") for s in staff_list)
                if not current_staff_in_list:
                    staff_list.append({"name": staff_name, "id": staff.get("id")})
            except Exception as e:
                print("❌ スタッフリスト取得エラー:", e)
                # エラー時は現在のスタッフのみ
                staff_list = [{"name": staff_name, "id": staff.get("id")}]
            
            # 日付のデフォルト値（クエリパラメータがあればそれ、なければ今日）
            date_param = request.args.get("date")
            if date_param:
                try:
                    # 日付形式を検証
                    datetime.strptime(date_param, "%Y-%m-%d")
                    today_date = date_param
                except:
                    today_date = datetime.now(JST).strftime("%Y-%m-%d")
            else:
                today_date = datetime.now(JST).strftime("%Y-%m-%d")
            
            return render_template("admin_karte_new_log.html", patient=patient, staff_name=staff_name, staff_list=staff_list, today_date=today_date)
        except Exception as e:
            print("❌ 患者取得エラー:", e)
            flash("患者の取得に失敗しました", "error")
            return redirect("/admin/karte")
    
    # POST処理
    try:
        # staff_nameはフォームから取得し、空文字の場合はNoneに変換
        staff_name = request.form.get("staff_name", "").strip() or None
        
        # スキーマ準拠のデータ構造
        log_data = {
            "patient_id": patient_id,
            "date": request.form.get("date", "").strip(),
            "place_type": request.form.get("place_type", "").strip(),
            "place_name": request.form.get("place_name", "").strip(),
            "chief_complaint": request.form.get("chief_complaint", "").strip(),
            "body_state": request.form.get("body_state", "").strip(),
            "treatment": request.form.get("treatment", "").strip(),
            "staff_name": staff_name,
            "memo": request.form.get("memo", "").strip(),
            "created_at": now_iso(),
        }
        
        res = supabase_admin.table("karte_logs").insert(log_data).execute()
        log_id = res.data[0]["id"] if res.data else None
        
        flash("施術ログを作成しました", "success")
        return redirect(f"/admin/karte/{patient_id}")
    except Exception as e:
        print("❌ 施術ログ作成エラー:", e)
        flash(f"施術ログの作成に失敗しました: {e}", "error")
        return redirect(f"/admin/karte/{patient_id}/log/new")


@app.route("/admin/karte/<patient_id>/log/<log_id>/edit", methods=["GET", "POST"])
@staff_required
def admin_karte_log_edit(patient_id, log_id):
    """施術ログ編集"""
    if request.method == "GET":
        try:
            res = supabase_admin.table("karte_logs").select("*").eq("id", log_id).execute()
            if not res.data:
                flash("ログが見つかりません", "error")
                return redirect(f"/admin/karte/{patient_id}")
            log = res.data[0]
            
            # patient_idの整合性チェック
            if log.get("patient_id") != patient_id:
                flash("患者IDが一致しません", "error")
                return redirect(f"/admin/karte/{patient_id}")
            
            res_patient = supabase_admin.table("patients").select("id, name").eq("id", patient_id).execute()
            patient = res_patient.data[0] if res_patient.data else None
            
            if not patient:
                flash("患者が見つかりません", "error")
                return redirect("/admin/karte")
            
            # 画像取得
            try:
                res_images = supabase_admin.table("karte_images").select("*").eq("log_id", log_id).execute()
                images = res_images.data or []
            except Exception as e:
                print(f"⚠️ WARNING - karte_images取得エラー: {e}")
                images = []
            log["images"] = images
            
            staff = session.get("staff", {})
            staff_name = log.get("staff_name") or staff.get("name", "スタッフ")
            
            # スタッフリストを取得（新規作成画面と同じロジック）
            staff_list = []
            try:
                try:
                    res_staff = supabase_admin.table("staff").select("id, name").execute()
                    if res_staff.data:
                        staff_list = [{"name": s.get("name", "不明"), "id": s.get("id")} for s in res_staff.data]
                except:
                    staff_list = [{"name": staff_name, "id": staff.get("id")}]
                
                current_staff_in_list = any(s.get("id") == staff.get("id") for s in staff_list)
                if not current_staff_in_list:
                    staff_list.append({"name": staff_name, "id": staff.get("id")})
            except Exception as e:
                print("❌ スタッフリスト取得エラー:", e)
                staff_list = [{"name": staff_name, "id": staff.get("id")}]
            
            return render_template("admin_karte_log_edit.html", log=log, patient=patient, staff_name=staff_name, staff_list=staff_list)
        except Exception as e:
            print("❌ ログ取得エラー:", e)
            flash("ログの取得に失敗しました", "error")
            return redirect(f"/admin/karte/{patient_id}")
    
    # POST処理
    try:
        # staff_nameはフォームから取得し、空文字の場合はNoneに変換
        staff_name = request.form.get("staff_name", "").strip() or None
        
        update_data = {
            "date": request.form.get("date", "").strip(),
            "place_type": request.form.get("place_type", "").strip(),
            "place_name": request.form.get("place_name", "").strip(),
            "chief_complaint": request.form.get("chief_complaint", "").strip(),
            "body_state": request.form.get("body_state", "").strip(),
            "treatment": request.form.get("treatment", "").strip(),
            "staff_name": staff_name,
            "memo": request.form.get("memo", "").strip(),
        }
        
        supabase_admin.table("karte_logs").update(update_data).eq("id", log_id).execute()
        flash("施術ログを更新しました", "success")
        
        return redirect(f"/admin/karte/{patient_id}")
    except Exception as e:
        print("❌ 施術ログ更新エラー:", e)
        flash(f"施術ログの更新に失敗しました: {e}", "error")
        return redirect(f"/admin/karte/log/{log_id}/edit")


@app.route("/admin/karte/log/<log_id>/img", methods=["POST"])
@staff_required
def admin_karte_log_upload_image(log_id):
    """画像アップロード"""
    try:
        if "image" not in request.files:
            return jsonify({"error": "画像が選択されていません"}), 400
        
        file = request.files["image"]
        if file.filename == "":
            return jsonify({"error": "ファイルが選択されていません"}), 400
        
        # ファイル名を生成
        ext = os.path.splitext(file.filename)[1].lower()
        safe_name = f"{uuid.uuid4().hex}{ext}"
        storage_path = f"{log_id}/{safe_name}"
        
        # MIMEタイプを取得
        mime_type, _ = mimetypes.guess_type(file.filename)
        if not mime_type:
            mime_type = "application/octet-stream"
        
        # Supabase Storageにアップロード
        file_data = file.read()
        supabase_admin.storage.from_("karte-images").upload(
            path=storage_path,
            file=file_data,
            file_options={"content-type": mime_type}
        )
        
        # public URLを取得
        public_url = supabase_admin.storage.from_("karte-images").get_public_url(storage_path)
        
        # karte_imagesテーブルに保存
        supabase_admin.table("karte_images").insert({
            "log_id": log_id,
            "image_url": public_url,
            "storage_path": storage_path,
            "created_at": now_iso(),
        }).execute()
        
        return jsonify({"success": True, "url": public_url})
    except Exception as e:
        print("❌ 画像アップロードエラー:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/admin/karte/<patient_id>/delete", methods=["POST"])
@admin_required
def admin_karte_delete(patient_id):
    """カルテ削除（管理者のみ）"""
    try:
        supabase_admin.table("patients").delete().eq("id", patient_id).execute()
        flash("カルテを削除しました", "success")
    except Exception as e:
        print("❌ カルテ削除エラー:", e)
        flash(f"カルテの削除に失敗しました: {e}", "error")
    return redirect("/admin/karte")


@app.route("/admin/karte/log/<log_id>/delete", methods=["POST"])
@admin_required
def admin_karte_log_delete(log_id):
    """施術ログ削除（管理者のみ）"""
    try:
        # ログからpatient_idを取得
        res = supabase_admin.table("karte_logs").select("patient_id").eq("id", log_id).execute()
        patient_id = res.data[0].get("patient_id") if res.data else None
        
        # 画像を削除
        res_images = supabase_admin.table("karte_images").select("storage_path").eq("log_id", log_id).execute()
        for img in res_images.data or []:
            storage_path = img.get("storage_path")
            if storage_path:
                try:
                    supabase_admin.storage.from_("karte-images").remove([storage_path])
                except:
                    pass
        
        # 画像レコードを削除
        supabase_admin.table("karte_images").delete().eq("log_id", log_id).execute()
        
        # ログを削除
        supabase_admin.table("karte_logs").delete().eq("id", log_id).execute()
        
        flash("施術ログを削除しました", "success")
        return redirect(f"/admin/karte/{patient_id}")
    except Exception as e:
        print("❌ 施術ログ削除エラー:", e)
        flash(f"施術ログの削除に失敗しました: {e}", "error")
        return redirect("/admin/karte")


@app.route("/admin/karte/image/<image_id>/delete", methods=["POST"])
@admin_required
def admin_karte_image_delete(image_id):
    """画像削除（管理者のみ）"""
    try:
        # 画像情報を取得
        res = supabase_admin.table("karte_images").select("log_id, storage_path").eq("id", image_id).execute()
        if not res.data:
            return jsonify({"error": "画像が見つかりません"}), 404
        
        image = res.data[0]
        log_id = image.get("log_id")
        storage_path = image.get("storage_path")
        
        # Storageから削除
        if storage_path:
            try:
                supabase_admin.storage.from_("karte-images").remove([storage_path])
            except:
                pass
        
        # 画像レコードを削除
        supabase_admin.table("karte_images").delete().eq("id", image_id).execute()
        
        # ログからpatient_idを取得
        res_log = supabase_admin.table("karte_logs").select("patient_id").eq("id", log_id).execute()
        patient_id = res_log.data[0].get("patient_id") if res_log.data else None
        
        flash("画像を削除しました", "success")
        return redirect(f"/admin/karte/{patient_id}")
    except Exception as e:
        print("❌ 画像削除エラー:", e)
        flash(f"画像の削除に失敗しました: {e}", "error")
        return redirect("/admin/karte")


# ===========================
# NEWS 詳細（slug 版）
# ===========================
@app.route("/news/<slug>")
def show_news(slug):
    res = supabase.table("news").select("*").eq("slug", slug).execute()
    if not res.data:
        return render_template("404.html"), 404

    news = res.data[0]

    if not news.get("body"):
        news["body"] = "<p>この記事の内容は準備中です。</p>"

    return render_template("news_detail.html", news=news)



@app.route("/news")
def news_list():
    # Supabase から取得（下書き以外）
    res = supabase.table("news").select("*").order("created_at", desc=True).execute()
    items = res.data or []

    # 日付整形（blogs と合わせる）
    for n in items:
        n["date"] = (n.get("created_at") or "")[:10]

    return render_template("news.html", news_list=items)




# ===================================================
# ✅ トップ
# ===================================================
@app.route("/")
def index():

    # ----------------------------------------
    # 最新ブログ 3件
    # ----------------------------------------
    latest_blogs = []
    try:
        latest_blogs_res = (
            supabase
            .table("blogs")
            .select("*")
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
        latest_blogs = latest_blogs_res.data or []
    except Exception as e:
        print("❌ latest_blogs 取得エラー:", e)



    # ----------------------------------------
    # 最新ニュース 3件
    # ----------------------------------------
    latest_news = []
    try:
        latest_news_res = (
            supabase
            .table("news")
            .select("*")
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
        latest_news = latest_news_res.data or []

        # ★ created_at → date に変換
        for n in latest_news:
            if n.get("created_at"):
                n["date"] = n["created_at"][:10]
            else:
                n["date"] = ""
    except Exception as e:
        print("❌ latest_news 取得エラー:", e)



    # ----------------------------------------
    # スケジュール読み込み（今日を左端に）
    # ----------------------------------------
    with open("static/data/schedule.json", encoding="utf-8") as f:
        schedule = json.load(f)

    today = datetime.now().date()
    upcoming = []

    for s in schedule:
        d = datetime.strptime(s["date"], "%Y-%m-%d").date()
        if d >= today:
            upcoming.append(s)

    upcoming = upcoming[:10]



    # ----------------------------------------
    # レンダリング
    # ----------------------------------------
    return render_template(
        "index.html",
        latest_blogs=latest_blogs,
        latest_news=latest_news,
        schedule=upcoming,
        today=today
    )




# =====================================
# いいね API（Supabase版・トグル式）
# =====================================
@app.route("/api/like/<int:blog_id>", methods=["POST"])
def api_like(blog_id):
    try:
        user_token = request.cookies.get("user_token")
        if not user_token:
            user_token = str(uuid.uuid4())

        # 既に like しているか判定
        res = supabase.table("likes").select("*").eq("blog_id", blog_id).eq("user_token", user_token).execute()
        rows = res.data

        if rows:
            row = rows[0]
            new_state = not row["liked"]   # トグル切り替え
            supabase.table("likes").update({"liked": new_state}).eq("id", row["id"]).execute()
        else:
            new_state = True
            supabase.table("likes").insert({
                "blog_id": blog_id,
                "user_token": user_token,
                "liked": True
            }).execute()

        # 総いいね数 (liked=Trueのみ)
        count_res = supabase.table("likes").select("liked", count="exact").eq("blog_id", blog_id).eq("liked", True).execute()
        like_count = count_res.count

        resp = jsonify({"status": "ok", "count": like_count, "liked": new_state})
        resp.set_cookie("user_token", user_token, max_age=3600*24*365)
        return resp

    except Exception as e:
        print("LIKE ERROR:", e)
        return {"status": "error", "message": str(e)}, 500





# ===================================================
# 💬 Supabase コメント API
# ===================================================
@app.route("/api/comment", methods=["POST"])
def api_comment():
    # JSON かフォームデータかを自動判定
    if request.is_json:
        req = request.get_json()
    else:
        req = request.form

    slug = req.get("slug", "").strip()
    name = req.get("name", "匿名").strip()
    body = req.get("body", "").strip()

    if not slug or not body:
        return {"error": "コメントが空です"}, 400

    # blog_id を取得
    res = supabase.table("blogs").select("id").eq("slug", slug).execute()
    if not res.data:
        return {"error": "記事が見つかりません"}, 404

    blog_id = res.data[0]["id"]

    # コメント保存（分までの時刻）
    created_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    supabase.table("comments").insert({
        "blog_id": blog_id,
        "name": name,
        "body": body,
        "created_at": created_at
    }).execute()

    # 📨 コメント通知メール（SendGrid）
    body_text = (
        f"ブログ: {slug}\n"
        f"名前: {name}\n"
        f"時間: {created_at}\n"
        f"コメント:\n{body}"
    )

    send_email(
        from_addr=FROM_ADDRESS,
        to_addr="comment@karin-sb.jp",
        subject=f"【KARiN.】新しいコメント（{slug}）",
        content=body_text,
        reply_to=FROM_ADDRESS
    )

    # 🔥 ここがポイント：記事ページに戻す（即最新コメント反映！）
    return redirect(url_for("show_blog", slug=slug))



@app.route("/admin/comments")
@staff_required
def admin_comments():

    try:
        # ✅ 未返信コメント（reply が NULL）
        res_unreplied = (
            supabase
            .table("comments")
            .select("*")
            .is_("reply", None)
            .order("created_at", desc=True)
            .execute()
        )

        unreplied = res_unreplied.data or []

        # ✅ blog_id からブログ情報を後から付与
        for c in unreplied:
            blog_id = c.get("blog_id")
            if blog_id:
                b = supabase.table("blogs").select("title, slug").eq("id", blog_id).execute()
                if b.data:
                    c["blog"] = b.data[0]
                else:
                    c["blog"] = None


        res_replied = (
            supabase
            .table("comments")
            .select("*")
            .not_.is_("reply", None) 
            .order("reply_date", desc=True)
            .limit(6)
            .execute()
        )

        replied = res_replied.data or []

        for c in replied:
            blog_id = c.get("blog_id")
            if blog_id:
                b = supabase.table("blogs").select("title, slug").eq("id", blog_id).execute()
                if b.data:
                    c["blog"] = b.data[0]
                else:
                    c["blog"] = None


        return render_template(
            "admin_comments.html",
            unreplied=unreplied,
            replied=replied
        )

    except Exception as e:
        print("❌ ADMIN COMMENTS ERROR:", e)
        return "コメント取得エラー", 500
    


@app.route("/admin/reply/<comment_id>", methods=["GET", "POST"])
@staff_required
def admin_reply(comment_id):

    # =========================
    # ✅ GET：返信画面の表示
    # =========================
    if request.method == "GET":
        res = (
            supabase
            .table("comments")
            .select("*")
            .eq("id", str(comment_id))
            .execute()
        )

        if not res.data:
            return "コメントが見つかりません", 404

        comment = res.data[0]
        return render_template("comment_reply.html", comment=comment)

    # =========================
    # ✅ POST：返信の保存
    # =========================
    reply_text = request.form.get("reply")
    if not reply_text:
        return "返信内容が空です", 400

    reply_date = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    # ✅ ログイン中スタッフ名をそのまま使用
    reply_author = session["staff"]["name"]

    # ✅ コメント更新（返信内容 + 日付 + 返信者）
    update_res = (
        supabase
        .table("comments")
        .update({
            "reply": reply_text,
            "reply_date": reply_date,
            "reply_author": reply_author
        })
        .eq("id", str(comment_id))
        .execute()
    )

    print("UPDATE_RES:", update_res)

    # ✅ メール通知（今まで通り）
    send_email(
        from_addr=FROM_ADDRESS,
        to_addr="comment@karin-sb.jp",
        subject="【KARiN.】コメント返信通知",
        content=f"コメントID {comment_id} に返信:\n{reply_text}",
        reply_to=FROM_ADDRESS
    )

    # ✅ 返信後は「元のブログ」ではなく「管理画面の一覧」に戻す
    return redirect("/admin/comments")







@app.route("/sitemap.xml")
def sitemap():
    try:
        pages = []

        base_url = "https://karin-sb.jp"

        # --- 固定ページ ---
        static_urls = [
            "/", "/treatment", "/price", "/contact",
            "/form", "/login", "/register", "/blog", "/news"
        ]
        for url in static_urls:
            pages.append(
                f"<url><loc>{base_url}{url}</loc><changefreq>weekly</changefreq></url>"
            )

        # --- ブログ ---
        if os.path.exists("static/data/blogs.json"):
            with open("static/data/blogs.json", encoding="utf-8") as f:
                blogs = json.load(f)
            for b in blogs:
                pages.append(
                    f"<url><loc>{base_url}/blog/{b['id']}</loc><changefreq>weekly</changefreq></url>"
                )

        # --- お知らせ ---
        if os.path.exists("static/data/news.json"):
            with open("static/data/news.json", encoding="utf-8") as f:
                news = json.load(f)
            for n in news:
                pages.append(
                    f"<url><loc>{base_url}/news/{n['id']}</loc><changefreq>weekly</changefreq></url>"
                )

        # --- XML 全体（⚠️ 最初の改行なし） ---
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(pages) +
            "</urlset>"
        )

        return app.response_class(xml, mimetype="application/xml")

    except Exception as e:
        print("❌ sitemap 生成エラー:", e)
        return "Sitemap generation error", 500

@app.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Disallow: /mypage",
        "Disallow: /login",
        "Disallow: /register",
        "",
        "Allow: /",
        "",
        "Sitemap: https://karin-sb.jp/sitemap.xml"
    ]
    return "\n".join(lines), 200, {"Content-Type": "text/plain"}



# ==========================================
# 予約管理
# ==========================================

@app.route("/admin/reservations", methods=["GET"])
@staff_required
def admin_reservations():
    """予約管理（カレンダー表示）"""
    try:
        # クエリパラメータ取得
        ym = request.args.get("ym")  # YYYY-MM
        day = request.args.get("day")  # YYYY-MM-DD
        place_type_filter = request.args.get("place_type", "all")  # all/in_house/visit/field
        staff_filter = request.args.get("staff", "all")  # all or staff_name
        
        # 現在日時（JST）
        now_jst = datetime.now(JST)
        
        # ymが未指定なら当月
        if ym:
            try:
                year, month = map(int, ym.split("-"))
                current_date = datetime(year, month, 1, tzinfo=JST)
            except:
                current_date = now_jst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            current_date = now_jst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # 月初と月末（翌月1日の直前）
        start_date = current_date
        if current_date.month == 12:
            end_date = datetime(current_date.year + 1, 1, 1, tzinfo=JST)
        else:
            end_date = datetime(current_date.year, current_date.month + 1, 1, tzinfo=JST)
        
        # dayが未指定なら今日
        if day:
            try:
                selected_day = datetime.strptime(day, "%Y-%m-%d").date()
            except:
                selected_day = now_jst.date()
        else:
            selected_day = now_jst.date()
        
        # 予約取得（月初〜月末）
        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()
        
        query = supabase_admin.table("reservations").select("*").gte("reserved_at", start_iso).lt("reserved_at", end_iso)
        
        # フィルタ適用
        if place_type_filter != "all":
            query = query.eq("place_type", place_type_filter)
        if staff_filter != "all":
            query = query.eq("staff_name", staff_filter)
        
        res_reservations = query.order("reserved_at", desc=False).execute()
        reservations = res_reservations.data or []
        
        # patient_idの集合を取得
        patient_ids = list({r.get("patient_id") for r in reservations if r.get("patient_id")})
        
        # 患者情報を一括取得
        patient_map = {}
        if patient_ids:
            res_patients = supabase_admin.table("patients").select("id, last_name, first_name, name").in_("id", patient_ids).execute()
            if res_patients.data:
                patient_map = {p["id"]: p for p in res_patients.data}
        
        # 予約に患者情報を結合
        for reservation in reservations:
            patient_id = reservation.get("patient_id")
            patient = patient_map.get(patient_id)
            if patient:
                # 名前を結合
                name = f"{patient.get('last_name', '')} {patient.get('first_name', '')}".strip()
                if not name:
                    name = patient.get("name", "不明")
                reservation["patient_name"] = name
                reservation["patient"] = patient
            else:
                reservation["patient_name"] = "不明"
                reservation["patient"] = None
        
        # 日付ごとの件数マップ（YYYY-MM-DD -> 件数）
        counts_by_day = {}
        for r in reservations:
            # reserved_atをJSTの日付に変換
            try:
                dt = datetime.fromisoformat(r.get("reserved_at", "").replace("Z", "+00:00"))
                dt_jst = dt.astimezone(JST)
                day_key = dt_jst.strftime("%Y-%m-%d")
                counts_by_day[day_key] = counts_by_day.get(day_key, 0) + 1
            except:
                pass
        
        # 選択日の予約一覧（その日の00:00〜24:00）
        selected_day_start = datetime.combine(selected_day, datetime.min.time()).replace(tzinfo=JST)
        selected_day_end = selected_day_start + timedelta(days=1)
        selected_day_start_iso = selected_day_start.isoformat()
        selected_day_end_iso = selected_day_end.isoformat()
        
        reservations_of_day = [
            r for r in reservations
            if selected_day_start_iso <= r.get("reserved_at", "") < selected_day_end_iso
        ]
        # 時刻順にソート
        reservations_of_day.sort(key=lambda x: x.get("reserved_at", ""))
        
        # 予約の時刻をJSTで表示用に変換
        for r in reservations_of_day:
            try:
                dt_str = r.get("reserved_at", "")
                if dt_str:
                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    dt_jst = dt.astimezone(JST)
                    r["reserved_at_display"] = dt_jst.strftime("%H:%M")
                else:
                    r["reserved_at_display"] = "時刻不明"
            except:
                r["reserved_at_display"] = "時刻不明"
        
        # スタッフリスト取得（フィルタ用）
        staff_list = []
        try:
            try:
                res_staff = supabase_admin.table("staff").select("id, name").execute()
                if res_staff.data:
                    staff_list = [{"name": s.get("name", "不明"), "id": s.get("id")} for s in res_staff.data]
            except:
                pass
            # 現在のスタッフも追加
            staff = session.get("staff", {})
            current_staff_name = staff.get("name", "スタッフ")
            if not any(s.get("name") == current_staff_name for s in staff_list):
                staff_list.append({"name": current_staff_name, "id": staff.get("id")})
        except Exception as e:
            print("❌ スタッフリスト取得エラー:", e)
            staff = session.get("staff", {})
            staff_list = [{"name": staff.get("name", "スタッフ"), "id": staff.get("id")}]
        
        # 前月・次月の計算
        if current_date.month == 1:
            prev_month = datetime(current_date.year - 1, 12, 1, tzinfo=JST)
        else:
            prev_month = datetime(current_date.year, current_date.month - 1, 1, tzinfo=JST)
        
        if current_date.month == 12:
            next_month = datetime(current_date.year + 1, 1, 1, tzinfo=JST)
        else:
            next_month = datetime(current_date.year, current_date.month + 1, 1, tzinfo=JST)
        
        # カレンダー表示用の日付計算
        calendar_days = []
        # 月初の曜日（0=月曜日、6=日曜日）
        first_weekday = current_date.weekday()
        # 月の日数
        if current_date.month == 12:
            next_month_first = datetime(current_date.year + 1, 1, 1, tzinfo=JST)
        else:
            next_month_first = datetime(current_date.year, current_date.month + 1, 1, tzinfo=JST)
        days_in_month = (next_month_first - current_date).days
        
        return render_template(
            "admin_reservations.html",
            current_date=current_date,
            selected_day=selected_day,
            reservations=reservations,
            counts_by_day=counts_by_day,
            reservations_of_day=reservations_of_day,
            place_type_filter=place_type_filter,
            staff_filter=staff_filter,
            staff_list=staff_list,
            prev_month=prev_month.strftime("%Y-%m"),
            next_month=next_month.strftime("%Y-%m"),
            current_ym=current_date.strftime("%Y-%m"),
            first_weekday=first_weekday,
            days_in_month=days_in_month,
            now_jst=now_jst
        )
    except Exception as e:
        print("❌ 予約一覧取得エラー:", e)
        flash("予約一覧の取得に失敗しました", "error")
        return redirect("/admin/dashboard")


@app.route("/admin/reservations/new", methods=["GET", "POST"])
@staff_required
def admin_reservations_new():
    """新規予約作成"""
    if request.method == "GET":
        try:
            # 患者一覧取得（autocomplete用に姓名分離フィールド・生年月日・紹介者も取得）
            res_patients = supabase_admin.table("patients").select("id, last_name, first_name, last_kana, first_kana, name, kana, birthday, introducer").order("created_at", desc=True).execute()
            patients = res_patients.data or []
            
            # スタッフリスト取得
            staff = session.get("staff", {})
            staff_name = staff.get("name", "スタッフ")
            staff_list = []
            try:
                try:
                    res_staff = supabase_admin.table("staff").select("id, name").execute()
                    if res_staff.data:
                        staff_list = [{"name": s.get("name", "不明"), "id": s.get("id")} for s in res_staff.data]
                except:
                    pass
                current_staff_in_list = any(s.get("id") == staff.get("id") for s in staff_list)
                if not current_staff_in_list:
                    staff_list.append({"name": staff_name, "id": staff.get("id")})
            except Exception as e:
                print("❌ スタッフリスト取得エラー:", e)
                staff_list = [{"name": staff_name, "id": staff.get("id")}]
            
            return render_template("admin_reservations_new.html", patients=patients, staff_name=staff_name, staff_list=staff_list)
        except Exception as e:
            print("❌ 予約作成画面取得エラー:", e)
            flash("予約作成画面の取得に失敗しました", "error")
            return redirect("/admin/reservations")
    
    # POST処理
    try:
        # 患者選択方式を確認
        patient_mode = request.form.get("patient_mode", "existing")
        
        # 新規患者作成の場合
        if patient_mode == "new":
            # 新規患者データを作成
            last_name = request.form.get("last_name", "").strip()
            first_name = request.form.get("first_name", "").strip()
            last_kana = request.form.get("last_kana", "").strip()
            first_kana = request.form.get("first_kana", "").strip()
            phone = request.form.get("phone", "").strip() or None
            patient_memo = request.form.get("patient_memo", "").strip() or None
            
            # 必須項目チェック
            if not last_name or not first_name or not last_kana or not first_kana:
                flash("姓・名・セイ・メイは必須です", "error")
                return redirect("/admin/reservations/new")
            
            # 名前を結合（name, kana）
            name = f"{last_name} {first_name}".strip()
            kana = f"{last_kana} {first_kana}".strip()
            
            # 新規患者を登録
            patient_data = {
                "last_name": last_name,
                "first_name": first_name,
                "last_kana": last_kana,
                "first_kana": first_kana,
                "name": name,
                "kana": kana,
                "phone": phone,
                "note": patient_memo,
                "visibility": "all",
                "created_at": now_iso()
            }
            
            res_patient = supabase_admin.table("patients").insert(patient_data).execute()
            if not res_patient.data:
                flash("患者の登録に失敗しました", "error")
                return redirect("/admin/reservations/new")
            
            patient_id = res_patient.data[0]["id"]
            redirect_to_karte = True  # 新規患者の場合はカルテ詳細へ
        else:
            # 既存患者選択の場合
            patient_id = request.form.get("patient_id", "").strip()
            if not patient_id:
                flash("患者を選択してください。検索して患者をクリックしてください。", "error")
                return redirect("/admin/reservations/new")
            
            # 患者が存在するか確認
            res_check = supabase_admin.table("patients").select("id").eq("id", patient_id).execute()
            if not res_check.data:
                flash("選択された患者が見つかりません", "error")
                return redirect("/admin/reservations/new")
            
            redirect_to_karte = False  # 既存患者の場合は予約一覧へ
        
        # 日時取得（datetime-local形式）
        reserved_at_str = request.form.get("reserved_at", "").strip()
        if not reserved_at_str:
            flash("予約日時を入力してください", "error")
            return redirect("/admin/reservations/new")
        
        # datetime-local形式をISO形式に変換
        try:
            dt_naive = datetime.strptime(reserved_at_str, "%Y-%m-%dT%H:%M")
            dt_jst = dt_naive.replace(tzinfo=JST)
            reserved_at_iso = dt_jst.isoformat()
        except Exception as e:
            flash("予約日時の形式が正しくありません", "error")
            return redirect("/admin/reservations/new")
        
        # 施術時間（手入力があればそれを優先）
        duration_custom = request.form.get("duration_minutes_custom", "").strip()
        if duration_custom:
            try:
                duration_minutes = int(duration_custom)
            except:
                duration_minutes = int(request.form.get("duration_minutes", "60") or "60")
        else:
            duration_minutes = int(request.form.get("duration_minutes", "60") or "60")
        place_type = request.form.get("place_type", "").strip()
        if place_type not in ["in_house", "visit", "field"]:
            flash("現場区分を選択してください", "error")
            return redirect("/admin/reservations/new")
        
        place_name = request.form.get("place_name", "").strip() or None
        staff_name = request.form.get("staff_name", "").strip() or None
        memo = request.form.get("memo", "").strip() or None
        
        # 予約作成
        reservation_data = {
            "patient_id": patient_id,
            "reserved_at": reserved_at_iso,
            "duration_minutes": duration_minutes,
            "place_type": place_type,
            "place_name": place_name,
            "staff_name": staff_name,
            "status": "reserved",
            "memo": memo,
            "created_at": now_iso()
        }
        
        supabase_admin.table("reservations").insert(reservation_data).execute()
        
        flash("予約を作成しました", "success")
        
        # リダイレクト先を決定
        if redirect_to_karte:
            # 新規患者の場合はカルテ詳細へ
            return redirect(f"/admin/karte/{patient_id}")
        else:
            # 既存患者の場合は予約一覧へ
            day_str = dt_jst.strftime("%Y-%m-%d")
            ym_str = dt_jst.strftime("%Y-%m")
            return redirect(f"/admin/reservations?ym={ym_str}&day={day_str}")
    except Exception as e:
        print("❌ 予約作成エラー:", e)
        flash(f"予約の作成に失敗しました: {e}", "error")
        return redirect("/admin/reservations/new")


@app.route("/admin/reservations/<reservation_id>/status", methods=["POST"])
@staff_required
def admin_reservations_status(reservation_id):
    """予約ステータス更新"""
    try:
        new_status = request.form.get("status", "").strip()
        if new_status not in ["reserved", "visited", "completed", "canceled"]:
            flash("無効なステータスです", "error")
            return redirect("/admin/reservations")
        
        supabase_admin.table("reservations").update({"status": new_status}).eq("id", reservation_id).execute()
        
        flash("予約ステータスを更新しました", "success")
        return redirect(request.referrer or "/admin/reservations")
    except Exception as e:
        print("❌ 予約ステータス更新エラー:", e)
        flash("予約ステータスの更新に失敗しました", "error")
        return redirect("/admin/reservations")


@app.route("/admin/reservations/<reservation_id>/delete", methods=["POST"])
@staff_required
def admin_reservations_delete(reservation_id):
    """予約削除"""
    try:
        supabase_admin.table("reservations").delete().eq("id", reservation_id).execute()
        flash("予約を削除しました", "success")
        return redirect(request.referrer or "/admin/reservations")
    except Exception as e:
        print("❌ 予約削除エラー:", e)
        flash("予約の削除に失敗しました", "error")
        return redirect("/admin/reservations")


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

# ===================================================
# ✅ 起動
# ===================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
