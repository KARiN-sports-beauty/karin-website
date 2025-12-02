from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, jsonify
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))
from flask_mail import Mail, Message
import gspread
from google.oauth2.service_account import Credentials
import json, os
from dotenv import load_dotenv
import requests
from supabase import create_client, Client
import uuid




# ===============================
# Supabase 接続設定
# ===============================
SUPABASE_URL = "https://pmuvlinhusxesmhwsxtz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBtdXZsaW5odXN4ZXNtaHdzeHR6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM3OTA1ODAsImV4cCI6MjA3OTM2NjU4MH0.efXpBSYXAqMqvYnQQX1CUSnaymft7j_HzXZX6bHCXHA"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)




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
# ▼ .envを読み込む
# =====================================
load_dotenv()

# =====================================
# ▼ Flaskアプリ初期化
# =====================================
app = Flask(__name__, template_folder="templates")

# =====================================
# ▼ Gmail送信用設定（安全版）
# =====================================
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'karin.sports.beauty@gmail.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = ("KARiN. 初診受付フォーム", app.config['MAIL_USERNAME'])

mail = Mail(app)

# =====================================
# ▼ GAS Webhook URL（🟢 新追加）
# =====================================
GAS_URL_FORM = "https://script.google.com/macros/s/AKfycbxwY-01BQjrneGxlxDaYAxfS7PAZNzVWvDzc5UUEppDGvzle961tynQctdtQYHn1Wah3w/exec"
GAS_URL_CONTACT = "https://script.google.com/macros/s/AKfycbxic_oSKyB_HC_IFmSXlbwer43n1AxqqCVqt1TasEA6nB4pkezOc72s1mRmwDF6jaxt/exec"

# =====================================
# ▼ ユーティリティ関数
# =====================================
def format_datetime(dt_str):
    if dt_str:
        try:
            dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
            return dt.strftime("%Y年%m月%d日 %H:%M")
        except ValueError:
            return dt_str
    return ""

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
# 初診フォーム送信（GAS対応版）
# ===================================================
@app.route("/submit_form", methods=["POST"])
def submit_form():
    try:
        data = {
            "name": request.form.get("name"),
            "kana": request.form.get("kana"),
            "age": request.form.get("age"),
            "gender": request.form.get("gender"),
            "phone": request.form.get("phone"),
            "email": request.form.get("email"),
            "address": request.form.get("address"),
            "preferred_date1": format_datetime(request.form.get("preferred_date1")),
            "preferred_date2": format_datetime(request.form.get("preferred_date2")),
            "preferred_date3": format_datetime(request.form.get("preferred_date3")),
            "chief_complaint": request.form.get("chief_complaint"),
            "onset": request.form.get("onset"),
            "pain_level": request.form.get("pain_level"),
            "shinkyu_pref": request.form.get("shinkyu_pref"),
            "electric_pref": request.form.get("electric_pref"),
            "pressure_pref": request.form.get("pressure_pref"),
            "heart": request.form.get("heart"),
            "pregnant": request.form.get("pregnant"),
            "chronic": request.form.get("chronic"),
            "surgery": request.form.get("surgery"),
            "under_medical": request.form.get("under_medical"),
            "signature": request.form.get("signature"),
            "agreed_date": f"{request.form.get('agree_year')}年{request.form.get('agree_month')}月{request.form.get('agree_day')}日",
        }

        GAS_URL_FORM = "https://script.google.com/macros/s/AKfycbyUAS--yGnXqF4dS9VQTUfMf7BmSXt1rVbAWTyDxYpg13t0A2B9S0y9dYdMOMFziFST1w/exec"

        print("📨 送信されるJSON:")
        print(json.dumps(data, ensure_ascii=False, indent=2))

        response = requests.post(GAS_URL_FORM, json=data)

        print("🛰️ FORM GASレスポンス:", response.status_code, response.text)

        # 🟢 LINE通知
        line_message = f"""
【初診フォーム】
お名前：{data['name']}
ふりがな：{data['kana']}
年齢：{data['age']}
性別：{data['gender']}
電話番号：{data['phone']}
メール：{data['email']}
第1希望：{data['preferred_date1']}
主訴：{data['chief_complaint']}
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
        timestamp = datetime.now().strftime("%Y/%m/%d %H:%M")

        # --- GAS 送信 ---
        GAS_URL_CONTACT = "https://script.google.com/macros/s/AKfycbxiSIZo3k3I89KrD8PEMeyqd51tfsOlzdSYdAIx4NgK75OGhJb-pLh52ezg7QBaq84F/exec"

        data = {
            "name": name,
            "phone": phone,
            "email": email,
            "message": message,
            "timestamp": timestamp
        }

        response = requests.post(GAS_URL_CONTACT, json=data, timeout=10)

        print("🛰️ CONTACT GASレスポンス:", response.status_code, response.text)

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

        return redirect(url_for(
            "thanks",
            message="ご予約・お問い合わせありがとうございました。<br>内容を確認のうえ、24時間以内にご連絡いたします。"
        ))

    except Exception as e:
        print("❌ お問い合わせエラー:", e)
        return f"サーバーエラー: {str(e)}", 500



# ===================================================
# ✅ thanks.html
# ===================================================
@app.route("/thanks")
def thanks():
    message = request.args.get("message", "送信ありがとうございました。内容を確認のうえ、24時間以内にご連絡いたします。")
    return render_template("thanks.html", message=message)

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

    # 最新ブログ 3件
    latest_blogs_res = (
        supabase
        .table("blogs")
        .select("*")
        .order("created_at", desc=True)
        .limit(3)
        .execute()
    )
    latest_blogs = latest_blogs_res.data or []

    # 最新ニュース 3件
    latest_news_res = (
        supabase
        .table("news")
        .select("*")
        .order("created_at", desc=True)
        .limit(3)
        .execute()
    )
    latest_news = latest_news_res.data or []

    # スケジュールだけは JSON のまま
    with open("static/data/schedule.json", encoding="utf-8") as f:
        schedule = json.load(f)

    today = datetime.now().strftime("%Y-%m-%d")
    upcoming = [s for s in schedule if s["date"] >= today][:10]

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
    name = request.form.get("name", "匿名").strip()
    body = request.form.get("body", "").strip()
    slug = request.form.get("slug", "").strip()

    if not body:
        return {"error": "コメントが空です"}, 400

    if not slug:
        return {"error": "slug がありません"}, 400

    # slug → blog.id を取得
    blog_res = supabase.table("blogs").select("id").eq("slug", slug).execute()
    if not blog_res.data:
        return {"error": "ブログが見つかりません"}, 404

    blog_id = blog_res.data[0]["id"]

    # コメント保存
    res = supabase.table("comments").insert({
        "id": str(uuid.uuid4()),
        "blog_id": blog_id,
        "name": name,
        "body": body,
        "created_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    }).execute()

    # ✉️ Gmail通知
    try:
        msg = Message(
            subject=f"【KARiN.】新しいコメントが届きました（Blog: {slug}）",
            sender="karin.sports.beauty@gmail.com",
            recipients=["karin.sports.beauty@gmail.com"],
            body=f"ブログ Slug: {slug}\n名前: {name}\nコメント:\n{body}"
        )
        mail.send(msg)
    except Exception as e:
        print("MAIL ERROR:", e)

    return {"success": True}





@app.route("/sitemap.xml")
def sitemap():
    try:
        pages = []

        base_url = "https://karin-website.onrender.com"

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
        "Sitemap: https://karin-website.onrender.com/sitemap.xml"
    ]
    return "\n".join(lines), 200, {"Content-Type": "text/plain"}



@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

# ===================================================
# ✅ 起動
# ===================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
