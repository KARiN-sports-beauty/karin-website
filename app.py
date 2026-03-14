from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, jsonify, flash
from datetime import datetime, timedelta, timezone
import calendar
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
# ▼ ユーティリティ関数
# =====================================
def calc_age(birthday_str):
    if not birthday_str:
        return None
    birthday = datetime.strptime(birthday_str, "%Y-%m-%d").date()
    today = datetime.now(JST).date()
    age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
    return age


def parse_time_parts(value, default_hour=7, default_minute=0):
    if value is None:
        return default_hour, default_minute
    if hasattr(value, "strftime"):
        value = value.strftime("%H:%M")
    value_str = str(value).strip()
    if not value_str:
        return default_hour, default_minute
    parts = value_str.split(":")
    if len(parts) < 2:
        return default_hour, default_minute
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        return hour, minute
    except Exception:
        return default_hour, default_minute


def normalize_blog_image_url(image_url):
    if not image_url:
        return ""
    image_url = image_url.strip()
    if not image_url:
        return ""
    if image_url.startswith("http"):
        return image_url
    if image_url.startswith("/static/"):
        filename = image_url.replace("/static/", "")
        return url_for("static", filename=filename)
    if image_url.startswith("static/"):
        filename = image_url.replace("static/", "")
        return url_for("static", filename=filename)
    if re.search(r"\.(jpg|jpeg|png|webp)$", image_url, re.IGNORECASE):
        return url_for("static", filename=f"images/blogs/{image_url}")
    return image_url


def upload_blog_image(file):
    if not file or file.filename == "":
        return ""
    ext = os.path.splitext(file.filename)[1].lower()
    allowed_exts = {".jpg", ".jpeg", ".png", ".webp"}
    if ext not in allowed_exts:
        raise ValueError("画像は jpg / jpeg / png / webp のみ対応です")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = safe_name

    mime_type = file.mimetype
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(file.filename)
    if not mime_type:
        mime_type = "application/octet-stream"

    file_data = file.read()
    supabase_admin.storage.from_("blog-images").upload(
        path=storage_path,
        file=file_data,
        file_options={"content-type": mime_type}
    )

    return supabase_admin.storage.from_("blog-images").get_public_url(storage_path)


@app.route("/admin/blogs/body-image", methods=["POST"])
@staff_required
def admin_blog_body_image_upload():
    """ブログ本文用の画像アップロード"""
    try:
        if "image" not in request.files:
            return jsonify({"error": "画像が選択されていません"}), 400
        file = request.files["image"]
        if file.filename == "":
            return jsonify({"error": "ファイルが選択されていません"}), 400

        public_url = upload_blog_image(file)
        return jsonify({"success": True, "url": public_url})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print("❌ ブログ本文画像アップロードエラー:", e)
        return jsonify({"error": str(e)}), 500


def calculate_salary(staff_name, year, month, area="tokyo"):
    """
    スタッフの給与を自動計算する関数
    
    計算ロジック（自動計算用の参考値）：
    1. 基本給/資格給は手入力のため自動計算しない
    2. 歩合給 = 指名料（予約から自動集計）
    3. 交通費 = スタッフの日報申請を集計
    
    Args:
        staff_name: スタッフ名
        year: 年
        month: 月
        area: エリア（tokyo/fukuoka）- 最低時給の決定に使用
    
    Returns:
        dict: {
            "base_salary": 基本給,
            "commission": 資格給（手入力用のため0）,
            "nomination_fee": 歩合給（指名料）,
            "transportation": 交通費,
            "total_salary": 総支給,
            "working_hours": 実働時間（時間）,
            "revenue": 売上
        }
    """
    # 基本実働時間（40h×4週 = 160時間）
    base_working_hours = 160
    
    # 月の開始日と終了日
    month_start = f"{year}-{month:02d}-01"
    if month in [1, 3, 5, 7, 8, 10, 12]:
        month_end = f"{year}-{month:02d}-31"
    elif month in [4, 6, 9, 11]:
        month_end = f"{year}-{month:02d}-30"
    else:
        if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
            month_end = f"{year}-{month:02d}-29"
        else:
            month_end = f"{year}-{month:02d}-28"
    
    # 実働時間を計算（日報から）
    working_hours = base_working_hours  # デフォルト値
    try:
        res_reports = supabase_admin.table("staff_daily_reports").select("id").eq("staff_name", staff_name).gte("report_date", month_start).lte("report_date", month_end).execute()
        report_ids = [r["id"] for r in (res_reports.data or [])]
        
        if report_ids:
            total_minutes = 0
            res_items = supabase_admin.table("staff_daily_report_items").select("start_time, end_time, break_minutes").in_("daily_report_id", report_ids).execute()
            for item in (res_items.data or []):
                start_time = item.get("start_time")
                end_time = item.get("end_time")
                break_minutes = item.get("break_minutes", 0) or 0
                
                if start_time and end_time:
                    try:
                        # 時刻文字列をパース（HH:MM形式）
                        if isinstance(start_time, str):
                            start_parts = start_time.split(":")
                            start_hour = int(start_parts[0])
                            start_minute = int(start_parts[1]) if len(start_parts) > 1 else 0
                        else:
                            start_hour = int(start_time)
                            start_minute = 0
                        
                        if isinstance(end_time, str):
                            end_parts = end_time.split(":")
                            end_hour = int(end_parts[0])
                            end_minute = int(end_parts[1]) if len(end_parts) > 1 else 0
                        else:
                            end_hour = int(end_time)
                            end_minute = 0
                        
                        # 時間差を計算（分単位）
                        start_total_minutes = start_hour * 60 + start_minute
                        end_total_minutes = end_hour * 60 + end_minute
                        
                        # 日を跨ぐ場合の処理
                        if end_total_minutes < start_total_minutes:
                            end_total_minutes += 24 * 60
                        
                        item_minutes = end_total_minutes - start_total_minutes - break_minutes
                        if item_minutes > 0:
                            total_minutes += item_minutes
                    except Exception as e:
                        print(f"⚠️ WARNING - 実働時間計算エラー: {e}")
                        continue
            
            # 分を時間に変換
            working_hours = total_minutes / 60.0 if total_minutes > 0 else base_working_hours
    except Exception as e:
        print(f"⚠️ WARNING - 実働時間取得エラー: {e}")
    
    # 基本給/資格給は手入力のため自動計算しない
    base_salary = 0
    
    # 売上を集計（予約テーブルから直接集計：税抜き料金、出張費、指名料を個別に集計）
    base_revenue = 0  # 税抜き料金の合計
    transportation_total = 0  # 出張費の合計
    try:
        # 予約完了分の予約データを取得
        res_reservations = supabase_admin.table("reservations").select("base_price, transportation_fee, place_type").eq("staff_name", staff_name).eq("status", "completed").gte("reserved_at", month_start).lte("reserved_at", month_end).execute()
        
        for reservation in (res_reservations.data or []):
            # 税抜き料金を集計（院内・往診・帯同すべて）
            base_price = reservation.get("base_price", 0) or 0
            base_revenue += base_price
            
            # 出張費を集計（往診の場合のみ）
            transportation_fee = reservation.get("transportation_fee", 0) or 0
            transportation_total += transportation_fee
    except Exception as e:
        print(f"⚠️ WARNING - 売上集計エラー: {e}")
    
    # 資格給（手入力のため自動計算しない）
    commission = 0
    
    # 総売上 = 税抜き料金（給与計算用の参考値）
    revenue = base_revenue
    
    # 指名料を集計（予約から）
    nomination_fee = 0
    try:
        # 予約完了分の指名料を集計
        res_reservations = supabase_admin.table("reservations").select("nomination_fee, place_type, selected_menus, staff_name, nominated_staff_ids").eq("staff_name", staff_name).eq("status", "completed").gte("reserved_at", month_start).lte("reserved_at", month_end).execute()
        
        for reservation in (res_reservations.data or []):
            # 対応スタッフの指名料を集計
            res_nomination_fee = reservation.get("nomination_fee", 0) or 0
            place_type = reservation.get("place_type", "")
            selected_menus_str = reservation.get("selected_menus", [])
            
            if isinstance(selected_menus_str, str):
                try:
                    selected_menus_str = json.loads(selected_menus_str)
                except:
                    selected_menus_str = []
            
            # 本指名・枠指名の金額を計算
            if "本指名(¥1,000)" in selected_menus_str or "本指名(¥10,000)" in selected_menus_str:
                if place_type == "field":
                    nomination_fee += 5000
                else:
                    nomination_fee += 500
            elif "枠指名(¥500)" in selected_menus_str or "枠指名(¥5,000)" in selected_menus_str:
                if place_type == "field":
                    nomination_fee += 5000
                else:
                    nomination_fee += 500
        
        # 枠指名で対応していないスタッフの指名料も集計
        res_frame_reservations = supabase_admin.table("reservations").select("nominated_staff_ids, place_type, selected_menus").eq("status", "completed").gte("reserved_at", month_start).lte("reserved_at", month_end).execute()
        
        for reservation in (res_frame_reservations.data or []):
            nominated_staff_ids_str = reservation.get("nominated_staff_ids", [])
            if isinstance(nominated_staff_ids_str, str):
                try:
                    nominated_staff_ids_str = json.loads(nominated_staff_ids_str)
                except:
                    nominated_staff_ids_str = []
            
            # このスタッフが枠指名リストに含まれているか確認
            if staff_name in nominated_staff_ids_str:
                # 対応スタッフを取得
                res_main = supabase_admin.table("reservations").select("staff_name").eq("id", reservation.get("id")).execute()
                main_staff = res_main.data[0].get("staff_name") if res_main.data else None
                
                # 対応スタッフでない場合のみ追加
                if main_staff != staff_name:
                    place_type = reservation.get("place_type", "")
                    selected_menus_str = reservation.get("selected_menus", [])
                    if isinstance(selected_menus_str, str):
                        try:
                            selected_menus_str = json.loads(selected_menus_str)
                        except:
                            selected_menus_str = []
                    
                    if "枠指名(¥500)" in selected_menus_str or "枠指名(¥5,000)" in selected_menus_str:
                        if place_type == "field":
                            nomination_fee += 1000
                        else:
                            nomination_fee += 100
    except Exception as e:
        print(f"⚠️ WARNING - 指名料集計エラー: {e}")
    
    # 交通費を集計（スタッフ日報の交通費申請から）
    transportation = 0
    try:
        # スタッフIDを取得
        staff_id = None
        try:
            users = supabase_admin.auth.admin.list_users()
            for u in users:
                meta = u.user_metadata or {}
                if not meta.get("approved", False):
                    continue
                last_name = meta.get("last_name", "")
                first_name = meta.get("first_name", "")
                display_name = f"{last_name} {first_name}".strip() if last_name and first_name else meta.get("name", "")
                if display_name == staff_name:
                    staff_id = u.id
                    break
        except:
            pass
        
        if staff_id:
            # スタッフ日報の交通費申請テーブルから集計
            res_transportation = supabase_admin.table("staff_daily_report_transportations").select("amount").eq("staff_id", staff_id).gte("date", month_start).lte("date", month_end).execute()
            for trans in (res_transportation.data or []):
                transportation += trans.get("amount", 0) or 0
    except Exception as e:
        print(f"⚠️ WARNING - 交通費集計エラー: {e}")
    
    # 総支給 = 基本給 + 資格給 + 歩合給(指名料) + 出張費 + 交通費
    # 出張費は給与に直接反映（予約テーブルから集計）
    total_salary = base_salary + commission + nomination_fee + transportation_total + transportation
    
    return {
        "base_salary": base_salary,
        "commission": commission,
        "nomination_fee": nomination_fee,
        "transportation_fee": transportation_total,  # 出張費
        "transportation": transportation,  # 交通費
        "total_salary": total_salary,
        "working_hours": working_hours,
        "revenue": revenue  # 税抜き料金の合計
    }


def _half_year_range(year: int, month: int):
    if month <= 6:
        return 1, 6
    return 7, 12


def _sum_staff_revenue(staff_name: str, year: int, start_month: int, end_month: int) -> int:
    revenue_total = 0
    try:
        start_date = f"{year}-{start_month:02d}-01"
        end_day = calendar.monthrange(year, end_month)[1]
        end_date = f"{year}-{end_month:02d}-{end_day:02d}"
        res_reservations = (
            supabase_admin
            .table("reservations")
            .select("base_price")
            .eq("staff_name", staff_name)
            .eq("status", "completed")
            .gte("reserved_at", start_date)
            .lte("reserved_at", end_date)
            .execute()
        )
        for reservation in (res_reservations.data or []):
            revenue_total += reservation.get("base_price", 0) or 0
    except Exception as e:
        print(f"⚠️ WARNING - 半期売上集計エラー: {e}")
    return int(revenue_total)


def _sum_staff_pay_total(
    staff_id: str,
    year: int,
    start_month: int,
    end_month: int,
    exclude_salary_id: str | None = None,
    exclude_month: int | None = None
) -> int:
    total = 0
    try:
        res_salaries = (
            supabase_admin
            .table("staff_salaries")
            .select("id, month, base_salary, commission, nomination_fee")
            .eq("staff_id", staff_id)
            .eq("year", year)
            .gte("month", start_month)
            .lte("month", end_month)
            .execute()
        )
        for sal in (res_salaries.data or []):
            if exclude_salary_id and str(sal.get("id")) == str(exclude_salary_id):
                continue
            if exclude_month and sal.get("month") == exclude_month:
                continue
            total += (sal.get("base_salary", 0) or 0)
            total += (sal.get("commission", 0) or 0)
            total += (sal.get("nomination_fee", 0) or 0)
    except Exception as e:
        print(f"⚠️ WARNING - 半期給与合計エラー: {e}")
    return int(total)


def calculate_special_bonus(
    year: int,
    month: int,
    staff_id: str,
    staff_name: str,
    base_salary: float,
    commission: float,
    nomination_fee: float,
    exclude_salary_id: str | None = None
) -> dict:
    if month not in [6, 12]:
        return {"bonus": 0, "revenue_total": 0, "existing_total": 0}

    start_month, end_month = _half_year_range(year, month)
    revenue_total = _sum_staff_revenue(staff_name, year, start_month, end_month)
    existing_total = _sum_staff_pay_total(
        staff_id,
        year,
        start_month,
        end_month,
        exclude_salary_id=exclude_salary_id,
        exclude_month=month
    )
    current_total = (base_salary or 0) + (commission or 0) + (nomination_fee or 0)
    bonus = max(0, int(revenue_total * 0.35) - int(existing_total + current_total))
    return {"bonus": bonus, "revenue_total": revenue_total, "existing_total": existing_total}


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

@app.route("/yoyogiuehara/shinkyu")
def yoyogiuehara_shinkyu():
    return render_template("yoyogiuehara_shinkyu.html")

@app.route("/yakuin/shinkyu")
def yakuin_shinkyu():
    return render_template("yakuin_shinkyu.html")

@app.route("/lp-yoyogiuehara")
def lp_yoyogiuehara():
    return render_template("lp-yoyogiuehara.html")

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
        chiropractic = request.form.get("chiropractic", "").strip()
        heart = request.form.get("heart", "").strip()
        pregnant = request.form.get("pregnant", "").strip()
        chronic = request.form.get("chronic", "").strip()
        surgery = request.form.get("surgery", "").strip()
        under_medical = request.form.get("under_medical", "").strip()
        # 同意書確認チェックボックス
        agreement_confirmed = request.form.get("agreement_confirmed") == "on"
        if not agreement_confirmed:
            flash("同意書を確認の上、チェックボックスにチェックを入れてください", "error")
            return redirect(url_for("form"))
        
        # 希望日をフォーマット
        preferred_date1 = normalize_datetime(request.form.get("preferred_date1"))
        preferred_date2 = normalize_datetime(request.form.get("preferred_date2"))
        preferred_date3 = normalize_datetime(request.form.get("preferred_date3"))

        # agreed_atは送信日時で自動設定（YYYY-MM-DD形式）
        agreed_at = datetime.now(JST).strftime("%Y-%m-%d")
        
        # 署名は姓名を結合（後方互換性のため）
        signature = name
        
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
            "chiropractic": chiropractic,
            "heart": heart,
            "pregnant": pregnant,
            "chronic": chronic,
            "surgery": surgery,
            "under_medical": under_medical,
            "preferred_date1": preferred_date1,
            "preferred_date2": preferred_date2,
            "preferred_date3": preferred_date3,
            "signature": signature,  # 後方互換性のため姓名を保存
            "agreed_at": agreed_at,  # 送信日時で自動設定
            "agreement_confirmed": True,  # チェックボックスで確認済み
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
        last_name = request.form.get("last_name", "").strip()
        first_name = request.form.get("first_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not last_name or not first_name or not phone or not email or not password:
            return render_template("staff_register.html", error="全ての項目を入力してください。")

        # 姓と名を結合してnameを作成（半角スペース区切り）
        name = f"{last_name} {first_name}".strip()

        # Supabase Auth にユーザー作成（未承認、メール確認スキップ）
        try:
            user = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "email_confirm": True,  # メール確認をスキップ
                    "data": {
                        "last_name": last_name,
                        "first_name": first_name,
                        "name": name,  # 後方互換性のため
                        "phone": phone,
                        "approved": False
                    }
                }
            })

        except Exception as e:
            print("STAFF REGISTER ERROR:", e)
            return render_template("staff_register.html", error="登録に失敗しました。")

        # 成功時はログイン画面にリダイレクト
        return redirect(url_for("staff_login_page", success="登録完了しました。管理者の承認後にログインできます。"))

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
        
        # 姓・名から表示名を生成（半角スペース区切り）
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            display_name = f"{last_name} {first_name}"
        else:
            # 後方互換性：既存データはnameフィールドを使用
            display_name = meta.get("name", "未設定")

        staff_list.append({
            "id": u.id,
            "email": u.email,
            "name": display_name,
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

        # 承認処理（既存のメタデータを保持しながらapprovedをTrueに設定）
        updated_metadata = meta.copy()
        updated_metadata["approved"] = True
        
        print(f"🔍 承認処理 - User ID: {user_id}, 既存メタデータ: {meta}, 更新後メタデータ: {updated_metadata}")
        
        # メール確認も完了させる（email_confirmed_atを現在時刻に設定）
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        
        supabase_admin.auth.admin.update_user_by_id(
            user_id,
            {
                "user_metadata": updated_metadata,
                "email_confirmed_at": now_utc.isoformat()  # メール確認を完了
            }
        )
        
        # 更新確認（デバッグ用）
        try:
            updated_users = supabase_admin.auth.admin.list_users()
            updated_user = next((u for u in updated_users if u.id == user_id), None)
            if updated_user:
                print(f"✅ 承認後確認 - User ID: {user_id}, メタデータ: {updated_user.user_metadata}, Approved: {updated_user.user_metadata.get('approved', False) if updated_user.user_metadata else False}")
        except Exception as e:
            print(f"⚠️ 承認後確認エラー: {e}")

        # 表示名を生成（姓・名から、半角スペース区切り）
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            display_name = f"{last_name} {first_name}"
        else:
            # 後方互換性：既存データはnameフィールドを使用
            display_name = meta.get("name", "")

        flash("スタッフを承認しました", "success")

    except Exception as e:
        print("❌ APPROVE ERROR:", e)
        flash("承認処理に失敗しました。", "error")

    return redirect("/admin/staff")




# 承認解除（停止）
@app.route("/admin/staff/disable/<user_id>", methods=["POST"])
@admin_required
def admin_staff_disable(user_id):
    try:
        # ユーザー情報の取得
        users = supabase_admin.auth.admin.list_users()
        user = next((u for u in users if u.id == user_id), None)
        
        if not user:
            flash("ユーザーが見つかりません", "error")
            return redirect("/admin/staff")
        
        meta = user.user_metadata or {}
        
        # 既存のメタデータを保持しながらapprovedをFalseに設定
        updated_metadata = meta.copy()
        updated_metadata["approved"] = False
        
        supabase_admin.auth.admin.update_user_by_id(
            user_id,
            {"user_metadata": updated_metadata}
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
    """スタッフページ（メインページ：カード選択画面）"""
    staff = session.get("staff")
    return render_template("staff_profile_menu.html", staff=staff)


@app.route("/staff/profile/edit", methods=["GET", "POST"])
@staff_required
def staff_profile_edit():
    """プロフィール編集画面"""
    # 手技リスト（treatmentページから）
    treatment_options = [
        "鍼灸治療",
        "美容鍼",
        "整体",
        "ストレッチ",
        "リコンディショニング",
        "トレーニング",
        "テクニカ・ガビラン",
        "アクティベーター",
        "カッピング（吸玉）",
        "コンプレフロス",
        "オイルトリートメント",
        "トレーナー帯同"
    ]
    
    if request.method == "GET":
        staff = session.get("staff")
        
        # ユーザーメタデータから情報を取得
        try:
            users = supabase_admin.auth.admin.list_users()
            user = next((u for u in users if u.id == staff["id"]), None)
            if user:
                meta = user.user_metadata or {}
                staff["last_name"] = meta.get("last_name", "")
                staff["first_name"] = meta.get("first_name", "")
                staff["last_kana"] = meta.get("last_kana", "")
                staff["first_kana"] = meta.get("first_kana", "")
                staff["birthday"] = meta.get("birthday", "")
                # 電話番号は登録時に保存されたものを優先、なければセッションから取得
                staff["phone"] = meta.get("phone", "") or staff.get("phone", "")
                staff["postal_code"] = meta.get("postal_code", "")
                staff["address"] = meta.get("address", "")
                staff["hobbies_skills"] = meta.get("hobbies_skills", "")
                staff["available_techniques"] = meta.get("available_techniques", [])  # リスト
                staff["one_word"] = meta.get("one_word", "")
                staff["blog_comment"] = meta.get("blog_comment", "")
                profile_image_url = meta.get("profile_image_url", "")
                # プロフィール画像URLが相対パスの場合はurl_forで解決
                if profile_image_url:
                    if not profile_image_url.startswith("http"):
                        if profile_image_url.startswith("/static/"):
                            filename = profile_image_url.replace("/static/", "")
                            profile_image_url = url_for("static", filename=filename)
                        elif profile_image_url.startswith("static/"):
                            filename = profile_image_url.replace("static/", "")
                            profile_image_url = url_for("static", filename=filename)
                    # staffオブジェクトとセッションの両方に設定
                    staff["profile_image_url"] = profile_image_url
                    session["staff"]["profile_image_url"] = profile_image_url
                else:
                    # profile_image_urlが空の場合は、staffオブジェクトからも削除
                    staff["profile_image_url"] = None
                    if "profile_image_url" in session.get("staff", {}):
                        session["staff"]["profile_image_url"] = None
        except:
            pass

        return render_template(
            "staff_profile_edit.html",
            staff=staff,
            treatment_options=treatment_options,
            message=request.args.get("message")
        )
    
    # POST処理（プロフィール更新）
    try:
        staff = session.get("staff")
        user_id = staff["id"]

        last_name = request.form.get("last_name", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_kana = request.form.get("last_kana", "").strip()
        first_kana = request.form.get("first_kana", "").strip()
        birthday = request.form.get("birthday", "").strip()
        new_phone = request.form.get("phone", "").strip()
        postal_code = request.form.get("postal_code", "").strip()
        address = request.form.get("address", "").strip()
        hobbies_skills = request.form.get("hobbies_skills", "").strip()
        available_techniques = request.form.getlist("available_techniques")  # 複数選択
        one_word = request.form.get("one_word", "").strip()
        blog_comment = request.form.get("blog_comment", "").strip()

        if not last_name or not first_name:
            return redirect(url_for("staff_profile_edit", message="姓と名を入力してください"))

        # 姓と名を結合してnameを作成（半角スペース区切り）
        new_name = f"{last_name} {first_name}".strip()

        # 写真アップロード処理
        profile_image_url = None
        if "profile_image" in request.files:
            file = request.files["profile_image"]
            if file and file.filename:
                # ファイル名を安全に生成
                import uuid
                import os
                from werkzeug.utils import secure_filename
                
                filename = secure_filename(file.filename)
                ext = os.path.splitext(filename)[1]
                unique_filename = f"{user_id}_{uuid.uuid4().hex[:8]}{ext}"
                
                # static/staff_profiles/ ディレクトリに保存
                static_folder = app.static_folder or os.path.join(os.path.dirname(__file__), "static")
                upload_dir = os.path.join(static_folder, "staff_profiles")
                os.makedirs(upload_dir, exist_ok=True)
                
                file_path = os.path.join(upload_dir, unique_filename)
                file.save(file_path)
                
                # URLを生成
                profile_image_url = f"/static/staff_profiles/{unique_filename}"

        # 既存のメタデータを取得してマージ
        try:
            users = supabase_admin.auth.admin.list_users()
            user = next((u for u in users if u.id == user_id), None)
            existing_meta = user.user_metadata if user else {}
        except:
            existing_meta = {}

        # メタデータを更新（既存のデータを保持）
        updated_metadata = existing_meta.copy()
        updated_metadata.update({
            "last_name": last_name,
            "first_name": first_name,
            "last_kana": last_kana,
            "first_kana": first_kana,
            "name": new_name,  # 後方互換性のため
            "birthday": birthday if birthday else None,
            "phone": new_phone,
            "postal_code": postal_code,
            "address": address,
            "hobbies_skills": hobbies_skills,
            "available_techniques": available_techniques,
            "one_word": one_word,
            "blog_comment": blog_comment
        })
        
        # 写真がアップロードされた場合のみ更新
        if profile_image_url:
            updated_metadata["profile_image_url"] = profile_image_url

        # Supabase Auth メタデータ更新
        result = supabase_admin.auth.admin.update_user_by_id(
            uid=user_id,
            attributes={
                "user_metadata": updated_metadata
            }
        )

        # セッション情報を更新（ここ重要）
        session["staff"]["name"] = new_name
        session["staff"]["last_name"] = last_name
        session["staff"]["first_name"] = first_name
        session["staff"]["phone"] = new_phone
        
        # 写真がアップロードされた場合、セッションにも反映
        if profile_image_url:
            session["staff"]["profile_image_url"] = profile_image_url

        return redirect(url_for(
            "staff_profile_edit",
            message="プロフィールを更新しました"
        ))

    except Exception as e:
        import traceback
        print("PROFILE UPDATE ERROR:", e)
        print(traceback.format_exc())
        return f"エラーが発生しました: {e}", 500





@app.route("/staff/login", methods=["GET"])
def staff_login_page():
    success = request.args.get("success")
    error = request.args.get("error")
    return render_template("stafflogin.html", success=success, error=error)


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
    
    # デバッグ用：メタデータの内容を確認
    print(f"🔍 ログイン試行 - Email: {email}, Metadata: {metadata}, Approved: {metadata.get('approved', False)}")

    # 🔥 承認チェック（ここが正しい位置）
    if not metadata.get("approved", False):
        print(f"⚠️ 承認されていないユーザー: {email}")
        return render_template("stafflogin.html", error="まだ管理者の承認が必要です")

    # 🔹 表示名を決定（姓・名から生成、半角スペース区切り）
    last_name = metadata.get("last_name", "")
    first_name = metadata.get("first_name", "")
    if last_name and first_name:
        full_name = f"{last_name} {first_name}"
    else:
        # 後方互換性：既存データはnameフィールドを使用
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
        "last_name": last_name,
        "first_name": first_name,
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

    sb = supabase.table("blogs").select("*").eq("draft", False)

    if category:
        sb = sb.eq("category", category)

    if query:
        sb = sb.ilike("title", f"%{query}%")

    res = sb.order("created_at", desc=True).execute()
    blogs = res.data or []
    for blog_item in blogs:
        blog_item["image"] = normalize_blog_image_url(blog_item.get("image"))

    # カテゴリ一覧（全公開記事から抽出）
    categories = []
    try:
        res_categories = supabase.table("blogs").select("category").eq("draft", False).execute()
        category_set = {
            c.get("category").strip()
            for c in (res_categories.data or [])
            if c.get("category") and c.get("category").strip()
        }
        categories = sorted(category_set)
    except Exception as e:
        print(f"⚠️ WARNING - カテゴリ取得エラー: {e}")
        categories = []

    return render_template("blog.html", blogs=blogs, categories=categories, current_category=category, query=query)



# ===========================
# ブログ詳細（slug 版）
# ===========================
@app.route("/blog/<slug>")
def show_blog(slug):
    try:
        # 対象ブログ取得（slug で検索）
        # 公開されているブログのみ取得（draft=False）
        res = supabase.table("blogs").select("*").eq("slug", slug).eq("draft", False).execute()
        data = res.data

        if not data:
            # 下書きも含めて検索（管理者用）
            try:
                res_draft = supabase_admin.table("blogs").select("*").eq("slug", slug).execute()
                if res_draft.data:
                    data = res_draft.data
            except:
                pass

        if not data:
            return render_template("404.html"), 404

        blog = data[0]
        blog["image"] = normalize_blog_image_url(blog.get("image"))
        blog_id = blog["id"]  # ← コメント・いいね取得用に必要

        # コメント取得（新しい順）
        comments = []
        try:
            comments_res = (
                supabase
                .table("comments")
                .select("*")
                .eq("blog_id", blog_id)
                .order("created_at", desc=True)
                .execute()
            )
            comments = comments_res.data or []
        except Exception as e:
            print(f"⚠️ コメント取得エラー: {e}")
            comments = []

        print("💬 COMMENTS_DEBUG:", comments)  # ← これ追加
        
        # 著者情報を取得
        author_info = None
        author_staff_id = blog.get("author_staff_id")
        
        print(f"🔍 ブログ著者情報デバッグ - author_staff_id: {author_staff_id}")
        
        if author_staff_id:
            try:
                users = supabase_admin.auth.admin.list_users()
                author_user = next((u for u in users if u.id == author_staff_id), None)
                if author_user:
                    meta = author_user.user_metadata or {}
                    last_name = meta.get("last_name", "")
                    first_name = meta.get("first_name", "")
                    last_kana = meta.get("last_kana", "")
                    first_kana = meta.get("first_kana", "")
                    
                    # 姓名を生成
                    if last_name and first_name:
                        author_name = f"{last_name} {first_name}"
                    else:
                        author_name = meta.get("name", "スタッフ")
                    
                    # セイメイを生成
                    if last_kana and first_kana:
                        author_kana = f"{last_kana} {first_kana}"
                    else:
                        author_kana = meta.get("kana", "")
                    
                    profile_image_url = meta.get("profile_image_url", "")
                    print(f"🔍 著者プロフィール画像URL（取得時）: {profile_image_url}")
                    
                    # profile_image_urlが相対パスの場合、url_forで解決
                    if profile_image_url and not profile_image_url.startswith("http"):
                        # /static/staff_profiles/... の形式の場合
                        if profile_image_url.startswith("/static/"):
                            filename = profile_image_url.replace("/static/", "")
                            profile_image_url = url_for("static", filename=filename)
                        elif profile_image_url.startswith("static/"):
                            filename = profile_image_url.replace("static/", "")
                            profile_image_url = url_for("static", filename=filename)
                        else:
                            # パスが指定されていない場合はそのまま使用（相対パスの場合）
                            pass
                    print(f"🔍 著者プロフィール画像URL（処理後）: {profile_image_url}")
                    
                    author_info = {
                        "name": author_name,
                        "kana": author_kana,
                        "blog_comment": meta.get("blog_comment", ""),
                        "profile_image_url": profile_image_url
                    }
                    print(f"🔍 著者情報取得成功 - name: {author_name}, profile_image_url: {profile_image_url}")
                else:
                    print(f"⚠️ 著者ユーザーが見つかりません - author_staff_id: {author_staff_id}")
            except Exception as e:
                print(f"⚠️ 著者情報取得エラー: {e}")
                import traceback
                print(traceback.format_exc())
                author_info = None
        else:
            print("⚠️ ブログにauthor_staff_idが設定されていません")
            # author_staff_idが設定されていない場合、最新のブログ作成者を取得（フォールバック）
            try:
                # 同じslugまたは最新のブログからauthor_staff_idを取得
                res_latest = supabase_admin.table("blogs").select("author_staff_id").eq("slug", slug).order("created_at", desc=True).limit(1).execute()
                if res_latest.data and res_latest.data[0].get("author_staff_id"):
                    author_staff_id = res_latest.data[0]["author_staff_id"]
                    print(f"🔍 フォールバック: 最新のブログからauthor_staff_idを取得 - {author_staff_id}")
                    
                    # 再度著者情報を取得
                    users = supabase_admin.auth.admin.list_users()
                    author_user = next((u for u in users if u.id == author_staff_id), None)
                    if author_user:
                        meta = author_user.user_metadata or {}
                        last_name = meta.get("last_name", "")
                        first_name = meta.get("first_name", "")
                        last_kana = meta.get("last_kana", "")
                        first_kana = meta.get("first_kana", "")
                        
                        if last_name and first_name:
                            author_name = f"{last_name} {first_name}"
                        else:
                            author_name = meta.get("name", "スタッフ")
                        
                        if last_kana and first_kana:
                            author_kana = f"{last_kana} {first_kana}"
                        else:
                            author_kana = meta.get("kana", "")
                        
                        profile_image_url = meta.get("profile_image_url", "")
                        print(f"🔍 フォールバック: 著者プロフィール画像URL（取得時）: {profile_image_url}")
                        if profile_image_url and not profile_image_url.startswith("http"):
                            if profile_image_url.startswith("/static/"):
                                filename = profile_image_url.replace("/static/", "")
                                profile_image_url = url_for("static", filename=filename)
                            elif profile_image_url.startswith("static/"):
                                filename = profile_image_url.replace("static/", "")
                                profile_image_url = url_for("static", filename=filename)
                        print(f"🔍 フォールバック: 著者プロフィール画像URL（処理後）: {profile_image_url}")
                        
                        author_info = {
                            "name": author_name,
                            "kana": author_kana,
                            "blog_comment": meta.get("blog_comment", ""),
                            "profile_image_url": profile_image_url
                        }
            except Exception as e:
                print(f"⚠️ フォールバック著者情報取得エラー: {e}")

        return render_template(
            "blog_detail.html",
            blog=blog,
            comments=comments,
            author_info=author_info
        )
    except Exception as e:
        import traceback
        print(f"❌ ブログ表示エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        return render_template("404.html"), 500


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
    image_file = request.files.get("image_file")
    if image_file and image_file.filename:
        try:
            image = upload_blog_image(image_file)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("admin_blog_new.html")
        except Exception as e:
            print("❌ ブログ画像アップロードエラー:", e)
            flash(f"画像アップロードに失敗しました: {e}", "error")
            return render_template("admin_blog_new.html")
    category = request.form.get("category", "").strip()
    tags_raw = request.form.get("tags", "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    body_raw = request.form.get("body", "").strip()
    body_html = body_raw.replace("\n", "<br>") if body_raw else "<p>(本文未入力)</p>"
    draft = request.form.get("draft") == "on"
    
    # 現在ログイン中のスタッフIDを取得
    staff = session.get("staff", {})
    author_staff_id = staff.get("id")
    
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
        "author_staff_id": author_staff_id,
    }
    
    try:
        supabase_admin.table("blogs").insert(insert_data).execute()
        flash("ブログを作成しました", "success")
        return redirect("/admin/blogs")
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
    image_file = request.files.get("image_file")
    if image_file and image_file.filename:
        try:
            image = upload_blog_image(image_file)
        except ValueError as e:
            flash(str(e), "error")
            return redirect(f"/admin/blogs/edit/{blog_id}")
        except Exception as e:
            print("❌ ブログ画像アップロードエラー:", e)
            flash(f"画像アップロードに失敗しました: {e}", "error")
            return redirect(f"/admin/blogs/edit/{blog_id}")
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
        return redirect("/admin/blogs")
    except Exception as e:
        print("❌ ブログ更新エラー:", e)
        flash(f"ブログの更新に失敗しました: {e}", "error")
        return redirect(f"/admin/blogs/edit/{blog_id}")


@app.route("/admin/blogs/delete/<blog_id>", methods=["POST"])
@staff_required
def admin_blog_delete(blog_id):
    """ブログ削除（関連するコメントも削除）"""
    try:
        # blog_idを数値に変換（UUIDの場合はそのまま）
        try:
            blog_id_int = int(blog_id)
        except ValueError:
            blog_id_int = blog_id  # UUIDの場合は文字列のまま
        
        # まず、関連するコメントを削除
        deleted_comments = 0
        try:
            # 削除前にコメント数を確認
            res_comments = supabase_admin.table("comments").select("id", count="exact").eq("blog_id", blog_id_int).execute()
            comment_count = res_comments.count or 0
            
            if comment_count > 0:
                # コメントを削除
                res_delete = supabase_admin.table("comments").delete().eq("blog_id", blog_id_int).execute()
                deleted_comments = comment_count
                print(f"✅ ブログID {blog_id_int} のコメント {deleted_comments} 件を削除しました")
            else:
                print(f"ℹ️ ブログID {blog_id_int} に関連するコメントはありませんでした")
        except Exception as e:
            import traceback
            print(f"⚠️ コメント削除エラー: {e}")
            print(f"⚠️ トレースバック: {traceback.format_exc()}")
        
        # 最後にブログを削除
        supabase_admin.table("blogs").delete().eq("id", blog_id_int).execute()
        
        if deleted_comments > 0:
            flash(f"ブログと関連するコメント {deleted_comments} 件を削除しました", "success")
        else:
            flash("ブログを削除しました", "success")
    except Exception as e:
        import traceback
        print("❌ ブログ削除エラー:", e)
        print(f"❌ トレースバック: {traceback.format_exc()}")
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
            res_all = supabase_admin.table("patients").select("id, last_name, first_name, last_kana, first_kana, name, kana, birthday, introducer, introduced_by_patient_id").order("name").execute()
            all_patients = res_all.data or []
            
            # 紹介者IDの集合を取得
            introducer_ids = list({
                p.get("introduced_by_patient_id")
                for p in all_patients
                if p.get("introduced_by_patient_id")
            })
            
            # 紹介者情報を一括取得（vip_levelも含む）
            introducer_map = {}
            if introducer_ids:
                res_introducers = supabase_admin.table("patients").select("id, last_name, first_name, last_kana, first_kana, vip_level").in_("id", introducer_ids).execute()
                if res_introducers.data:
                    introducer_map = {
                        intro["id"]: intro for intro in res_introducers.data
                    }
            
            # 各患者に紹介者情報と紹介者数を結合
            for patient in all_patients:
                # 紹介者情報を結合
                intro_id = patient.get("introduced_by_patient_id")
                if intro_id and intro_id in introducer_map:
                    introducer_info = introducer_map[intro_id]
                    patient["introducer_info"] = introducer_info
                else:
                    patient["introducer_info"] = None
                
                # 紹介者数を取得
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
        
        # VIPフラグ取得（管理者のみ）
        vip_level = "none"  # デフォルト値
        if session.get("staff", {}).get("is_admin"):
            vip_level_str = request.form.get("vip_level", "none").strip()
            if vip_level_str in ["none", "star", "clover"]:
                vip_level = vip_level_str
        
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
            "vip_level": vip_level,
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

        # ✅ IN句で紹介者を一括取得（ここが最重要：姓名分離フィールドとvip_levelも取得）
        if introducer_ids:
            res_intro = (
                supabase_admin
                .table("patients")
                .select("id, last_name, first_name, last_kana, first_kana, name, vip_level")
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
        res_introduced_patients = None  # 予約数集計でも使用するため、スコープを広げる
        if patients:
            patient_ids = [p.get("id") for p in patients if p.get("id")]
            if patient_ids:
                # introduced_by_patient_idがpatient_idsに含まれる患者を一括取得（IDも取得して予約数集計に使用）
                res_introduced_patients = supabase_admin.table("patients").select("id, introduced_by_patient_id").in_("introduced_by_patient_id", patient_ids).execute()
                if res_introduced_patients.data:
                    # 紹介者IDごとにカウント（Python側で集計）
                    for patient_record in res_introduced_patients.data:
                        intro_id = patient_record.get("introduced_by_patient_id")
                        if intro_id:
                            introduced_count_map[intro_id] = introduced_count_map.get(intro_id, 0) + 1
        else:
            res_introduced_patients = None

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
        
        # ✅ 紹介経由予約数を一括取得（N+1を避ける）
        # 既存のres_introduced_patientsの結果を再利用して、紹介者IDごとの紹介された患者IDリストを作成
        introduced_patient_ids_map = {}  # {紹介者ID: [紹介された患者IDのリスト]}
        if res_introduced_patients and res_introduced_patients.data:
            for patient_record in res_introduced_patients.data:
                intro_id = patient_record.get("introduced_by_patient_id")
                patient_id = patient_record.get("id")  # 紹介された患者のID
                if intro_id and patient_id:
                    if intro_id not in introduced_patient_ids_map:
                        introduced_patient_ids_map[intro_id] = []
                    introduced_patient_ids_map[intro_id].append(patient_id)
        
        # 全紹介された患者IDを収集（重複除去）
        all_introduced_patient_ids = list(set([
            pid for patient_ids in introduced_patient_ids_map.values() for pid in patient_ids
        ]))
        
        # 紹介経由予約数を一括取得（キャンセル除外）
        reservation_count_map = {}  # {紹介者ID: 予約数}
        if all_introduced_patient_ids:
            try:
                res_reservations = supabase_admin.table("reservations").select("patient_id").in_("patient_id", all_introduced_patient_ids).neq("status", "canceled").execute()
                if res_reservations.data:
                    # 紹介者IDごとに予約数を集計
                    for reservation in res_reservations.data:
                        patient_id = reservation.get("patient_id")
                        # この患者を紹介した紹介者を特定
                        for introducer_id, introduced_patient_ids in introduced_patient_ids_map.items():
                            if patient_id in introduced_patient_ids:
                                reservation_count_map[introducer_id] = reservation_count_map.get(introducer_id, 0) + 1
            except Exception as e:
                print(f"⚠️ WARNING - 紹介経由予約数取得エラー: {e}")
                # エラーが発生してもランキング表示は続行
        
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
                    
                    # 紹介経由予約数を取得
                    reservation_count = reservation_count_map.get(introducer_id, 0)
                    
                    introducer_ranking.append({
                        "patient_id": introducer_id,
                        "name": name,
                        "count": count,
                        "reservation_count": reservation_count
                    })
        
        # ✅ 予約数順ランキング取得（上位10名）
        # 本人の予約数 + 紹介した患者の予約数の合計でランキング
        # 1. 全患者の本人の予約数を取得（キャンセル除外）
        all_patient_ids = [p.get("id") for p in patients if p.get("id")]
        patient_own_reservation_count_map = {}  # {patient_id: 本人の予約数}
        if all_patient_ids:
            try:
                res_own_reservations = supabase_admin.table("reservations").select("patient_id").in_("patient_id", all_patient_ids).neq("status", "canceled").execute()
                if res_own_reservations.data:
                    for reservation in res_own_reservations.data:
                        patient_id = reservation.get("patient_id")
                        if patient_id:
                            patient_own_reservation_count_map[patient_id] = patient_own_reservation_count_map.get(patient_id, 0) + 1
            except Exception as e:
                print(f"⚠️ WARNING - 本人予約数取得エラー: {e}")
        
        # 2. 各患者の総予約数 = 本人の予約数 + 紹介した患者の予約数
        total_reservation_count_map = {}  # {patient_id: 総予約数}
        
        # 本人の予約数を追加
        for patient_id, count in patient_own_reservation_count_map.items():
            total_reservation_count_map[patient_id] = count
        
        # 紹介した患者の予約数を追加（reservation_count_mapは紹介者IDごとの紹介経由予約数）
        for introducer_id, count in reservation_count_map.items():
            if introducer_id in total_reservation_count_map:
                total_reservation_count_map[introducer_id] += count
            else:
                total_reservation_count_map[introducer_id] = count
        
        # 3. 総予約数でソート（降順）
        reservation_ranking = []
        if total_reservation_count_map:
            sorted_by_reservation = sorted(
                total_reservation_count_map.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]  # 上位10名のみ
            
            # 各患者の情報を取得
            for patient_id, total_reservation_count in sorted_by_reservation:
                patient_info = None
                # まずpatientsから検索
                for p in patients:
                    if p.get("id") == patient_id:
                        patient_info = p
                        break
                
                # patientsに見つからない場合はintroducer_mapから検索
                if not patient_info:
                    patient_info = introducer_map.get(patient_id)
                
                # まだ見つからない場合は個別に取得
                if not patient_info:
                    try:
                        res_p = supabase_admin.table("patients").select("id, last_name, first_name, name").eq("id", patient_id).execute()
                        if res_p.data:
                            patient_info = res_p.data[0]
                    except:
                        pass
                
                if patient_info:
                    # 名前を結合
                    name = f"{patient_info.get('last_name', '')} {patient_info.get('first_name', '')}".strip()
                    if not name:
                        name = patient_info.get('name', '不明')
                    
                    # 紹介人数も取得
                    intro_count = introduced_count_map.get(patient_id, 0)
                    
                    # 本人の予約数と紹介経由予約数を取得（表示用）
                    own_count = patient_own_reservation_count_map.get(patient_id, 0)
                    introduced_count = reservation_count_map.get(patient_id, 0)
                    
                    reservation_ranking.append({
                        "patient_id": patient_id,
                        "name": name,
                        "count": intro_count,
                        "reservation_count": total_reservation_count,
                        "own_reservation_count": own_count,
                        "introduced_reservation_count": introduced_count
                    })
        
        # デバッグ用ログ
        print(f"🔍 DEBUG - reservation_count_map: {len(reservation_count_map)}件")
        print(f"🔍 DEBUG - patient_own_reservation_count_map: {len(patient_own_reservation_count_map)}件")
        print(f"🔍 DEBUG - total_reservation_count_map: {len(total_reservation_count_map)}件")
        print(f"🔍 DEBUG - reservation_ranking: {len(reservation_ranking)}件")
        print(f"🔍 DEBUG - introducer_ranking: {len(introducer_ranking)}件")

        return render_template("admin_karte.html", patients=patients, introducer_ranking=introducer_ranking, reservation_ranking=reservation_ranking)

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
        
        # 紹介者情報取得（姓名分離フィールドとvip_levelも取得）
        introducer_info = None
        if patient.get("introduced_by_patient_id"):
            res_intro = supabase_admin.table("patients").select("id, last_name, first_name, last_kana, first_kana, vip_level").eq("id", patient.get("introduced_by_patient_id")).execute()
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
        
        # 累計予約数を取得（全期間、キャンセル除外）
        try:
            res_reservations = supabase_admin.table("reservations").select("id", count="exact").eq("patient_id", patient_id).neq("status", "canceled").execute()
            patient["total_reservation_count"] = res_reservations.count or 0
        except Exception as e:
            print(f"⚠️ WARNING - 累計予約数取得エラー: {e}")
            patient["total_reservation_count"] = 0
        
        # この患者が紹介した患者一覧を取得（vip_levelも含む）
        res_introduced_patients = supabase_admin.table("patients").select("id, last_name, first_name, last_kana, first_kana, name, kana, birthday, vip_level, category, gender").eq("introduced_by_patient_id", patient_id).order("created_at", desc=True).execute()
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
        
        # 初診日を取得（最古の施術ログの日付）
        first_visit_date = None
        if logs:
            first_visit_date = logs[-1].get("date")
        patient["first_visit_date"] = first_visit_date
        
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
        
        # 現在の予約状況を取得（キャンセルされていない、未来の予約）
        current_reservations = []
        try:
            now_jst = datetime.now(JST)
            now_iso = now_jst.isoformat()
            
            res_reservations = (
                supabase_admin.table("reservations")
                .select("*")
                .eq("patient_id", patient_id)
                .neq("status", "canceled")
                .gte("reserved_at", now_iso)
                .order("reserved_at")
                .execute()
            )
            reservations = res_reservations.data or []
            
            # 患者情報を結合（既にpatient変数があるので、予約に追加）
            for r in reservations:
                # 名前を結合
                name = f"{patient.get('last_name', '')} {patient.get('first_name', '')}".strip()
                if not name:
                    name = patient.get("name", "不明")
                r["patient_name"] = name
                r["patient"] = patient
                
                # 時刻をJSTで表示用に変換
                try:
                    dt_str = r.get("reserved_at", "")
                    if dt_str:
                        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                        dt_jst = dt.astimezone(JST)
                        r["reserved_at_display"] = dt_jst.strftime("%Y年%m月%d日 %H:%M")
                    else:
                        r["reserved_at_display"] = "時刻不明"
                except:
                    r["reserved_at_display"] = "時刻不明"
                
                # nomination_typeが存在しない場合はデフォルト値'本指名'を設定
                if "nomination_type" not in r or not r.get("nomination_type"):
                    r["nomination_type"] = "本指名"
                
                # nominated_staff_idsをJSONからパース
                try:
                    nominated_staff_ids_str = r.get("nominated_staff_ids")
                    if nominated_staff_ids_str:
                        if isinstance(nominated_staff_ids_str, str):
                            r["nominated_staff_ids"] = json.loads(nominated_staff_ids_str)
                        else:
                            r["nominated_staff_ids"] = nominated_staff_ids_str
                    else:
                        r["nominated_staff_ids"] = []
                except:
                    r["nominated_staff_ids"] = []
            
            current_reservations = reservations
        except Exception as e:
            print(f"⚠️ WARNING - 予約状況取得エラー: {e}")
            current_reservations = []
        
        # 過去の利用状況を取得（完了した予約、直近3回）
        past_reservations = []
        try:
            now_jst = datetime.now(JST)
            now_iso = now_jst.isoformat()
            
            res_past_reservations = (
                supabase_admin.table("reservations")
                .select("*")
                .eq("patient_id", patient_id)
                .eq("status", "completed")
                .lt("reserved_at", now_iso)
                .order("reserved_at", desc=True)
                .limit(3)
                .execute()
            )
            past_reservations_data = res_past_reservations.data or []
            
            # 患者情報を結合（既にpatient変数があるので、予約に追加）
            for r in past_reservations_data:
                # 名前を結合
                name = f"{patient.get('last_name', '')} {patient.get('first_name', '')}".strip()
                if not name:
                    name = patient.get("name", "不明")
                r["patient_name"] = name
                r["patient"] = patient
                
                # 時刻をJSTで表示用に変換
                try:
                    dt_str = r.get("reserved_at", "")
                    if dt_str:
                        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                        dt_jst = dt.astimezone(JST)
                        r["reserved_at_display"] = dt_jst.strftime("%Y年%m月%d日 %H:%M")
                    else:
                        r["reserved_at_display"] = "時刻不明"
                except:
                    r["reserved_at_display"] = "時刻不明"
                
                # nomination_typeが存在しない場合はデフォルト値'本指名'を設定
                if "nomination_type" not in r or not r.get("nomination_type"):
                    r["nomination_type"] = "本指名"
                
                # nominated_staff_idsをJSONからパース
                try:
                    nominated_staff_ids_str = r.get("nominated_staff_ids")
                    if nominated_staff_ids_str:
                        if isinstance(nominated_staff_ids_str, str):
                            r["nominated_staff_ids"] = json.loads(nominated_staff_ids_str)
                        else:
                            r["nominated_staff_ids"] = nominated_staff_ids_str
                    else:
                        r["nominated_staff_ids"] = []
                except:
                    r["nominated_staff_ids"] = []
            
            past_reservations = past_reservations_data
        except Exception as e:
            print(f"⚠️ WARNING - 過去の利用状況取得エラー: {e}")
            past_reservations = []
        
        return render_template("admin_karte_detail.html", patient=patient, logs=logs, is_admin=is_admin, current_reservations=current_reservations, past_reservations=past_reservations)
    except Exception as e:
        print("❌ カルテ詳細取得エラー:", e)
        flash("カルテ詳細の取得に失敗しました", "error")
        return redirect("/admin/karte")


@app.route("/admin/karte/<patient_id>/vip", methods=["POST"])
@admin_required
def admin_karte_vip(patient_id):
    """VIPフラグ更新（管理者のみ）"""
    try:
        vip_level = request.form.get("vip_level", "none").strip()
        
        # 値の検証
        if vip_level not in ["none", "star", "clover"]:
            flash("無効なVIPフラグ値です", "error")
            return redirect(f"/admin/karte/{patient_id}")
        
        # 更新
        supabase_admin.table("patients").update({"vip_level": vip_level}).eq("id", patient_id).execute()
        
        flash("VIPフラグを更新しました", "success")
        return redirect(f"/admin/karte/{patient_id}")
    except Exception as e:
        print(f"❌ VIPフラグ更新エラー: {e}")
        flash("VIPフラグの更新に失敗しました", "error")
        return redirect(f"/admin/karte/{patient_id}")


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
            "chiropractic": request.form.get("chiropractic", "").strip(),
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
    upcoming = []
    try:
        with open("static/data/schedule.json", encoding="utf-8") as f:
            schedule = json.load(f)

        today = datetime.now().date()

        for s in schedule:
            try:
                # 日付フォーマットを正規化（"2026-1-31" → "2026-01-31"）
                date_str = s.get("date", "")
                if date_str:
                    d = None
                    normalized_date = None
                    
                    # 既に正しいフォーマットの場合
                    try:
                        d = datetime.strptime(date_str, "%Y-%m-%d").date()
                        normalized_date = date_str
                    except:
                        # ゼロパディングがない場合（"2026-1-31"など）
                        parts = date_str.split("-")
                        if len(parts) == 3:
                            year, month, day = parts
                            normalized_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                            try:
                                d = datetime.strptime(normalized_date, "%Y-%m-%d").date()
                            except:
                                print(f"⚠️ WARNING - 日付解析失敗: {normalized_date}")
                                continue
                        else:
                            print(f"⚠️ WARNING - 日付フォーマット不正: {date_str}")
                            continue
                    
                    if d and d >= today:
                        # 正規化した日付を反映
                        s["date"] = normalized_date
                        # 表示用の月/日も追加（必ず設定）
                        # normalized_dateは "YYYY-MM-DD" 形式なので、[5:7]と[8:10]で取得
                        if len(normalized_date) >= 10:
                            s["month"] = normalized_date[5:7]
                            s["day"] = normalized_date[8:10]
                        else:
                            # フォールバック: 日付文字列から直接取得
                            parts = normalized_date.split("-")
                            if len(parts) >= 3:
                                s["month"] = parts[1].zfill(2)
                                s["day"] = parts[2].zfill(2)
                            else:
                                s["month"] = "01"
                                s["day"] = "01"
                        upcoming.append(s)
            except Exception as e:
                print(f"⚠️ WARNING - スケジュール日付解析エラー: {e}, date: {s.get('date', '')}")
                continue

        upcoming = upcoming[:10]
    except Exception as e:
        print("❌ schedule.json 読み込みエラー:", e)
        upcoming = []  # エラー時は空リストを返す



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
            "/form", "/login", "/register", "/blog", "/news", "/yoyogiuehara/shinkyu", "/yakuin/shinkyu"
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
        
        # 患者情報を一括取得（category, gender, vip_levelも取得）
        patient_map = {}
        if patient_ids:
            res_patients = supabase_admin.table("patients").select("id, last_name, first_name, name, category, gender, vip_level").in_("id", patient_ids).execute()
            if res_patients.data:
                patient_map = {p["id"]: p for p in res_patients.data}
        
        # 予約情報にnomination_type、nominated_staff_ids、areaを追加
        for reservation in reservations:
            # nomination_typeが存在しない場合はデフォルト値'本指名'を設定
            if "nomination_type" not in reservation or not reservation.get("nomination_type"):
                reservation["nomination_type"] = "本指名"
            
            # nominated_staff_idsをJSONからパース
            try:
                nominated_staff_ids_str = reservation.get("nominated_staff_ids")
                if nominated_staff_ids_str:
                    if isinstance(nominated_staff_ids_str, str):
                        reservation["nominated_staff_ids"] = json.loads(nominated_staff_ids_str)
                    else:
                        reservation["nominated_staff_ids"] = nominated_staff_ids_str
                else:
                    reservation["nominated_staff_ids"] = []
            except:
                reservation["nominated_staff_ids"] = []
        
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
        # 月初の曜日（0=日曜日、6=土曜日）
        # calendar.monthrange は月曜日=0なので、日曜始まりに変換
        first_weekday = (calendar.monthrange(current_date.year, current_date.month)[0] + 1) % 7
        # 月の日数
        if current_date.month == 12:
            next_month_first = datetime(current_date.year + 1, 1, 1, tzinfo=JST)
        else:
            next_month_first = datetime(current_date.year, current_date.month + 1, 1, tzinfo=JST)
        days_in_month = (next_month_first - current_date).days
        
        # スケジュール読み込み（休日の判定用）
        schedule_map = {}  # {日付文字列（YYYY-MM-DD）: place}
        try:
            with open("static/data/schedule.json", encoding="utf-8") as f:
                all_schedule = json.load(f)
            for s in all_schedule:
                # 日付フォーマットを正規化（"2025-12-1" → "2025-12-01"）
                date_str = s.get("date", "")
                if date_str:
                    try:
                        # 日付をパースして正規化
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                        normalized_date = date_obj.strftime("%Y-%m-%d")
                        schedule_map[normalized_date] = s.get("place", "")
                    except:
                        # フォーマットが異なる場合（"2025-12-1"など）
                        parts = date_str.split("-")
                        if len(parts) == 3:
                            year, month, day = parts
                            normalized_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                            schedule_map[normalized_date] = s.get("place", "")
        except Exception as e:
            print("❌ schedule.json 読み込みエラー:", e)
        
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
            now_jst=now_jst,
            schedule_map=schedule_map
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
            # 日付パラメータを取得（初期値として使用）
            date_param = request.args.get("date", "")
            initial_date = None
            if date_param:
                try:
                    # YYYY-MM-DD形式をdatetime-local形式に変換（時刻は9:00をデフォルト）
                    date_obj = datetime.strptime(date_param, "%Y-%m-%d")
                    initial_date = date_obj.strftime("%Y-%m-%dT09:00")
                except:
                    pass
            
            # 患者一覧取得（autocomplete用に姓名分離フィールド・生年月日・紹介者も取得）
            res_patients = supabase_admin.table("patients").select("id, last_name, first_name, last_kana, first_kana, name, kana, birthday, introducer, introduced_by_patient_id").order("created_at", desc=True).execute()
            patients = res_patients.data or []
            
            # 紹介者IDの集合を取得
            introducer_ids = list({
                p.get("introduced_by_patient_id")
                for p in patients
                if p.get("introduced_by_patient_id")
            })
            
            # 紹介者情報を一括取得（vip_levelも含む）
            introducer_map = {}
            if introducer_ids:
                res_introducers = supabase_admin.table("patients").select("id, last_name, first_name, last_kana, first_kana, vip_level").in_("id", introducer_ids).execute()
                if res_introducers.data:
                    introducer_map = {
                        intro["id"]: intro for intro in res_introducers.data
                    }
            
            # 各患者に紹介者情報を結合
            for patient in patients:
                intro_id = patient.get("introduced_by_patient_id")
                if intro_id and intro_id in introducer_map:
                    introducer_info = introducer_map[intro_id]
                    patient["introducer_info"] = introducer_info
                else:
                    patient["introducer_info"] = None
            
            # スタッフリスト取得（承認済みスタッフ全員）
            staff = session.get("staff", {})
            staff_name = staff.get("name", "スタッフ")
            staff_list = []
            try:
                # Supabase Authから承認済みスタッフを取得
                users = supabase_admin.auth.admin.list_users()
                for u in users:
                    meta = u.user_metadata or {}
                    # 承認済みのみ表示
                    if not meta.get("approved", False):
                        continue
                    
                    # 姓・名から表示名を生成（半角スペース区切り）
                    last_name = meta.get("last_name", "")
                    first_name = meta.get("first_name", "")
                    if last_name and first_name:
                        display_name = f"{last_name} {first_name}"
                    else:
                        # 後方互換性：既存データはnameフィールドを使用
                        display_name = meta.get("name", "未設定")
                    
                    staff_list.append({
                        "name": display_name,
                        "id": u.id
                    })
                
                # 名前順でソート
                staff_list.sort(key=lambda x: x["name"])
            except Exception as e:
                print("❌ スタッフリスト取得エラー:", e)
                # エラー時は現在のスタッフのみ
                staff_list = [{"name": staff_name, "id": staff.get("id")}]
            
            return render_template("admin_reservations_new.html", patients=patients, staff_name=staff_name, staff_list=staff_list, initial_date=initial_date)
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
        
        # 予約重複チェック（同一スタッフ × 時間帯が被る場合）
        # 予約終了時刻を計算
        reserved_end = dt_jst + timedelta(minutes=duration_minutes)
        reserved_end_iso = reserved_end.isoformat()
        
        # 重複チェック：同じスタッフで、時間帯が被る予約を検索
        # キャンセル済みは除外
        query = supabase_admin.table("reservations").select("id, reserved_at, duration_minutes, staff_name, patient_id").eq("staff_name", staff_name).neq("status", "canceled")
        
        # 時間帯が被る予約を検索
        res_overlapping = query.execute()
        overlapping_reservations = []
        
        if res_overlapping.data:
            for other_res in res_overlapping.data:
                try:
                    other_start_str = other_res.get("reserved_at", "")
                    other_duration = other_res.get("duration_minutes", 60)
                    if other_start_str:
                        other_start = datetime.fromisoformat(other_start_str.replace("Z", "+00:00")).astimezone(JST)
                        other_end = other_start + timedelta(minutes=other_duration)
                        
                        # 時間帯が被るかチェック
                        if dt_jst < other_end and reserved_end > other_start:
                            overlapping_reservations.append(other_res)
                except:
                    pass
        
        if overlapping_reservations:
            # 重複している予約の情報を取得
            patient_ids = [r.get("patient_id") for r in overlapping_reservations if r.get("patient_id")]
            patient_map = {}
            if patient_ids:
                res_patients = supabase_admin.table("patients").select("id, last_name, first_name, name").in_("id", patient_ids).execute()
                if res_patients.data:
                    for p in res_patients.data:
                        name = f"{p.get('last_name', '')} {p.get('first_name', '')}".strip()
                        patient_map[p["id"]] = name or p.get("name", "不明")
            
            # エラーメッセージを作成
            conflict_details = []
            for conflict in overlapping_reservations:
                conflict_start = datetime.fromisoformat(conflict.get("reserved_at", "").replace("Z", "+00:00")).astimezone(JST)
                conflict_patient_name = patient_map.get(conflict.get("patient_id"), "不明")
                conflict_details.append(f"{conflict_start.strftime('%Y-%m-%d %H:%M')} - {conflict_patient_name}")
            
            flash(f"予約が重複しています。同じスタッフの以下の予約と時間帯が被っています：\n" + "\n".join(conflict_details), "error")
            return redirect("/admin/reservations/new")
        
        # エリア取得
        area = request.form.get("area", "").strip() or None
        if area and area not in ["tokyo", "fukuoka"]:
            area = None
        
        # メニュー取得（施術時間を決定）
        menu = request.form.get("menu", "").strip()
        duration_minutes = 90  # デフォルト値
        if menu:
            if menu == "other":
                # 「その他」の場合はデフォルト90分
                duration_minutes = 90
            else:
                # メニューから施術時間を取得（60/90/120など）
                try:
                    duration_minutes = int(menu)
                except:
                    duration_minutes = 90
        
        # 指名タイプ取得（日本語値：'本指名','枠指名','希望','フリー'）
        nomination_type = request.form.get("nomination_type", "本指名").strip()
        # 英語値から日本語値への変換（後方互換性のため）
        nomination_type_map = {"main": "本指名", "frame": "枠指名", "hope": "希望", "free": "フリー"}
        if nomination_type in nomination_type_map:
            nomination_type = nomination_type_map[nomination_type]
        # 有効な値でない場合はデフォルト値
        if nomination_type not in ["本指名", "枠指名", "希望", "フリー"]:
            nomination_type = "本指名"
        
        # 枠指名スタッフID取得（全スタッフ選択可能）
        nominated_staff_ids = []
        nomination_priority = None
        if nomination_type == "枠指名":
            # フォームから全てのframe_staff_*を取得（数に制限なし）
            i = 1
            while True:
                frame_staff = request.form.get(f"frame_staff_{i}", "").strip()
                if not frame_staff:
                    break
                frame_priority = request.form.get(f"frame_priority_{i}", "").strip()
                # スタッフ名を追加（現状はstaff_nameのみ、将来staff_idに置換可能）
                nominated_staff_ids.append(frame_staff)
                if frame_priority:
                    try:
                        priority_int = int(frame_priority)
                        if not nomination_priority or priority_int < nomination_priority:
                            nomination_priority = priority_int
                    except:
                        pass
                i += 1
        
        # 価格取得
        base_price_str = request.form.get("base_price", "").strip()
        try:
            base_price = int(base_price_str) if base_price_str else None
        except:
            base_price = None
        
        # 選択されたメニュー取得（複数選択可）
        selected_menus = request.form.getlist("selected_menus")
        
        # 指名料取得
        nomination_fee_str = request.form.get("nomination_fee", "0").strip()
        try:
            nomination_fee = int(nomination_fee_str) if nomination_fee_str else 0
        except:
            nomination_fee = 0
        
        # 割引取得
        discount_str = request.form.get("discount", "0").strip()
        try:
            discount = int(discount_str) if discount_str else 0
        except:
            discount = 0
        
        # 出張費取得
        transportation_fee_str = request.form.get("transportation_fee", "0").strip()
        transportation_fee_other_str = request.form.get("transportation_fee_other", "0").strip()
        try:
            if transportation_fee_str == "other":
                transportation_fee = int(transportation_fee_other_str) if transportation_fee_other_str else 0
            else:
                transportation_fee = int(transportation_fee_str) if transportation_fee_str else 0
        except:
            transportation_fee = 0
        
        # 消費税取得
        tax_str = request.form.get("tax", "0").strip()
        try:
            tax = int(tax_str) if tax_str else 0
        except:
            # 消費税が未入力の場合は自動計算 料金 × 0.1（指名料と出張費にはかからない）
            if base_price:
                tax = int((base_price or 0) * 0.1)
            else:
                tax = 0
        
        # 予約作成
        reservation_data = {
            "patient_id": patient_id,
            "reserved_at": reserved_at_iso,
            "duration_minutes": duration_minutes,
            "place_type": place_type,
            "place_name": place_name,
            "staff_name": staff_name,
            "area": area,
            "nomination_type": nomination_type,
            "nominated_staff_ids": nominated_staff_ids or [],
            "nomination_priority": nomination_priority,
            "base_price": base_price,
            "selected_menus": selected_menus,
            "nomination_fee": nomination_fee,
            "discount": discount,
            "transportation_fee": transportation_fee,
            "tax": tax,
            "status": "reserved",
            "memo": memo,
            "created_at": now_iso()
        }
        
        try:
            res_reservation = supabase_admin.table("reservations").insert(reservation_data).execute()
            if not res_reservation.data:
                flash("予約の作成に失敗しました（データが返されませんでした）", "error")
                return redirect("/admin/reservations/new")
        except Exception as insert_error:
            print(f"❌ 予約作成エラー: {insert_error}")
            flash(f"予約の作成に失敗しました: {str(insert_error)}", "error")
            return redirect("/admin/reservations/new")
        
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
        import traceback
        print("❌ 予約作成エラー:", e)
        print("❌ トレースバック:", traceback.format_exc())
        flash(f"予約の作成に失敗しました: {str(e)}", "error")
        return redirect("/admin/reservations/new")


@app.route("/admin/reservations/<reservation_id>/status", methods=["POST"])
@staff_required
def admin_reservations_status(reservation_id):
    """予約ステータス更新"""
    try:
        new_status = request.form.get("status", "").strip()
        payment_method = request.form.get("payment_method", "").strip()
        receipt_status = request.form.get("receipt_status", "").strip()
        if new_status not in ["reserved", "visited", "completed", "canceled"]:
            flash("無効なステータスです", "error")
            return redirect("/admin/reservations")
        
        # 予約情報を取得（日報反映用）
        res_reservation = supabase_admin.table("reservations").select("*").eq("id", reservation_id).execute()
        if not res_reservation.data:
            flash("予約が見つかりません", "error")
            return redirect("/admin/reservations")
        reservation = res_reservation.data[0]
        
        # ステータス更新
        supabase_admin.table("reservations").update({"status": new_status}).eq("id", reservation_id).execute()

        # 支払い方法（任意）を保存
        if new_status == "completed":
            update_fields = {}
            if payment_method:
                update_fields["payment_method"] = payment_method
            if receipt_status:
                update_fields["receipt_status"] = receipt_status
            if update_fields:
                try:
                    supabase_admin.table("reservations").update(update_fields).eq("id", reservation_id).execute()
                except Exception as e:
                    print(f"⚠️ payment/receipt 更新エラー: {e}")
        
        # 予約完了時に日報へ自動反映（院内 or 往診のみ）
        if new_status == "completed":
            try:
                staff_name = reservation.get("staff_name")
                place_type = reservation.get("place_type")
                patient_id = reservation.get("patient_id")
                reserved_at_str = reservation.get("reserved_at")
                
                # 院内・往診・帯同すべてで日報に反映
                if staff_name and place_type in ["in_house", "visit", "field"] and patient_id and reserved_at_str:
                    # 予約日時をJSTに変換して日付を取得
                    dt = datetime.fromisoformat(reserved_at_str.replace("Z", "+00:00"))
                    dt_jst = dt.astimezone(JST)
                    date_str = dt_jst.strftime("%Y-%m-%d")
                    
                    # 当日の日報を取得または作成
                    res_report = supabase_admin.table("staff_daily_reports").select("*").eq("staff_name", staff_name).eq("report_date", date_str).execute()
                    
                    if res_report.data:
                        report_id = res_report.data[0]["id"]
                    else:
                        # 日報が存在しない場合は作成
                        # week_keyを計算（YYYY-WW形式、ISO週番号を使用）
                        report_date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                        iso_calendar = report_date_obj.isocalendar()
                        week_key = f"{iso_calendar[0]}-{iso_calendar[1]:02d}"
                        
                        report_data = {
                            "staff_name": staff_name,
                            "report_date": date_str,
                            "week_key": week_key,
                            "memo": None,
                            "created_at": now_iso(),
                            "updated_at": now_iso()
                        }
                        res_new_report = supabase_admin.table("staff_daily_reports").insert(report_data).execute()
                        if res_new_report.data:
                            report_id = res_new_report.data[0]["id"]
                        else:
                            report_id = None
                    
                    if report_id:
                        # 該当区分の勤務カードを取得または作成
                        res_items = supabase_admin.table("staff_daily_report_items").select("*").eq("daily_report_id", report_id).eq("work_type", place_type).execute()
                        
                        if res_items.data:
                            # 既存のカードがあれば最初の1つを使用
                            item_id = res_items.data[0]["id"]
                        else:
                            # カードが存在しない場合は作成
                            item_data = {
                                "daily_report_id": report_id,
                                "work_type": place_type,
                                "start_time": None,
                                "end_time": None,
                                "break_minutes": 0,
                                "memo": None,
                                "created_at": now_iso()
                            }
                            res_new_item = supabase_admin.table("staff_daily_report_items").insert(item_data).execute()
                            if res_new_item.data:
                                item_id = res_new_item.data[0]["id"]
                            else:
                                item_id = None
                        
                        if item_id:
                            # 患者情報を取得（名前表示用）
                            patient_name = "患者不明"
                            try:
                                res_patient = supabase_admin.table("patients").select("last_name, first_name, name").eq("id", patient_id).execute()
                                if res_patient.data:
                                    p = res_patient.data[0]
                                    name = f"{p.get('last_name', '')} {p.get('first_name', '')}".strip()
                                    patient_name = name or p.get("name", "患者不明")
                            except:
                                pass
                            
                            # 予約情報からコース名と価格を取得
                            course_name = None
                            base_price = reservation.get("base_price") or 0
                            transportation_fee = reservation.get("transportation_fee") or 0
                            nomination_fee = reservation.get("nomination_fee") or 0
                            discount = reservation.get("discount") or 0
                            nomination_type = reservation.get("nomination_type", "本指名")
                            
                            # 英語値から日本語値への変換（後方互換性のため）
                            nomination_type_map = {"main": "本指名", "frame": "枠指名", "hope": "希望", "free": "フリー"}
                            if nomination_type in nomination_type_map:
                                nomination_type = nomination_type_map[nomination_type]
                            
                            # メニュー名を生成（指名タイプ＋現場区分の形式で統一）
                            place_type_label = {"in_house": "院内", "visit": "往診", "field": "帯同"}.get(place_type, "")
                            
                            # 表記ルール：本指名（院内）、枠指名（帯同）の形式（本指名/枠指名は必ずこの形式）
                            if nomination_type in ["本指名", "枠指名"]:
                                course_name = f"{nomination_type}（{place_type_label}）"
                            else:
                                # 希望/フリーの場合は従来通り（エリア＋時間）
                                area = reservation.get("area")
                                duration = reservation.get("duration_minutes")
                                if area and duration:
                                    area_label = "東京" if area == "tokyo" else "福岡" if area == "fukuoka" else ""
                                    course_name = f"{area_label} {duration}分コース"
                                else:
                                    course_name = f"{nomination_type}（{place_type_label}）"
                            
                            # スタッフ日報の売上金額 = 新規予約作成フォームの合計金額そのまま
                            # 合計金額 = 料金 + 出張費 + 指名料 - 割引 + 消費税
                            tax = reservation.get("tax") or 0
                            amount = base_price + transportation_fee + nomination_fee - discount + tax
                            
                            # 患者・売上明細を追加（重複チェック）
                            try:
                                res_existing = supabase_admin.table("staff_daily_report_patients").select("*").eq("item_id", item_id).eq("reservation_id", reservation_id).execute()
                                if not res_existing.data:
                                    patient_data = {
                                        "item_id": item_id,
                                        "patient_id": patient_id,
                                        "reservation_id": reservation_id,
                                        "course_name": course_name,
                                        "amount": amount,  # (料金 - 割引) × 1.1 + 出張費
                                        "memo": None,
                                        "created_at": now_iso()
                                    }
                                    supabase_admin.table("staff_daily_report_patients").insert(patient_data).execute()
                                    print(f"✅ 日報に患者情報を追加しました: staff_name={staff_name}, report_date={date_str}, reservation_id={reservation_id}, amount={amount}")
                                    
                            except Exception as e:
                                print(f"❌ 日報への患者情報追加エラー: {e}")
                                print(f"   スタッフ: {staff_name}, 日付: {date_str}, 予約ID: {reservation_id}")
                                raise  # エラーを上位に伝播
                            
                            # 枠指名スタッフ全員の日報にも反映（対応スタッフ以外）
                            nominated_staff_ids_str = reservation.get("nominated_staff_ids")
                            nominated_staff_names = []
                            if nominated_staff_ids_str:
                                try:
                                    if isinstance(nominated_staff_ids_str, str):
                                        nominated_staff_names = json.loads(nominated_staff_ids_str)
                                    else:
                                        nominated_staff_names = nominated_staff_ids_str
                                except:
                                    nominated_staff_names = []
                            
                            # 枠指名スタッフが存在する場合、対応スタッフ以外にも0円で追加
                            if nomination_type == "枠指名" and nominated_staff_names:
                                # 各枠指名スタッフの日報に0円で追加（対応スタッフは既に処理済みなのでスキップ）
                                for nominated_staff_name in nominated_staff_names:
                                    if nominated_staff_name == staff_name:
                                        continue  # 対応スタッフは既に処理済み
                                    
                                    # 該当スタッフの当日の日報を取得または作成
                                    res_nom_report = supabase_admin.table("staff_daily_reports").select("*").eq("staff_name", nominated_staff_name).eq("report_date", date_str).execute()
                                    
                                    if res_nom_report.data:
                                        nom_report_id = res_nom_report.data[0]["id"]
                                    else:
                                        # week_keyを計算（YYYY-WW形式、ISO週番号を使用）
                                        report_date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                                        iso_calendar = report_date_obj.isocalendar()
                                        week_key = f"{iso_calendar[0]}-{iso_calendar[1]:02d}"
                                        
                                        nom_report_data = {
                                            "staff_name": nominated_staff_name,
                                            "report_date": date_str,
                                            "week_key": week_key,
                                            "memo": None,
                                            "created_at": now_iso(),
                                            "updated_at": now_iso()
                                        }
                                        res_new_nom_report = supabase_admin.table("staff_daily_reports").insert(nom_report_data).execute()
                                        if res_new_nom_report.data:
                                            nom_report_id = res_new_nom_report.data[0]["id"]
                                        else:
                                            nom_report_id = None
                                    
                                    if nom_report_id:
                                        # 該当区分の勤務カードを取得または作成
                                        res_nom_items = supabase_admin.table("staff_daily_report_items").select("*").eq("daily_report_id", nom_report_id).eq("work_type", place_type).execute()
                                        
                                        if res_nom_items.data:
                                            nom_item_id = res_nom_items.data[0]["id"]
                                        else:
                                            nom_item_data = {
                                                "daily_report_id": nom_report_id,
                                                "work_type": place_type,
                                                "start_time": None,
                                                "end_time": None,
                                                "break_minutes": 0,
                                                "memo": None,
                                                "created_at": now_iso()
                                            }
                                            res_new_nom_item = supabase_admin.table("staff_daily_report_items").insert(nom_item_data).execute()
                                            if res_new_nom_item.data:
                                                nom_item_id = res_new_nom_item.data[0]["id"]
                                            else:
                                                nom_item_id = None
                                        
                                        if nom_item_id:
                                            # 枠指名の場合の処理
                                            # 帯同の場合：対応しなかった指名スタッフに1000円
                                            # それ以外の場合：対応しなかった指名スタッフに100円
                                            frame_nomination_fee = 1000 if place_type == "field" else 100
                                            
                                            try:
                                                res_nom_existing = supabase_admin.table("staff_daily_report_patients").select("*").eq("item_id", nom_item_id).eq("reservation_id", reservation_id).execute()
                                                if not res_nom_existing.data:
                                                    nom_patient_data = {
                                                        "item_id": nom_item_id,
                                                        "patient_id": patient_id,
                                                        "reservation_id": reservation_id,
                                                        "course_name": f"枠指名（{place_type_label}）",  # 表記ルール統一
                                                        "amount": frame_nomination_fee,  # 枠指名で対応スタッフに選ばれなかった場合の金額
                                                        "memo": None,
                                                        "created_at": now_iso()
                                                    }
                                                    supabase_admin.table("staff_daily_report_patients").insert(nom_patient_data).execute()
                                                    print(f"✅ 枠指名スタッフの日報に追加しました: staff_name={nominated_staff_name}, report_date={date_str}, reservation_id={reservation_id}, amount={frame_nomination_fee}")
                                                    
                                            except Exception as e:
                                                print(f"❌ 枠指名スタッフの日報への患者情報追加エラー: {e}")
                                                print(f"   スタッフ: {nominated_staff_name}, 日付: {date_str}, 予約ID: {reservation_id}")
                                                raise  # エラーを上位に伝播
            except Exception as e:
                print(f"⚠️ WARNING - 日報への自動反映エラー: {e}")
                # 日報反映エラーは警告のみ（予約ステータス更新は成功）
        
        flash("予約ステータスを更新しました", "success")
        return redirect(request.referrer or "/admin/reservations")
    except Exception as e:
        print("❌ 予約ステータス更新エラー:", e)
        flash("予約ステータスの更新に失敗しました", "error")
        return redirect("/admin/reservations")


@app.route("/admin/reservations/<reservation_id>/edit", methods=["GET", "POST"])
@staff_required
def admin_reservations_edit(reservation_id):
    """予約編集"""
    if request.method == "GET":
        try:
            # 予約情報取得
            res = supabase_admin.table("reservations").select("*").eq("id", reservation_id).execute()
            if not res.data:
                flash("予約が見つかりません", "error")
                return redirect("/admin/reservations")
            reservation = res.data[0]
            
            # 患者情報取得
            patient_id = reservation.get("patient_id")
            res_patient = supabase_admin.table("patients").select("id, last_name, first_name, name").eq("id", patient_id).execute()
            if res_patient.data:
                patient = res_patient.data[0]
                name = f"{patient.get('last_name', '')} {patient.get('first_name', '')}".strip()
                reservation["patient_name"] = name or patient.get("name", "不明")
            else:
                reservation["patient_name"] = "不明"
            
            # reserved_atをdatetime-local形式に変換
            try:
                dt_str = reservation.get("reserved_at", "")
                if dt_str:
                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    dt_jst = dt.astimezone(JST)
                    reservation["reserved_at_display_local"] = dt_jst.strftime("%Y-%m-%dT%H:%M")
                else:
                    reservation["reserved_at_display_local"] = ""
            except:
                reservation["reserved_at_display_local"] = ""
            
            # nominated_staff_idsをJSONからパース
            try:
                nominated_staff_ids_str = reservation.get("nominated_staff_ids")
                if nominated_staff_ids_str:
                    if isinstance(nominated_staff_ids_str, str):
                        reservation["nominated_staff_ids"] = json.loads(nominated_staff_ids_str)
                    else:
                        reservation["nominated_staff_ids"] = nominated_staff_ids_str
                else:
                    reservation["nominated_staff_ids"] = []
            except:
                reservation["nominated_staff_ids"] = []
            
            # selected_menusをJSONからパース
            try:
                selected_menus_str = reservation.get("selected_menus")
                if selected_menus_str:
                    if isinstance(selected_menus_str, str):
                        reservation["selected_menus"] = json.loads(selected_menus_str)
                    else:
                        reservation["selected_menus"] = selected_menus_str
                else:
                    reservation["selected_menus"] = []
            except:
                reservation["selected_menus"] = []
            
            # nomination_feeとdiscountのデフォルト値
            if reservation.get("nomination_fee") is None:
                reservation["nomination_fee"] = 0
            if reservation.get("discount") is None:
                reservation["discount"] = 0
            
            # スタッフリスト取得（承認済みスタッフ全員）
            staff = session.get("staff", {})
            staff_name = staff.get("name", "スタッフ")
            staff_list = []
            try:
                # Supabase Authから承認済みスタッフを取得
                users = supabase_admin.auth.admin.list_users()
                for u in users:
                    meta = u.user_metadata or {}
                    # 承認済みのみ表示
                    if not meta.get("approved", False):
                        continue
                    
                    # 姓・名から表示名を生成（半角スペース区切り）
                    last_name = meta.get("last_name", "")
                    first_name = meta.get("first_name", "")
                    if last_name and first_name:
                        display_name = f"{last_name} {first_name}"
                    else:
                        # 後方互換性：既存データはnameフィールドを使用
                        display_name = meta.get("name", "未設定")
                    
                    staff_list.append({
                        "name": display_name,
                        "id": u.id
                    })
                
                # 名前順でソート
                staff_list.sort(key=lambda x: x["name"])
            except Exception as e:
                print("❌ スタッフリスト取得エラー:", e)
                # エラー時は現在のスタッフのみ
                staff_list = [{"name": staff_name, "id": staff.get("id")}]
            
            return render_template("admin_reservations_edit.html", reservation=reservation, staff_list=staff_list)
        except Exception as e:
            print("❌ 予約編集画面取得エラー:", e)
            flash("予約編集画面の取得に失敗しました", "error")
            return redirect("/admin/reservations")
    
    # POST処理
    try:
        # 既存の予約情報を取得（重複チェック用）
        res_existing = supabase_admin.table("reservations").select("*").eq("id", reservation_id).execute()
        if not res_existing.data:
            flash("予約が見つかりません", "error")
            return redirect("/admin/reservations")
        existing_reservation = res_existing.data[0]
        
        # 日時取得（datetime-local形式）
        reserved_at_str = request.form.get("reserved_at", "").strip()
        if not reserved_at_str:
            flash("予約日時を入力してください", "error")
            return redirect(f"/admin/reservations/{reservation_id}/edit")
        
        # datetime-local形式をISO形式に変換
        try:
            dt_naive = datetime.strptime(reserved_at_str, "%Y-%m-%dT%H:%M")
            dt_jst = dt_naive.replace(tzinfo=JST)
            reserved_at_iso = dt_jst.isoformat()
        except Exception as e:
            flash("予約日時の形式が正しくありません", "error")
            return redirect(f"/admin/reservations/{reservation_id}/edit")
        
        place_type = request.form.get("place_type", "").strip()
        if place_type not in ["in_house", "visit", "field"]:
            flash("現場区分を選択してください", "error")
            return redirect(f"/admin/reservations/{reservation_id}/edit")
        
        place_name = request.form.get("place_name", "").strip() or None
        staff_name = request.form.get("staff_name", "").strip() or None
        
        # エリア取得
        area = request.form.get("area", "").strip() or None
        if area and area not in ["tokyo", "fukuoka"]:
            area = None
        
        # メニュー取得（施術時間を決定）
        menu = request.form.get("menu", "").strip()
        duration_minutes = existing_reservation.get("duration_minutes", 90)  # 既存値またはデフォルト
        if menu:
            if menu == "other":
                # 「その他」の場合は既存のduration_minutesを維持（またはデフォルト90分）
                duration_minutes = existing_reservation.get("duration_minutes", 90)
            else:
                # メニューから施術時間を取得（60/90/120など）
                try:
                    duration_minutes = int(menu)
                except:
                    duration_minutes = existing_reservation.get("duration_minutes", 90)
        
        # 指名タイプ取得（日本語値：'本指名','枠指名','希望','フリー'）
        nomination_type = request.form.get("nomination_type", "本指名").strip()
        # 英語値から日本語値への変換（後方互換性のため）
        nomination_type_map = {"main": "本指名", "frame": "枠指名", "hope": "希望", "free": "フリー"}
        if nomination_type in nomination_type_map:
            nomination_type = nomination_type_map[nomination_type]
        # 有効な値でない場合はデフォルト値
        if nomination_type not in ["本指名", "枠指名", "希望", "フリー"]:
            nomination_type = "本指名"
        
        # 枠指名スタッフID取得（全スタッフ選択可能）
        nominated_staff_ids = []
        nomination_priority = None
        if nomination_type == "枠指名":
            # フォームから全てのframe_staff_*を取得（数に制限なし）
            i = 1
            while True:
                frame_staff = request.form.get(f"frame_staff_{i}", "").strip()
                if not frame_staff:
                    break
                frame_priority = request.form.get(f"frame_priority_{i}", "").strip()
                nominated_staff_ids.append(frame_staff)
                if frame_priority:
                    try:
                        priority_int = int(frame_priority)
                        if not nomination_priority or priority_int < nomination_priority:
                            nomination_priority = priority_int
                    except:
                        pass
                i += 1
        
        # 価格取得
        base_price_str = request.form.get("base_price", "").strip()
        try:
            base_price = int(base_price_str) if base_price_str else None
        except:
            base_price = None
        
        # 選択されたメニュー取得（複数選択可）
        selected_menus = request.form.getlist("selected_menus")
        
        # 指名料取得
        nomination_fee_str = request.form.get("nomination_fee", "0").strip()
        try:
            nomination_fee = int(nomination_fee_str) if nomination_fee_str else 0
        except:
            nomination_fee = 0
        
        # 割引取得
        discount_str = request.form.get("discount", "0").strip()
        try:
            discount = int(discount_str) if discount_str else 0
        except:
            discount = 0
        
        # 出張費取得
        transportation_fee_str = request.form.get("transportation_fee", "0").strip()
        transportation_fee_other_str = request.form.get("transportation_fee_other", "0").strip()
        try:
            if transportation_fee_str == "other":
                transportation_fee = int(transportation_fee_other_str) if transportation_fee_other_str else 0
            else:
                transportation_fee = int(transportation_fee_str) if transportation_fee_str else 0
        except:
            transportation_fee = 0
        
        # 消費税取得
        tax_str = request.form.get("tax", "0").strip()
        try:
            tax = int(tax_str) if tax_str else 0
        except:
            # 消費税が未入力の場合は自動計算 料金 × 0.1（指名料と出張費にはかからない）
            if base_price:
                tax = int((base_price or 0) * 0.1)
            else:
                tax = 0
        
        status = request.form.get("status", "").strip()
        if status not in ["reserved", "visited", "completed", "canceled"]:
            flash("無効なステータスです", "error")
            return redirect(f"/admin/reservations/{reservation_id}/edit")
        
        memo = request.form.get("memo", "").strip() or None
        
        # 予約重複チェック（同一スタッフ × 時間帯が被る場合）
        # 予約終了時刻を計算
        reserved_end = dt_jst + timedelta(minutes=duration_minutes)
        reserved_end_iso = reserved_end.isoformat()
        
        # 重複チェック：同じスタッフで、時間帯が被る予約を検索
        # 自分自身の予約は除外
        query = supabase_admin.table("reservations").select("id, reserved_at, duration_minutes, staff_name, patient_id").eq("staff_name", staff_name).neq("id", reservation_id)
        
        # キャンセル済みは除外
        query = query.neq("status", "canceled")
        
        # 時間帯が被る予約を検索
        # 条件：新しい予約の開始時刻 < 既存予約の終了時刻 AND 新しい予約の終了時刻 > 既存予約の開始時刻
        res_overlapping = query.execute()
        overlapping_reservations = []
        
        if res_overlapping.data:
            for other_res in res_overlapping.data:
                try:
                    other_start_str = other_res.get("reserved_at", "")
                    other_duration = other_res.get("duration_minutes", 60)
                    if other_start_str:
                        other_start = datetime.fromisoformat(other_start_str.replace("Z", "+00:00")).astimezone(JST)
                        other_end = other_start + timedelta(minutes=other_duration)
                        
                        # 時間帯が被るかチェック
                        if dt_jst < other_end and reserved_end > other_start:
                            overlapping_reservations.append(other_res)
                except:
                    pass
        
        if overlapping_reservations:
            # 重複している予約の情報を取得
            patient_ids = [r.get("patient_id") for r in overlapping_reservations if r.get("patient_id")]
            patient_map = {}
            if patient_ids:
                res_patients = supabase_admin.table("patients").select("id, last_name, first_name, name").in_("id", patient_ids).execute()
                if res_patients.data:
                    for p in res_patients.data:
                        name = f"{p.get('last_name', '')} {p.get('first_name', '')}".strip()
                        patient_map[p["id"]] = name or p.get("name", "不明")
            
            # エラーメッセージを作成
            conflict_details = []
            for conflict in overlapping_reservations:
                conflict_start = datetime.fromisoformat(conflict.get("reserved_at", "").replace("Z", "+00:00")).astimezone(JST)
                conflict_patient_name = patient_map.get(conflict.get("patient_id"), "不明")
                conflict_details.append(f"{conflict_start.strftime('%Y-%m-%d %H:%M')} - {conflict_patient_name}")
            
            flash(f"予約が重複しています。同じスタッフの以下の予約と時間帯が被っています：\n" + "\n".join(conflict_details), "error")
            return redirect(f"/admin/reservations/{reservation_id}/edit")
        
        # 予約更新
        update_data = {
            "reserved_at": reserved_at_iso,
            "duration_minutes": duration_minutes,
            "place_type": place_type,
            "place_name": place_name,
            "staff_name": staff_name,
            "area": area,
            "nomination_type": nomination_type,
            "nominated_staff_ids": nominated_staff_ids or [],
            "nomination_priority": nomination_priority,
            "base_price": base_price,
            "selected_menus": selected_menus,
            "nomination_fee": nomination_fee,
            "discount": discount,
            "transportation_fee": transportation_fee,
            "tax": tax,
            "status": status,
            "memo": memo,
            "updated_at": now_iso()
        }
        
        supabase_admin.table("reservations").update(update_data).eq("id", reservation_id).execute()
        
        # 予約更新時に日報データも連動更新（base_price、course_name、nomination_type）
        try:
            # この予約に関連する日報患者情報を取得
            res_patients = supabase_admin.table("staff_daily_report_patients").select("*").eq("reservation_id", reservation_id).execute()
            if res_patients.data:
                # コース名を生成（予約完了時と同じロジック）
                course_name = None
                place_type_label = {"in_house": "院内", "visit": "往診", "field": "帯同"}.get(place_type, "")
                
                # 表記ルール：本指名（院内）、枠指名（帯同）の形式
                if nomination_type in ["本指名", "枠指名"]:
                    course_name = f"{nomination_type}（{place_type_label}）"
                else:
                    # 希望/フリーの場合はエリア＋時間
                    if area and duration_minutes:
                        area_label = "東京" if area == "tokyo" else "福岡" if area == "fukuoka" else ""
                        course_name = f"{area_label} {duration_minutes}分コース"
                    else:
                        course_name = f"{nomination_type}（{place_type_label}）"
                
                # 日報患者情報を更新
                for patient_report in res_patients.data:
                    patient_update_data = {}
                    
                    # base_priceが変更された場合は金額を更新
                    if base_price is not None:
                        patient_update_data["amount"] = base_price
                    
                    # コース名を更新
                    if course_name:
                        patient_update_data["course_name"] = course_name
                    
                    if patient_update_data:
                        supabase_admin.table("staff_daily_report_patients").update(patient_update_data).eq("id", patient_report["id"]).execute()
                
                print(f"✅ 予約更新に伴い、日報データも更新しました: reservation_id={reservation_id}, base_price={base_price}, course_name={course_name}")
        except Exception as e:
            print(f"⚠️ WARNING - 予約更新時の日報データ同期エラー: {e}")
            # エラーが発生しても予約更新は成功しているので警告のみ
        
        flash("予約を更新しました（日報データにも反映済み）", "success")
        
        # 予約日付にリダイレクト
        day_str = dt_jst.strftime("%Y-%m-%d")
        ym_str = dt_jst.strftime("%Y-%m")
        return redirect(f"/admin/reservations?ym={ym_str}&day={day_str}")
    except Exception as e:
        import traceback
        print("❌ 予約更新エラー:", e)
        print("❌ トレースバック:", traceback.format_exc())
        flash(f"予約の更新に失敗しました: {str(e)}", "error")
        return redirect(f"/admin/reservations/{reservation_id}/edit")


@app.route("/admin/reservations/<reservation_id>/delete", methods=["POST"])
@staff_required
def admin_reservations_delete(reservation_id):
    """予約削除"""
    try:
        # 予約を削除
        # 注意: データベースのCASCADE設定により、staff_daily_report_patientsからも自動的に削除される
        # 現在の設定が ON DELETE SET NULL の場合は、明示的に削除する必要がある
        # ON DELETE CASCADE に変更した場合は、以下の明示的な削除処理は不要（データベースが自動削除）
        try:
            # 念のため、削除前に確認（ログ用）
            res_patients = supabase_admin.table("staff_daily_report_patients").select("id", count="exact").eq("reservation_id", reservation_id).execute()
            patient_count = res_patients.count or 0
            if patient_count > 0:
                # データベースが ON DELETE SET NULL の場合、明示的に削除
                # ON DELETE CASCADE の場合は、予約削除時に自動的に削除されるため不要
                supabase_admin.table("staff_daily_report_patients").delete().eq("reservation_id", reservation_id).execute()
                print(f"✅ 日報から予約ID {reservation_id} に関連する患者情報 {patient_count} 件を削除しました")
        except Exception as e:
            print(f"⚠️ WARNING - 日報患者情報削除エラー: {e}")
            # エラーが発生しても予約削除は続行（CASCADE設定があれば自動削除される）
        
        # 予約を削除（CASCADE設定により、staff_daily_report_patientsからも自動削除される）
        supabase_admin.table("reservations").delete().eq("id", reservation_id).execute()
        flash("予約を削除しました（日報からも削除済み）", "success")
        return redirect(request.referrer or "/admin/reservations")
    except Exception as e:
        print("❌ 予約削除エラー:", e)
        flash("予約の削除に失敗しました", "error")
        return redirect("/admin/reservations")


# ===================================================
# スタッフ日報管理
# ===================================================
@app.route("/staff/daily-report/new", methods=["GET", "POST"])
@staff_required
def staff_daily_report_new():
    """スタッフ用日報作成（1日1枚＋複数勤務カード）"""
    if request.method == "GET":
        # ログイン中のスタッフ情報を取得
        staff = session.get("staff", {})
        staff_name = staff.get("name", "スタッフ")
        today_date = request.args.get("date", datetime.now(JST).strftime("%Y-%m-%d"))
        
        # 選択された日付の既存日報を取得
        existing_report = None
        existing_items = []
        try:
            res_existing = supabase_admin.table("staff_daily_reports").select("*").eq("staff_name", staff_name).eq("report_date", today_date).execute()
            if res_existing.data:
                existing_report = res_existing.data[0]
                report_id = existing_report["id"]
                res_items = supabase_admin.table("staff_daily_report_items").select("*").eq("daily_report_id", report_id).order("created_at", desc=False).execute()
                existing_items = res_items.data or []
                
                # 各勤務カードに紐づく患者情報を取得（予約完了時に追加された患者情報）
                if existing_items:
                    item_ids = [item["id"] for item in existing_items]
                    try:
                        res_patients = supabase_admin.table("staff_daily_report_patients").select("*").in_("item_id", item_ids).execute()
                        patients_data = res_patients.data or []
                        
                        # 患者IDと予約IDを収集
                        patient_ids = [p.get("patient_id") for p in patients_data if p.get("patient_id")]
                        reservation_ids = [p.get("reservation_id") for p in patients_data if p.get("reservation_id")]
                        
                        # 患者情報を一括取得
                        patients_info_map = {}
                        if patient_ids:
                            try:
                                res_patients_info = supabase_admin.table("patients").select("id, last_name, first_name, name").in_("id", patient_ids).execute()
                                if res_patients_info.data:
                                    for p_info in res_patients_info.data:
                                        p_id = p_info.get("id")
                                        # 姓名を結合（姓名分離フィールド優先、なければnameフィールド）
                                        last_name = p_info.get("last_name", "")
                                        first_name = p_info.get("first_name", "")
                                        if last_name or first_name:
                                            patients_info_map[p_id] = f"{last_name} {first_name}".strip()
                                        else:
                                            patients_info_map[p_id] = p_info.get("name", "患者不明")
                            except Exception as e:
                                print(f"⚠️ WARNING - 患者情報取得エラー: {e}")
                        
                        # 予約情報を一括取得（duration_minutesとstatusを取得するため）
                        reservations_info_map = {}
                        reservations_status_map = {}
                        invalid_reservation_ids = []
                        if reservation_ids:
                            try:
                                res_reservations_info = supabase_admin.table("reservations").select("id, duration_minutes, status").in_("id", reservation_ids).execute()
                                if res_reservations_info.data:
                                    for r_info in res_reservations_info.data:
                                        r_id = r_info.get("id")
                                        reservations_info_map[r_id] = r_info.get("duration_minutes")
                                        reservations_status_map[r_id] = r_info.get("status")
                                # 存在しない予約IDを収集（予約が削除された場合）
                                found_reservation_ids = {r_info.get("id") for r_info in res_reservations_info.data}
                                invalid_reservation_ids = [rid for rid in reservation_ids if rid not in found_reservation_ids]
                            except Exception as e:
                                print(f"⚠️ WARNING - 予約情報取得エラー: {e}")
                        
                        # 予約が存在しない、または完了状態でない場合は日報から削除
                        if reservation_ids:
                            try:
                                # 完了状態でない予約IDを収集
                                invalid_reservation_ids.extend([
                                    rid for rid in reservation_ids 
                                    if rid in reservations_status_map and reservations_status_map[rid] != "completed"
                                ])
                                
                                # 無効な予約に関連する日報患者情報を削除
                                if invalid_reservation_ids:
                                    supabase_admin.table("staff_daily_report_patients").delete().in_("reservation_id", invalid_reservation_ids).execute()
                                    print(f"✅ 無効な予約に関連する日報患者情報を削除しました: {len(invalid_reservation_ids)}件")
                                    # 削除後、患者データからも除外
                                    patients_data = [p for p in patients_data if p.get("reservation_id") not in invalid_reservation_ids]
                            except Exception as e:
                                print(f"⚠️ WARNING - 無効な予約の日報患者情報削除エラー: {e}")
                        
                        # 患者情報をitem_idごとにグループ化
                        patients_map = {}
                        for patient in patients_data:
                            item_id = patient.get("item_id")
                            if item_id not in patients_map:
                                patients_map[item_id] = []
                            # 患者姓名を追加
                            patient_id = patient.get("patient_id")
                            patient["patient_name"] = patients_info_map.get(patient_id, "患者不明")
                            
                            # コース名に時間を追加（duration_minutesがある場合）
                            reservation_id = patient.get("reservation_id")
                            duration = reservations_info_map.get(reservation_id)
                            course_name = patient.get("course_name", "")
                            if duration and course_name:
                                # コース名の形式を変更（例：「60分　本指名（往診）」）
                                if "（" in course_name:
                                    # 既に括弧がある場合は、時間を前に追加
                                    patient["course_name_display"] = f"{duration}分　{course_name}"
                                else:
                                    patient["course_name_display"] = f"{duration}分　{course_name}"
                            else:
                                patient["course_name_display"] = course_name
                            
                            patients_map[item_id].append(patient)
                        
                        # 各勤務カードに患者情報を追加
                        for item in existing_items:
                            item_id = item.get("id")
                            item["patients"] = patients_map.get(item_id, [])
                    except Exception as e:
                        print(f"⚠️ WARNING - 患者情報取得エラー: {e}")
                        # エラーが発生しても処理を続行（患者情報なしとして扱う）
                        for item in existing_items:
                            item["patients"] = []
        except:
            pass
        
        # 実働時間計算
        now_jst = datetime.now(JST)
        
        # 今週の開始日（月曜日）
        week_start = now_jst - timedelta(days=now_jst.weekday())
        week_start_date = week_start.date()
        
        # 今週の実働時間を計算
        weekly_hours = 0
        try:
            res_weekly_reports = supabase_admin.table("staff_daily_reports").select("id").eq("staff_name", staff_name).gte("report_date", week_start_date.strftime("%Y-%m-%d")).lte("report_date", now_jst.strftime("%Y-%m-%d")).execute()
            report_ids = [r["id"] for r in res_weekly_reports.data] if res_weekly_reports.data else []
            if report_ids:
                res_weekly_items = supabase_admin.table("staff_daily_report_items").select("start_time, end_time, break_minutes").in_("daily_report_id", report_ids).execute()
                if res_weekly_items.data:
                    for item in res_weekly_items.data:
                        start = item.get("start_time")
                        end = item.get("end_time")
                        break_mins = item.get("break_minutes", 0) or 0
                        if start and end:
                            try:
                                # time型をdatetimeに変換して計算
                                start_parts = str(start).split(":")
                                end_parts = str(end).split(":")
                                start_dt = datetime(2000, 1, 1, int(start_parts[0]), int(start_parts[1]))
                                end_dt = datetime(2000, 1, 1, int(end_parts[0]), int(end_parts[1]))
                                if end_dt < start_dt:
                                    end_dt += timedelta(days=1)
                                diff = end_dt - start_dt
                                hours = diff.total_seconds() / 3600 - (break_mins / 60)
                                weekly_hours += max(0, hours)
                            except:
                                pass
        except:
            weekly_hours = 0
        
        # 週目標時間40h（その週の実働時間 - 40h）
        # 例：42h実働した場合は +2時間
        target_hours = 40
        diff_hours = weekly_hours - target_hours
        
        # 日報作成初日を取得
        first_report_date = None
        try:
            res_first = supabase_admin.table("staff_daily_reports").select("report_date").eq("staff_name", staff_name).order("report_date", desc=False).limit(1).execute()
            if res_first.data:
                first_report_date = datetime.strptime(res_first.data[0]["report_date"], "%Y-%m-%d").date()
        except:
            pass
        
        # 累積実働時間を計算（全期間）
        total_hours = 0
        try:
            res_all_reports = supabase_admin.table("staff_daily_reports").select("id").eq("staff_name", staff_name).execute()
            report_ids = [r["id"] for r in res_all_reports.data] if res_all_reports.data else []
            if report_ids:
                res_all_items = supabase_admin.table("staff_daily_report_items").select("start_time, end_time, break_minutes").in_("daily_report_id", report_ids).execute()
                if res_all_items.data:
                    for item in res_all_items.data:
                        start = item.get("start_time")
                        end = item.get("end_time")
                        break_mins = item.get("break_minutes", 0) or 0
                        if start and end:
                            try:
                                start_parts = str(start).split(":")
                                end_parts = str(end).split(":")
                                start_dt = datetime(2000, 1, 1, int(start_parts[0]), int(start_parts[1]))
                                end_dt = datetime(2000, 1, 1, int(end_parts[0]), int(end_parts[1]))
                                if end_dt < start_dt:
                                    end_dt += timedelta(days=1)
                                diff = end_dt - start_dt
                                hours = diff.total_seconds() / 3600 - (break_mins / 60)
                                total_hours += max(0, hours)
                            except:
                                pass
        except:
            total_hours = 0
        
        # 過不足計算：日報作成初日の週から今日の週まで、毎週40hずつ目標とする
        # 累計実働時間 - (週数 × 40h)
        # 例：4週間経ったタイミングで、ノルマは160h。本人が154h実働していたとしたら-6時間
        if first_report_date:
            # 初日の週の月曜日を取得
            first_report_datetime = datetime.combine(first_report_date, datetime.min.time())
            first_weekday = first_report_datetime.weekday()  # 0=月曜日
            first_week_monday = first_report_datetime - timedelta(days=first_weekday)
            
            # 今日の週の月曜日を取得
            today_weekday = now_jst.weekday()  # 0=月曜日
            today_week_monday = now_jst - timedelta(days=today_weekday)
            
            # 週数を計算（初日の週から今日の週まで、今日の週も含む）
            days_diff = (today_week_monday.date() - first_week_monday.date()).days
            weeks_passed = max(1, (days_diff // 7) + 1)  # 最低1週（初日の週）
            
            target_total_hours = weeks_passed * 40
            weekly_hours_diff = total_hours - target_total_hours
        else:
            # 初日がない場合は0
            weekly_hours_diff = 0
        
        # 管理者チェック
        staff = session.get("staff", {})
        is_admin = staff.get("is_admin") == True
        
        # 交通費情報を取得（既存の日報がある場合）
        transportations = []
        if existing_report:
            try:
                res_transportations = supabase_admin.table("staff_daily_report_transportations").select("*").eq("daily_report_id", existing_report["id"]).execute()
                transportations = res_transportations.data or []
            except Exception as e:
                print(f"⚠️ WARNING - 交通費情報取得エラー: {e}")
                transportations = []
        
        return render_template(
            "staff_daily_report_new.html",
            staff_name=staff_name,
            today_date=today_date,
            existing_report=existing_report,
            existing_items=existing_items,
            transportations=transportations,
            weekly_hours=round(weekly_hours, 1),
            diff_hours=round(diff_hours, 1),
            weekly_hours_diff=round(weekly_hours_diff, 1),
            is_admin=is_admin
        )
    
    # POST処理
    try:
        staff = session.get("staff", {})
        staff_name = staff.get("name", "スタッフ")
        
        # 日報基本情報
        report_date = request.form.get("report_date", "").strip()
        
        # バリデーション
        if not report_date:
            flash("日付を入力してください", "error")
            return redirect(f"/staff/daily-report/new?date={report_date}")
        
        # 本日のシフト（memo）を取得
        report_memo = request.form.get("report_memo", "").strip() or None
        
        # 当日の日報が既に存在するかチェック
        res_existing = supabase_admin.table("staff_daily_reports").select("*").eq("staff_name", staff_name).eq("report_date", report_date).execute()
        
        if res_existing.data:
            # 既存の日報を更新（memoとupdated_atを更新）
            report_id = res_existing.data[0]["id"]
            supabase_admin.table("staff_daily_reports").update({
                "memo": report_memo,
                "updated_at": now_iso()
            }).eq("id", report_id).execute()
        else:
            # 新規日報を作成
            # week_keyを計算（YYYY-WW形式、ISO週番号を使用）
            report_date_obj = datetime.strptime(report_date, "%Y-%m-%d")
            iso_calendar = report_date_obj.isocalendar()
            week_key = f"{iso_calendar[0]}-{iso_calendar[1]:02d}"
            
            report_data = {
                "staff_name": staff_name,
                "report_date": report_date,
                "week_key": week_key,
                "memo": report_memo,
                "created_at": now_iso(),
                "updated_at": now_iso()
            }
            res_new_report = supabase_admin.table("staff_daily_reports").insert(report_data).execute()
            if not res_new_report.data:
                flash("日報の作成に失敗しました", "error")
                return redirect(f"/staff/daily-report/new?date={report_date}")
            report_id = res_new_report.data[0]["id"]
        
        # 勤務カードを取得（work_type_1, start_time_1, ... の形式）
        work_cards = []
        card_index = 1
        while True:
            work_type = request.form.get(f"work_type_{card_index}", "").strip()
            if not work_type:
                break
            
            if work_type not in ["in_house", "visit", "field"]:
                card_index += 1
                continue
            
            start_time = request.form.get(f"start_time_{card_index}", "").strip() or None
            end_time = request.form.get(f"end_time_{card_index}", "").strip() or None
            break_minutes_str = request.form.get(f"break_minutes_{card_index}", "0").strip()
            session_count_str = request.form.get(f"session_count_{card_index}", "0").strip()
            memo = request.form.get(f"memo_{card_index}", "").strip() or None
            
            try:
                break_minutes_int = int(break_minutes_str) if break_minutes_str else 0
            except:
                break_minutes_int = 0
            
            try:
                session_count_int = int(session_count_str) if session_count_str else 0
            except:
                session_count_int = 0
            
            work_cards.append({
                "work_type": work_type,
                "start_time": start_time,
                "end_time": end_time,
                "break_minutes": break_minutes_int,
                "session_count": session_count_int,
                "memo": memo
            })
            card_index += 1
        
        # 勤務カードが0枚でも保存可能（勤務していない日の場合）
        # 既存の勤務カードと患者情報を取得（削除前に保存）
        existing_patients_data = []
        try:
            # 既存の勤務カードを取得
            res_existing_items = supabase_admin.table("staff_daily_report_items").select("*").eq("daily_report_id", report_id).order("created_at", desc=False).execute()
            existing_items = res_existing_items.data or []
            
            if existing_items:
                existing_item_ids = [item["id"] for item in existing_items]
                # 既存の患者情報を取得
                res_existing_patients = supabase_admin.table("staff_daily_report_patients").select("*").in_("item_id", existing_item_ids).execute()
                existing_patients_data = res_existing_patients.data or []
                
                # 既存のitem_idとインデックスのマッピングを作成（順序を保持）
                existing_item_id_to_index = {item["id"]: idx for idx, item in enumerate(existing_items)}
                # 患者情報にインデックスを追加
                for patient_data in existing_patients_data:
                    old_item_id = patient_data.get("item_id")
                    patient_data["_old_item_index"] = existing_item_id_to_index.get(old_item_id, -1)
        except Exception as e:
            print(f"⚠️ WARNING - 既存患者情報取得エラー: {e}")
            existing_patients_data = []
        
        # 既存の勤務カードを削除（再作成のため、CASCADEで患者情報も削除される）
        supabase_admin.table("staff_daily_report_items").delete().eq("daily_report_id", report_id).execute()
        
        # 勤務カードを挿入（勤務カードが0枚の場合は何も挿入しない）
        new_item_ids = []
        for card in work_cards:
            item_data = {
                "daily_report_id": report_id,
                "work_type": card["work_type"],
                "start_time": card["start_time"],
                "end_time": card["end_time"],
                "break_minutes": card["break_minutes"],
                "session_count": card.get("session_count", 0),
                "memo": card["memo"],
                "created_at": now_iso()
            }
            res_new_item = supabase_admin.table("staff_daily_report_items").insert(item_data).execute()
            if res_new_item.data:
                new_item_ids.append(res_new_item.data[0]["id"])
        
        # 既存の患者情報を新しいitem_idに再マッピング（インデックス順で対応）
        if existing_patients_data and new_item_ids:
            for patient_data in existing_patients_data:
                old_index = patient_data.get("_old_item_index", -1)
                # インデックスが有効で、新しいitem_idが存在する場合
                if 0 <= old_index < len(new_item_ids):
                    new_item_id = new_item_ids[old_index]
                    # 新しいitem_idで患者情報を再作成
                    patient_insert_data = {
                        "item_id": new_item_id,
                        "patient_id": patient_data.get("patient_id"),
                        "reservation_id": patient_data.get("reservation_id"),
                        "course_name": patient_data.get("course_name"),
                        "amount": patient_data.get("amount"),
                        "memo": patient_data.get("memo"),
                        "created_at": now_iso()  # 新しい作成日時を設定
                    }
                    try:
                        supabase_admin.table("staff_daily_report_patients").insert(patient_insert_data).execute()
                    except Exception as e:
                        print(f"⚠️ WARNING - 患者情報再作成エラー: {e}")
        
        # 交通費情報を保存
        staff_id = staff.get("id")
        if staff_id:
            try:
                # 既存の交通費を削除（再作成のため）
                if res_existing.data:
                    supabase_admin.table("staff_daily_report_transportations").delete().eq("daily_report_id", report_id).execute()
                
                # 交通費を取得（transport_type_1, route_1, amount_1, memo_1 の形式）
                transport_index = 1
                while True:
                    transport_type = request.form.get(f"transport_type_{transport_index}", "").strip()
                    if not transport_type:
                        break
                    
                    route = request.form.get(f"route_{transport_index}", "").strip() or None
                    amount_str = request.form.get(f"amount_{transport_index}", "0").strip()
                    memo = request.form.get(f"memo_{transport_index}", "").strip() or None
                    
                    try:
                        amount_int = int(amount_str) if amount_str else 0
                    except:
                        amount_int = 0
                    
                    if amount_int > 0:
                        transportation_data = {
                            "daily_report_id": report_id,
                            "staff_id": staff_id,
                            "date": report_date,
                            "transport_type": transport_type,
                            "route": route,
                            "amount": amount_int,
                            "memo": memo,
                            "created_at": now_iso()
                        }
                        supabase_admin.table("staff_daily_report_transportations").insert(transportation_data).execute()
                    
                    transport_index += 1
            except Exception as e:
                print(f"⚠️ WARNING - 交通費保存エラー: {e}")
        
        flash("日報を登録しました", "success")
        return redirect(f"/staff/daily-report/new?date={report_date}")
    except Exception as e:
        import traceback
        print(f"❌ 日報作成エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash(f"日報の登録に失敗しました: {str(e)}", "error")
        # エラー時も日付パラメータを保持
        report_date = request.form.get("report_date", "").strip()
        if report_date:
            return redirect(f"/staff/daily-report/new?date={report_date}")
        else:
            return redirect("/staff/daily-report/new")


@app.route("/staff/daily-reports/years")
@staff_required
def staff_daily_reports_years():
    """スタッフ用：年一覧ページ"""
    try:
        staff = session.get("staff", {})
        staff_name = staff.get("name", "スタッフ")
        
        # 日報が存在する年を取得
        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").eq("staff_name", staff_name).order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        # 年を抽出して重複を除去
        years_set = set()
        for report in reports:
            report_date = report.get("report_date")
            if report_date:
                year = report_date[:4]  # YYYY-MM-DDから年を抽出
                years_set.add(year)
        
        years_list = sorted(years_set, reverse=True)  # 新しい年から順に
        
        return render_template("staff_daily_reports_years.html", years=years_list, staff_name=staff_name)
    except Exception as e:
        print(f"❌ 年一覧取得エラー: {e}")
        flash("年一覧の取得に失敗しました", "error")
        return redirect("/staff/profile")


@app.route("/staff/daily-reports/years/<year>")
@staff_required
def staff_daily_reports_months(year):
    """スタッフ用：月一覧ページ"""
    try:
        staff = session.get("staff", {})
        staff_name = staff.get("name", "スタッフ")
        
        # 指定年の日報が存在する月を取得
        year_start = f"{year}-01-01"
        year_end = f"{year}-12-31"
        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").eq("staff_name", staff_name).gte("report_date", year_start).lte("report_date", year_end).order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        # 月を抽出して重複を除去
        months_set = set()
        for report in reports:
            report_date = report.get("report_date")
            if report_date:
                month = report_date[5:7]  # YYYY-MM-DDから月を抽出
                months_set.add(month)
        
        months_list = sorted(months_set, reverse=True)  # 新しい月から順に
        
        # 月の日本語名をマッピング
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        
        months_with_names = [(m, month_names.get(m, m)) for m in months_list]
        
        return render_template("staff_daily_reports_months.html", year=year, months=months_with_names, staff_name=staff_name)
    except Exception as e:
        print(f"❌ 月一覧取得エラー: {e}")
        flash("月一覧の取得に失敗しました", "error")
        return redirect("/staff/daily-reports/years")


@app.route("/staff/daily-reports/years/<year>/months/<month>")
@staff_required
def staff_daily_reports_list(year, month):
    """スタッフ用：日報一覧ページ（指定年月）"""
    try:
        staff = session.get("staff", {})
        staff_name = staff.get("name", "スタッフ")
        
        # 指定年月の日報を取得
        month_start = f"{year}-{month}-01"
        # 月末日を計算
        if month in ["01", "03", "05", "07", "08", "10", "12"]:
            month_end = f"{year}-{month}-31"
        elif month in ["04", "06", "09", "11"]:
            month_end = f"{year}-{month}-30"
        else:  # 2月
            # うるう年判定（簡易版）
            year_int = int(year)
            if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                month_end = f"{year}-{month}-29"
            else:
                month_end = f"{year}-{month}-28"
        
        res_reports = supabase_admin.table("staff_daily_reports").select("*").eq("staff_name", staff_name).gte("report_date", month_start).lte("report_date", month_end).order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        # 各日報の勤務カードを取得
        report_ids = [r["id"] for r in reports]
        items_map = {}
        patients_map = {}
        
        if report_ids:
            # 勤務カードを一括取得
            res_items = supabase_admin.table("staff_daily_report_items").select("*").in_("daily_report_id", report_ids).order("created_at", desc=False).execute()
            items = res_items.data or []
            
            # report_idごとにグループ化
            for item in items:
                report_id = item.get("daily_report_id")
                if report_id not in items_map:
                    items_map[report_id] = []
                items_map[report_id].append(item)
            
            # 患者・売上明細を一括取得
            item_ids = [item["id"] for item in items]
            patients = []
            patient_map = {}
            if item_ids:
                try:
                    res_patients = supabase_admin.table("staff_daily_report_patients").select("*").in_("item_id", item_ids).execute()
                    patients = res_patients.data or []
                    
                    # 患者情報を一括取得（名前表示用）
                    patient_ids_from_reports = [p.get("patient_id") for p in patients if p.get("patient_id")]
                    if patient_ids_from_reports:
                        res_patient_names = supabase_admin.table("patients").select("id, last_name, first_name, name").in_("id", patient_ids_from_reports).execute()
                        if res_patient_names.data:
                            for p in res_patient_names.data:
                                name = f"{p.get('last_name', '')} {p.get('first_name', '')}".strip()
                                patient_map[p["id"]] = name or p.get("name", "患者不明")
                    
                    # item_idごとにグループ化
                    for patient in patients:
                        item_id = patient.get("item_id")
                        if item_id not in patients_map:
                            patients_map[item_id] = []
                        patient_name = patient_map.get(patient.get("patient_id"), "患者不明")
                        patient["patient_name"] = patient_name
                        patients_map[item_id].append(patient)
                except Exception as e:
                    print(f"⚠️ WARNING - 日報患者情報取得エラー（テーブルが存在しない可能性）: {e}")
                    patients = []
                    patient_map = {}
        
        # 日報に勤務カードと患者情報を結合
        for report in reports:
            report_id = report["id"]
            report["items"] = []
            
            if report_id in items_map:
                for item in items_map[report_id]:
                    item_id = item["id"]
                    item["patients"] = patients_map.get(item_id, [])
                    
                    # 時間表示用のフォーマット
                    if item.get("start_time"):
                        try:
                            start_time_str = item["start_time"]
                            if isinstance(start_time_str, str) and len(start_time_str) >= 5:
                                item["start_time_display"] = start_time_str[:5]
                        except:
                            item["start_time_display"] = None
                    else:
                        item["start_time_display"] = None
                    
                    if item.get("end_time"):
                        try:
                            end_time_str = item["end_time"]
                            if isinstance(end_time_str, str) and len(end_time_str) >= 5:
                                item["end_time_display"] = end_time_str[:5]
                        except:
                            item["end_time_display"] = None
                    else:
                        item["end_time_display"] = None
                    
                    report["items"].append(item)
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        month_name = month_names.get(month, month)
        
        return render_template("staff_daily_reports_list.html", year=year, month=month, month_name=month_name, reports=reports, staff_name=staff_name)
    except Exception as e:
        import traceback
        print(f"❌ 日報一覧取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("日報一覧の取得に失敗しました", "error")
        return redirect(f"/staff/daily-reports/years/{year}")


@app.route("/staff/transportations/years")
@staff_required
def staff_transportations_years():
    """スタッフ用：交通費申請 - 年一覧ページ"""
    try:
        staff = session.get("staff", {})
        staff_id = staff.get("id")
        
        # 交通費が存在する年を取得
        try:
            res_transportations = supabase_admin.table("staff_daily_report_transportations").select("date").eq("staff_id", staff_id).order("date", desc=True).execute()
            transportations = res_transportations.data or []
        except Exception as e:
            print(f"⚠️ WARNING - 交通費情報取得エラー: {e}")
            transportations = []
        
        # 年を抽出して重複を除去
        years_set = set()
        for trans in transportations:
            date = trans.get("date")
            if date:
                year = date[:4]  # YYYY-MM-DDから年を抽出
                years_set.add(year)
        
        years_list = sorted(years_set, reverse=True)  # 新しい年から順に
        
        return render_template("staff_transportations_years.html", years=years_list, staff_name=staff.get("name", "スタッフ"), staff_id=staff_id, is_admin=False)
    except Exception as e:
        print(f"❌ 交通費年一覧取得エラー: {e}")
        flash("年一覧の取得に失敗しました", "error")
        return redirect("/staff/profile")


@app.route("/staff/transportations/years/<year>")
@staff_required
def staff_transportations_months(year):
    """スタッフ用：交通費申請 - 月一覧ページ"""
    try:
        staff = session.get("staff", {})
        staff_id = staff.get("id")
        
        # 指定年の交通費が存在する月を取得
        year_start = f"{year}-01-01"
        year_end = f"{year}-12-31"
        try:
            res_transportations = supabase_admin.table("staff_daily_report_transportations").select("date").eq("staff_id", staff_id).gte("date", year_start).lte("date", year_end).order("date", desc=True).execute()
            transportations = res_transportations.data or []
        except Exception as e:
            print(f"⚠️ WARNING - 交通費情報取得エラー: {e}")
            transportations = []
        
        # 月を抽出して重複を除去
        months_set = set()
        for trans in transportations:
            date = trans.get("date")
            if date:
                month = date[5:7]  # YYYY-MM-DDから月を抽出
                months_set.add(month)
        
        months_list = sorted(months_set, reverse=True)  # 新しい月から順に
        
        # 月の日本語名をマッピング
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        
        months_with_names = [(m, month_names.get(m, m)) for m in months_list]
        
        return render_template("staff_transportations_months.html", year=year, months=months_with_names, staff_name=staff.get("name", "スタッフ"), staff_id=staff_id, is_admin=False)
    except Exception as e:
        print(f"❌ 交通費月一覧取得エラー: {e}")
        flash("月一覧の取得に失敗しました", "error")
        return redirect("/staff/transportations/years")


@app.route("/staff/transportations/years/<year>/months/<month>")
@staff_required
def staff_transportations_list(year, month):
    """スタッフ用：交通費申請 - 一覧ページ（指定年月）"""
    try:
        staff = session.get("staff", {})
        staff_id = staff.get("id")
        
        # 指定年月の交通費を取得
        month_start = f"{year}-{month}-01"
        # 月末日を計算
        if month in ["01", "03", "05", "07", "08", "10", "12"]:
            month_end = f"{year}-{month}-31"
        elif month in ["04", "06", "09", "11"]:
            month_end = f"{year}-{month}-30"
        else:  # 2月
            year_int = int(year)
            if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                month_end = f"{year}-{month}-29"
            else:
                month_end = f"{year}-{month}-28"
        
        try:
            res_transportations = supabase_admin.table("staff_daily_report_transportations").select("*").eq("staff_id", staff_id).gte("date", month_start).lte("date", month_end).order("date", desc=True).execute()
            transportations = res_transportations.data or []
        except Exception as e:
            print(f"⚠️ WARNING - 交通費情報取得エラー: {e}")
            transportations = []
        
        # 各交通費に対応する日報のmemo（本日のシフト）を取得
        daily_report_ids = list(set(t.get("daily_report_id") for t in transportations if t.get("daily_report_id")))
        daily_reports_map = {}
        if daily_report_ids:
            try:
                res_reports = supabase_admin.table("staff_daily_reports").select("id, memo").in_("id", daily_report_ids).execute()
                if res_reports.data:
                    for report in res_reports.data:
                        daily_reports_map[report["id"]] = report.get("memo") or ""
            except Exception as e:
                print(f"⚠️ WARNING - 日報情報取得エラー: {e}")
        
        # 交通費データに本日のシフトを追加
        for trans in transportations:
            daily_report_id = trans.get("daily_report_id")
            trans["shift_memo"] = daily_reports_map.get(daily_report_id, "") if daily_report_id else ""
        
        # 月合計を計算（Python側で集計）
        month_total = sum(t.get("amount", 0) or 0 for t in transportations)
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        month_name = month_names.get(month, month)
        
        return render_template("staff_transportations_list.html", year=year, month=month, month_name=month_name, transportations=transportations, month_total=month_total, staff_name=staff.get("name", "スタッフ"), staff_id=staff_id, is_admin=False)
    except Exception as e:
        import traceback
        print(f"❌ 交通費一覧取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("交通費一覧の取得に失敗しました", "error")
        return redirect(f"/staff/transportations/years/{year}")


# ===================================================
# 管理者用：スタッフの交通費申請閲覧
# ===================================================
@app.route("/admin/staff-reports/<staff_id>/transportations/years")
@admin_required
def admin_staff_transportations_years(staff_id):
    """管理者用：スタッフの交通費申請 - 年一覧ページ"""
    try:
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/staff-reports")
        
        meta = staff_user.user_metadata or {}
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # 交通費が存在する年を取得
        try:
            res_transportations = supabase_admin.table("staff_daily_report_transportations").select("date").eq("staff_id", staff_id).order("date", desc=True).execute()
            transportations = res_transportations.data or []
        except Exception as e:
            print(f"⚠️ WARNING - 交通費情報取得エラー: {e}")
            transportations = []
        
        # 年を抽出して重複を除去
        years_set = set()
        for trans in transportations:
            date = trans.get("date")
            if date:
                year = date[:4]  # YYYY-MM-DDから年を抽出
                years_set.add(year)
        
        years_list = sorted(years_set, reverse=True)  # 新しい年から順に
        
        return render_template("staff_transportations_years.html", years=years_list, staff_name=staff_name, staff_id=staff_id, is_admin=True)
    except Exception as e:
        print(f"❌ 交通費年一覧取得エラー: {e}")
        flash("年一覧の取得に失敗しました", "error")
        return redirect(f"/admin/staff-reports/{staff_id}/menu")


@app.route("/admin/staff-reports/<staff_id>/transportations/years/<year>")
@admin_required
def admin_staff_transportations_months(staff_id, year):
    """管理者用：スタッフの交通費申請 - 月一覧ページ"""
    try:
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/staff-reports")
        
        meta = staff_user.user_metadata or {}
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # 指定年の交通費が存在する月を取得
        year_start = f"{year}-01-01"
        year_end = f"{year}-12-31"
        try:
            res_transportations = supabase_admin.table("staff_daily_report_transportations").select("date").eq("staff_id", staff_id).gte("date", year_start).lte("date", year_end).order("date", desc=True).execute()
            transportations = res_transportations.data or []
        except Exception as e:
            print(f"⚠️ WARNING - 交通費情報取得エラー: {e}")
            transportations = []
        
        # 月を抽出して重複を除去
        months_set = set()
        for trans in transportations:
            date = trans.get("date")
            if date:
                month = date[5:7]  # YYYY-MM-DDから月を抽出
                months_set.add(month)
        
        months_list = sorted(months_set, reverse=True)  # 新しい月から順に
        
        # 月の日本語名をマッピング
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        
        months_with_names = [(m, month_names.get(m, m)) for m in months_list]
        
        return render_template("staff_transportations_months.html", year=year, months=months_with_names, staff_name=staff_name, staff_id=staff_id, is_admin=True)
    except Exception as e:
        print(f"❌ 交通費月一覧取得エラー: {e}")
        flash("月一覧の取得に失敗しました", "error")
        return redirect(f"/admin/staff-reports/{staff_id}/transportations/years")


@app.route("/admin/staff-reports/<staff_id>/transportations/years/<year>/months/<month>")
@admin_required
def admin_staff_transportations_list(staff_id, year, month):
    """管理者用：スタッフの交通費申請 - 一覧ページ（指定年月）"""
    try:
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/staff-reports")
        
        meta = staff_user.user_metadata or {}
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # 指定年月の交通費を取得
        month_start = f"{year}-{month}-01"
        # 月末日を計算
        if month in ["01", "03", "05", "07", "08", "10", "12"]:
            month_end = f"{year}-{month}-31"
        elif month in ["04", "06", "09", "11"]:
            month_end = f"{year}-{month}-30"
        else:  # 2月
            year_int = int(year)
            if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                month_end = f"{year}-{month}-29"
            else:
                month_end = f"{year}-{month}-28"
        
        try:
            res_transportations = supabase_admin.table("staff_daily_report_transportations").select("*").eq("staff_id", staff_id).gte("date", month_start).lte("date", month_end).order("date", desc=True).execute()
            transportations = res_transportations.data or []
        except Exception as e:
            print(f"⚠️ WARNING - 交通費情報取得エラー: {e}")
            transportations = []
        
        # 各交通費に対応する日報のmemo（本日のシフト）を取得
        daily_report_ids = list(set(t.get("daily_report_id") for t in transportations if t.get("daily_report_id")))
        daily_reports_map = {}
        if daily_report_ids:
            try:
                res_reports = supabase_admin.table("staff_daily_reports").select("id, memo").in_("id", daily_report_ids).execute()
                if res_reports.data:
                    for report in res_reports.data:
                        daily_reports_map[report["id"]] = report.get("memo") or ""
            except Exception as e:
                print(f"⚠️ WARNING - 日報情報取得エラー: {e}")
        
        # 交通費データに本日のシフトを追加
        for trans in transportations:
            daily_report_id = trans.get("daily_report_id")
            trans["shift_memo"] = daily_reports_map.get(daily_report_id, "") if daily_report_id else ""
        
        # 月合計を計算（Python側で集計）
        month_total = sum(t.get("amount", 0) or 0 for t in transportations)
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        month_name = month_names.get(month, month)
        
        return render_template("staff_transportations_list.html", year=year, month=month, month_name=month_name, transportations=transportations, month_total=month_total, staff_name=staff_name, staff_id=staff_id, is_admin=True)
    except Exception as e:
        import traceback
        print(f"❌ 交通費一覧取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("交通費一覧の取得に失敗しました", "error")
        return redirect(f"/admin/staff-reports/{staff_id}/transportations/years/{year}")


# ===================================================
# 月次売上一覧（管理者）
# ===================================================
@app.route("/admin/revenue")
@admin_required
def admin_revenue_index():
    """月次売上一覧のインデックス（年一覧にリダイレクト）"""
    return redirect("/admin/revenue/years")


@app.route("/admin/revenue/years")
@admin_required
def admin_revenue_years():
    """月次売上一覧 - 年選択"""
    try:
        # 日報が存在する年を取得（全スタッフ）
        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        years_set = set()
        for report in reports:
            report_date = report.get("report_date")
            if report_date:
                year = report_date[:4]
                years_set.add(year)
        
        years_list = sorted(years_set, reverse=True)
        
        return render_template("admin_revenue_years_new.html", years=years_list)
    except Exception as e:
        print(f"❌ 年一覧取得エラー: {e}")
        flash("年一覧の取得に失敗しました", "error")
        return redirect("/admin/dashboard")


@app.route("/admin/revenue/years/<year>/months")
@admin_required
def admin_revenue_months(year):
    """月次売上一覧 - 月選択"""
    try:
        # 指定年の日報が存在する月を取得（全スタッフ）
        year_start = f"{year}-01-01"
        year_end = f"{year}-12-31"
        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").gte("report_date", year_start).lte("report_date", year_end).order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        months_set = set()
        for report in reports:
            report_date = report.get("report_date")
            if report_date:
                month = report_date[5:7]
                months_set.add(month)
        
        months_list = sorted(months_set, reverse=True)

        # 年間売上（全体）を集計（work_type別内訳も取得）
        total_revenue = 0
        in_house_revenue = 0
        visit_revenue = 0
        field_revenue = 0
        try:
            res_reports_all = supabase_admin.table("staff_daily_reports").select("id").gte("report_date", year_start).lte("report_date", year_end).execute()
            report_ids = [r["id"] for r in (res_reports_all.data or [])]
            if report_ids:
                res_items = supabase_admin.table("staff_daily_report_items").select("id, work_type").in_("daily_report_id", report_ids).execute()
                items = res_items.data or []
                item_ids = [item["id"] for item in items]
                work_type_map = {item["id"]: item.get("work_type") for item in items if item.get("id")}
                if item_ids:
                    res_patients = supabase_admin.table("staff_daily_report_patients").select("amount, item_id").in_("item_id", item_ids).execute()
                    for patient in (res_patients.data or []):
                        amount = patient.get("amount", 0) or 0
                        total_revenue += amount
                        work_type = work_type_map.get(patient.get("item_id"))
                        if work_type == "in_house":
                            in_house_revenue += amount
                        elif work_type == "visit":
                            visit_revenue += amount
                        elif work_type == "field":
                            field_revenue += amount
        except Exception as e:
            print(f"⚠️ WARNING - 年間売上集計エラー: {e}")
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        
        months_with_names = [(m, month_names.get(m, m)) for m in months_list]
        
        return render_template(
            "admin_revenue_months_new.html",
            year=year,
            months=months_with_names,
            total_revenue=total_revenue,
            in_house_revenue=in_house_revenue,
            visit_revenue=visit_revenue,
            field_revenue=field_revenue
        )
    except Exception as e:
        print(f"❌ 月一覧取得エラー: {e}")
        flash("月一覧の取得に失敗しました", "error")
        return redirect("/admin/revenue/years")


@app.route("/admin/revenue/years/<year>/months/<month>")
@admin_required
def admin_revenue_month_selection(year, month):
    """月次売上一覧 - 「全体」と「各スタッフ」の選択"""
    try:
        # スタッフ一覧を取得
        users = supabase_admin.auth.admin.list_users()
        staff_list = []
        
        for u in users:
            meta = u.user_metadata or {}
            if not meta.get("approved", False):
                continue
            
            last_name = meta.get("last_name", "")
            first_name = meta.get("first_name", "")
            if last_name and first_name:
                display_name = f"{last_name} {first_name}"
            else:
                display_name = meta.get("name", "未設定")
            
            staff_list.append({
                "id": u.id,
                "name": display_name
            })
        
        staff_list.sort(key=lambda x: x["name"])
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        month_name = month_names.get(month, month)
        
        return render_template("admin_revenue_month_selection.html", year=year, month=month, month_name=month_name, staff_list=staff_list)
    except Exception as e:
        print(f"❌ 選択ページ取得エラー: {e}")
        flash("選択ページの取得に失敗しました", "error")
        return redirect(f"/admin/revenue/years/{year}/months")


@app.route("/admin/revenue/years/<year>/months/<month>/all")
@admin_required
def admin_revenue_month_all(year, month):
    """月次売上一覧 - 全体の月次詳細（全スタッフ合計、帯同は現場ごとに分ける）"""
    try:
        # 指定年月の日報を取得（全スタッフ）
        month_start = f"{year}-{month}-01"
        if month in ["01", "03", "05", "07", "08", "10", "12"]:
            month_end = f"{year}-{month}-31"
        elif month in ["04", "06", "09", "11"]:
            month_end = f"{year}-{month}-30"
        else:
            year_int = int(year)
            if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                month_end = f"{year}-{month}-29"
            else:
                month_end = f"{year}-{month}-28"
        
        res_reports = supabase_admin.table("staff_daily_reports").select("id, report_date").gte("report_date", month_start).lte("report_date", month_end).execute()
        reports_data = res_reports.data or []
        report_ids = [r["id"] for r in reports_data]
        
        # 日報IDと日付のマッピングを作成
        report_date_map = {r["id"]: r.get("report_date") for r in reports_data}
        
        # 勤務カードを取得
        items = []
        if report_ids:
            res_items = supabase_admin.table("staff_daily_report_items").select("*").in_("daily_report_id", report_ids).execute()
            items = res_items.data or []
            
        # 患者情報を取得
        item_ids = [item["id"] for item in items]
        patients_map = {}
        patient_info_map = {}
        if item_ids:
            try:
                res_patients = supabase_admin.table("staff_daily_report_patients").select("*").in_("item_id", item_ids).execute()
                patients = res_patients.data or []
                
                patient_ids = [p.get("patient_id") for p in patients if p.get("patient_id")]
                
                if patient_ids:
                    try:
                        res_patient_info = supabase_admin.table("patients").select("id, last_name, first_name, name").in_("id", patient_ids).execute()
                        if res_patient_info.data:
                            for p_info in res_patient_info.data:
                                p_id = p_info.get("id")
                                last_name = p_info.get("last_name", "")
                                first_name = p_info.get("first_name", "")
                                if last_name or first_name:
                                    patient_info_map[p_id] = f"{last_name} {first_name}".strip()
                                else:
                                    patient_info_map[p_id] = p_info.get("name", "患者不明")
                    except Exception as e:
                        print(f"⚠️ WARNING - 患者情報取得エラー: {e}")
                
                for patient in patients:
                    item_id = patient.get("item_id")
                    if item_id not in patients_map:
                        patients_map[item_id] = []
                    patient_id = patient.get("patient_id")
                    if patient_id and patient_id in patient_info_map:
                        patient["patient_name"] = patient_info_map[patient_id]
                    else:
                        patient["patient_name"] = None
                    patients_map[item_id].append(patient)
            except Exception as e:
                print(f"⚠️ WARNING - 患者情報取得エラー: {e}")
        
        # 各itemに患者情報と金額を追加
        for item in items:
            item_id = item.get("id")
            daily_report_id = item.get("daily_report_id")
            item["report_date"] = report_date_map.get(daily_report_id, "")
            item["patients"] = patients_map.get(item_id, [])
            item["total_amount"] = sum(p.get("amount", 0) or 0 for p in item["patients"])
            
            # 実働時間を計算
            working_minutes = 0
            if item.get("start_time") and item.get("end_time"):
                try:
                    start_parts = item["start_time"].split(":")
                    end_parts = item["end_time"].split(":")
                    start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
                    end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])
                    break_minutes = item.get("break_minutes", 0) or 0
                    working_minutes = end_minutes - start_minutes - break_minutes
                    if working_minutes < 0:
                        working_minutes = 0
                except:
                    working_minutes = 0
            item["working_hours"] = round(working_minutes / 60, 1) if working_minutes > 0 else 0
        
        # work_typeごとに集計
        in_house_items = [item for item in items if item.get("work_type") == "in_house"]
        visit_items = [item for item in items if item.get("work_type") == "visit"]
        field_items = [item for item in items if item.get("work_type") == "field"]
        
        # 帯同は現場ごとに分ける
        field_by_place = {}  # {place_name: [items]}
        for item in field_items:
            place_name = None
            if item.get("patients"):
                # 帯同の場合、patient_nameが現場名として使われる
                place_name = item["patients"][0].get("patient_name") if item["patients"] else None
            if not place_name:
                place_name = "現場名不明"
            
            if place_name not in field_by_place:
                field_by_place[place_name] = []
            field_by_place[place_name].append(item)
        
        # 日付順でソート
        def sort_by_date(item):
            date_str = item.get("report_date", "")
            if date_str:
                try:
                    return datetime.strptime(date_str, "%Y-%m-%d")
                except:
                    return datetime.min
            return datetime.min
        
        in_house_items.sort(key=sort_by_date, reverse=True)
        visit_items.sort(key=sort_by_date, reverse=True)
        for place_name in field_by_place:
            field_by_place[place_name].sort(key=sort_by_date, reverse=True)
        
        # 集計
        in_house_revenue = sum(item.get("total_amount", 0) for item in in_house_items)
        visit_revenue = sum(item.get("total_amount", 0) for item in visit_items)
        field_revenue = sum(item.get("total_amount", 0) for item in field_items)
        total_revenue = in_house_revenue + visit_revenue + field_revenue
        
        in_house_hours = sum(item.get("working_hours", 0) for item in in_house_items)
        visit_hours = sum(item.get("working_hours", 0) for item in visit_items)
        field_hours = sum(item.get("working_hours", 0) for item in field_items)
        total_hours = in_house_hours + visit_hours + field_hours
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        month_name = month_names.get(month, month)
        
        return render_template(
            "admin_revenue_month_all.html",
            year=year,
            month=month,
            month_name=month_name,
            in_house_revenue=in_house_revenue,
            visit_revenue=visit_revenue,
            field_revenue=field_revenue,
            total_revenue=total_revenue,
            in_house_hours=round(in_house_hours, 1),
            visit_hours=round(visit_hours, 1),
            field_hours=round(field_hours, 1),
            total_hours=round(total_hours, 1),
            in_house_items=in_house_items,
            visit_items=visit_items,
            field_by_place=field_by_place
        )
    except Exception as e:
        import traceback
        print(f"❌ 全体月次売上取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("全体月次売上の取得に失敗しました", "error")
        return redirect(f"/admin/revenue/years/{year}/months/{month}")


# ===================================================
# 請求書一覧（管理者）
# ===================================================
@app.route("/admin/invoices")
@admin_required
def admin_invoices_index():
    """請求書一覧のインデックス（年一覧にリダイレクト）"""
    return redirect("/admin/invoices/years")


@app.route("/admin/invoices/years")
@admin_required
def admin_invoices_years():
    """請求書一覧 - 年選択"""
    try:
        # 請求書が存在する年を取得
        try:
            res_invoices = supabase_admin.table("invoices").select("year").order("year", desc=True).execute()
            invoices = res_invoices.data or []
            
            years_set = set()
            for invoice in invoices:
                year = invoice.get("year")
                if year:
                    years_set.add(str(year))
            
            years_list = sorted([int(y) for y in years_set], reverse=True)
            years_list = [str(y) for y in years_list]
        except Exception as e:
            print(f"⚠️ WARNING - 請求書年一覧取得エラー: {e}")
            years_list = []
        
        # 日報が存在する年も取得（請求書がなくても選択できるように）
        try:
            res_reports = supabase_admin.table("staff_daily_reports").select("report_date").order("report_date", desc=True).execute()
            reports = res_reports.data or []
            
            report_years_set = set()
            for report in reports:
                report_date = report.get("report_date")
                if report_date:
                    year = report_date[:4]
                    report_years_set.add(year)
            
            # 両方の年を結合
            all_years = sorted(set(years_list + list(report_years_set)), reverse=True, key=int)
        except Exception as e:
            print(f"⚠️ WARNING - 日報年一覧取得エラー: {e}")
            all_years = years_list
        
        # 現在の年も追加（データがなくても選択できるように）
        current_year = str(datetime.now().year)
        if current_year not in all_years:
            all_years.insert(0, current_year)
        
        return render_template("admin_invoices_years.html", years=all_years)
    except Exception as e:
        print(f"❌ 年一覧取得エラー: {e}")
        flash("年一覧の取得に失敗しました", "error")
        return redirect("/admin/dashboard")


@app.route("/admin/invoices/years/<year>/months")
@admin_required
def admin_invoices_months(year):
    """請求書一覧 - 月選択"""
    try:
        # 指定年の請求書が存在する月を取得
        months_set = set()
        try:
            res_invoices = supabase_admin.table("invoices").select("month").eq("year", int(year)).execute()
            invoices = res_invoices.data or []
            for invoice in invoices:
                month = invoice.get("month")
                if month:
                    months_set.add(str(month).zfill(2))
        except Exception as e:
            print(f"⚠️ WARNING - 請求書月一覧取得エラー: {e}")
        
        # 日報が存在する月も取得
        try:
            year_start = f"{year}-01-01"
            year_end = f"{year}-12-31"
            res_reports = supabase_admin.table("staff_daily_reports").select("report_date").gte("report_date", year_start).lte("report_date", year_end).execute()
            reports = res_reports.data or []
            for report in reports:
                report_date = report.get("report_date")
                if report_date:
                    month = report_date[5:7]
                    months_set.add(month)
        except Exception as e:
            print(f"⚠️ WARNING - 日報月一覧取得エラー: {e}")
        
        months_list = sorted([int(m) for m in months_set], reverse=True)
        months_list = [str(m).zfill(2) for m in months_list]
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        
        months_with_names = [(m, month_names.get(m, m)) for m in months_list]
        
        return render_template("admin_invoices_months.html", year=year, months=months_with_names)
    except Exception as e:
        print(f"❌ 月一覧取得エラー: {e}")
        flash("月一覧の取得に失敗しました", "error")
        return redirect("/admin/invoices/years")


@app.route("/admin/invoices/years/<year>/months/<month>/auto-create", methods=["POST"])
@admin_required
def admin_invoices_auto_create(year, month):
    """請求書の自動作成（その月の帯同データから現場ごとに作成）"""
    try:
        # 指定年月の帯同データを取得
        month_start = f"{year}-{month}-01"
        if month in ["01", "03", "05", "07", "08", "10", "12"]:
            month_end = f"{year}-{month}-31"
        elif month in ["04", "06", "09", "11"]:
            month_end = f"{year}-{month}-30"
        else:
            year_int = int(year)
            if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                month_end = f"{year}-{month}-29"
            else:
                month_end = f"{year}-{month}-28"
        
        # 日報を取得
        res_reports = supabase_admin.table("staff_daily_reports").select("id, report_date").gte("report_date", month_start).lte("report_date", month_end).execute()
        reports_data = res_reports.data or []
        report_ids = [r["id"] for r in reports_data]
        report_date_map = {r["id"]: r.get("report_date") for r in reports_data}
        
        # 帯同の勤務カードを取得
        field_items = []
        if report_ids:
            res_items = supabase_admin.table("staff_daily_report_items").select("*").eq("work_type", "field").in_("daily_report_id", report_ids).execute()
            field_items = res_items.data or []
        
        # 患者情報を取得
        item_ids = [item["id"] for item in field_items]
        patients_map = {}
        if item_ids:
            try:
                res_patients = supabase_admin.table("staff_daily_report_patients").select("*").in_("item_id", item_ids).execute()
                patients = res_patients.data or []
                
                # 患者IDを収集
                patient_ids = [p.get("patient_id") for p in patients if p.get("patient_id")]
                patient_info_map = {}
                if patient_ids:
                    try:
                        res_patient_info = supabase_admin.table("patients").select("id, last_name, first_name, name").in_("id", patient_ids).execute()
                        if res_patient_info.data:
                            for p_info in res_patient_info.data:
                                p_id = p_info.get("id")
                                last_name = p_info.get("last_name", "")
                                first_name = p_info.get("first_name", "")
                                if last_name or first_name:
                                    patient_info_map[p_id] = f"{last_name} {first_name}".strip()
                                else:
                                    patient_info_map[p_id] = p_info.get("name", "患者不明")
                    except Exception as e:
                        print(f"⚠️ WARNING - 患者情報取得エラー: {e}")
                
                for patient in patients:
                    item_id = patient.get("item_id")
                    if item_id not in patients_map:
                        patients_map[item_id] = []
                    patient_id = patient.get("patient_id")
                    if patient_id and patient_id in patient_info_map:
                        patient["patient_name"] = patient_info_map[patient_id]
                    else:
                        patient["patient_name"] = None
                    patients_map[item_id].append(patient)
            except Exception as e:
                print(f"⚠️ WARNING - 患者情報取得エラー: {e}")
        
        # 現場ごとにグループ化
        field_by_place = {}
        for item in field_items:
            item_id = item.get("id")
            daily_report_id = item.get("daily_report_id")
            item["report_date"] = report_date_map.get(daily_report_id, "")
            item["patients"] = patients_map.get(item_id, [])
            
            place_name = None
            if item.get("patients"):
                place_name = item["patients"][0].get("patient_name") if item["patients"] else None
            if not place_name:
                place_name = "現場名不明"
            
            if place_name not in field_by_place:
                field_by_place[place_name] = []
            field_by_place[place_name].append(item)
        
        # 既存の請求書をチェック（重複作成を防ぐ）
        existing_invoices = {}
        try:
            res_existing = supabase_admin.table("invoices").select("id, place_name").eq("year", int(year)).eq("month", int(month)).execute()
            if res_existing.data:
                for inv in res_existing.data:
                    existing_invoices[inv.get("place_name")] = inv.get("id")
        except Exception as e:
            print(f"⚠️ WARNING - 既存請求書チェックエラー: {e}")
        
        # 各現場ごとに請求書を作成
        created_count = 0
        skipped_count = 0
        
        for place_name, items in field_by_place.items():
            # 既存の請求書がある場合はスキップ
            if place_name in existing_invoices:
                skipped_count += 1
                continue
            
            # 合計金額を計算
            total_amount = 0
            for item in items:
                for patient in item.get("patients", []):
                    total_amount += patient.get("amount", 0) or 0
            
            if total_amount == 0:
                continue  # 金額が0の場合はスキップ
            
            # 請求書番号を生成（INV-YYYY-MM-XXX形式）
            try:
                # その月の請求書数を取得して連番を決める
                res_count = supabase_admin.table("invoices").select("id", count="exact").eq("year", int(year)).eq("month", int(month)).execute()
                existing_count = res_count.count or 0
                invoice_number = f"INV-{year}-{month}-{str(existing_count + 1).zfill(3)}"
            except Exception as e:
                print(f"⚠️ WARNING - 請求書番号生成エラー: {e}")
                invoice_number = f"INV-{year}-{month}-001"
            
            # 発行日（月末）と支払期限（翌月末）を計算
            if month in ["01", "03", "05", "07", "08", "10", "12"]:
                issue_date = f"{year}-{month}-31"
            elif month in ["04", "06", "09", "11"]:
                issue_date = f"{year}-{month}-30"
            else:
                year_int = int(year)
                if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                    issue_date = f"{year}-{month}-29"
                else:
                    issue_date = f"{year}-{month}-28"
            
            # 翌月末を計算
            next_month = int(month) + 1
            next_year = int(year)
            if next_month > 12:
                next_month = 1
                next_year += 1
            
            if next_month in [1, 3, 5, 7, 8, 10, 12]:
                due_date = f"{next_year}-{str(next_month).zfill(2)}-31"
            elif next_month in [4, 6, 9, 11]:
                due_date = f"{next_year}-{str(next_month).zfill(2)}-30"
            else:
                if (next_year % 4 == 0 and next_year % 100 != 0) or (next_year % 400 == 0):
                    due_date = f"{next_year}-{str(next_month).zfill(2)}-29"
                else:
                    due_date = f"{next_year}-{str(next_month).zfill(2)}-28"
            
            # 消費税計算（外税、税率10%）
            subtotal_amount = total_amount
            tax_amount = int(subtotal_amount * 0.1)
            total_with_tax = subtotal_amount + tax_amount
            
            # 請求先情報を取得（既存の情報があれば）
            place_address = None
            place_phone = None
            place_contact_person = None
            try:
                res_place = supabase_admin.table("invoice_places").select("*").eq("place_name", place_name).execute()
                if res_place.data:
                    place_info = res_place.data[0]
                    place_address = place_info.get("address")
                    place_phone = place_info.get("phone")
                    place_contact_person = place_info.get("contact_person")
            except Exception as e:
                print(f"⚠️ WARNING - 請求先情報取得エラー: {e}")
            
            # 請求書を作成
            try:
                invoice_data = {
                    "invoice_number": invoice_number,
                    "place_name": place_name,
                    "place_address": place_address,
                    "place_phone": place_phone,
                    "place_contact_person": place_contact_person,
                    "year": int(year),
                    "month": int(month),
                    "issue_date": issue_date,
                    "due_date": due_date,
                    "subtotal_amount": subtotal_amount,
                    "tax_amount": tax_amount,
                    "total_amount": total_with_tax,
                    "status": "draft"
                }
                
                res_invoice = supabase_admin.table("invoices").insert(invoice_data).execute()
                invoice_id = res_invoice.data[0]["id"]
                
                # 請求書明細を作成
                invoice_items = []
                for item in items:
                    for patient in item.get("patients", []):
                        amount = patient.get("amount", 0) or 0
                        if amount > 0:
                            item_data = {
                                "invoice_id": invoice_id,
                                "daily_report_item_id": item.get("id"),
                                "report_date": item.get("report_date"),
                                "description": f"トレーナー帯同",
                                "amount": amount
                            }
                            invoice_items.append(item_data)
                
                if invoice_items:
                    supabase_admin.table("invoice_items").insert(invoice_items).execute()
                
                created_count += 1
            except Exception as e:
                print(f"⚠️ WARNING - 請求書作成エラー ({place_name}): {e}")
                continue
        
        if created_count > 0:
            flash(f"{created_count}件の請求書を作成しました。", "success")
        if skipped_count > 0:
            flash(f"{skipped_count}件の請求書は既に存在するためスキップしました。", "warning")
        if created_count == 0 and skipped_count == 0:
            flash("作成できる請求書がありませんでした。", "warning")
        
        return redirect(f"/admin/invoices/years/{year}/months/{month}")
    except Exception as e:
        import traceback
        print(f"❌ 請求書自動作成エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("請求書の自動作成に失敗しました", "error")
        return redirect(f"/admin/invoices/years/{year}/months/{month}")


@app.route("/admin/invoices/new", methods=["GET", "POST"])
@admin_required
def admin_invoice_new():
    """請求書 - 新規作成"""
    if request.method == "POST":
        try:
            # フォームデータを取得
            place_name = request.form.get("place_name", "").strip()
            place_address = request.form.get("place_address", "").strip()
            place_phone = request.form.get("place_phone", "").strip()
            place_contact_person = request.form.get("place_contact_person", "").strip()
            year = int(request.form.get("year"))
            month = int(request.form.get("month"))
            issue_date = request.form.get("issue_date")
            due_date = request.form.get("due_date")
            notes = request.form.get("notes", "").strip()
            
            # 請求書を作成
            invoice_data = {
                "place_name": place_name,
                "address": place_address,
                "phone": place_phone,
                "contact_person": place_contact_person,
                "year": year,
                "month": month,
                "issue_date": issue_date,
                "due_date": due_date,
                "notes": notes,
                "total_amount": 0,
                "created_at": now_iso()
            }
            
            res_invoice = supabase_admin.table("invoices").insert(invoice_data).execute()
            invoice_id = res_invoice.data[0]["id"]
            
            # 明細を追加
            item_count = int(request.form.get("item_count", 0))
            items = []
            for i in range(item_count):
                description = request.form.get(f"item_description_{i}", "").strip()
                quantity = request.form.get(f"item_quantity_{i}", "0").strip()
                unit_price = request.form.get(f"item_unit_price_{i}", "0").strip()
                report_date = request.form.get(f"item_report_date_{i}", "").strip()
                
                if description:
                    try:
                        qty = int(quantity) if quantity else 0
                        price = float(unit_price) if unit_price else 0
                        amount = qty * price
                        
                        items.append({
                            "invoice_id": invoice_id,
                            "description": description,
                            "quantity": qty,
                            "unit_price": price,
                            "amount": amount,
                            "report_date": report_date if report_date else None,
                            "created_at": now_iso()
                        })
                    except:
                        continue
            
            if items:
                supabase_admin.table("invoice_items").insert(items).execute()
                
                # 合計金額を計算
                total_amount = sum(item["amount"] for item in items)
                supabase_admin.table("invoices").update({"total_amount": total_amount}).eq("id", invoice_id).execute()
            
            flash("請求書を作成しました", "success")
            return redirect(f"/admin/invoices/{invoice_id}")
        except Exception as e:
            import traceback
            print(f"❌ 請求書作成エラー: {e}")
            print(f"❌ トレースバック: {traceback.format_exc()}")
            flash(f"請求書の作成に失敗しました: {e}", "error")
            return redirect("/admin/invoices/years")
    
    # GET: 新規作成フォーム
    # 既存の請求先が取得できなくてもフォームは表示する
    existing_places = []
    try:
        res_existing = supabase_admin.table("invoices").select("place_name, address, phone, contact_person").order("created_at", desc=True).limit(50).execute()
        seen_places = set()
        for inv in (res_existing.data or []):
            place = inv.get("place_name")
            if place and place not in seen_places:
                existing_places.append({
                    "place_name": place,
                    "address": inv.get("address", ""),
                    "phone": inv.get("phone", ""),
                    "contact_person": inv.get("contact_person", "")
                })
                seen_places.add(place)
    except Exception as e:
        print(f"❌ 請求書新規作成フォーム取得エラー: {e}")

    current_year = datetime.now().year

    return render_template(
        "admin_invoice_new.html",
        existing_places=existing_places,
        current_year=current_year
    )


@app.route("/admin/invoices/<invoice_id>")
@admin_required
def admin_invoice_detail(invoice_id):
    """請求書詳細"""
    try:
        # 請求書を取得
        res_invoice = supabase_admin.table("invoices").select("*").eq("id", invoice_id).execute()
        if not res_invoice.data:
            flash("請求書が見つかりません", "error")
            return redirect("/admin/invoices/years")
        
        invoice = res_invoice.data[0]
        
        # 請求書明細を取得
        res_items = supabase_admin.table("invoice_items").select("*").eq("invoice_id", invoice_id).order("report_date").execute()
        items = res_items.data or []
        
        # 自社情報
        company_info = {
            "name": "KARiN.",
            "address": "福岡県福岡市中央区小笹1-5-11-803",
            "phone": "09081549313",
            "bank": "三井住友銀行",
            "branch": "神田駅前支店",
            "account_type": "普通",
            "account_number": "1741051",
            "account_name": "藤田幸士"
        }
        
        month_names = {
            1: "1月", 2: "2月", 3: "3月", 4: "4月",
            5: "5月", 6: "6月", 7: "7月", 8: "8月",
            9: "9月", 10: "10月", 11: "11月", 12: "12月"
        }
        month_name = month_names.get(invoice.get("month"), str(invoice.get("month")))
        
        return render_template(
            "admin_invoice_detail.html",
            invoice=invoice,
            items=items,
            company_info=company_info,
            month_name=month_name
        )
    except Exception as e:
        import traceback
        print(f"❌ 請求書詳細取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("請求書詳細の取得に失敗しました", "error")
        return redirect("/admin/invoices/years")


@app.route("/admin/invoices/<invoice_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_invoice_edit(invoice_id):
    """請求書編集"""
    try:
        # 請求書を取得
        res_invoice = supabase_admin.table("invoices").select("*").eq("id", invoice_id).execute()
        if not res_invoice.data:
            flash("請求書が見つかりません", "error")
            return redirect("/admin/invoices/years")
        
        invoice = res_invoice.data[0]
        
        if request.method == "GET":
            # 請求書明細を取得
            res_items = supabase_admin.table("invoice_items").select("*").eq("invoice_id", invoice_id).order("report_date").execute()
            items = res_items.data or []
            
            # 請求先情報を取得（既存の情報があれば）
            place_info = None
            try:
                res_place = supabase_admin.table("invoice_places").select("*").eq("place_name", invoice.get("place_name")).execute()
                if res_place.data:
                    place_info = res_place.data[0]
            except Exception as e:
                print(f"⚠️ WARNING - 請求先情報取得エラー: {e}")
            
            month_names = {
                1: "1月", 2: "2月", 3: "3月", 4: "4月",
                5: "5月", 6: "6月", 7: "7月", 8: "8月",
                9: "9月", 10: "10月", 11: "11月", 12: "12月"
            }
            month_name = month_names.get(invoice.get("month"), str(invoice.get("month")))
            
            return render_template(
                "admin_invoice_edit.html",
                invoice=invoice,
                items=items,
                place_info=place_info,
                month_name=month_name
            )
        
        # POST処理
        place_address = request.form.get("place_address", "").strip()
        place_phone = request.form.get("place_phone", "").strip()
        place_contact_person = request.form.get("place_contact_person", "").strip()
        issue_date = request.form.get("issue_date", "").strip()
        due_date = request.form.get("due_date", "").strip()
        status = request.form.get("status", "draft").strip()
        sent_at = request.form.get("sent_at", "").strip() or None
        paid_at = request.form.get("paid_at", "").strip() or None
        notes = request.form.get("notes", "").strip()
        
        # 請求先情報を保存（invoice_placesテーブル）
        place_name = invoice.get("place_name")
        try:
            # 既存の情報があるかチェック
            res_existing = supabase_admin.table("invoice_places").select("id").eq("place_name", place_name).execute()
            if res_existing.data:
                # 更新
                supabase_admin.table("invoice_places").update({
                    "address": place_address or None,
                    "phone": place_phone or None,
                    "contact_person": place_contact_person or None,
                    "updated_at": datetime.now(JST).isoformat()
                }).eq("id", res_existing.data[0]["id"]).execute()
            else:
                # 新規作成
                supabase_admin.table("invoice_places").insert({
                    "place_name": place_name,
                    "address": place_address or None,
                    "phone": place_phone or None,
                    "contact_person": place_contact_person or None
                }).execute()
        except Exception as e:
            print(f"⚠️ WARNING - 請求先情報保存エラー: {e}")
        
        # 請求書を更新
        update_data = {
            "place_address": place_address or None,
            "place_phone": place_phone or None,
            "place_contact_person": place_contact_person or None,
            "issue_date": issue_date or invoice.get("issue_date"),
            "due_date": due_date or invoice.get("due_date"),
            "status": status,
            "sent_at": sent_at,
            "paid_at": paid_at,
            "notes": notes or None,
            "updated_at": datetime.now(JST).isoformat()
        }
        
        supabase_admin.table("invoices").update(update_data).eq("id", invoice_id).execute()
        
        flash("請求書を更新しました", "success")
        return redirect(f"/admin/invoices/{invoice_id}")
    except Exception as e:
        import traceback
        print(f"❌ 請求書編集エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("請求書の更新に失敗しました", "error")
        return redirect(f"/admin/invoices/{invoice_id}/edit")


@app.route("/admin/invoices/years/<year>/months/<month>")
@admin_required
def admin_invoices_list(year, month):
    """請求書一覧 - その月の請求書一覧"""
    try:
        # 指定年月の請求書を取得
        try:
            res_invoices = supabase_admin.table("invoices").select("*").eq("year", int(year)).eq("month", int(month)).order("created_at", desc=True).execute()
            invoices = res_invoices.data or []
        except Exception as e:
            print(f"⚠️ WARNING - 請求書一覧取得エラー: {e}")
            invoices = []
        
        # 請求書明細も取得
        invoice_items_map = {}
        if invoices:
            invoice_ids = [inv["id"] for inv in invoices]
            try:
                res_items = supabase_admin.table("invoice_items").select("*").in_("invoice_id", invoice_ids).execute()
                items = res_items.data or []
                for item in items:
                    invoice_id = item.get("invoice_id")
                    if invoice_id not in invoice_items_map:
                        invoice_items_map[invoice_id] = []
                    invoice_items_map[invoice_id].append(item)
            except Exception as e:
                print(f"⚠️ WARNING - 請求書明細取得エラー: {e}")
        
        # 各請求書に明細を追加
        for invoice in invoices:
            invoice_id = invoice.get("id")
            invoice["items"] = invoice_items_map.get(invoice_id, [])
        
        # その月に帯同データがあるかチェック（自動作成ボタン表示用）
        has_field_data = False
        try:
            month_start = f"{year}-{month}-01"
            if month in ["01", "03", "05", "07", "08", "10", "12"]:
                month_end = f"{year}-{month}-31"
            elif month in ["04", "06", "09", "11"]:
                month_end = f"{year}-{month}-30"
            else:
                year_int = int(year)
                if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                    month_end = f"{year}-{month}-29"
                else:
                    month_end = f"{year}-{month}-28"
            
            res_reports = supabase_admin.table("staff_daily_reports").select("id").gte("report_date", month_start).lte("report_date", month_end).execute()
            report_ids = [r["id"] for r in res_reports.data] if res_reports.data else []
            
            if report_ids:
                res_items = supabase_admin.table("staff_daily_report_items").select("id").eq("work_type", "field").in_("daily_report_id", report_ids).limit(1).execute()
                if res_items.data:
                    has_field_data = True
        except Exception as e:
            print(f"⚠️ WARNING - 帯同データチェックエラー: {e}")
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        month_name = month_names.get(month, month)
        
        return render_template(
            "admin_invoices_list.html",
            year=year,
            month=month,
            month_name=month_name,
            invoices=invoices,
            has_field_data=has_field_data
        )
    except Exception as e:
        import traceback
        print(f"❌ 請求書一覧取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("請求書一覧の取得に失敗しました", "error")
        return redirect(f"/admin/invoices/years/{year}/months")


# ===================================================
# スタッフ別月次売上一覧（管理者） - 既存ルートを維持
# ===================================================
@app.route("/admin/revenue/staff")
@admin_required
def admin_revenue_staff():
    """スタッフ別月次売上一覧 - スタッフ選択"""
    try:
        # 承認済みスタッフのみ取得
        users = supabase_admin.auth.admin.list_users()
        staff_list = []
        
        for u in users:
            meta = u.user_metadata or {}
            if not meta.get("approved", False):
                continue
            
            last_name = meta.get("last_name", "")
            first_name = meta.get("first_name", "")
            if last_name and first_name:
                display_name = f"{last_name} {first_name}"
            else:
                display_name = meta.get("name", "未設定")
            
            staff_list.append({
                "id": u.id,
                "name": display_name
            })
        
        staff_list.sort(key=lambda x: x["name"])
        
        return render_template("admin_revenue_staff.html", staff_list=staff_list)
    except Exception as e:
        print(f"❌ スタッフ一覧取得エラー: {e}")
        flash("スタッフ一覧の取得に失敗しました", "error")
        return redirect("/admin/dashboard")


@app.route("/admin/revenue/staff/<staff_id>/years")
@admin_required
def admin_revenue_staff_years(staff_id):
    """スタッフ別月次売上一覧 - 年選択"""
    try:
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/revenue/staff")
        
        meta = staff_user.user_metadata or {}
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # 日報が存在する年を取得
        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").eq("staff_name", staff_name).order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        years_set = set()
        for report in reports:
            report_date = report.get("report_date")
            if report_date:
                year = report_date[:4]
                years_set.add(year)
        
        years_list = sorted(years_set, reverse=True)
        
        return render_template("admin_revenue_years.html", years=years_list, staff_id=staff_id, staff_name=staff_name)
    except Exception as e:
        print(f"❌ 年一覧取得エラー: {e}")
        flash("年一覧の取得に失敗しました", "error")
        return redirect("/admin/revenue/staff")


@app.route("/admin/revenue/staff/<staff_id>/years/<year>")
@admin_required
def admin_revenue_staff_months(staff_id, year):
    """スタッフ別月次売上一覧 - 月選択"""
    try:
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/revenue/staff")
        
        meta = staff_user.user_metadata or {}
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # 指定年の日報が存在する月を取得
        year_start = f"{year}-01-01"
        year_end = f"{year}-12-31"
        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").eq("staff_name", staff_name).gte("report_date", year_start).lte("report_date", year_end).order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        months_set = set()
        for report in reports:
            report_date = report.get("report_date")
            if report_date:
                month = report_date[5:7]
                months_set.add(month)
        
        months_list = sorted(months_set, reverse=True)
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        months_with_names = [(m, month_names.get(m, m)) for m in months_list]
        
        return render_template("admin_revenue_months.html", year=year, months=months_with_names, staff_id=staff_id, staff_name=staff_name)
    except Exception as e:
        print(f"❌ 月一覧取得エラー: {e}")
        flash("月一覧の取得に失敗しました", "error")
        return redirect(f"/admin/revenue/staff/{staff_id}/years")


@app.route("/admin/revenue/staff/<staff_id>/years/<year>/months/<month>")
@admin_required
def admin_revenue_month_detail(staff_id, year, month):
    """スタッフ別月次売上一覧 - 月詳細（Python側で集計）"""
    try:
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/revenue/staff")
        
        meta = staff_user.user_metadata or {}
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # 指定年月の日報を取得
        month_start = f"{year}-{month}-01"
        if month in ["01", "03", "05", "07", "08", "10", "12"]:
            month_end = f"{year}-{month}-31"
        elif month in ["04", "06", "09", "11"]:
            month_end = f"{year}-{month}-30"
        else:
            year_int = int(year)
            if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                month_end = f"{year}-{month}-29"
            else:
                month_end = f"{year}-{month}-28"
        
        res_reports = supabase_admin.table("staff_daily_reports").select("id, report_date").eq("staff_name", staff_name).gte("report_date", month_start).lte("report_date", month_end).execute()
        reports_data = res_reports.data or []
        report_ids = [r["id"] for r in reports_data]
        
        # 日報IDと日付のマッピングを作成
        report_date_map = {r["id"]: r.get("report_date") for r in reports_data}
        
        # 勤務カードを取得
        items = []
        if report_ids:
            res_items = supabase_admin.table("staff_daily_report_items").select("*").in_("daily_report_id", report_ids).execute()
            items = res_items.data or []
        
        # 患者情報を取得
        item_ids = [item["id"] for item in items]
        patients_map = {}
        patient_info_map = {}  # 患者ID -> 患者名のマッピング
        if item_ids:
            try:
                res_patients = supabase_admin.table("staff_daily_report_patients").select("*").in_("item_id", item_ids).execute()
                patients = res_patients.data or []
                
                # 患者IDを収集
                patient_ids = [p.get("patient_id") for p in patients if p.get("patient_id")]
                
                # 患者情報を一括取得（名前表示用）
                if patient_ids:
                    try:
                        res_patient_info = supabase_admin.table("patients").select("id, last_name, first_name, name").in_("id", patient_ids).execute()
                        if res_patient_info.data:
                            for p_info in res_patient_info.data:
                                p_id = p_info.get("id")
                                last_name = p_info.get("last_name", "")
                                first_name = p_info.get("first_name", "")
                                if last_name or first_name:
                                    patient_info_map[p_id] = f"{last_name} {first_name}".strip()
                                else:
                                    patient_info_map[p_id] = p_info.get("name", "患者不明")
                    except Exception as e:
                        print(f"⚠️ WARNING - 患者情報取得エラー: {e}")
                
                for patient in patients:
                    item_id = patient.get("item_id")
                    if item_id not in patients_map:
                        patients_map[item_id] = []
                    # 患者名を追加
                    patient_id = patient.get("patient_id")
                    if patient_id and patient_id in patient_info_map:
                        patient["patient_name"] = patient_info_map[patient_id]
                    else:
                        patient["patient_name"] = None
                    patients_map[item_id].append(patient)
            except Exception as e:
                print(f"⚠️ WARNING - 患者情報取得エラー: {e}")
        
        # 各itemに患者情報と金額を追加（Python側で集計）
        for item in items:
            item_id = item.get("id")
            daily_report_id = item.get("daily_report_id")
            
            # 日報の日付を追加
            item["report_date"] = report_date_map.get(daily_report_id, "")
            
            item["patients"] = patients_map.get(item_id, [])
            item["total_amount"] = sum(p.get("amount", 0) or 0 for p in item["patients"])
            
            # 実働時間を計算（start_time, end_time, break_minutesから）
            working_minutes = 0
            if item.get("start_time") and item.get("end_time"):
                try:
                    start_parts = item["start_time"].split(":")
                    end_parts = item["end_time"].split(":")
                    start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
                    end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])
                    break_minutes = item.get("break_minutes", 0) or 0
                    working_minutes = end_minutes - start_minutes - break_minutes
                    if working_minutes < 0:
                        working_minutes = 0
                except:
                    working_minutes = 0
            item["working_hours"] = round(working_minutes / 60, 1) if working_minutes > 0 else 0
        
        # work_typeごとに集計（Python側で集計）
        in_house_items = [item for item in items if item.get("work_type") == "in_house"]
        visit_items = [item for item in items if item.get("work_type") == "visit"]
        field_items = [item for item in items if item.get("work_type") == "field"]
        
        # 日付順でソート（新しい日付から）
        def sort_by_date(item):
            date_str = item.get("report_date", "")
            if date_str:
                try:
                    return datetime.strptime(date_str, "%Y-%m-%d")
                except:
                    return datetime.min
            return datetime.min
        
        in_house_items.sort(key=sort_by_date, reverse=True)
        visit_items.sort(key=sort_by_date, reverse=True)
        field_items.sort(key=sort_by_date, reverse=True)
        
        in_house_revenue = sum(item.get("total_amount", 0) for item in in_house_items)
        visit_revenue = sum(item.get("total_amount", 0) for item in visit_items)
        field_revenue = sum(item.get("total_amount", 0) for item in field_items)
        total_revenue = in_house_revenue + visit_revenue + field_revenue
        
        in_house_hours = sum(item.get("working_hours", 0) for item in in_house_items)
        visit_hours = sum(item.get("working_hours", 0) for item in visit_items)
        field_hours = sum(item.get("working_hours", 0) for item in field_items)
        total_hours = in_house_hours + visit_hours + field_hours
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        month_name = month_names.get(month, month)
        
        return render_template(
            "admin_revenue_month_detail.html",
            year=year,
            month=month,
            month_name=month_name,
            staff_id=staff_id,
            staff_name=staff_name,
            in_house_revenue=in_house_revenue,
            visit_revenue=visit_revenue,
            field_revenue=field_revenue,
            total_revenue=total_revenue,
            in_house_hours=round(in_house_hours, 1),
            visit_hours=round(visit_hours, 1),
            field_hours=round(field_hours, 1),
            total_hours=round(total_hours, 1),
            in_house_items=in_house_items,
            visit_items=visit_items,
            field_items=field_items
        )
    except Exception as e:
        import traceback
        print(f"❌ 月次売上取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("月次売上の取得に失敗しました", "error")
        return redirect(f"/admin/revenue/staff/{staff_id}/years")


@app.route("/admin/daily-reports", methods=["GET"])
@staff_required
def admin_daily_reports_index():
    """日報一覧のインデックス（年一覧にリダイレクト）"""
    return redirect("/admin/daily-reports/years")


@app.route("/admin/daily-reports/years", methods=["GET"])
@staff_required
def admin_daily_reports_years():
    """日報一覧 - 年一覧"""
    try:
        # 日報が存在する年を取得（全スタッフ）
        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        years_set = set()
        for report in reports:
            report_date = report.get("report_date")
            if report_date:
                year = report_date[:4]
                years_set.add(year)
        
        # 現在の年も追加（データがなくても選択できるように）
        current_year = str(datetime.now().year)
        years_set.add(current_year)
        
        years_list = sorted(years_set, reverse=True, key=int)
        
        return render_template("admin_daily_reports_years.html", years=years_list)
    except Exception as e:
        import traceback
        print(f"❌ 年一覧取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("年一覧の取得に失敗しました", "error")
        return redirect("/admin/dashboard")


@app.route("/admin/daily-reports/years/<year>", methods=["GET"])
@staff_required
def admin_daily_reports_months(year):
    """日報一覧 - 月一覧"""
    try:
        # 指定年の日報が存在する月を取得（全スタッフ）
        year_start = f"{year}-01-01"
        year_end = f"{year}-12-31"
        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").gte("report_date", year_start).lte("report_date", year_end).order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        months_set = set()
        for report in reports:
            report_date = report.get("report_date")
            if report_date:
                month = report_date[5:7]
                months_set.add(month)
        
        months_list = sorted(months_set, reverse=True)
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        
        months_with_names = [(m, month_names.get(m, m)) for m in months_list]
        
        return render_template("admin_daily_reports_months.html", year=year, months=months_with_names)
    except Exception as e:
        import traceback
        print(f"❌ 月一覧取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("月一覧の取得に失敗しました", "error")
        return redirect("/admin/daily-reports/years")


@app.route("/admin/daily-reports/years/<year>/months/<month>", methods=["GET"])
@staff_required
def admin_daily_reports_dates(year, month):
    """日報一覧 - 日付一覧（シート選択）"""
    try:
        # 指定年月の日報が存在する日付を取得（全スタッフ）
        month_start = f"{year}-{month}-01"
        if month in ["01", "03", "05", "07", "08", "10", "12"]:
            month_end = f"{year}-{month}-31"
        elif month in ["04", "06", "09", "11"]:
            month_end = f"{year}-{month}-30"
        else:
            year_int = int(year)
            if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                month_end = f"{year}-{month}-29"
            else:
                month_end = f"{year}-{month}-28"
        
        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").gte("report_date", month_start).lte("report_date", month_end).order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        dates_set = set()
        for report in reports:
            report_date = report.get("report_date")
            if report_date:
                dates_set.add(report_date)
        
        dates_list = sorted(dates_set, reverse=True)
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        month_name = month_names.get(month, month)
        
        return render_template("admin_daily_reports_dates.html", year=year, month=month, month_name=month_name, dates=dates_list)
    except Exception as e:
        import traceback
        print(f"❌ 日付一覧取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("日付一覧の取得に失敗しました", "error")
        return redirect(f"/admin/daily-reports/years/{year}")


@app.route("/admin/daily-reports/years/<year>/months/<month>/dates/<date>", methods=["GET"])
@app.route("/admin/daily-reports", methods=["GET"])
@staff_required
def admin_daily_reports(year=None, month=None, date=None):
    """
    会社の公式日報一覧（1日1画面、全スタッフ統合表示）
    - スタッフ：自分の分のみ編集可能
    - 管理者：全て編集可能
    """
    try:
        # 日付パラメータ取得（URLパスから、またはクエリパラメータから、デフォルトは今日）
        if date:
            selected_date = date
        else:
            selected_date = request.args.get("date")
            if not selected_date:
                # yearとmonthが指定されている場合は、その月の最初の日付を取得
                year = request.args.get("year")
                month = request.args.get("month")
                if year and month:
                    # その月に日報が存在する最初の日付を取得
                    month_start = f"{year}-{month}-01"
                    if month in ["01", "03", "05", "07", "08", "10", "12"]:
                        month_end = f"{year}-{month}-31"
                    elif month in ["04", "06", "09", "11"]:
                        month_end = f"{year}-{month}-30"
                    else:
                        year_int = int(year)
                        if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                            month_end = f"{year}-{month}-29"
                        else:
                            month_end = f"{year}-{month}-28"
                    
                    try:
                        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").gte("report_date", month_start).lte("report_date", month_end).order("report_date", desc=True).execute()
                        if res_reports.data and len(res_reports.data) > 0:
                            selected_date = res_reports.data[0].get("report_date")
                    except Exception as e:
                        print(f"⚠️ WARNING - 月の最初の日付取得エラー: {e}")
                
                # デフォルトは今日
                if not selected_date:
                    selected_date = datetime.now(JST).strftime("%Y-%m-%d")
        
        # ログイン中のスタッフ情報を取得
        staff = session.get("staff", {})
        staff_id = staff.get("id")
        staff_name = staff.get("name", "スタッフ")
        is_admin = staff.get("is_admin", False)
        
        # 指定日の全スタッフの日報を取得
        res_reports = supabase_admin.table("staff_daily_reports").select("*").eq("report_date", selected_date).execute()
        reports = res_reports.data or []
        
        # 日報IDを収集
        report_ids = [r["id"] for r in reports]
        
        # 指定日の全勤務カードを取得
        items = []
        if report_ids:
            res_items = supabase_admin.table("staff_daily_report_items").select("*").in_("daily_report_id", report_ids).execute()
            items = res_items.data or []
            
        # スタッフ名マップを作成（report_id -> staff_name）
        staff_name_map = {}
        for report in reports:
            staff_name_map[report["id"]] = report.get("staff_name", "スタッフ不明")
        
        # 各勤務カードにスタッフ名を追加
            for item in items:
                report_id = item.get("daily_report_id")
            item["staff_name"] = staff_name_map.get(report_id, "スタッフ不明")
            # 編集権限を判定（スタッフは自分の分のみ、管理者は全て）
            item["can_edit"] = is_admin or (item["staff_name"] == staff_name)
        
        # work_typeで分類（院内・往診・帯同）
        in_house_items = []
        visit_items = []
        field_items = []
        
        for item in items:
            work_type = item.get("work_type")
            if work_type == "in_house":
                in_house_items.append(item)
            elif work_type == "visit":
                visit_items.append(item)
            elif work_type == "field":
                field_items.append(item)
        
        # 開始時間順でソート
        def sort_by_start_time(item):
            start_time = item.get("start_time", "")
            if isinstance(start_time, str):
                try:
                    parts = start_time.split(":")
                    return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
                except:
                    return (99, 99)  # 時間が無効な場合は最後に
            return (99, 99)
        
        in_house_items.sort(key=sort_by_start_time)
        visit_items.sort(key=sort_by_start_time)
        field_items.sort(key=sort_by_start_time)
        
        # 患者情報を取得
        item_ids = [item["id"] for item in items]
        patients_map = {}  # {item_id: [patients]}
        patient_info_map = {}  # {patient_id: {name, vip_level}}
        
        if item_ids:
            try:
                # 患者紐付け情報を取得
                res_patients = supabase_admin.table("staff_daily_report_patients").select("*").in_("item_id", item_ids).execute()
                patients = res_patients.data or []
                
                # 患者IDを収集
                patient_ids = [p.get("patient_id") for p in patients if p.get("patient_id")]
                
                # 患者情報を一括取得（名前・VIPフラグ）
                if patient_ids:
                    res_patient_info = supabase_admin.table("patients").select("id, last_name, first_name, name, vip_level").in_("id", patient_ids).execute()
                    if res_patient_info.data:
                        for p in res_patient_info.data:
                            name = f"{p.get('last_name', '')} {p.get('first_name', '')}".strip()
                            patient_info_map[p["id"]] = {
                                "name": name or p.get("name", "患者不明"),
                                "vip_level": p.get("vip_level")
                            }
                
                # 予約情報を先に取得して、コース名マップを作成（院内・往診用）
                reservation_ids = [p.get("reservation_id") for p in patients if p.get("reservation_id")]
                invalid_reservation_ids = []
                reservation_course_map = {}  # {reservation_id: course_name}
                if reservation_ids:
                    try:
                        res_reservations_info = supabase_admin.table("reservations").select("id, status, course_name").in_("id", reservation_ids).execute()
                        found_reservation_ids = {r.get("id") for r in res_reservations_info.data} if res_reservations_info.data else set()
                        # 存在しない予約IDを収集
                        invalid_reservation_ids.extend([rid for rid in reservation_ids if rid not in found_reservation_ids])
                        # 完了状態でない予約IDを収集、コース名をマップに追加
                        if res_reservations_info.data:
                            for r_info in res_reservations_info.data:
                                if r_info.get("status") != "completed":
                                    invalid_reservation_ids.append(r_info.get("id"))
                                else:
                                    # 完了状態の予約からコース名を取得
                                    reservation_course_map[r_info.get("id")] = r_info.get("course_name", "")
                        
                        # 無効な予約に関連する日報患者情報を削除
                        if invalid_reservation_ids:
                            supabase_admin.table("staff_daily_report_patients").delete().in_("reservation_id", invalid_reservation_ids).execute()
                            print(f"✅ 全体の日報から無効な予約に関連する患者情報を削除しました: {len(invalid_reservation_ids)}件")
                            # 削除後、患者データからも除外
                            patients = [p for p in patients if p.get("reservation_id") not in invalid_reservation_ids]
                    except Exception as e:
                        print(f"⚠️ WARNING - 予約情報チェックエラー: {e}")
                
                # item_idごとにグループ化
                for patient in patients:
                    item_id = patient.get("item_id")
                    patient_id = patient.get("patient_id")
                    reservation_id = patient.get("reservation_id")
                    
                    if item_id not in patients_map:
                        patients_map[item_id] = []
                    
                    # 患者名とVIPフラグを追加
                    if patient_id and patient_id in patient_info_map:
                        patient["patient_name"] = patient_info_map[patient_id]["name"]
                        patient["vip_level"] = patient_info_map[patient_id]["vip_level"]
                    else:
                        patient["patient_name"] = None
                        patient["vip_level"] = None
                    
                    # コース名を予約データから取得して反映（院内・往診用、編集時の反映のため）
                    # 予約データのコース名を優先（staff_daily_report_patientsのcourse_nameが空の場合、予約データから取得）
                    if reservation_id and reservation_id in reservation_course_map:
                        reservation_course = reservation_course_map[reservation_id]
                        # 既存のcourse_nameが空の場合は予約データのcourse_nameを使用
                        if not patient.get("course_name") and reservation_course:
                            patient["course_name"] = reservation_course
                            # staff_daily_report_patientsテーブルにも反映（既存レコードを更新）
                            try:
                                supabase_admin.table("staff_daily_report_patients").update({"course_name": reservation_course}).eq("id", patient.get("id")).execute()
                            except Exception as e:
                                print(f"⚠️ WARNING - コース名更新エラー: {e}")
                    
                    patients_map[item_id].append(patient)
            except Exception as e:
                print(f"⚠️ WARNING - 日報患者情報取得エラー: {e}")
            
            # 各勤務カードに患者情報を結合
        for item in items:
                item_id = item.get("id")
                item["patients"] = patients_map.get(item_id, [])
                
                # 金額を計算（Python側で集計）
                patients = item["patients"]
                item["total_amount"] = sum(p.get("amount", 0) or 0 for p in patients)
                
                # 時刻表示用に整形
                if item.get("start_time"):
                    try:
                        if isinstance(item["start_time"], str):
                            time_parts = item["start_time"].split(":")
                            item["start_time_display"] = f"{time_parts[0]}:{time_parts[1]}"
                        else:
                            item["start_time_display"] = str(item["start_time"])[:5]
                    except:
                        item["start_time_display"] = item.get("start_time", "")
                else:
                    item["start_time_display"] = ""
                
                if item.get("end_time"):
                    try:
                        if isinstance(item["end_time"], str):
                            time_parts = item["end_time"].split(":")
                            item["end_time_display"] = f"{time_parts[0]}:{time_parts[1]}"
                        else:
                            item["end_time_display"] = str(item["end_time"])[:5]
                    except:
                        item["end_time_display"] = item.get("end_time", "")
                else:
                    item["end_time_display"] = ""
        
        # 当日小計・当月累計を計算（Python側で集計）
        # 当日小計（各itemのtotal_amountを使用）
        in_house_day_total = sum(item.get("total_amount", 0) for item in in_house_items)
        visit_day_total = sum(item.get("total_amount", 0) for item in visit_items)
        field_day_total = sum(item.get("total_amount", 0) for item in field_items)
        
        # 当月累計（指定日の月の1日から指定日まで）
        month_start = selected_date[:7] + "-01"  # YYYY-MM-01
        res_month_reports = supabase_admin.table("staff_daily_reports").select("id").gte("report_date", month_start).lte("report_date", selected_date).execute()
        month_report_ids = [r["id"] for r in res_month_reports.data] if res_month_reports.data else []
        
        in_house_month_total = 0
        visit_month_total = 0
        field_month_total = 0
        
        if month_report_ids:
            res_month_items = supabase_admin.table("staff_daily_report_items").select("id, work_type").in_("daily_report_id", month_report_ids).execute()
            month_items = res_month_items.data or []
            month_item_ids = [item["id"] for item in month_items]
            
            if month_item_ids:
                try:
                    res_month_patients = supabase_admin.table("staff_daily_report_patients").select("item_id, amount").in_("item_id", month_item_ids).execute()
                    month_patients = res_month_patients.data or []
                    
                    # work_typeごとに集計（Python側で集計）
                    for item in month_items:
                        item_id = item.get("id")
                        work_type = item.get("work_type")
                        # 当月の患者情報からitem_idに紐づく金額を集計
                        item_total = sum(p.get("amount", 0) or 0 for p in month_patients if p.get("item_id") == item_id)
                        
                        if work_type == "in_house":
                            in_house_month_total += item_total
                        elif work_type == "visit":
                            visit_month_total += item_total
                        elif work_type == "field":
                            field_month_total += item_total
                except Exception as e:
                    print(f"⚠️ WARNING - 当月累計計算エラー: {e}")
        
        # その月の全日付を取得（日付ボタン用）
        month_dates = []
        year_param = request.args.get("year")
        month_param = request.args.get("month")
        if not year_param or not month_param:
            # selected_dateから年と月を抽出
            year_param = selected_date[:4]
            month_param = selected_date[5:7]
        
        if year_param and month_param:
            month_start = f"{year_param}-{month_param}-01"
            if month_param in ["01", "03", "05", "07", "08", "10", "12"]:
                month_end = f"{year_param}-{month_param}-31"
            elif month_param in ["04", "06", "09", "11"]:
                month_end = f"{year_param}-{month_param}-30"
            else:
                year_int = int(year_param)
                if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                    month_end = f"{year_param}-{month_param}-29"
                else:
                    month_end = f"{year_param}-{month_param}-28"
            
            try:
                res_month_reports = supabase_admin.table("staff_daily_reports").select("report_date").gte("report_date", month_start).lte("report_date", month_end).order("report_date", desc=True).execute()
                if res_month_reports.data:
                    dates_set = set()
                    for report in res_month_reports.data:
                        report_date = report.get("report_date")
                        if report_date:
                            dates_set.add(report_date)
                    month_dates = sorted(list(dates_set), reverse=True)
            except Exception as e:
                print(f"⚠️ WARNING - 月の日付一覧取得エラー: {e}")
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        month_name = month_names.get(month_param, month_param) if month_param else ""
        
        return render_template(
            "admin_daily_reports.html",
            selected_date=selected_date,
            year=year_param,
            month=month_param,
            month_name=month_name,
            month_dates=month_dates,
            in_house_items=in_house_items,
            visit_items=visit_items,
            field_items=field_items,
            in_house_day_total=in_house_day_total,
            visit_day_total=visit_day_total,
            field_day_total=field_day_total,
            in_house_month_total=in_house_month_total,
            visit_month_total=visit_month_total,
            field_month_total=field_month_total,
            is_admin=is_admin,
            staff_name=staff_name
        )
    except Exception as e:
        import traceback
        print(f"❌ 日報一覧取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("日報一覧の取得中にエラーが発生しました", "error")
        return redirect(url_for("admin_dashboard"))

@app.route("/admin/daily-reports/patient/<patient_report_id>/amount", methods=["POST"])
@staff_required
def admin_daily_reports_patient_amount(patient_report_id):
    """日報患者の金額を更新（予約データにも同期）"""
    try:
        amount_str = request.form.get("amount", "").strip()
        try:
            amount = int(amount_str) if amount_str else None
        except:
            amount = None
        
        if amount is None or amount < 0:
            flash("有効な金額を入力してください", "error")
            return redirect("/admin/daily-reports")
        
        # 日報患者情報を取得
        res_patient = supabase_admin.table("staff_daily_report_patients").select("id, reservation_id, amount").eq("id", patient_report_id).execute()
        if not res_patient.data:
            flash("日報患者情報が見つかりません", "error")
            return redirect("/admin/daily-reports")
        
        patient_report = res_patient.data[0]
        reservation_id = patient_report.get("reservation_id")
        
        # 日報患者の金額を更新
        supabase_admin.table("staff_daily_report_patients").update({"amount": amount}).eq("id", patient_report_id).execute()
        
        # 予約データにも同期（base_priceを更新）
        if reservation_id:
            try:
                supabase_admin.table("reservations").update({"base_price": amount}).eq("id", reservation_id).execute()
            except Exception as e:
                print(f"⚠️ WARNING - 予約データの同期エラー: {e}")
                # 日報更新は成功しているので警告のみ
        
        flash("金額を更新しました（予約データにも反映済み）", "success")
        return redirect(request.referrer or "/admin/daily-reports")
    except Exception as e:
        print("❌ 日報患者金額更新エラー:", e)
        flash("金額の更新に失敗しました", "error")
        return redirect("/admin/daily-reports")
    except Exception as e:
        import traceback
        print(f"❌ 日報一覧取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("日報一覧の取得に失敗しました", "error")
        return redirect("/admin/dashboard")


@app.route("/admin/daily-reports/item/<item_id>/update", methods=["POST"])
@staff_required
def admin_daily_reports_item_update(item_id):
    """日報勤務カードの更新（既存レコードを更新）"""
    try:
        # ログイン中のスタッフ情報を取得
        staff = session.get("staff", {})
        staff_name = staff.get("name", "スタッフ")
        is_admin = staff.get("is_admin", False)
        
        # 勤務カード情報を取得
        res_item = supabase_admin.table("staff_daily_report_items").select("*, daily_report_id").eq("id", item_id).execute()
        if not res_item.data:
            flash("勤務カードが見つかりません", "error")
            return redirect("/admin/daily-reports")
        
        item = res_item.data[0]
        daily_report_id = item.get("daily_report_id")
        work_type = item.get("work_type")  # 勤務カードのwork_typeを取得
        
        # 日報情報を取得してスタッフ名を確認
        res_report = supabase_admin.table("staff_daily_reports").select("staff_name").eq("id", daily_report_id).execute()
        if not res_report.data:
            flash("日報が見つかりません", "error")
            return redirect("/admin/daily-reports")
        
        report_staff_name = res_report.data[0].get("staff_name", "")
        
        # 編集権限チェック（スタッフは自分の分のみ、管理者は全て）
        if not is_admin and report_staff_name != staff_name:
            flash("編集権限がありません", "error")
            return redirect("/admin/daily-reports")
        
        # フォームデータを取得
        start_time = request.form.get("start_time", "").strip() or None
        end_time = request.form.get("end_time", "").strip() or None
        break_minutes_str = request.form.get("break_minutes", "").strip()
        break_minutes = int(break_minutes_str) if break_minutes_str and break_minutes_str.isdigit() else 0
        session_count_str = request.form.get("session_count", "").strip()
        session_count = int(session_count_str) if session_count_str and session_count_str.isdigit() else None
        memo = request.form.get("memo", "").strip() or None
        nomination_type = request.form.get("nomination_type", "").strip() or None
        
        # 勤務カードを更新
        update_data = {
            "start_time": start_time,
            "end_time": end_time,
            "break_minutes": break_minutes,
            "memo": memo,
            "nomination_type": nomination_type
        }
        if session_count is not None:
            update_data["session_count"] = session_count
        
        supabase_admin.table("staff_daily_report_items").update(update_data).eq("id", item_id).execute()
        
        # 患者情報の更新（複数患者に対応）
        patient_ids = request.form.getlist("patient_id[]")
        patient_amounts = request.form.getlist("patient_amount[]")
        patient_course_names = request.form.getlist("patient_course_name[]")
        patient_report_ids = request.form.getlist("patient_report_id[]")
        
        # 既存の患者情報を取得
        res_patients = supabase_admin.table("staff_daily_report_patients").select("*").eq("item_id", item_id).execute()
        existing_patients = res_patients.data or []
        existing_patient_report_ids = {p.get("id") for p in existing_patients}
        
        # 予約IDを収集してコース名を取得（院内・往診用）
        reservation_ids_for_course = []
        for p in existing_patients:
            reservation_id = p.get("reservation_id")
            if reservation_id:
                reservation_ids_for_course.append(reservation_id)
        
        reservation_course_map = {}
        if reservation_ids_for_course:
            try:
                res_reservations = supabase_admin.table("reservations").select("id, course_name, status").in_("id", reservation_ids_for_course).execute()
                if res_reservations.data:
                    for r in res_reservations.data:
                        if r.get("status") == "completed":
                            reservation_course_map[r.get("id")] = r.get("course_name", "")
            except Exception as e:
                print(f"⚠️ WARNING - 予約コース名取得エラー: {e}")
        
        # 患者情報を更新
        for i, patient_report_id in enumerate(patient_report_ids):
            if patient_report_id and patient_report_id in existing_patient_report_ids:
                # 既存の患者情報を更新
                patient_amount = int(patient_amounts[i]) if i < len(patient_amounts) and patient_amounts[i] and patient_amounts[i].isdigit() else 0
                patient_course_name = patient_course_names[i] if i < len(patient_course_names) else None
                
                # 予約データからコース名を取得（院内・往診用、編集時に反映）
                patient_data = next((p for p in existing_patients if p.get("id") == patient_report_id), None)
                if patient_data:
                    reservation_id = patient_data.get("reservation_id")
                    
                    # 院内・往診の場合、予約データからコース名を取得して反映（編集時に予約データの最新値を反映）
                    if work_type in ["in_house", "visit"] and reservation_id and reservation_id in reservation_course_map:
                        # 予約データからコース名を取得（入力値が空の場合は予約データの値を使用、入力値がある場合は入力値を優先）
                        reservation_course_name = reservation_course_map[reservation_id]
                        if reservation_course_name:
                            # 入力値が空の場合は予約データの値を使用、入力値がある場合は入力値を優先
                            if not patient_course_name or patient_course_name.strip() == "":
                                patient_course_name = reservation_course_name
                    
                    patient_update_data = {
                        "amount": patient_amount,
                        "course_name": patient_course_name if work_type in ["in_house", "visit"] else None
                    }
                    
                    # reservation_idがある場合は予約データも更新（院内・往診のみ）
                    if reservation_id and work_type in ["in_house", "visit"]:
                        try:
                            # 予約データのbase_priceを更新
                            supabase_admin.table("reservations").update({"base_price": patient_amount}).eq("id", reservation_id).execute()
                            # 予約データのcourse_nameを更新（編集時に変更があった場合）
                            if patient_course_name:
                                supabase_admin.table("reservations").update({"course_name": patient_course_name}).eq("id", reservation_id).execute()
                        except Exception as e:
                            print(f"⚠️ WARNING - 予約データの同期エラー: {e}")
                    elif work_type == "field":
                        # 帯同の場合、adminのみ金額編集可能（既に権限チェック済み）
                        # 帯同の金額はstaff_daily_report_patientsにのみ保存（予約データへの同期は不要）
                        pass
                    
                    # staff_daily_report_patientsを更新
                    supabase_admin.table("staff_daily_report_patients").update(patient_update_data).eq("id", patient_report_id).execute()
                else:
                    # patient_dataが見つからない場合でも更新を試みる
                    patient_update_data = {
                        "amount": patient_amount,
                        "course_name": patient_course_name if work_type in ["in_house", "visit"] else None
                    }
                    supabase_admin.table("staff_daily_report_patients").update(patient_update_data).eq("id", patient_report_id).execute()
        
        # 日報の日付を取得して適切にredirect
        res_report_for_date = supabase_admin.table("staff_daily_reports").select("report_date").eq("id", daily_report_id).execute()
        selected_date = res_report_for_date.data[0].get("report_date") if res_report_for_date.data else None
        
        flash("日報を更新しました", "success")
        if selected_date:
            return redirect(url_for("admin_daily_reports", date=selected_date))
        else:
            return redirect("/admin/daily-reports")
    except Exception as e:
        import traceback
        print(f"❌ 日報更新エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        
        # エラー時も日付を取得して適切にredirect
        try:
            res_item_error = supabase_admin.table("staff_daily_report_items").select("daily_report_id").eq("id", item_id).execute()
            if res_item_error.data:
                daily_report_id_error = res_item_error.data[0].get("daily_report_id")
                res_report_error = supabase_admin.table("staff_daily_reports").select("report_date").eq("id", daily_report_id_error).execute()
                selected_date_error = res_report_error.data[0].get("report_date") if res_report_error.data else None
                if selected_date_error:
                    flash("日報の更新に失敗しました", "error")
                    return redirect(url_for("admin_daily_reports", date=selected_date_error))
        except:
            pass
        
        flash("日報の更新に失敗しました", "error")
        return redirect("/admin/daily-reports")


# ===================================================
# スタッフ報告（管理者用）
# ===================================================
@app.route("/staff/daily-report/patient/<patient_report_id>/update", methods=["POST"])
@staff_required
def staff_daily_report_patient_update(patient_report_id):
    """スタッフ用：日報患者の金額とコース名を更新（金額は予約データにも同期）"""
    try:
        data = request.get_json()
        amount_str = data.get("amount", "") if data else request.form.get("amount", "").strip()
        course_name = data.get("course_name", "") if data else request.form.get("course_name", "").strip()
        
        try:
            amount = int(amount_str) if amount_str else None
        except:
            amount = None
        
        if amount is None or amount < 0:
            return jsonify({"success": False, "message": "有効な金額を入力してください"}), 400
        
        # 日報患者情報を取得
        res_patient = supabase_admin.table("staff_daily_report_patients").select("id, reservation_id, amount, course_name").eq("id", patient_report_id).execute()
        if not res_patient.data:
            return jsonify({"success": False, "message": "日報患者情報が見つかりません"}), 404
        
        patient_report = res_patient.data[0]
        reservation_id = patient_report.get("reservation_id")
        
        # 更新データを準備
        update_data = {
            "amount": amount
        }
        if course_name:
            update_data["course_name"] = course_name
        
        # 日報患者の金額とコース名を更新
        supabase_admin.table("staff_daily_report_patients").update(update_data).eq("id", patient_report_id).execute()
        
        # 予約データにも同期（base_priceを更新）
        if reservation_id:
            try:
                supabase_admin.table("reservations").update({"base_price": amount}).eq("id", reservation_id).execute()
                print(f"✅ 日報患者と予約データを更新しました: patient_report_id={patient_report_id}, reservation_id={reservation_id}, amount={amount}, course_name={course_name}")
            except Exception as e:
                print(f"⚠️ WARNING - 予約データの同期エラー: {e}")
                # 日報更新は成功しているので警告のみ
        
        return jsonify({"success": True, "message": "金額とコース名を更新しました（金額は予約データにも反映済み）"}), 200
    except Exception as e:
        print(f"❌ 日報患者更新エラー: {e}")
        import traceback
        print(traceback.format_exc())
        return jsonify({"success": False, "message": "更新に失敗しました"}), 500


@app.route("/admin/staff-reports")
@admin_required
def admin_staff_reports():
    """スタッフ報告一覧（承認済みスタッフのカード一覧）"""
    try:
        # 承認済みスタッフのみ取得
        users = supabase_admin.auth.admin.list_users()
        staff_list = []
        
        for u in users:
            meta = u.user_metadata or {}
            
            # 承認済みのみ表示
            if not meta.get("approved", False):
                continue
            
            # 姓・名から表示名を生成（半角スペース区切り）
            last_name = meta.get("last_name", "")
            first_name = meta.get("first_name", "")
            if last_name and first_name:
                display_name = f"{last_name} {first_name}"
            else:
                # 後方互換性：既存データはnameフィールドを使用
                display_name = meta.get("name", "未設定")
            
            # セイメイを生成
            last_kana = meta.get("last_kana", "")
            first_kana = meta.get("first_kana", "")
            if last_kana and first_kana:
                kana_name = f"{last_kana} {first_kana}"
            else:
                kana_name = meta.get("kana", "未入力")
            
            staff_list.append({
                "id": u.id,
                "email": u.email,
                "name": display_name,
                "kana": kana_name,
                "birthday": meta.get("birthday", "未入力"),
                "phone": meta.get("phone", "未登録"),
                "created_at": str(u.created_at)[:10] if u.created_at else "不明",
            })
        
        # 名前順でソート
        staff_list.sort(key=lambda x: x["name"])
        
        return render_template("admin_staff_reports.html", staff_list=staff_list)
    except Exception as e:
        print(f"❌ スタッフ報告一覧取得エラー: {e}")
        flash("スタッフ一覧の取得に失敗しました", "error")
        return redirect("/admin/dashboard")


@app.route("/admin/staff-reports/<staff_id>/menu")
@admin_required
def admin_staff_report_menu(staff_id):
    """スタッフ報告メニューページ（管理者用）"""
    try:
        # 現在ログイン中のスタッフIDを取得
        current_staff = session.get("staff", {})
        current_staff_id = current_staff.get("id")
        
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/staff-reports")
        
        meta = staff_user.user_metadata or {}
        
        # 姓・名から表示名を生成（半角スペース区切り）
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # 現在のログイン中のスタッフが自分のページにアクセスしている場合
        if current_staff_id == staff_id:
            # 編集可能なメニューを表示
            return render_template(
                "staff_profile_menu.html",
                staff=current_staff
            )
        else:
            # 他のスタッフの場合は閲覧のみ
            return render_template(
                "admin_staff_report_menu.html",
                staff_id=staff_id,
                staff_name=staff_name,
                staff_email=staff_user.email,
                staff_phone=meta.get("phone", "未登録")
            )
    except Exception as e:
        import traceback
        print(f"❌ スタッフ報告メニュー取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("スタッフ情報の取得に失敗しました", "error")
        return redirect("/admin/staff-reports")


@app.route("/admin/staff-reports/<staff_id>/reports")
@admin_required
def admin_staff_report_detail(staff_id):
    """各スタッフの報告閲覧ページ"""
    try:
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/staff-reports")
        
        meta = staff_user.user_metadata or {}
        
        # 姓・名から表示名を生成（半角スペース区切り）
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # クエリパラメータ取得
        work_type_filter = request.args.get("work_type", "all")
        date_from = request.args.get("date_from", "")
        date_to = request.args.get("date_to", "")
        
        # 該当スタッフの日報のみ取得
        query = supabase_admin.table("staff_daily_reports").select("*").eq("staff_name", staff_name).order("report_date", desc=True).order("created_at", desc=True)
        
        # フィルタ適用
        if date_from:
            query = query.gte("report_date", date_from)
        if date_to:
            query = query.lte("report_date", date_to)
        
        res_reports = query.execute()
        reports = res_reports.data or []
        
        # 各日報の勤務カードを取得
        report_ids = [r["id"] for r in reports]
        items_map = {}
        patients_map = {}
        
        if report_ids:
            # 勤務カードを一括取得
            res_items = supabase_admin.table("staff_daily_report_items").select("*").in_("daily_report_id", report_ids).order("created_at", desc=False).execute()
            items = res_items.data or []
            
            # フィルタ適用（work_type）
            if work_type_filter != "all":
                items = [item for item in items if item.get("work_type") == work_type_filter]
            
            # report_idごとにグループ化
            for item in items:
                report_id = item.get("daily_report_id")
                if report_id not in items_map:
                    items_map[report_id] = []
                items_map[report_id].append(item)
            
            # 患者・売上明細を一括取得
            item_ids = [item["id"] for item in items]
            patients = []
            patient_map = {}
            if item_ids:
                try:
                    res_patients = supabase_admin.table("staff_daily_report_patients").select("*").in_("item_id", item_ids).execute()
                    patients = res_patients.data or []
                    
                    # 患者情報を一括取得（名前表示用）
                    patient_ids_from_reports = [p.get("patient_id") for p in patients if p.get("patient_id")]
                    if patient_ids_from_reports:
                        res_patient_names = supabase_admin.table("patients").select("id, last_name, first_name, name").in_("id", patient_ids_from_reports).execute()
                        if res_patient_names.data:
                            for p in res_patient_names.data:
                                name = f"{p.get('last_name', '')} {p.get('first_name', '')}".strip()
                                patient_map[p["id"]] = name or p.get("name", "患者不明")
                    
                    # item_idごとにグループ化
                    for patient in patients:
                        item_id = patient.get("item_id")
                        if item_id not in patients_map:
                            patients_map[item_id] = []
                        patient_name = patient_map.get(patient.get("patient_id"), "患者不明")
                        patient["patient_name"] = patient_name
                        patients_map[item_id].append(patient)
                except Exception as e:
                    print(f"⚠️ WARNING - 日報患者情報取得エラー（テーブルが存在しない可能性）: {e}")
                    patients = []
                    patient_map = {}
        
        # 日報に勤務カードと患者情報を結合
        for report in reports:
            report_id = report["id"]
            report["items"] = []
            
            if report_id in items_map:
                for item in items_map[report_id]:
                    item_id = item["id"]
                    item["patients"] = patients_map.get(item_id, [])
                    
                    # 時間表示用のフォーマット
                    if item.get("start_time"):
                        try:
                            start_time_str = item["start_time"]
                            if isinstance(start_time_str, str) and len(start_time_str) >= 5:
                                item["start_time_display"] = start_time_str[:5]
                        except:
                            item["start_time_display"] = None
                    else:
                        item["start_time_display"] = None
                    
                    if item.get("end_time"):
                        try:
                            end_time_str = item["end_time"]
                            if isinstance(end_time_str, str) and len(end_time_str) >= 5:
                                item["end_time_display"] = end_time_str[:5]
                        except:
                            item["end_time_display"] = None
                    else:
                        item["end_time_display"] = None
                    
                    report["items"].append(item)
        
        return render_template(
            "admin_staff_report_detail.html",
            staff_id=staff_id,
            staff_name=staff_name,
            staff_email=staff_user.email,
            staff_phone=meta.get("phone", "未登録"),
            reports=reports,
            work_type_filter=work_type_filter,
            date_from=date_from,
            date_to=date_to,
            is_admin=True  # 管理者は閲覧のみ
        )
    except Exception as e:
        import traceback
        print(f"❌ スタッフ報告詳細取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("スタッフ報告の取得に失敗しました", "error")
        return redirect("/admin/staff-reports")


@app.route("/admin/staff-reports/<staff_id>/reports/years")
@admin_required
def admin_staff_reports_years(staff_id):
    """管理者用：年一覧ページ"""
    try:
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/staff-reports")
        
        meta = staff_user.user_metadata or {}
        
        # 姓・名から表示名を生成（半角スペース区切り）
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # 日報が存在する年を取得
        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").eq("staff_name", staff_name).order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        # 年を抽出して重複を除去
        years_set = set()
        for report in reports:
            report_date = report.get("report_date")
            if report_date:
                year = report_date[:4]  # YYYY-MM-DDから年を抽出
                years_set.add(year)
        
        years_list = sorted(years_set, reverse=True)  # 新しい年から順に
        
        return render_template("admin_staff_reports_years.html", years=years_list, staff_id=staff_id, staff_name=staff_name)
    except Exception as e:
        print(f"❌ 年一覧取得エラー: {e}")
        flash("年一覧の取得に失敗しました", "error")
        return redirect(f"/admin/staff-reports/{staff_id}/menu")


@app.route("/admin/staff-reports/<staff_id>/reports/years/<year>")
@admin_required
def admin_staff_reports_months(staff_id, year):
    """管理者用：月一覧ページ"""
    try:
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/staff-reports")
        
        meta = staff_user.user_metadata or {}
        
        # 姓・名から表示名を生成（半角スペース区切り）
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # 指定年の日報が存在する月を取得
        year_start = f"{year}-01-01"
        year_end = f"{year}-12-31"
        res_reports = supabase_admin.table("staff_daily_reports").select("report_date").eq("staff_name", staff_name).gte("report_date", year_start).lte("report_date", year_end).order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        # 月を抽出して重複を除去
        months_set = set()
        for report in reports:
            report_date = report.get("report_date")
            if report_date:
                month = report_date[5:7]  # YYYY-MM-DDから月を抽出
                months_set.add(month)
        
        months_list = sorted(months_set, reverse=True)  # 新しい月から順に
        
        # 月の日本語名をマッピング
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        
        months_with_names = [(m, month_names.get(m, m)) for m in months_list]
        
        return render_template("admin_staff_reports_months.html", year=year, months=months_with_names, staff_id=staff_id, staff_name=staff_name)
    except Exception as e:
        print(f"❌ 月一覧取得エラー: {e}")
        flash("月一覧の取得に失敗しました", "error")
        return redirect(f"/admin/staff-reports/{staff_id}/reports/years")


@app.route("/admin/staff-reports/<staff_id>/reports/years/<year>/months/<month>")
@admin_required
def admin_staff_reports_list(staff_id, year, month):
    """管理者用：日報一覧ページ（指定年月）"""
    try:
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/staff-reports")
        
        meta = staff_user.user_metadata or {}
        
        # 姓・名から表示名を生成（半角スペース区切り）
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # 指定年月の日報を取得
        month_start = f"{year}-{month}-01"
        # 月末日を計算
        if month in ["01", "03", "05", "07", "08", "10", "12"]:
            month_end = f"{year}-{month}-31"
        elif month in ["04", "06", "09", "11"]:
            month_end = f"{year}-{month}-30"
        else:  # 2月
            # うるう年判定（簡易版）
            year_int = int(year)
            if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                month_end = f"{year}-{month}-29"
            else:
                month_end = f"{year}-{month}-28"
        
        res_reports = supabase_admin.table("staff_daily_reports").select("*").eq("staff_name", staff_name).gte("report_date", month_start).lte("report_date", month_end).order("report_date", desc=True).execute()
        reports = res_reports.data or []
        
        # 各日報の勤務カードを取得
        report_ids = [r["id"] for r in reports]
        items_map = {}
        patients_map = {}
        
        if report_ids:
            # 勤務カードを一括取得
            res_items = supabase_admin.table("staff_daily_report_items").select("*").in_("daily_report_id", report_ids).order("created_at", desc=False).execute()
            items = res_items.data or []
            
            # report_idごとにグループ化
            for item in items:
                report_id = item.get("daily_report_id")
                if report_id not in items_map:
                    items_map[report_id] = []
                items_map[report_id].append(item)
            
            # 患者・売上明細を一括取得
            item_ids = [item["id"] for item in items]
            patients = []
            patient_map = {}
            if item_ids:
                try:
                    res_patients = supabase_admin.table("staff_daily_report_patients").select("*").in_("item_id", item_ids).execute()
                    patients = res_patients.data or []
                    
                    # 患者情報を一括取得（名前表示用）
                    patient_ids_from_reports = [p.get("patient_id") for p in patients if p.get("patient_id")]
                    if patient_ids_from_reports:
                        res_patient_names = supabase_admin.table("patients").select("id, last_name, first_name, name").in_("id", patient_ids_from_reports).execute()
                        if res_patient_names.data:
                            for p in res_patient_names.data:
                                name = f"{p.get('last_name', '')} {p.get('first_name', '')}".strip()
                                patient_map[p["id"]] = name or p.get("name", "患者不明")
                    
                    # item_idごとにグループ化
                    for patient in patients:
                        item_id = patient.get("item_id")
                        if item_id not in patients_map:
                            patients_map[item_id] = []
                        patient_name = patient_map.get(patient.get("patient_id"), "患者不明")
                        patient["patient_name"] = patient_name
                        patients_map[item_id].append(patient)
                except Exception as e:
                    print(f"⚠️ WARNING - 日報患者情報取得エラー（テーブルが存在しない可能性）: {e}")
                    patients = []
                    patient_map = {}
        
        # 日報に勤務カードと患者情報を結合
        for report in reports:
            report_id = report["id"]
            report["items"] = []
            
            if report_id in items_map:
                for item in items_map[report_id]:
                    item_id = item["id"]
                    item["patients"] = patients_map.get(item_id, [])
                    
                    # 時間表示用のフォーマット
                    if item.get("start_time"):
                        try:
                            start_time_str = item["start_time"]
                            if isinstance(start_time_str, str) and len(start_time_str) >= 5:
                                item["start_time_display"] = start_time_str[:5]
                        except:
                            item["start_time_display"] = None
                    else:
                        item["start_time_display"] = None
                    
                    if item.get("end_time"):
                        try:
                            end_time_str = item["end_time"]
                            if isinstance(end_time_str, str) and len(end_time_str) >= 5:
                                item["end_time_display"] = end_time_str[:5]
                        except:
                            item["end_time_display"] = None
                    else:
                        item["end_time_display"] = None
                    
                    report["items"].append(item)
        
        month_names = {
            "01": "1月", "02": "2月", "03": "3月", "04": "4月",
            "05": "5月", "06": "6月", "07": "7月", "08": "8月",
            "09": "9月", "10": "10月", "11": "11月", "12": "12月"
        }
        month_name = month_names.get(month, month)
        
        return render_template("admin_staff_reports_list.html", year=year, month=month, month_name=month_name, reports=reports, staff_id=staff_id, staff_name=staff_name, is_admin=True)
    except Exception as e:
        import traceback
        print(f"❌ 日報一覧取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("日報一覧の取得に失敗しました", "error")
        return redirect(f"/admin/staff-reports/{staff_id}/reports/years/{year}")


@app.route("/admin/staff-reports/<staff_id>/profile")
@admin_required
def admin_staff_report_profile(staff_id):
    """スタッフプロフィール閲覧ページ（管理者用、閲覧のみ）"""
    try:
        # 手技リスト（treatmentページから）
        treatment_options = [
            "鍼灸治療",
            "美容鍼",
            "整体",
            "ストレッチ",
            "リコンディショニング",
            "トレーニング",
            "テクニカ・ガビラン",
            "アクティベーター",
            "カッピング（吸玉）",
            "コンプレフロス",
            "オイルトリートメント",
            "トレーナー帯同"
        ]
        
        # スタッフ情報を取得
        users = supabase_admin.auth.admin.list_users()
        staff_user = next((u for u in users if u.id == staff_id), None)
        
        if not staff_user:
            flash("スタッフが見つかりません", "error")
            return redirect("/admin/staff-reports")
        
        meta = staff_user.user_metadata or {}
        
        # 姓・名から表示名を生成（半角スペース区切り）
        last_name = meta.get("last_name", "")
        first_name = meta.get("first_name", "")
        if last_name and first_name:
            staff_name = f"{last_name} {first_name}"
        else:
            staff_name = meta.get("name", "未設定")
        
        # プロフィール画像URLを取得し、相対パスの場合は解決
        profile_image_url = meta.get("profile_image_url", "")
        if profile_image_url and not profile_image_url.startswith("http"):
            # 相対パスの場合はurl_forで解決
            if profile_image_url.startswith("/static/"):
                filename = profile_image_url.replace("/static/", "")
                profile_image_url = url_for("static", filename=filename)
            elif profile_image_url.startswith("static/"):
                filename = profile_image_url.replace("static/", "")
                profile_image_url = url_for("static", filename=filename)
        
        # すべてのプロフィール情報を取得
        staff_data = {
            "id": staff_user.id,
            "email": staff_user.email,
            "name": staff_name,
            "last_name": last_name,
            "first_name": first_name,
            "last_kana": meta.get("last_kana", ""),
            "first_kana": meta.get("first_kana", ""),
            "birthday": meta.get("birthday", ""),
            "phone": meta.get("phone", ""),
            "postal_code": meta.get("postal_code", ""),
            "address": meta.get("address", ""),
            "hobbies_skills": meta.get("hobbies_skills", ""),
            "available_techniques": meta.get("available_techniques", []),  # リスト
            "one_word": meta.get("one_word", ""),
            "blog_comment": meta.get("blog_comment", ""),
            "profile_image_url": profile_image_url,
            "created_at": str(staff_user.created_at)[:10] if staff_user.created_at else "不明"
        }
        
        return render_template(
            "admin_staff_profile_view.html",
            staff_id=staff_id,
            staff=staff_data,
            staff_name=staff_name,
            treatment_options=treatment_options
        )
    except Exception as e:
        import traceback
        print(f"❌ スタッフプロフィール閲覧エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash("スタッフ情報の取得に失敗しました", "error")
        return redirect("/admin/staff-reports")


# ===================================================
# ✅ 報告書管理（/admin/reports）
# ===================================================
@app.route("/admin/reports")
@staff_required
def admin_reports():
    """報告書一覧（現場別）"""
    try:
        field_name_param = request.args.get("field_name", "").strip()
        
        if field_name_param:
            # 特定現場の報告書一覧を表示
            res = supabase_admin.table("field_reports").select("*").eq("field_name", field_name_param).order("report_date", desc=True).order("created_at", desc=True).execute()
            reports = res.data or []
            return render_template("admin_reports.html", reports=reports, selected_field_name=field_name_param, show_reports=True)
        else:
            # 現場ごとのカードを表示
            res = supabase_admin.table("field_reports").select("field_name").execute()
            all_reports = res.data or []
            
            # 現場名の一意なリストを取得（重複排除）
            field_names = list(set([r.get("field_name") for r in all_reports if r.get("field_name")]))
            field_names.sort()  # アルファベット順にソート
            
            # 各現場の報告書数を取得
            field_counts = {}
            for field_name in field_names:
                try:
                    count_res = supabase_admin.table("field_reports").select("id", count="exact").eq("field_name", field_name).execute()
                    field_counts[field_name] = count_res.count or 0
                except:
                    field_counts[field_name] = 0
            
            return render_template("admin_reports.html", field_names=field_names, field_counts=field_counts, show_reports=False)
    except Exception as e:
        print(f"❌ 報告書一覧取得エラー: {e}")
        flash("報告書一覧の取得に失敗しました", "error")
        return redirect("/admin/dashboard")


@app.route("/admin/reports/new", methods=["GET", "POST"])
@staff_required
def admin_reports_new():
    """新規報告書作成"""
    if request.method == "GET":
        try:
            # スタッフリスト取得
            staff = session.get("staff", {})
            staff_name = staff.get("name", "スタッフ")
            staff_list = []
            try:
                users = supabase_admin.auth.admin.list_users()
                for u in users:
                    meta = u.user_metadata or {}
                    if not meta.get("approved", False):
                        continue
                    last_name = meta.get("last_name", "")
                    first_name = meta.get("first_name", "")
                    if last_name and first_name:
                        display_name = f"{last_name} {first_name}"
                    else:
                        display_name = meta.get("name", "未設定")
                    staff_list.append({"name": display_name, "id": u.id})
                staff_list.sort(key=lambda x: x["name"])
            except Exception as e:
                print("❌ スタッフリスト取得エラー:", e)
                staff_list = [{"name": staff_name, "id": staff.get("id")}]
            
            # 複製元の報告書を取得（copy_from_fieldパラメータがある場合）
            copy_from_field = request.args.get("copy_from_field", "").strip()
            copy_from_report = None
            if copy_from_field:
                try:
                    res = supabase_admin.table("field_reports").select("*").eq("field_name", copy_from_field).order("report_date", desc=True).order("created_at", desc=True).limit(1).execute()
                    if res.data:
                        copy_from_report = res.data[0]
                except Exception as e:
                    print(f"⚠️ WARNING - 複製元報告書取得エラー: {e}")
            
            return render_template("admin_reports_new.html", staff_list=staff_list, staff_name=staff_name, copy_from_report=copy_from_report)
        except Exception as e:
            print(f"❌ 報告書作成画面取得エラー: {e}")
            flash("報告書作成画面の取得に失敗しました", "error")
            return redirect("/admin/reports")
    
    # POST処理
    try:
        field_name = request.form.get("field_name", "").strip()
        report_date = request.form.get("report_date", "").strip()
        place = request.form.get("place", "").strip() or None
        staff_names_raw = request.form.getlist("staff_names")
        staff_names = [s.strip() for s in staff_names_raw if s.strip()]
        special_notes = request.form.get("special_notes", "").strip() or None
        
        if not field_name or not report_date:
            flash("現場名と日付は必須です", "error")
            return redirect("/admin/reports/new")
        
        if not staff_names:
            flash("対応スタッフを1名以上選択してください", "error")
            return redirect("/admin/reports/new")
        
        # 列数を対応スタッフの人数に合わせて設定（n名ならn+1、最低3列）
        column_count = max(3, len(staff_names) + 1)
        
        # 開始時間・終了時間（デフォルト値）
        start_time = request.form.get("start_time", "07:00").strip() or "07:00"
        end_time = request.form.get("end_time", "22:00").strip() or "22:00"
        
        # 報告書を作成
        report_data = {
            "field_name": field_name,
            "report_date": report_date,
            "place": place,
            "staff_names": staff_names,
            "column_count": column_count,
            "special_notes": special_notes,
            "created_at": now_iso(),
            "updated_at": now_iso()
        }
        
        # start_timeとend_timeを追加（カラムが存在しない場合に備えてエラーハンドリング）
        def insert_report_with_time(data):
            try:
                data["start_time"] = start_time
                data["end_time"] = end_time
                return supabase_admin.table("field_reports").insert(data).execute()
            except Exception as e:
                error_str = str(e)
                # end_timeカラムが存在しない場合
                if "end_time" in error_str:
                    try:
                        # start_timeのみで再試行
                        data_no_end = data.copy()
                        if "end_time" in data_no_end:
                            del data_no_end["end_time"]
                        data_no_end["start_time"] = start_time
                        return supabase_admin.table("field_reports").insert(data_no_end).execute()
                    except Exception:
                        # start_timeも存在しない場合は、カラムなしで挿入
                        data_no_time = data.copy()
                        if "start_time" in data_no_time:
                            del data_no_time["start_time"]
                        if "end_time" in data_no_time:
                            del data_no_time["end_time"]
                        return supabase_admin.table("field_reports").insert(data_no_time).execute()
                raise

        try:
            res = insert_report_with_time(report_data)
        except Exception as e:
            error_str = str(e)
            if "column_count" in error_str or "check constraint" in error_str:
                # DB制約が3列以上の場合のフォールバック
                report_data_fallback = report_data.copy()
                report_data_fallback["column_count"] = 3
                res = insert_report_with_time(report_data_fallback)
                flash("列数制約のため3列で作成しました。2列にしたい場合はDB制約の更新が必要です。", "error")
            else:
                raise
        report_id = res.data[0]["id"] if res.data else None
        
        if not report_id:
            flash("報告書の作成に失敗しました", "error")
            return redirect("/admin/reports/new")
        
        # 時間スロットを初期化（開始時間〜終了時間、30分単位、各列）
        time_slots = []
        try:
            start_hour, start_min = parse_time_parts(start_time, 7, 0)
            end_hour, end_min = parse_time_parts(end_time, 22, 0)
            
            # 開始時間から終了時間まで30分刻みで生成
            current_hour = start_hour
            current_min = start_min
            while current_hour < end_hour or (current_hour == end_hour and current_min <= end_min):
                minute_str = f"{current_min:02d}"
                for col_idx in range(column_count):
                    time_slots.append({
                        "report_id": report_id,
                        "time": str(current_hour),
                        "time_minute": minute_str,
                        "column_index": col_idx,
                        "content": None,
                        "created_at": now_iso()
                    })
                
                # 30分進める
                current_min += 30
                if current_min >= 60:
                    current_hour += 1
                    current_min = 0
        except Exception as e:
            print(f"⚠️ WARNING - 時間スロット生成エラー: {e}")
            # エラー時はデフォルト値（7時〜22時、30分単位）
            for hour in range(7, 23):
                for minute in ['00', '30']:
                    for col_idx in range(column_count):
                        time_slots.append({
                            "report_id": report_id,
                            "time": str(hour),
                            "time_minute": minute,
                            "column_index": col_idx,
                            "content": None,
                            "created_at": now_iso()
                        })
        
        if time_slots:
            supabase_admin.table("field_report_time_slots").insert(time_slots).execute()
        
        # スタッフ詳細を初期化（患者情報を取得）
        staff_details = []
        for staff_name in staff_names:
            # 施術ログから自動反映（現場名（place_name）と日付が一致するもの）
            treatment_content = None
            status = None
            patient_id = None
            patient_name = None
            try:
                res_logs = supabase_admin.table("karte_logs").select("treatment, body_state, patient_id").eq("date", report_date).eq("place_name", field_name).eq("staff_name", staff_name).execute()
                if res_logs.data:
                    log = res_logs.data[0]
                    treatment_content = log.get("treatment")
                    status = log.get("body_state")
                    patient_id = log.get("patient_id")
                    
                    # 患者名を取得
                    if patient_id:
                        try:
                            res_patient = supabase_admin.table("patients").select("id, last_name, first_name, name").eq("id", patient_id).execute()
                            if res_patient.data:
                                p = res_patient.data[0]
                                last_name = p.get("last_name", "")
                                first_name = p.get("first_name", "")
                                if last_name or first_name:
                                    patient_name = f"{last_name} {first_name}".strip()
                                else:
                                    patient_name = p.get("name", "患者不明")
                        except:
                            pass
            except Exception as e:
                print(f"⚠️ WARNING - 施術ログ自動反映エラー: {e}")
                pass
            
            staff_details.append({
                "report_id": report_id,
                "staff_name": staff_name,
                "status": status,
                "treatment_content": treatment_content,
                "patient_name": patient_name,
                "created_at": now_iso()
            })
        
        if staff_details:
            try:
                supabase_admin.table("field_report_staff_details").insert(staff_details).execute()
            except Exception as e:
                error_str = str(e)
                if "patient_name" in error_str:
                    sanitized_details = []
                    for detail in staff_details:
                        detail_no_patient = detail.copy()
                        if "patient_name" in detail_no_patient:
                            del detail_no_patient["patient_name"]
                        sanitized_details.append(detail_no_patient)
                    supabase_admin.table("field_report_staff_details").insert(sanitized_details).execute()
                else:
                    raise
        
        flash("報告書を作成しました", "success")
        return redirect(f"/admin/reports/{report_id}/edit")
    except Exception as e:
        import traceback
        print(f"❌ 報告書作成エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash(f"報告書の作成に失敗しました: {e}", "error")
        return redirect("/admin/reports/new")


@app.route("/admin/reports/<report_id>/edit", methods=["GET", "POST"])
@staff_required
def admin_reports_edit(report_id):
    """報告書編集"""
    if request.method == "GET":
        try:
            res = supabase_admin.table("field_reports").select("*").eq("id", report_id).execute()
            if not res.data:
                flash("報告書が見つかりません", "error")
                return redirect("/admin/reports")
            report = res.data[0]
            
            # デフォルト値設定
            start_time = report.get("start_time", "07:00")
            end_time = report.get("end_time", "22:00")
            if not start_time:
                start_time = "07:00"
            if not end_time:
                end_time = "22:00"
            report["start_time"] = start_time
            report["end_time"] = end_time
            
            # 時間範囲を計算（テンプレート用、30分単位）
            time_ranges = []
            try:
                start_hour, start_min = parse_time_parts(start_time, 7, 0)
                end_hour, end_min = parse_time_parts(end_time, 22, 0)
                
                current_hour = start_hour
                current_min = start_min
                # 終了時間まで30分刻みで生成
                while current_hour < end_hour or (current_hour == end_hour and current_min <= end_min):
                    time_ranges.append({
                        "hour": current_hour,
                        "minute": current_min
                    })
                    current_min += 30
                    if current_min >= 60:
                        current_hour += 1
                        current_min = 0
            except Exception as e:
                print(f"⚠️ WARNING - 時間範囲計算エラー: {e}")
                # エラー時はデフォルト（7時〜22時、30分単位）
                for hour in range(7, 23):
                    time_ranges.append({"hour": hour, "minute": 0})
                    time_ranges.append({"hour": hour, "minute": 30})
            
            # 時間スロットを取得
            try:
                res_slots = supabase_admin.table("field_report_time_slots").select("*").eq("report_id", report_id).order("time").order("time_minute").order("column_index").execute()
                time_slots = res_slots.data or []
            except Exception as e:
                print(f"⚠️ WARNING - 時間スロット取得エラー: {e}")
                time_slots = []
            
            # 時間スロットをマップに変換（高速検索用）
            time_slots_map = {}
            for slot in time_slots:
                slot_time = slot.get('time', '')
                slot_minute = slot.get('time_minute', '00')
                slot_col = slot.get('column_index', 0)
                key = f"{slot_time}_{slot_minute}_{slot_col}"
                time_slots_map[key] = slot.get("content", "")
            
            # スタッフ詳細を取得
            try:
                res_staff = supabase_admin.table("field_report_staff_details").select("*").eq("report_id", report_id).execute()
                staff_details = res_staff.data or []
            except Exception as e:
                print(f"⚠️ WARNING - スタッフ詳細取得エラー: {e}")
                staff_details = []

            # 施術ログから最新情報を反映（現場名・日付・スタッフ名一致）
            staff_details_map = {d.get("staff_name"): d for d in staff_details if d.get("staff_name")}
            report_date_value = report.get("report_date")
            report_date_str = str(report_date_value) if report_date_value is not None else ""
            report_staff_names = report.get("staff_names") or []
            enriched_staff_details = []

            for staff_name in report_staff_names:
                detail = staff_details_map.get(staff_name, {
                    "report_id": report_id,
                    "staff_name": staff_name,
                    "status": None,
                    "treatment_content": None,
                    "patient_name": None
                })

                try:
                    res_logs = supabase_admin.table("karte_logs").select("treatment, body_state, patient_id").eq("date", report_date_str).eq("place_name", report["field_name"]).eq("staff_name", staff_name).order("created_at", desc=True).limit(1).execute()
                    if res_logs.data:
                        log = res_logs.data[0]
                        detail["treatment_content"] = log.get("treatment")
                        detail["status"] = log.get("body_state")
                        patient_id = log.get("patient_id")
                        if patient_id:
                            res_patient = supabase_admin.table("patients").select("id, last_name, first_name, name").eq("id", patient_id).execute()
                            if res_patient.data:
                                p = res_patient.data[0]
                                last_name = p.get("last_name", "")
                                first_name = p.get("first_name", "")
                                if last_name or first_name:
                                    detail["patient_name"] = f"{last_name} {first_name}".strip()
                                else:
                                    detail["patient_name"] = p.get("name", "患者不明")
                except Exception as e:
                    print(f"⚠️ WARNING - 施術ログ自動反映エラー: {e}")

                enriched_staff_details.append(detail)

            staff_details = enriched_staff_details
            
            # スタッフリスト取得
            staff = session.get("staff", {})
            staff_name = staff.get("name", "スタッフ")
            staff_list = []
            try:
                users = supabase_admin.auth.admin.list_users()
                for u in users:
                    meta = u.user_metadata or {}
                    if not meta.get("approved", False):
                        continue
                    last_name = meta.get("last_name", "")
                    first_name = meta.get("first_name", "")
                    if last_name and first_name:
                        display_name = f"{last_name} {first_name}"
                    else:
                        display_name = meta.get("name", "未設定")
                    staff_list.append({"name": display_name, "id": u.id})
                staff_list.sort(key=lambda x: x["name"])
            except Exception as e:
                print("❌ スタッフリスト取得エラー:", e)
                staff_list = [{"name": staff_name, "id": staff.get("id")}]
            
            return render_template("admin_reports_edit.html", report=report, time_slots=time_slots, time_slots_map=time_slots_map, time_ranges=time_ranges, staff_details=staff_details, staff_list=staff_list, staff_name=staff_name)
        except Exception as e:
            print(f"❌ 報告書取得エラー: {e}")
            flash("報告書の取得に失敗しました", "error")
            return redirect("/admin/reports")
    
    # POST処理
    try:
        field_name = request.form.get("field_name", "").strip()
        report_date = request.form.get("report_date", "").strip()
        place = request.form.get("place", "").strip() or None
        staff_names_raw = request.form.getlist("staff_names")
        staff_names = [s.strip() for s in staff_names_raw if s.strip()]
        special_notes = request.form.get("special_notes", "").strip() or None
        
        if not field_name or not report_date:
            flash("現場名と日付は必須です", "error")
            return redirect(f"/admin/reports/{report_id}/edit")
        
        if not staff_names:
            flash("対応スタッフを1名以上選択してください", "error")
            return redirect(f"/admin/reports/{report_id}/edit")
        
        # 列数を対応スタッフの人数に合わせて設定（n名ならn+1、最低3列）
        column_count = max(3, len(staff_names) + 1)
        
        # 開始時間・終了時間
        start_time = request.form.get("start_time", "07:00").strip() or "07:00"
        end_time = request.form.get("end_time", "22:00").strip() or "22:00"
        
        # 報告書を更新
        update_data = {
            "field_name": field_name,
            "report_date": report_date,
            "place": place,
            "staff_names": staff_names,
            "column_count": column_count,
            "start_time": start_time,
            "end_time": end_time,
            "special_notes": special_notes,
            "updated_at": now_iso()
        }

        try:
            supabase_admin.table("field_reports").update(update_data).eq("id", report_id).execute()
        except Exception as e:
            error_str = str(e)
            if "column_count" in error_str or "check constraint" in error_str:
                update_data_fallback = update_data.copy()
                update_data_fallback["column_count"] = 3
                supabase_admin.table("field_reports").update(update_data_fallback).eq("id", report_id).execute()
                flash("列数制約のため3列で更新しました。2列にしたい場合はDB制約の更新が必要です。", "error")
            else:
                raise
        
        # 時間スロットを更新
        # 既存のスロットを削除して再作成
        supabase_admin.table("field_report_time_slots").delete().eq("report_id", report_id).execute()
        
        time_slots = []
        try:
            start_hour, start_min = map(int, start_time.split(':'))
            end_hour, end_min = map(int, end_time.split(':'))
            
            # 開始時間から終了時間まで30分刻みで生成
            current_hour = start_hour
            current_min = start_min
            while current_hour < end_hour or (current_hour == end_hour and current_min <= end_min):
                minute_str = f"{current_min:02d}"
                for col_idx in range(column_count):
                    content_key = f"time_slot_{current_hour}_{minute_str}_{col_idx}"
                    content = request.form.get(content_key, "").strip() or None
                    time_slots.append({
                        "report_id": report_id,
                        "time": str(current_hour),
                        "time_minute": minute_str,
                        "column_index": col_idx,
                        "content": content,
                        "created_at": now_iso()
                    })
                
                # 30分進める
                current_min += 30
                if current_min >= 60:
                    current_hour += 1
                    current_min = 0
        except Exception as e:
            print(f"⚠️ WARNING - 時間スロット生成エラー: {e}")
            # エラー時はデフォルト値（7時〜26時）
            for hour in range(7, 27):
                for minute in ['00', '30']:
                    for col_idx in range(column_count):
                        content_key = f"time_slot_{hour}_{minute}_{col_idx}"
                        content = request.form.get(content_key, "").strip() or None
                        time_slots.append({
                            "report_id": report_id,
                            "time": str(hour),
                            "time_minute": minute,
                            "column_index": col_idx,
                            "content": content,
                            "created_at": now_iso()
                        })
        
        if time_slots:
            supabase_admin.table("field_report_time_slots").insert(time_slots).execute()
        
        # スタッフ詳細を更新（施術ログから自動反映）
        supabase_admin.table("field_report_staff_details").delete().eq("report_id", report_id).execute()
        
        staff_details = []
        for staff_name in staff_names:
            # 施術ログから自動反映（現場名（place_name）と日付が一致するもの）
            treatment_content = None
            status = None
            patient_name = None
            try:
                res_logs = supabase_admin.table("karte_logs").select("treatment, body_state, patient_id").eq("date", report_date).eq("place_name", field_name).eq("staff_name", staff_name).execute()
                if res_logs.data:
                    log = res_logs.data[0]
                    treatment_content = log.get("treatment")
                    status = log.get("body_state")
                    patient_id = log.get("patient_id")
                    
                    # 患者名を取得
                    if patient_id:
                        try:
                            res_patient = supabase_admin.table("patients").select("id, last_name, first_name, name").eq("id", patient_id).execute()
                            if res_patient.data:
                                p = res_patient.data[0]
                                last_name = p.get("last_name", "")
                                first_name = p.get("first_name", "")
                                if last_name or first_name:
                                    patient_name = f"{last_name} {first_name}".strip()
                                else:
                                    patient_name = p.get("name", "患者不明")
                        except Exception as e:
                            print(f"⚠️ WARNING - 患者名取得エラー: {e}")
            except Exception as e:
                print(f"⚠️ WARNING - 施術ログ自動反映エラー: {e}")
            
            staff_details.append({
                "report_id": report_id,
                "staff_name": staff_name,
                "status": status,
                "treatment_content": treatment_content,
                "patient_name": patient_name,
                "created_at": now_iso()
            })
        
        if staff_details:
            try:
                supabase_admin.table("field_report_staff_details").insert(staff_details).execute()
            except Exception as e:
                error_str = str(e)
                if "patient_name" in error_str:
                    sanitized_details = []
                    for detail in staff_details:
                        detail_no_patient = detail.copy()
                        if "patient_name" in detail_no_patient:
                            del detail_no_patient["patient_name"]
                        sanitized_details.append(detail_no_patient)
                    supabase_admin.table("field_report_staff_details").insert(sanitized_details).execute()
                else:
                    raise
        
        flash("報告書を更新しました", "success")
        return redirect(f"/admin/reports/{report_id}/edit")
    except Exception as e:
        import traceback
        print(f"❌ 報告書更新エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash(f"報告書の更新に失敗しました: {e}", "error")
        return redirect(f"/admin/reports/{report_id}/edit")


@app.route("/admin/reports/<report_id>/delete", methods=["POST"])
@staff_required
def admin_reports_delete(report_id):
    """報告書削除"""
    try:
        supabase_admin.table("field_reports").delete().eq("id", report_id).execute()
        flash("報告書を削除しました", "success")
    except Exception as e:
        print(f"❌ 報告書削除エラー: {e}")
        flash("報告書の削除に失敗しました", "error")
    return redirect("/admin/reports")


# ===================================================
# ✅ 備品管理
# ===================================================
@app.route("/admin/equipment")
@admin_required
def admin_equipment_years():
    """備品管理 - 年選択"""
    try:
        # 年初備品在庫が存在する年を取得
        try:
            res_initial = supabase_admin.table("equipment_initial_stock").select("year").order("year", desc=True).execute()
            initial_years = res_initial.data or []
            years_set = set()
            for item in initial_years:
                year = item.get("year")
                if year:
                    years_set.add(str(year))
            
            years_list = sorted([int(y) for y in years_set], reverse=True)
            years_list = [str(y) for y in years_list]
        except Exception as e:
            print(f"⚠️ WARNING - 備品年一覧取得エラー: {e}")
            years_list = []
        
        # 現在の年も追加（データがなくても選択できるように）
        current_year = str(datetime.now().year)
        if current_year not in years_list:
            years_list.insert(0, current_year)
        
        return render_template("admin_equipment_years.html", years=years_list)
    except Exception as e:
        print(f"❌ 年一覧取得エラー: {e}")
        flash("年一覧の取得に失敗しました", "error")
        return redirect("/admin/dashboard")


@app.route("/admin/equipment/years/<year>")
@admin_required
def admin_equipment_year_detail(year):
    """備品管理 - 指定年の詳細"""
    try:
        year_int = int(year)
        
        # 備品マスタを取得
        res_items = supabase_admin.table("equipment_items").select("*").order("name").execute()
        equipment_items = res_items.data or []
        
        # 年初備品在庫数を取得
        res_initial = supabase_admin.table("equipment_initial_stock").select("*, equipment_items(name, unit)").eq("year", year_int).execute()
        initial_stocks = res_initial.data or []
        initial_stock_map = {item["equipment_item_id"]: item["quantity"] for item in initial_stocks}
        
        # 持ち出し備品を取得
        res_takeouts = supabase_admin.table("equipment_takeouts").select("*, equipment_items(name, unit)").gte("takeout_date", f"{year_int}-01-01").lte("takeout_date", f"{year_int}-12-31").order("takeout_date", desc=True).execute()
        takeouts = res_takeouts.data or []
        
        # 発注備品を取得
        res_orders = supabase_admin.table("equipment_orders").select("*, equipment_items(name, unit)").gte("order_date", f"{year_int}-01-01").lte("order_date", f"{year_int}-12-31").order("order_date", desc=True).execute()
        orders = res_orders.data or []
        
        # 現在庫数を計算
        current_stock_map = {}
        for item in equipment_items:
            item_id = item["id"]
            initial_qty = initial_stock_map.get(item_id, 0)
            
            # 持ち出し数を集計
            takeout_qty = sum(t.get("quantity", 0) for t in takeouts if t.get("equipment_item_id") == item_id)
            
            # 到着済み発注数を集計
            arrived_qty = sum(o.get("quantity", 0) for o in orders if o.get("equipment_item_id") == item_id and o.get("status") == "arrived")
            
            current_stock = initial_qty - takeout_qty + arrived_qty
            current_stock_map[item_id] = current_stock
        
        return render_template(
            "admin_equipment_year_detail.html",
            year=year,
            equipment_items=equipment_items,
            initial_stocks=initial_stocks,
            initial_stock_map=initial_stock_map,
            takeouts=takeouts,
            orders=orders,
            current_stock_map=current_stock_map
        )
    except Exception as e:
        import traceback
        print(f"❌ 備品管理詳細取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash(f"備品管理詳細の取得に失敗しました: {e}", "error")
        return redirect("/admin/equipment")


@app.route("/admin/equipment/years/<year>/initial-stock/new", methods=["GET", "POST"])
@admin_required
def admin_equipment_initial_stock_new(year):
    """年初備品在庫数 - 新規作成"""
    if request.method == "POST":
        try:
            equipment_item_id = request.form.get("equipment_item_id")
            quantity = int(request.form.get("quantity", 0))
            
            # 既存データをチェック
            res_existing = supabase_admin.table("equipment_initial_stock").select("*").eq("year", int(year)).eq("equipment_item_id", equipment_item_id).execute()
            if res_existing.data:
                flash("この備品の年初在庫数は既に登録されています", "error")
                return redirect(f"/admin/equipment/years/{year}")
            
            # 新規作成
            supabase_admin.table("equipment_initial_stock").insert({
                "year": int(year),
                "equipment_item_id": equipment_item_id,
                "quantity": quantity
            }).execute()
            
            flash("年初備品在庫数を登録しました", "success")
            return redirect(f"/admin/equipment/years/{year}")
        except Exception as e:
            print(f"❌ 年初備品在庫数登録エラー: {e}")
            flash(f"年初備品在庫数の登録に失敗しました: {e}", "error")
            return redirect(f"/admin/equipment/years/{year}")
    
    # GET: 新規作成フォーム
    try:
        res_items = supabase_admin.table("equipment_items").select("*").order("name").execute()
        equipment_items = res_items.data or []
        
        # 既に登録されている備品IDを取得
        res_initial = supabase_admin.table("equipment_initial_stock").select("equipment_item_id").eq("year", int(year)).execute()
        registered_ids = {item["equipment_item_id"] for item in (res_initial.data or [])}
        
        # 未登録の備品のみ表示
        available_items = [item for item in equipment_items if item["id"] not in registered_ids]
        
        # URLパラメータで備品IDが指定されている場合
        selected_item_id = request.args.get("equipment_item_id")
        
        return render_template(
            "admin_equipment_initial_stock_new.html",
            year=year,
            equipment_items=available_items,
            selected_item_id=selected_item_id
        )
    except Exception as e:
        print(f"❌ 備品一覧取得エラー: {e}")
        flash("備品一覧の取得に失敗しました", "error")
        return redirect(f"/admin/equipment/years/{year}")


@app.route("/admin/equipment/years/<year>/initial-stock/<stock_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_equipment_initial_stock_edit(year, stock_id):
    """年初備品在庫数 - 編集"""
    if request.method == "POST":
        try:
            quantity = int(request.form.get("quantity", 0))
            
            supabase_admin.table("equipment_initial_stock").update({
                "quantity": quantity
            }).eq("id", stock_id).execute()
            
            flash("年初備品在庫数を更新しました", "success")
            return redirect(f"/admin/equipment/years/{year}")
        except Exception as e:
            print(f"❌ 年初備品在庫数更新エラー: {e}")
            flash(f"年初備品在庫数の更新に失敗しました: {e}", "error")
            return redirect(f"/admin/equipment/years/{year}")
    
    # GET: 編集フォーム
    try:
        res_stock = supabase_admin.table("equipment_initial_stock").select("*, equipment_items(name, unit)").eq("id", stock_id).execute()
        if not res_stock.data:
            flash("年初備品在庫数が見つかりません", "error")
            return redirect(f"/admin/equipment/years/{year}")
        
        stock = res_stock.data[0]
        return render_template(
            "admin_equipment_initial_stock_edit.html",
            year=year,
            stock=stock
        )
    except Exception as e:
        print(f"❌ 年初備品在庫数取得エラー: {e}")
        flash("年初備品在庫数の取得に失敗しました", "error")
        return redirect(f"/admin/equipment/years/{year}")


@app.route("/admin/equipment/years/<year>/takeouts/new", methods=["GET", "POST"])
@admin_required
def admin_equipment_takeout_new(year):
    """持ち出し備品 - 新規作成"""
    if request.method == "POST":
        try:
            takeout_date = request.form.get("takeout_date")
            equipment_item_id = request.form.get("equipment_item_id")
            quantity = int(request.form.get("quantity", 0))
            memo = request.form.get("memo", "").strip()
            
            supabase_admin.table("equipment_takeouts").insert({
                "takeout_date": takeout_date,
                "equipment_item_id": equipment_item_id,
                "quantity": quantity,
                "memo": memo
            }).execute()
            
            flash("持ち出し備品を登録しました", "success")
            return redirect(f"/admin/equipment/years/{year}")
        except Exception as e:
            print(f"❌ 持ち出し備品登録エラー: {e}")
            flash(f"持ち出し備品の登録に失敗しました: {e}", "error")
            return redirect(f"/admin/equipment/years/{year}")
    
    # GET: 新規作成フォーム
    try:
        res_items = supabase_admin.table("equipment_items").select("*").order("name").execute()
        equipment_items = res_items.data or []
        
        return render_template(
            "admin_equipment_takeout_new.html",
            year=year,
            equipment_items=equipment_items
        )
    except Exception as e:
        print(f"❌ 備品一覧取得エラー: {e}")
        flash("備品一覧の取得に失敗しました", "error")
        return redirect(f"/admin/equipment/years/{year}")


@app.route("/admin/equipment/years/<year>/takeouts/<takeout_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_equipment_takeout_edit(year, takeout_id):
    """持ち出し備品 - 編集"""
    if request.method == "POST":
        try:
            takeout_date = request.form.get("takeout_date")
            equipment_item_id = request.form.get("equipment_item_id")
            quantity = int(request.form.get("quantity", 0))
            memo = request.form.get("memo", "").strip()
            
            supabase_admin.table("equipment_takeouts").update({
                "takeout_date": takeout_date,
                "equipment_item_id": equipment_item_id,
                "quantity": quantity,
                "memo": memo
            }).eq("id", takeout_id).execute()
            
            flash("持ち出し備品を更新しました", "success")
            return redirect(f"/admin/equipment/years/{year}")
        except Exception as e:
            print(f"❌ 持ち出し備品更新エラー: {e}")
            flash(f"持ち出し備品の更新に失敗しました: {e}", "error")
            return redirect(f"/admin/equipment/years/{year}")
    
    # GET: 編集フォーム
    try:
        res_takeout = supabase_admin.table("equipment_takeouts").select("*, equipment_items(name, unit)").eq("id", takeout_id).execute()
        if not res_takeout.data:
            flash("持ち出し備品が見つかりません", "error")
            return redirect(f"/admin/equipment/years/{year}")
        
        takeout = res_takeout.data[0]
        res_items = supabase_admin.table("equipment_items").select("*").order("name").execute()
        equipment_items = res_items.data or []
        
        return render_template(
            "admin_equipment_takeout_edit.html",
            year=year,
            takeout=takeout,
            equipment_items=equipment_items
        )
    except Exception as e:
        print(f"❌ 持ち出し備品取得エラー: {e}")
        flash("持ち出し備品の取得に失敗しました", "error")
        return redirect(f"/admin/equipment/years/{year}")


@app.route("/admin/equipment/years/<year>/takeouts/<takeout_id>/delete", methods=["POST"])
@admin_required
def admin_equipment_takeout_delete(year, takeout_id):
    """持ち出し備品 - 削除"""
    try:
        supabase_admin.table("equipment_takeouts").delete().eq("id", takeout_id).execute()
        flash("持ち出し備品を削除しました", "success")
    except Exception as e:
        print(f"❌ 持ち出し備品削除エラー: {e}")
        flash("持ち出し備品の削除に失敗しました", "error")
    return redirect(f"/admin/equipment/years/{year}")


@app.route("/admin/equipment/years/<year>/orders/new", methods=["GET", "POST"])
@admin_required
def admin_equipment_order_new(year):
    """発注備品 - 新規作成"""
    if request.method == "POST":
        try:
            order_date = request.form.get("order_date")
            equipment_item_id = request.form.get("equipment_item_id")
            quantity = int(request.form.get("quantity", 0))
            amount = request.form.get("amount", "").strip()
            amount_decimal = float(amount) if amount else None
            status = request.form.get("status", "pending")
            arrival_date = request.form.get("arrival_date", "").strip() or None
            memo = request.form.get("memo", "").strip()
            
            order_data = {
                "order_date": order_date,
                "equipment_item_id": equipment_item_id,
                "quantity": quantity,
                "status": status,
                "memo": memo
            }
            
            if amount_decimal is not None:
                order_data["amount"] = amount_decimal
            
            if arrival_date:
                order_data["arrival_date"] = arrival_date
            
            supabase_admin.table("equipment_orders").insert(order_data).execute()
            
            flash("発注備品を登録しました", "success")
            return redirect(f"/admin/equipment/years/{year}")
        except Exception as e:
            print(f"❌ 発注備品登録エラー: {e}")
            flash(f"発注備品の登録に失敗しました: {e}", "error")
            return redirect(f"/admin/equipment/years/{year}")
    
    # GET: 新規作成フォーム
    try:
        res_items = supabase_admin.table("equipment_items").select("*").order("name").execute()
        equipment_items = res_items.data or []
        
        return render_template(
            "admin_equipment_order_new.html",
            year=year,
            equipment_items=equipment_items
        )
    except Exception as e:
        print(f"❌ 備品一覧取得エラー: {e}")
        flash("備品一覧の取得に失敗しました", "error")
        return redirect(f"/admin/equipment/years/{year}")


@app.route("/admin/equipment/years/<year>/orders/<order_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_equipment_order_edit(year, order_id):
    """発注備品 - 編集"""
    if request.method == "POST":
        try:
            order_date = request.form.get("order_date")
            equipment_item_id = request.form.get("equipment_item_id")
            quantity = int(request.form.get("quantity", 0))
            amount = request.form.get("amount", "").strip()
            amount_decimal = float(amount) if amount else None
            status = request.form.get("status", "pending")
            arrival_date = request.form.get("arrival_date", "").strip() or None
            memo = request.form.get("memo", "").strip()
            
            order_data = {
                "order_date": order_date,
                "equipment_item_id": equipment_item_id,
                "quantity": quantity,
                "status": status,
                "memo": memo
            }
            
            if amount_decimal is not None:
                order_data["amount"] = amount_decimal
            else:
                order_data["amount"] = None
            
            if arrival_date:
                order_data["arrival_date"] = arrival_date
            else:
                order_data["arrival_date"] = None
            
            supabase_admin.table("equipment_orders").update(order_data).eq("id", order_id).execute()
            
            flash("発注備品を更新しました", "success")
            return redirect(f"/admin/equipment/years/{year}")
        except Exception as e:
            print(f"❌ 発注備品更新エラー: {e}")
            flash(f"発注備品の更新に失敗しました: {e}", "error")
            return redirect(f"/admin/equipment/years/{year}")
    
    # GET: 編集フォーム
    try:
        res_order = supabase_admin.table("equipment_orders").select("*, equipment_items(name, unit)").eq("id", order_id).execute()
        if not res_order.data:
            flash("発注備品が見つかりません", "error")
            return redirect(f"/admin/equipment/years/{year}")
        
        order = res_order.data[0]
        res_items = supabase_admin.table("equipment_items").select("*").order("name").execute()
        equipment_items = res_items.data or []
        
        return render_template(
            "admin_equipment_order_edit.html",
            year=year,
            order=order,
            equipment_items=equipment_items
        )
    except Exception as e:
        print(f"❌ 発注備品取得エラー: {e}")
        flash("発注備品の取得に失敗しました", "error")
        return redirect(f"/admin/equipment/years/{year}")


@app.route("/admin/equipment/years/<year>/orders/<order_id>/delete", methods=["POST"])
@admin_required
def admin_equipment_order_delete(year, order_id):
    """発注備品 - 削除"""
    try:
        supabase_admin.table("equipment_orders").delete().eq("id", order_id).execute()
        flash("発注備品を削除しました", "success")
    except Exception as e:
        print(f"❌ 発注備品削除エラー: {e}")
        flash("発注備品の削除に失敗しました", "error")
    return redirect(f"/admin/equipment/years/{year}")


@app.route("/admin/equipment/items/new", methods=["GET", "POST"])
@admin_required
def admin_equipment_item_new():
    """備品マスタ - 新規作成"""
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            unit = request.form.get("unit", "").strip()
            
            if not name:
                flash("備品名を入力してください", "error")
                return redirect("/admin/equipment/items/new")
            
            supabase_admin.table("equipment_items").insert({
                "name": name,
                "unit": unit
            }).execute()
            
            flash("備品を登録しました", "success")
            return redirect("/admin/equipment")
        except Exception as e:
            print(f"❌ 備品登録エラー: {e}")
            flash(f"備品の登録に失敗しました: {e}", "error")
            return redirect("/admin/equipment/items/new")
    
    # GET: 新規作成フォーム
    return render_template("admin_equipment_item_new.html")


@app.route("/admin/equipment/years/<year>/copy-from-previous", methods=["POST"])
@admin_required
def admin_equipment_copy_from_previous(year):
    """前年の現在庫数を年初在庫数としてコピー"""
    try:
        year_int = int(year)
        prev_year = year_int - 1
        
        # 前年のデータを取得
        res_prev_initial = supabase_admin.table("equipment_initial_stock").select("*, equipment_items(name, unit)").eq("year", prev_year).execute()
        prev_initial_stocks = res_prev_initial.data or []
        
        # 前年の持ち出し備品を取得
        res_prev_takeouts = supabase_admin.table("equipment_takeouts").select("*").gte("takeout_date", f"{prev_year}-01-01").lte("takeout_date", f"{prev_year}-12-31").execute()
        prev_takeouts = res_prev_takeouts.data or []
        
        # 前年の到着済み発注備品を取得
        res_prev_orders = supabase_admin.table("equipment_orders").select("*").gte("order_date", f"{prev_year}-01-01").lte("order_date", f"{prev_year}-12-31").eq("status", "arrived").execute()
        prev_orders = res_prev_orders.data or []
        
        # 前年の現在庫数を計算
        prev_current_stock_map = {}
        for stock in prev_initial_stocks:
            item_id = stock["equipment_item_id"]
            initial_qty = stock.get("quantity", 0)
            
            # 持ち出し数を集計
            takeout_qty = sum(t.get("quantity", 0) for t in prev_takeouts if t.get("equipment_item_id") == item_id)
            
            # 到着済み発注数を集計
            arrived_qty = sum(o.get("quantity", 0) for o in prev_orders if o.get("equipment_item_id") == item_id)
            
            current_stock = initial_qty - takeout_qty + arrived_qty
            if current_stock > 0:
                prev_current_stock_map[item_id] = current_stock
        
        # 現在の年の既存データを取得
        res_current = supabase_admin.table("equipment_initial_stock").select("equipment_item_id").eq("year", year_int).execute()
        existing_ids = {item["equipment_item_id"] for item in (res_current.data or [])}
        
        # 前年の現在庫数を現在の年の年初在庫数として登録
        new_stocks = []
        for item_id, quantity in prev_current_stock_map.items():
            if item_id not in existing_ids:
                new_stocks.append({
                    "year": year_int,
                    "equipment_item_id": item_id,
                    "quantity": quantity
                })
        
        if new_stocks:
            supabase_admin.table("equipment_initial_stock").insert(new_stocks).execute()
            flash(f"{len(new_stocks)}件の備品を前年から引き継ぎました", "success")
        else:
            flash("引き継ぐ備品がありませんでした", "info")
        
        return redirect(f"/admin/equipment/years/{year}")
    except Exception as e:
        import traceback
        print(f"❌ 前年からの引き継ぎエラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash(f"前年からの引き継ぎに失敗しました: {e}", "error")
        return redirect(f"/admin/equipment/years/{year}")


# ===================================================
# ✅ 収支管理
# ===================================================
@app.route("/admin/financial")
@admin_required
def admin_financial_years():
    """収支管理 - 年選択"""
    try:
        # 経費が存在する年を取得
        years_set = set()
        try:
            res_expenses = supabase_admin.table("expenses").select("year").order("year", desc=True).execute()
            for exp in (res_expenses.data or []):
                if exp.get("year"):
                    years_set.add(str(exp.get("year")))
        except Exception as e:
            print(f"⚠️ WARNING - 経費年一覧取得エラー: {e}")
        
        # スタッフ給与が存在する年を取得
        try:
            res_salaries = supabase_admin.table("staff_salaries").select("year").order("year", desc=True).execute()
            for sal in (res_salaries.data or []):
                if sal.get("year"):
                    years_set.add(str(sal.get("year")))
        except Exception as e:
            print(f"⚠️ WARNING - 給与年一覧取得エラー: {e}")
        
        # 日報が存在する年も取得
        try:
            res_reports = supabase_admin.table("staff_daily_reports").select("report_date").order("report_date", desc=True).execute()
            for report in (res_reports.data or []):
                report_date = report.get("report_date")
                if report_date:
                    year = report_date[:4]
                    years_set.add(year)
        except Exception as e:
            print(f"⚠️ WARNING - 日報年一覧取得エラー: {e}")
        
        # 請求書が存在する年も取得
        try:
            res_invoices = supabase_admin.table("invoices").select("year").order("year", desc=True).execute()
            for inv in (res_invoices.data or []):
                if inv.get("year"):
                    years_set.add(str(inv.get("year")))
        except Exception as e:
            print(f"⚠️ WARNING - 請求書年一覧取得エラー: {e}")
        
        years_list = sorted([int(y) for y in years_set], reverse=True)
        years_list = [str(y) for y in years_list]
        
        # 現在の年も追加
        current_year = str(datetime.now().year)
        if current_year not in years_list:
            years_list.insert(0, current_year)
        
        return render_template("admin_financial_years.html", years=years_list)
    except Exception as e:
        print(f"❌ 年一覧取得エラー: {e}")
        flash("年一覧の取得に失敗しました", "error")
        return redirect("/admin/dashboard")


@app.route("/admin/financial/years/<year>")
@admin_required
def admin_financial_year_detail(year):
    """収支管理 - 指定年の全体収支"""
    try:
        year_int = int(year)
        
        # 売上を集計（日報データから）
        year_start = f"{year_int}-01-01"
        year_end = f"{year_int}-12-31"
        
        total_revenue = 0
        monthly_revenue = {}
        
        try:
            # 日報を取得
            res_reports = supabase_admin.table("staff_daily_reports").select("id, report_date").gte("report_date", year_start).lte("report_date", year_end).execute()
            report_ids = [r["id"] for r in (res_reports.data or [])]
            report_date_map = {r["id"]: r.get("report_date") for r in (res_reports.data or [])}
            
            if report_ids:
                # 患者情報を取得
                res_items = supabase_admin.table("staff_daily_report_items").select("id, daily_report_id").in_("daily_report_id", report_ids).execute()
                item_ids = [item["id"] for item in (res_items.data or [])]
                
                if item_ids:
                    res_patients = supabase_admin.table("staff_daily_report_patients").select("amount, item_id").in_("item_id", item_ids).execute()
                    for patient in (res_patients.data or []):
                        amount = patient.get("amount", 0) or 0
                        total_revenue += amount
                        
                        # 月別集計
                        item_id = patient.get("item_id")
                        for item in (res_items.data or []):
                            if item["id"] == item_id:
                                report_id = item.get("daily_report_id")
                                report_date = report_date_map.get(report_id, "")
                                if report_date:
                                    month = int(report_date[5:7])
                                    monthly_revenue[month] = monthly_revenue.get(month, 0) + amount
                                break
        except Exception as e:
            print(f"⚠️ WARNING - 日報売上集計エラー: {e}")
        
        # 請求書の売上を集計
        try:
            res_invoices = supabase_admin.table("invoices").select("total_amount, month").eq("year", year_int).execute()
            for inv in (res_invoices.data or []):
                amount = inv.get("total_amount", 0) or 0
                total_revenue += amount
                month = inv.get("month")
                if month:
                    monthly_revenue[month] = monthly_revenue.get(month, 0) + amount
        except Exception as e:
            print(f"⚠️ WARNING - 請求書売上集計エラー: {e}")
        
        # 経費を集計
        total_expenses = 0
        monthly_expenses = {}
        expense_by_category = {}
        
        try:
            res_expenses = supabase_admin.table("expenses").select("*").eq("year", year_int).execute()
            for exp in (res_expenses.data or []):
                amount = exp.get("amount", 0) or 0
                total_expenses += amount
                
                month = exp.get("month")
                if month:
                    monthly_expenses[month] = monthly_expenses.get(month, 0) + amount
                
                category = exp.get("category", "other")
                expense_by_category[category] = expense_by_category.get(category, 0) + amount
        except Exception as e:
            print(f"⚠️ WARNING - 経費集計エラー: {e}")
        
        # スタッフ給与を集計（経費テーブルに含まれているが、念のため確認）
        try:
            res_salaries = supabase_admin.table("staff_salaries").select("total_salary, year, month").eq("year", year_int).execute()
            for sal in (res_salaries.data or []):
                amount = sal.get("total_salary", 0) or 0
                # 経費テーブルに既に含まれている可能性があるが、カテゴリ別集計のために確認
                month = sal.get("month")
                if month:
                    # 経費テーブルに給与が登録されているか確認（重複カウントを避ける）
                    # ここでは経費テーブルに既に含まれていると仮定
                    pass
        except Exception as e:
            print(f"⚠️ WARNING - スタッフ給与集計エラー: {e}")
        
        # スタッフの日報での交通費申請を経費に追加
        try:
            res_transportations = supabase_admin.table("staff_daily_report_transportations").select("amount, date").gte("date", year_start).lte("date", year_end).execute()
            for trans in (res_transportations.data or []):
                amount = trans.get("amount", 0) or 0
                if amount:
                    total_expenses += amount
                    
                    trans_date = trans.get("date", "")
                    if trans_date:
                        month = int(trans_date[5:7])
                        monthly_expenses[month] = monthly_expenses.get(month, 0) + amount
                    
                    # 旅費交通費カテゴリに追加
                    expense_by_category["transportation"] = expense_by_category.get("transportation", 0) + amount
        except Exception as e:
            print(f"⚠️ WARNING - 日報交通費経費集計エラー: {e}")
        
        # 備品発注（到着済み）を経費に追加
        try:
            res_orders = supabase_admin.table("equipment_orders").select("amount, order_date, status").eq("status", "arrived").gte("order_date", year_start).lte("order_date", year_end).execute()
            for order in (res_orders.data or []):
                amount = order.get("amount", 0) or 0
                if amount:
                    total_expenses += amount
                    
                    order_date = order.get("order_date", "")
                    if order_date:
                        month = int(order_date[5:7])
                        monthly_expenses[month] = monthly_expenses.get(month, 0) + amount
                    
                    expense_by_category["supplies"] = expense_by_category.get("supplies", 0) + amount
        except Exception as e:
            print(f"⚠️ WARNING - 備品発注経費集計エラー: {e}")
        
        # 全体収支
        total_profit = total_revenue - total_expenses
        
        # 月別収支
        monthly_profit = {}
        for month in range(1, 13):
            revenue = monthly_revenue.get(month, 0)
            expense = monthly_expenses.get(month, 0)
            monthly_profit[month] = revenue - expense
        
        month_names = {
            1: "1月", 2: "2月", 3: "3月", 4: "4月",
            5: "5月", 6: "6月", 7: "7月", 8: "8月",
            9: "9月", 10: "10月", 11: "11月", 12: "12月"
        }
        
        # その年に日報を上げたスタッフを取得
        staff_list = []
        try:
            res_reports = supabase_admin.table("staff_daily_reports").select("staff_id, staff_name, report_date").gte("report_date", year_start).lte("report_date", year_end).execute()
            staff_map = {}
            for report in (res_reports.data or []):
                staff_id = report.get("staff_id")
                staff_name = report.get("staff_name") or "スタッフ不明"
                if staff_id:
                    staff_map[staff_id] = staff_name
                else:
                    # staff_idがない場合は名前でまとめる
                    staff_map[staff_name] = staff_name
            for key, name in staff_map.items():
                staff_list.append({
                    "id": key,
                    "name": name
                })
            staff_list = sorted(staff_list, key=lambda x: x["name"])
        except Exception as e:
            print(f"⚠️ WARNING - 年別スタッフ取得エラー: {e}")

        return render_template(
            "admin_financial_year_detail.html",
            year=year,
            total_revenue=total_revenue,
            total_expenses=total_expenses,
            total_profit=total_profit,
            monthly_revenue=monthly_revenue,
            monthly_expenses=monthly_expenses,
            monthly_profit=monthly_profit,
            expense_by_category=expense_by_category,
            month_names=month_names,
            staff_list=staff_list
        )
    except Exception as e:
        import traceback
        print(f"❌ 収支管理詳細取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash(f"収支管理詳細の取得に失敗しました: {e}", "error")
        return redirect("/admin/financial")


@app.route("/admin/financial/years/<year>/months/<month>")
@admin_required
def admin_financial_month_detail(year, month):
    """収支管理 - 指定年月の詳細"""
    try:
        year_int = int(year)
        month_int = int(month)
        
        # 月の開始日と終了日
        month_start = f"{year_int}-{month_int:02d}-01"
        if month_int in [1, 3, 5, 7, 8, 10, 12]:
            month_end = f"{year_int}-{month_int:02d}-31"
        elif month_int in [4, 6, 9, 11]:
            month_end = f"{year_int}-{month_int:02d}-30"
        else:
            if (year_int % 4 == 0 and year_int % 100 != 0) or (year_int % 400 == 0):
                month_end = f"{year_int}-{month_int:02d}-29"
            else:
                month_end = f"{year_int}-{month_int:02d}-28"
        
        # 売上を集計（日報データから）
        month_revenue = 0
        staff_revenue = {}  # スタッフ別売上
        
        try:
            res_reports = supabase_admin.table("staff_daily_reports").select("id, report_date, staff_name").gte("report_date", month_start).lte("report_date", month_end).execute()
            report_ids = [r["id"] for r in (res_reports.data or [])]
            report_staff_map = {r["id"]: r.get("staff_name", "") for r in (res_reports.data or [])}
            
            if report_ids:
                res_items = supabase_admin.table("staff_daily_report_items").select("id, daily_report_id").in_("daily_report_id", report_ids).execute()
                item_ids = [item["id"] for item in (res_items.data or [])]
                item_report_map = {item["id"]: item.get("daily_report_id") for item in (res_items.data or [])}
                
                if item_ids:
                    res_patients = supabase_admin.table("staff_daily_report_patients").select("amount, item_id").in_("item_id", item_ids).execute()
                    for patient in (res_patients.data or []):
                        amount = patient.get("amount", 0) or 0
                        month_revenue += amount
                        
                        item_id = patient.get("item_id")
                        report_id = item_report_map.get(item_id)
                        staff_name = report_staff_map.get(report_id, "")
                        if staff_name:
                            staff_revenue[staff_name] = staff_revenue.get(staff_name, 0) + amount
        except Exception as e:
            print(f"⚠️ WARNING - 日報売上集計エラー: {e}")
        
        # 請求書の売上を集計
        try:
            res_invoices = supabase_admin.table("invoices").select("total_amount").eq("year", year_int).eq("month", month_int).execute()
            for inv in (res_invoices.data or []):
                amount = inv.get("total_amount", 0) or 0
                month_revenue += amount
        except Exception as e:
            print(f"⚠️ WARNING - 請求書売上集計エラー: {e}")
        
        # 経費を取得
        expenses = []
        try:
            res_expenses = supabase_admin.table("expenses").select("*").eq("year", year_int).eq("month", month_int).order("expense_date", desc=True).execute()
            expenses = res_expenses.data or []
        except Exception as e:
            print(f"⚠️ WARNING - 経費取得エラー: {e}")
        
        # スタッフの日報での交通費申請を経費に追加
        try:
            res_transportations = supabase_admin.table("staff_daily_report_transportations").select("*, staff_daily_reports!inner(staff_name, staff_id)").gte("date", month_start).lte("date", month_end).execute()
            for trans in (res_transportations.data or []):
                amount = trans.get("amount", 0) or 0
                if amount:
                    report_info = trans.get("staff_daily_reports")
                    if report_info:
                        # リレーションが配列の場合とオブジェクトの場合に対応
                        if isinstance(report_info, list) and len(report_info) > 0:
                            report_info = report_info[0]
                        if isinstance(report_info, dict):
                            staff_name = report_info.get("staff_name", "")
                            staff_id = report_info.get("staff_id")
                        else:
                            staff_name = ""
                            staff_id = None
                    else:
                        staff_name = ""
                        staff_id = None
                    
                    # 経費として追加（既にexpensesテーブルに登録されている可能性があるため、重複チェック）
                    trans_date = trans.get("date", "")
                    if trans_date:
                        # 同じ日付・同じスタッフ・同じ金額の経費が既に存在するかチェック
                        existing = False
                        for exp in expenses:
                            if (exp.get("expense_date") == trans_date and 
                                exp.get("staff_id") == staff_id and 
                                abs(exp.get("amount", 0) - amount) < 0.01 and
                                exp.get("category") in ["transportation", "travel"]):
                                existing = True
                                break
                        
                        if not existing:
                            expenses.append({
                                "id": trans.get("id"),
                                "expense_date": trans_date,
                                "year": year_int,
                                "month": month_int,
                                "category": "transportation",
                                "amount": amount,
                                "description": f"交通費申請{(' - ' + staff_name) if staff_name else ''}",
                                "staff_id": staff_id,
                                "staff_name": staff_name,
                                "linked_type": "daily_report_transportation",
                                "linked_id": trans.get("id")
                            })
        except Exception as e:
            print(f"⚠️ WARNING - 日報交通費経費追加エラー: {e}")
            # リレーションクエリが失敗する場合、別の方法で取得
            try:
                res_transportations = supabase_admin.table("staff_daily_report_transportations").select("id, amount, date, daily_report_id").gte("date", month_start).lte("date", month_end).execute()
                report_ids = list(set([t.get("daily_report_id") for t in (res_transportations.data or []) if t.get("daily_report_id")]))
                report_map = {}
                if report_ids:
                    res_reports = supabase_admin.table("staff_daily_reports").select("id, staff_name, staff_id").in_("id", report_ids).execute()
                    for r in (res_reports.data or []):
                        report_map[r.get("id")] = r
                
                for trans in (res_transportations.data or []):
                    amount = trans.get("amount", 0) or 0
                    if amount:
                        daily_report_id = trans.get("daily_report_id")
                        report_info = report_map.get(daily_report_id) if daily_report_id else None
                        staff_name = report_info.get("staff_name", "") if report_info else ""
                        staff_id = report_info.get("staff_id") if report_info else None
                        
                        trans_date = trans.get("date", "")
                        if trans_date:
                            existing = False
                            for exp in expenses:
                                if (exp.get("expense_date") == trans_date and 
                                    exp.get("staff_id") == staff_id and 
                                    abs(exp.get("amount", 0) - amount) < 0.01 and
                                    exp.get("category") in ["transportation", "travel"]):
                                    existing = True
                                    break
                            
                            if not existing:
                                expenses.append({
                                    "id": trans.get("id"),
                                    "expense_date": trans_date,
                                    "year": year_int,
                                    "month": month_int,
                                    "category": "transportation",
                                    "amount": amount,
                                    "description": f"交通費申請{(' - ' + staff_name) if staff_name else ''}",
                                    "staff_id": staff_id,
                                    "staff_name": staff_name,
                                    "linked_type": "daily_report_transportation",
                                    "linked_id": trans.get("id")
                                })
            except Exception as e2:
                print(f"⚠️ WARNING - 日報交通費経費追加（フォールバック）エラー: {e2}")
        
        # 予約割引の表示名（予約者名）に差し替え
        try:
            reservation_ids = set()
            for exp in expenses:
                if exp.get("linked_type") == "reservation_discount":
                    raw = exp.get("memo") or exp.get("description") or ""
                    match = re.search(r"予約ID[:：]\s*([0-9a-fA-F-]+)", raw)
                    if match:
                        reservation_ids.add(match.group(1))

            if reservation_ids:
                res_reservations = supabase_admin.table("reservations").select("id, patient_id").in_("id", list(reservation_ids)).execute()
                reservations = res_reservations.data or []
                patient_ids = [r.get("patient_id") for r in reservations if r.get("patient_id")]
                patient_map = {}
                if patient_ids:
                    res_patients = supabase_admin.table("patients").select("id, last_name, first_name, name").in_("id", patient_ids).execute()
                    for p in (res_patients.data or []):
                        name = f"{p.get('last_name', '')} {p.get('first_name', '')}".strip()
                        patient_map[p.get("id")] = name or p.get("name", "予約者不明")
                reservation_patient_map = {r.get("id"): patient_map.get(r.get("patient_id"), "予約者不明") for r in reservations}

                for exp in expenses:
                    if exp.get("linked_type") == "reservation_discount":
                        raw = exp.get("memo") or exp.get("description") or ""
                        match = re.search(r"予約ID[:：]\s*([0-9a-fA-F-]+)", raw)
                        if match:
                            res_id = match.group(1)
                            patient_name = reservation_patient_map.get(res_id, "予約者不明")
                            description = exp.get("description") or "施術割引"
                            prefix = description.split("（")[0].strip() if "（" in description else description.strip()
                            exp["display_description"] = f"{prefix}（{patient_name}）"
        except Exception as e:
            print(f"⚠️ WARNING - 割引表示名変換エラー: {e}")

        # 備品発注（到着済み）を取得
        equipment_expenses = []
        try:
            res_orders = supabase_admin.table("equipment_orders").select("*, equipment_items(name)").eq("status", "arrived").gte("order_date", month_start).lte("order_date", month_end).execute()
            equipment_expenses = res_orders.data or []
        except Exception as e:
            print(f"⚠️ WARNING - 備品発注取得エラー: {e}")
        
        # スタッフ給与を取得
        staff_salaries = []
        try:
            res_salaries = supabase_admin.table("staff_salaries").select("*").eq("year", year_int).eq("month", month_int).order("staff_name").execute()
            staff_salaries = res_salaries.data or []
        except Exception as e:
            print(f"⚠️ WARNING - スタッフ給与取得エラー: {e}")
        
        # 経費合計
        month_expenses = sum(exp.get("amount", 0) or 0 for exp in expenses)
        month_expenses += sum(e.get("amount", 0) or 0 for e in equipment_expenses)
        month_expenses += sum(sal.get("total_salary", 0) or 0 for sal in staff_salaries)
        
        # 月の収支
        month_profit = month_revenue - month_expenses
        
        month_name = {
            1: "1月", 2: "2月", 3: "3月", 4: "4月",
            5: "5月", 6: "6月", 7: "7月", 8: "8月",
            9: "9月", 10: "10月", 11: "11月", 12: "12月"
        }.get(month_int, f"{month_int}月")
        
        return render_template(
            "admin_financial_month_detail.html",
            year=year,
            month=month,
            month_name=month_name,
            month_revenue=month_revenue,
            month_expenses=month_expenses,
            month_profit=month_profit,
            staff_revenue=staff_revenue,
            expenses=expenses,
            equipment_expenses=equipment_expenses,
            staff_salaries=staff_salaries
        )
    except Exception as e:
        import traceback
        print(f"❌ 月次収支管理詳細取得エラー: {e}")
        print(f"❌ トレースバック: {traceback.format_exc()}")
        flash(f"月次収支管理詳細の取得に失敗しました: {e}", "error")
        return redirect(f"/admin/financial/years/{year}")


@app.route("/admin/financial/years/<year>/staff/<staff_id>")
@admin_required
def admin_financial_staff_months(year, staff_id):
    """収支管理 - スタッフ別の月一覧（給与）"""
    try:
        year_int = int(year)
        year_start = f"{year_int}-01-01"
        year_end = f"{year_int}-12-31"

        staff_name = None
        staff_area = "tokyo"
        try:
            users = supabase_admin.auth.admin.list_users()
            for u in users:
                if u.id == staff_id:
                    meta = u.user_metadata or {}
                    staff_name = f"{meta.get('last_name', '')} {meta.get('first_name', '')}".strip() or u.email
                    staff_area = meta.get("area", "tokyo")
                    break
        except Exception as e:
            print(f"⚠️ WARNING - スタッフ情報取得エラー: {e}")

        if not staff_name:
            staff_name = staff_id

        # 日報がある月を取得
        months_set = set()
        try:
            res_reports = supabase_admin.table("staff_daily_reports").select("report_date, staff_id, staff_name").gte("report_date", year_start).lte("report_date", year_end).execute()
            for report in (res_reports.data or []):
                report_staff_id = report.get("staff_id")
                report_staff_name = report.get("staff_name")
                if (report_staff_id and report_staff_id == staff_id) or (not report_staff_id and staff_name and report_staff_name == staff_name):
                    report_date = report.get("report_date")
                    if report_date and len(report_date) >= 7:
                        months_set.add(int(report_date[5:7]))
        except Exception as e:
            print(f"⚠️ WARNING - スタッフ月一覧取得エラー: {e}")

        months_list = sorted(list(months_set))
        month_cards = [{"num": m, "label": f"{m}月給与"} for m in months_list]

        return render_template(
            "admin_financial_staff_months.html",
            year=year,
            staff_id=staff_id,
            staff_name=staff_name or "スタッフ",
            staff_area=staff_area,
            month_cards=month_cards
        )
    except Exception as e:
        print(f"❌ スタッフ月一覧取得エラー: {e}")
        flash("スタッフ月一覧の取得に失敗しました", "error")
        return redirect(f"/admin/financial/years/{year}")


@app.route("/admin/financial/years/<year>/staff/<staff_id>/months/<month>")
@admin_required
def admin_financial_staff_salary_detail(year, staff_id, month):
    """収支管理 - スタッフ別給与詳細"""
    try:
        year_int = int(year)
        month_int = int(month)

        staff_name = None
        staff_area = "tokyo"
        try:
            users = supabase_admin.auth.admin.list_users()
            for u in users:
                if u.id == staff_id:
                    meta = u.user_metadata or {}
                    staff_name = f"{meta.get('last_name', '')} {meta.get('first_name', '')}".strip() or u.email
                    staff_area = meta.get("area", "tokyo")
                    break
        except Exception as e:
            print(f"⚠️ WARNING - スタッフ情報取得エラー: {e}")

        if not staff_name:
            staff_name = staff_id

        # 登録済み給与を優先
        salary = None
        try:
            res_salary = supabase_admin.table("staff_salaries").select("*").eq("year", year_int).eq("month", month_int).eq("staff_id", staff_id).execute()
            if res_salary.data:
                salary = res_salary.data[0]
        except Exception as e:
            print(f"⚠️ WARNING - スタッフ給与取得エラー: {e}")

        salary_calc = None
        bonus_calc = 0
        if not salary:
            try:
                if not staff_name:
                    # 日報から名前を補完
                    res_reports = supabase_admin.table("staff_daily_reports").select("staff_name").eq("staff_id", staff_id).gte("report_date", f"{year_int}-{month_int:02d}-01").lte("report_date", f"{year_int}-{month_int:02d}-31").execute()
                    if res_reports.data:
                        staff_name = res_reports.data[0].get("staff_name") or "スタッフ"
                salary_calc = calculate_salary(staff_name or "スタッフ", year_int, month_int, staff_area)
                bonus_result = calculate_special_bonus(
                    year_int,
                    month_int,
                    staff_id,
                    staff_name or "スタッフ",
                    salary_calc.get("base_salary", 0) or 0,
                    salary_calc.get("commission", 0) or 0,
                    salary_calc.get("nomination_fee", 0) or 0
                )
                bonus_calc = bonus_result["bonus"]
            except Exception as e:
                print(f"⚠️ WARNING - 給与自動計算エラー: {e}")
        else:
            try:
                bonus_result = calculate_special_bonus(
                    year_int,
                    month_int,
                    staff_id,
                    staff_name or "スタッフ",
                    salary.get("base_salary", 0) or 0,
                    salary.get("commission", 0) or 0,
                    salary.get("nomination_fee", 0) or 0,
                    exclude_salary_id=salary.get("id")
                )
                bonus_calc = salary.get("special_bonus") or bonus_result["bonus"]
            except Exception as e:
                print(f"⚠️ WARNING - 特別給計算エラー: {e}")

        return render_template(
            "admin_financial_staff_salary_detail.html",
            year=year,
            month=f"{month_int:02d}",
            staff_id=staff_id,
            staff_name=staff_name or "スタッフ",
            salary=salary,
            salary_calc=salary_calc,
            bonus_calc=bonus_calc
        )
    except Exception as e:
        print(f"❌ スタッフ給与詳細取得エラー: {e}")
        flash("スタッフ給与詳細の取得に失敗しました", "error")
        return redirect(f"/admin/financial/years/{year}")


@app.route("/admin/financial/years/<year>/expenses/new", methods=["GET", "POST"])
@admin_required
def admin_financial_expense_new(year):
    """経費 - 新規作成"""
    if request.method == "POST":
        try:
            expense_date = request.form.get("expense_date")
            category = request.form.get("category")
            amount = float(request.form.get("amount", 0))
            description = request.form.get("description", "").strip()
            staff_id = request.form.get("staff_id", "").strip() or None
            staff_name = request.form.get("staff_name", "").strip() or None
            memo = request.form.get("memo", "").strip()
            
            # 年月を抽出
            year_int = int(year)
            month_int = int(expense_date[5:7])
            
            expense_data = {
                "expense_date": expense_date,
                "year": year_int,
                "month": month_int,
                "category": category,
                "amount": amount,
                "description": description,
                "memo": memo,
                "linked_type": "manual"
            }
            
            if staff_id:
                expense_data["staff_id"] = staff_id
            if staff_name:
                expense_data["staff_name"] = staff_name
            
            supabase_admin.table("expenses").insert(expense_data).execute()
            
            flash("経費を登録しました", "success")
            return redirect(f"/admin/financial/years/{year}/months/{month_int:02d}")
        except Exception as e:
            print(f"❌ 経費登録エラー: {e}")
            flash(f"経費の登録に失敗しました: {e}", "error")
            return redirect(f"/admin/financial/years/{year}")
    
    # GET: 新規作成フォーム
    try:
        # スタッフ一覧を取得
        users = supabase_admin.auth.admin.list_users()
        staff_list = []
        for user in users:
            meta = user.user_metadata or {}
            if meta.get("approved") == True:
                name = f"{meta.get('last_name', '')} {meta.get('first_name', '')}".strip()
                if not name:
                    name = user.email
                staff_list.append({
                    "id": user.id,
                    "name": name,
                    "area": meta.get("area", "tokyo")
                })
        
        return render_template(
            "admin_financial_expense_new.html",
            year=year,
            staff_list=staff_list
        )
    except Exception as e:
        print(f"❌ 経費新規作成フォーム取得エラー: {e}")
        flash("フォームの取得に失敗しました", "error")
        return redirect(f"/admin/financial/years/{year}")


@app.route("/admin/financial/years/<year>/expenses/<expense_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_financial_expense_edit(year, expense_id):
    """経費 - 編集"""
    if request.method == "POST":
        try:
            res_existing = supabase_admin.table("expenses").select("*").eq("id", expense_id).execute()
            existing_expense = res_existing.data[0] if res_existing.data else None
            linked_type = existing_expense.get("linked_type") if existing_expense else None
            transportation_record = None

            if not existing_expense:
                res_transport = supabase_admin.table("staff_daily_report_transportations").select("*").eq("id", expense_id).execute()
                if res_transport.data:
                    transportation_record = res_transport.data[0]
                    linked_type = "daily_report_transportation"
                else:
                    flash("経費が見つかりません", "error")
                    return redirect(f"/admin/financial/years/{year}")

            expense_date = request.form.get("expense_date")
            category = request.form.get("category")
            amount = float(request.form.get("amount", 0))
            description = request.form.get("description", "").strip()
            staff_id = request.form.get("staff_id", "").strip() or None
            staff_name = request.form.get("staff_name", "").strip() or None
            memo = request.form.get("memo", "").strip()
            
            # 年月を抽出
            year_int = int(year)
            month_int = int(expense_date[5:7])
            
            # linked_typeに応じて編集内容を調整
            if linked_type == "salary":
                category = "salary"
                staff_id = existing_expense.get("staff_id")
                staff_name = existing_expense.get("staff_name")
            elif linked_type == "daily_report_transportation":
                # 交通費はスタッフ情報を固定
                if transportation_record:
                    report_id = transportation_record.get("daily_report_id")
                    report_staff_id = None
                    report_staff_name = None
                    if report_id:
                        res_report = supabase_admin.table("staff_daily_reports").select("staff_id, staff_name").eq("id", report_id).execute()
                        if res_report.data:
                            report_staff_id = res_report.data[0].get("staff_id")
                            report_staff_name = res_report.data[0].get("staff_name")
                    staff_id = report_staff_id
                    staff_name = report_staff_name
                category = "transportation"

            expense_data = {
                "expense_date": expense_date,
                "year": year_int,
                "month": month_int,
                "category": category,
                "amount": amount,
                "description": description,
                "memo": memo
            }
            
            if staff_id:
                expense_data["staff_id"] = staff_id
            else:
                expense_data["staff_id"] = None
            if staff_name:
                expense_data["staff_name"] = staff_name
            else:
                expense_data["staff_name"] = None
            
            if existing_expense:
                supabase_admin.table("expenses").update(expense_data).eq("id", expense_id).execute()
            elif linked_type == "daily_report_transportation":
                # 交通費はexpensesに保存して紐付け（以後はexpensesで編集）
                expense_data["linked_type"] = "daily_report_transportation"
                expense_data["linked_id"] = expense_id
                supabase_admin.table("expenses").insert(expense_data).execute()

            # linked_typeがある場合は関連データも更新
            if linked_type == "salary" and staff_id:
                try:
                    res_salary = supabase_admin.table("staff_salaries").select("*").eq("year", existing_expense.get("year")).eq("month", existing_expense.get("month")).eq("staff_id", staff_id).execute()
                    if res_salary.data:
                        salary = res_salary.data[0]
                        net_salary = amount - (salary.get("tax", 0) or 0) - (salary.get("social_insurance", 0) or 0) - (salary.get("other_deduction", 0) or 0)
                        salary_update = {
                            "total_salary": amount,
                            "net_salary": net_salary,
                            "memo": memo
                        }
                        # 日付変更がある場合は年月も更新
                        if expense_date:
                            salary_update["year"] = year_int
                            salary_update["month"] = month_int
                        supabase_admin.table("staff_salaries").update(salary_update).eq("id", salary["id"]).execute()
                except Exception as e:
                    print(f"⚠️ WARNING - 給与連動更新エラー: {e}")
            elif linked_type == "daily_report_transportation":
                try:
                    linked_id = (existing_expense.get("linked_id") if existing_expense else None) or expense_id
                    trans_update = {"amount": amount}
                    if expense_date:
                        trans_update["date"] = expense_date
                    if description:
                        trans_update["memo"] = description
                    supabase_admin.table("staff_daily_report_transportations").update(trans_update).eq("id", linked_id).execute()
                except Exception as e:
                    print(f"⚠️ WARNING - 交通費連動更新エラー: {e}")
            
            flash("経費を更新しました", "success")
            return redirect(f"/admin/financial/years/{year}/months/{month_int:02d}")
        except Exception as e:
            print(f"❌ 経費更新エラー: {e}")
            flash(f"経費の更新に失敗しました: {e}", "error")
            return redirect(f"/admin/financial/years/{year}")
    
    # GET: 編集フォーム
    try:
        res_expense = supabase_admin.table("expenses").select("*").eq("id", expense_id).execute()
        expense = res_expense.data[0] if res_expense.data else None
        if not expense:
            res_transport = supabase_admin.table("staff_daily_report_transportations").select("*").eq("id", expense_id).execute()
            if not res_transport.data:
                flash("経費が見つかりません", "error")
                return redirect(f"/admin/financial/years/{year}")

            transport = res_transport.data[0]
            report_staff_id = None
            report_staff_name = None
            report_id = transport.get("daily_report_id")
            if report_id:
                res_report = supabase_admin.table("staff_daily_reports").select("staff_id, staff_name").eq("id", report_id).execute()
                if res_report.data:
                    report_staff_id = res_report.data[0].get("staff_id")
                    report_staff_name = res_report.data[0].get("staff_name")

            transport_memo = transport.get("memo") if transport.get("memo") else ""
            expense = {
                "id": transport.get("id"),
                "expense_date": transport.get("date"),
                "category": "transportation",
                "amount": transport.get("amount"),
                "description": transport_memo or f"交通費申請{(' - ' + report_staff_name) if report_staff_name else ''}",
                "staff_id": report_staff_id,
                "staff_name": report_staff_name,
                "memo": transport_memo,
                "linked_type": "daily_report_transportation",
                "linked_id": transport.get("id")
            }
        
        # スタッフ一覧を取得
        users = supabase_admin.auth.admin.list_users()
        staff_list = []
        for user in users:
            meta = user.user_metadata or {}
            if meta.get("approved") == True:
                name = f"{meta.get('last_name', '')} {meta.get('first_name', '')}".strip()
                if not name:
                    name = user.email
                staff_list.append({
                    "id": user.id,
                    "name": name,
                    "area": meta.get("area", "tokyo")
                })
        
        return render_template(
            "admin_financial_expense_edit.html",
            year=year,
            expense=expense,
            staff_list=staff_list
        )
    except Exception as e:
        print(f"❌ 経費取得エラー: {e}")
        flash("経費の取得に失敗しました", "error")
        return redirect(f"/admin/financial/years/{year}")


@app.route("/admin/financial/years/<year>/expenses/<expense_id>/delete", methods=["POST"])
@admin_required
def admin_financial_expense_delete(year, expense_id):
    """経費 - 削除"""
    try:
        res_expense = supabase_admin.table("expenses").select("*").eq("id", expense_id).execute()
        expense = res_expense.data[0] if res_expense.data else None

        if expense:
            linked_type = expense.get("linked_type")

            # linked_typeに応じて関連データも削除
            if linked_type == "salary":
                staff_id = expense.get("staff_id")
                if staff_id:
                    supabase_admin.table("staff_salaries").delete().eq("year", expense.get("year")).eq("month", expense.get("month")).eq("staff_id", staff_id).execute()
            elif linked_type == "daily_report_transportation":
                linked_id = expense.get("linked_id") or expense_id
                supabase_admin.table("staff_daily_report_transportations").delete().eq("id", linked_id).execute()

            supabase_admin.table("expenses").delete().eq("id", expense_id).execute()
        else:
            # expensesにない交通費は直接削除
            supabase_admin.table("staff_daily_report_transportations").delete().eq("id", expense_id).execute()
        flash("経費を削除しました", "success")
    except Exception as e:
        print(f"❌ 経費削除エラー: {e}")
        flash("経費の削除に失敗しました", "error")
    return redirect(f"/admin/financial/years/{year}")


@app.route("/admin/financial/years/<year>/months/<month>/salaries/new", methods=["GET", "POST"])
@admin_required
def admin_financial_salary_new(year, month):
    """スタッフ給与 - 新規作成"""
    if request.method == "POST":
        try:
            staff_id = request.form.get("staff_id")
            staff_name = request.form.get("staff_name", "").strip()
            
            # 自動計算を使用するかどうか
            use_auto_calc = request.form.get("use_auto_calc") == "true"
            calc_result = None
            month_int = int(month)

            if use_auto_calc or month_int in [6, 12]:
                # スタッフのエリアを取得
                area = "tokyo"  # デフォルト
                try:
                    users = supabase_admin.auth.admin.list_users()
                    for u in users:
                        if u.id == staff_id:
                            meta = u.user_metadata or {}
                            area = meta.get("area", "tokyo")
                            break
                except:
                    pass
                
                # 自動計算（売上・歩合給・交通費の参考値）
                calc_result = calculate_salary(staff_name, int(year), month_int, area)

            # 手動入力（基本給・資格給は必須で手入力）
            base_salary = float(request.form.get("base_salary", 0) or 0)
            commission = float(request.form.get("commission", 0) or 0)

            if use_auto_calc and calc_result:
                nomination_fee = calc_result.get("nomination_fee", 0) or 0
                transportation = calc_result.get("transportation", 0) or 0
                revenue = calc_result.get("revenue", 0) or 0
            else:
                nomination_fee = float(request.form.get("nomination_fee", 0) or 0)
                transportation = float(request.form.get("transportation", 0) or 0)
                revenue = calc_result.get("revenue", 0) if calc_result else 0

            # 特別給（6月/12月のみ・半期合計で算出）
            bonus_result = calculate_special_bonus(
                int(year),
                month_int,
                staff_id,
                staff_name,
                base_salary,
                commission,
                nomination_fee
            )
            special_bonus = bonus_result["bonus"]
            
            tax = float(request.form.get("tax", 0) or 0)
            social_insurance = float(request.form.get("social_insurance", 0) or 0)
            other_deduction = float(request.form.get("other_deduction", 0) or 0)
            memo = request.form.get("memo", "").strip()
            
            # 総支給 = 基本給 + 資格給 + 歩合給(指名料) + 交通費 + 特別給
            total_salary = base_salary + commission + nomination_fee + transportation + special_bonus
            net_salary = total_salary - tax - social_insurance - other_deduction
            
            salary_data = {
                "year": int(year),
                "month": int(month),
                "staff_id": staff_id,
                "staff_name": staff_name,
                "base_salary": base_salary,
                "commission": commission,
                "nomination_fee": nomination_fee,
                "transportation": transportation,
                "special_bonus": special_bonus,
                "tax": tax,
                "social_insurance": social_insurance,
                "other_deduction": other_deduction,
                "total_salary": total_salary,
                "net_salary": net_salary,
                "memo": memo
            }
            
            supabase_admin.table("staff_salaries").insert(salary_data).execute()
            
            # 経費テーブルにも給与を追加
            expense_data = {
                "expense_date": f"{year}-{month:02d}-01",
                "year": int(year),
                "month": int(month),
                "category": "salary",
                "amount": total_salary,
                "description": f"{staff_name}の給与",
                "staff_id": staff_id,
                "staff_name": staff_name,
                "linked_type": "salary",
                "memo": memo
            }
            supabase_admin.table("expenses").insert(expense_data).execute()
            
            flash("スタッフ給与を登録しました", "success")
            return redirect(f"/admin/financial/years/{year}/months/{month}")
        except Exception as e:
            print(f"❌ スタッフ給与登録エラー: {e}")
            flash(f"スタッフ給与の登録に失敗しました: {e}", "error")
            return redirect(f"/admin/financial/years/{year}/months/{month}")
    
    # GET: 新規作成フォーム
    try:
        # スタッフ一覧を取得
        users = supabase_admin.auth.admin.list_users()
        staff_list = []
        for user in users:
            meta = user.user_metadata or {}
            if meta.get("approved") == True:
                name = f"{meta.get('last_name', '')} {meta.get('first_name', '')}".strip()
                if not name:
                    name = user.email
                staff_list.append({
                    "id": user.id,
                    "name": name
                })
        
        # 既に登録されているスタッフIDを取得
        res_existing = supabase_admin.table("staff_salaries").select("staff_id").eq("year", int(year)).eq("month", int(month)).execute()
        registered_ids = {sal["staff_id"] for sal in (res_existing.data or [])}
        
        # 未登録のスタッフのみ表示
        available_staff = [s for s in staff_list if s["id"] not in registered_ids]
        
        # 各スタッフの給与計算結果を取得（自動計算用）
        salary_calculations = {}
        for staff in available_staff:
            try:
                area = staff.get("area", "tokyo")
                calc_result = calculate_salary(staff["name"], int(year), int(month), area)
                half_year = calculate_special_bonus(
                    int(year),
                    int(month),
                    staff["id"],
                    staff["name"],
                    0,
                    0,
                    0
                )
                calc_result["half_year_revenue"] = half_year["revenue_total"]
                calc_result["half_year_existing_total"] = half_year["existing_total"]
                salary_calculations[staff["id"]] = calc_result
            except Exception as e:
                print(f"⚠️ WARNING - 給与計算エラー（{staff['name']}）: {e}")
                salary_calculations[staff["id"]] = None
        
        return render_template(
            "admin_financial_salary_new.html",
            year=year,
            month=month,
            staff_list=available_staff,
            salary_calculations=salary_calculations
        )
    except Exception as e:
        print(f"❌ スタッフ給与新規作成フォーム取得エラー: {e}")
        flash("フォームの取得に失敗しました", "error")
        return redirect(f"/admin/financial/years/{year}/months/{month}")


@app.route("/admin/financial/years/<year>/months/<month>/salaries/<salary_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_financial_salary_edit(year, month, salary_id):
    """スタッフ給与 - 編集"""
    if request.method == "POST":
        try:
            staff_id = request.form.get("staff_id")
            staff_name = request.form.get("staff_name", "").strip()
            
            # 自動計算を使用するかどうか
            use_auto_calc = request.form.get("use_auto_calc") == "true"
            calc_result = None
            month_int = int(month)

            if use_auto_calc or month_int in [6, 12]:
                # スタッフのエリアを取得
                area = "tokyo"  # デフォルト
                try:
                    users = supabase_admin.auth.admin.list_users()
                    for u in users:
                        if u.id == staff_id:
                            meta = u.user_metadata or {}
                            area = meta.get("area", "tokyo")
                            break
                except:
                    pass
                
                # 自動計算（売上・歩合給・交通費の参考値）
                calc_result = calculate_salary(staff_name, int(year), month_int, area)

            # 手動入力（基本給・資格給は必須で手入力）
            base_salary = float(request.form.get("base_salary", 0) or 0)
            commission = float(request.form.get("commission", 0) or 0)

            if use_auto_calc and calc_result:
                nomination_fee = calc_result.get("nomination_fee", 0) or 0
                transportation = calc_result.get("transportation", 0) or 0
                revenue = calc_result.get("revenue", 0) or 0
            else:
                nomination_fee = float(request.form.get("nomination_fee", 0) or 0)
                transportation = float(request.form.get("transportation", 0) or 0)
                revenue = calc_result.get("revenue", 0) if calc_result else 0

            # 特別給（6月/12月のみ・半期合計で算出）
            bonus_result = calculate_special_bonus(
                int(year),
                month_int,
                staff_id,
                staff_name,
                base_salary,
                commission,
                nomination_fee,
                exclude_salary_id=salary_id
            )
            special_bonus = bonus_result["bonus"]
            
            tax = float(request.form.get("tax", 0) or 0)
            social_insurance = float(request.form.get("social_insurance", 0) or 0)
            other_deduction = float(request.form.get("other_deduction", 0) or 0)
            memo = request.form.get("memo", "").strip()
            
            # 総支給 = 基本給 + 資格給 + 歩合給(指名料) + 交通費 + 特別給
            total_salary = base_salary + commission + nomination_fee + transportation + special_bonus
            net_salary = total_salary - tax - social_insurance - other_deduction
            
            salary_data = {
                "staff_id": staff_id,
                "staff_name": staff_name,
                "base_salary": base_salary,
                "commission": commission,
                "nomination_fee": nomination_fee,
                "transportation": transportation,
                "special_bonus": special_bonus,
                "tax": tax,
                "social_insurance": social_insurance,
                "other_deduction": other_deduction,
                "total_salary": total_salary,
                "net_salary": net_salary,
                "memo": memo
            }
            
            supabase_admin.table("staff_salaries").update(salary_data).eq("id", salary_id).execute()
            
            # 経費テーブルも更新
            res_expense = supabase_admin.table("expenses").select("id").eq("year", int(year)).eq("month", int(month)).eq("staff_id", staff_id).eq("category", "salary").eq("linked_type", "salary").execute()
            if res_expense.data:
                expense_id = res_expense.data[0]["id"]
                expense_data = {
                    "amount": total_salary,
                    "description": f"{staff_name}の給与",
                    "memo": memo
                }
                supabase_admin.table("expenses").update(expense_data).eq("id", expense_id).execute()
            
            flash("スタッフ給与を更新しました", "success")
            return redirect(f"/admin/financial/years/{year}/months/{month}")
        except Exception as e:
            print(f"❌ スタッフ給与更新エラー: {e}")
            flash(f"スタッフ給与の更新に失敗しました: {e}", "error")
            return redirect(f"/admin/financial/years/{year}/months/{month}")
    
    # GET: 編集フォーム
    try:
        res_salary = supabase_admin.table("staff_salaries").select("*").eq("id", salary_id).execute()
        if not res_salary.data:
            flash("スタッフ給与が見つかりません", "error")
            return redirect(f"/admin/financial/years/{year}/months/{month}")
        
        salary = res_salary.data[0]
        
        # スタッフ一覧を取得
        users = supabase_admin.auth.admin.list_users()
        staff_list = []
        for user in users:
            meta = user.user_metadata or {}
            if meta.get("approved") == True:
                name = f"{meta.get('last_name', '')} {meta.get('first_name', '')}".strip()
                if not name:
                    name = user.email
                staff_list.append({
                    "id": user.id,
                    "name": name
                })
        
        salary_calculation = None
        try:
            area = "tokyo"
            for staff in staff_list:
                if staff["id"] == salary.get("staff_id"):
                    area = staff.get("area", "tokyo")
                    break
            salary_calculation = calculate_salary(salary.get("staff_name", ""), int(year), int(month), area)
            half_year = calculate_special_bonus(
                int(year),
                int(month),
                salary.get("staff_id"),
                salary.get("staff_name", ""),
                0,
                0,
                0,
                exclude_salary_id=salary_id
            )
            salary_calculation["half_year_revenue"] = half_year["revenue_total"]
            salary_calculation["half_year_existing_total"] = half_year["existing_total"]
        except Exception as e:
            print(f"⚠️ WARNING - 給与計算データ生成エラー: {e}")

        return render_template(
            "admin_financial_salary_edit.html",
            year=year,
            month=month,
            salary=salary,
            staff_list=staff_list,
            salary_calculation=salary_calculation
        )
    except Exception as e:
        print(f"❌ スタッフ給与取得エラー: {e}")
        flash("スタッフ給与の取得に失敗しました", "error")
        return redirect(f"/admin/financial/years/{year}/months/{month}")


@app.route("/admin/financial/years/<year>/months/<month>/salaries/<salary_id>/delete", methods=["POST"])
@admin_required
def admin_financial_salary_delete(year, month, salary_id):
    """スタッフ給与 - 削除"""
    try:
        # 給与を取得して経費も削除
        res_salary = supabase_admin.table("staff_salaries").select("staff_id").eq("id", salary_id).execute()
        if res_salary.data:
            staff_id = res_salary.data[0].get("staff_id")
            supabase_admin.table("expenses").delete().eq("year", int(year)).eq("month", int(month)).eq("staff_id", staff_id).eq("category", "salary").eq("linked_type", "salary").execute()
        
        supabase_admin.table("staff_salaries").delete().eq("id", salary_id).execute()
        flash("スタッフ給与を削除しました", "success")
    except Exception as e:
        print(f"❌ スタッフ給与削除エラー: {e}")
        flash("スタッフ給与の削除に失敗しました", "error")
    return redirect(f"/admin/financial/years/{year}/months/{month}")


# ===================================================
# ✅ セルフケア動画管理
# ===================================================
@app.route("/admin/videos")
@staff_required
def admin_videos():
    """セルフケア動画一覧（あいうえお順）"""
    try:
        res = supabase_admin.table("self_care_videos").select("*").order("item_name").execute()
        videos = res.data or []
        return render_template("admin_videos.html", videos=videos)
    except Exception as e:
        print(f"❌ セルフケア動画一覧取得エラー: {e}")
        flash("動画一覧の取得に失敗しました", "error")
        return render_template("admin_videos.html", videos=[])


@app.route("/admin/videos/new", methods=["GET", "POST"])
@staff_required
def admin_video_new():
    """セルフケア動画 - 新規作成"""
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            if not name:
                flash("種目名を入力してください", "error")
                return render_template("admin_video_new.html")
            
            video_url = request.form.get("video_url", "").strip()
            if not video_url:
                flash("動画URLを入力してください", "error")
                return render_template("admin_video_new.html")
            
            purpose = request.form.get("purpose", "").strip()
            method = request.form.get("method", "").strip()
            recommended_for = request.form.get("recommended_for", "").strip()
            
            # ファイルアップロードがある場合
            if "video_file" in request.files:
                video_file = request.files["video_file"]
                if video_file and video_file.filename:
                    try:
                        # Supabase Storageにアップロード
                        file_name = video_file.filename
                        ext = os.path.splitext(file_name)[1].lower()
                        safe_name = f"{uuid.uuid4().hex}{ext}"
                        storage_path = f"self-care-videos/{safe_name}"
                        
                        mime_type, _ = mimetypes.guess_type(file_name)
                        if not mime_type:
                            mime_type = "video/mp4"  # デフォルト
                        
                        file_data = video_file.read()
                        supabase_admin.storage.from_("self-care-videos").upload(
                            path=storage_path,
                            file=file_data,
                            file_options={"content-type": mime_type}
                        )
                        
                        # 公開URLを取得
                        video_url = supabase_admin.storage.from_("self-care-videos").get_public_url(storage_path)
                    except Exception as e:
                        print(f"❌ 動画アップロードエラー: {e}")
                        flash(f"動画のアップロードに失敗しました: {e}", "error")
                        return render_template("admin_video_new.html")
            
            insert_data = {
                "name": name,
                "video_url": video_url,
                "purpose": purpose,
                "method": method,
                "recommended_for": recommended_for,
                "created_at": now_iso(),
                "updated_at": now_iso()
            }
            
            supabase_admin.table("self_care_videos").insert(insert_data).execute()
            flash("セルフケア動画を登録しました", "success")
            return redirect("/admin/videos")
        except Exception as e:
            print(f"❌ セルフケア動画登録エラー: {e}")
            flash(f"動画の登録に失敗しました: {e}", "error")
            return render_template("admin_video_new.html")
    
    # GET: 新規作成フォーム
    return render_template("admin_video_new.html")


@app.route("/admin/videos/<video_id>")
@staff_required
def admin_video_detail(video_id):
    """セルフケア動画 - 詳細表示"""
    try:
        res = supabase_admin.table("self_care_videos").select("*").eq("id", video_id).execute()
        if not res.data:
            flash("動画が見つかりません", "error")
            return redirect("/admin/videos")
        
        video = res.data[0]
        return render_template("admin_video_detail.html", video=video)
    except Exception as e:
        print(f"❌ セルフケア動画取得エラー: {e}")
        flash("動画の取得に失敗しました", "error")
        return redirect("/admin/videos")


@app.route("/admin/videos/<video_id>/edit", methods=["GET", "POST"])
@staff_required
def admin_video_edit(video_id):
    """セルフケア動画 - 編集"""
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            if not name:
                flash("種目名を入力してください", "error")
                return redirect(f"/admin/videos/{video_id}/edit")
            
            video_url = request.form.get("video_url", "").strip()
            if not video_url:
                flash("動画URLを入力してください", "error")
                return redirect(f"/admin/videos/{video_id}/edit")
            
            purpose = request.form.get("purpose", "").strip()
            method = request.form.get("method", "").strip()
            recommended_for = request.form.get("recommended_for", "").strip()
            
            # ファイルアップロードがある場合
            if "video_file" in request.files:
                video_file = request.files["video_file"]
                if video_file and video_file.filename:
                    try:
                        # Supabase Storageにアップロード
                        file_name = video_file.filename
                        ext = os.path.splitext(file_name)[1].lower()
                        safe_name = f"{uuid.uuid4().hex}{ext}"
                        storage_path = f"self-care-videos/{safe_name}"
                        
                        mime_type, _ = mimetypes.guess_type(file_name)
                        if not mime_type:
                            mime_type = "video/mp4"  # デフォルト
                        
                        file_data = video_file.read()
                        supabase_admin.storage.from_("self-care-videos").upload(
                            path=storage_path,
                            file=file_data,
                            file_options={"content-type": mime_type}
                        )
                        
                        # 公開URLを取得
                        video_url = supabase_admin.storage.from_("self-care-videos").get_public_url(storage_path)
                    except Exception as e:
                        print(f"❌ 動画アップロードエラー: {e}")
                        flash(f"動画のアップロードに失敗しました: {e}", "error")
                        return redirect(f"/admin/videos/{video_id}/edit")
            
            update_data = {
                "name": name,
                "video_url": video_url,
                "purpose": purpose,
                "method": method,
                "recommended_for": recommended_for,
                "updated_at": now_iso()
            }
            
            supabase_admin.table("self_care_videos").update(update_data).eq("id", video_id).execute()
            flash("セルフケア動画を更新しました", "success")
            return redirect(f"/admin/videos/{video_id}")
        except Exception as e:
            print(f"❌ セルフケア動画更新エラー: {e}")
            flash(f"動画の更新に失敗しました: {e}", "error")
            return redirect(f"/admin/videos/{video_id}/edit")
    
    # GET: 編集フォーム
    try:
        res = supabase_admin.table("self_care_videos").select("*").eq("id", video_id).execute()
        if not res.data:
            flash("動画が見つかりません", "error")
            return redirect("/admin/videos")
        
        video = res.data[0]
        return render_template("admin_video_edit.html", video=video)
    except Exception as e:
        print(f"❌ セルフケア動画取得エラー: {e}")
        flash("動画の取得に失敗しました", "error")
        return redirect("/admin/videos")


@app.route("/admin/videos/<video_id>/delete", methods=["POST"])
@staff_required
def admin_video_delete(video_id):
    """セルフケア動画 - 削除"""
    try:
        supabase_admin.table("self_care_videos").delete().eq("id", video_id).execute()
        flash("セルフケア動画を削除しました", "success")
    except Exception as e:
        print(f"❌ セルフケア動画削除エラー: {e}")
        flash("動画の削除に失敗しました", "error")
    return redirect("/admin/videos")


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

# ===================================================
# ✅ 起動
# ===================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
