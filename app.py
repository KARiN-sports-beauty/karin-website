from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session
from datetime import datetime, timedelta
from flask_mail import Mail, Message
import gspread
from google.oauth2.service_account import Credentials
import json, os
from dotenv import load_dotenv
import requests  # 🟢 GASにPOSTするために追加


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
        seven_days = today + timedelta(days=7)
        return [s for s in all_schedule if today <= datetime.strptime(s["date"], "%Y-%m-%d") <= seven_days]
    except Exception as e:
        print("❌ schedule.json 読み込みエラー:", e)
        return []

def load_blogs():
    with open("static/data/blogs.json", encoding="utf-8") as f:
        blogs = json.load(f)
    blogs.sort(key=lambda x: datetime.strptime(x["date"], "%Y-%m-%d"), reverse=True)
    return blogs

# コメント・いいね保存用ファイル
COMMENTS_FILE = "static/data/blog_comments.json"
LIKES_FILE = "static/data/blog_likes.json"


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


def load_comments():
    """ブログコメント全体を読み込み（{blog_id: [comments...]}）"""
    return load_json_safely(COMMENTS_FILE, {})


def save_comments(data):
    save_json_safely(COMMENTS_FILE, data)


def load_likes():
    """ブログいいね数を読み込み（{blog_id: count}）"""
    return load_json_safely(LIKES_FILE, {})


def save_likes(data):
    save_json_safely(LIKES_FILE, data)


# =====================================
# ▼ 各ページルート定義
# =====================================

@app.route("/treatment")
def treatment():
    items = [
        ("鍼灸治療", "腰痛・肩こり・頭痛・関節痛などの慢性痛をはじめ、自律神経のバランス調整による不眠や胃腸・呼吸器系の不調にも対応。", "treatment1.jpg"),
        ("美容鍼", "内側から美しさを引き出す自然派美容法。血行促進・ターンオーバー促進・肌質改善が期待できます。", "treatment2.jpg"),
        ("整体", "身体のバランスを整え、姿勢の改善や自然治癒力を引き出します。", "treatment3.jpg"),
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
@app.route("/blog")
def blog():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    blogs = load_blogs()

    if category:
        blogs = [b for b in blogs if b.get("category") == category]
    if query:
        blogs = [b for b in blogs if query.lower() in b["title"].lower() or query.lower() in b["excerpt"].lower()]
    categories = sorted(list(set(b.get("category") for b in load_blogs() if b.get("category"))))

    return render_template("blog.html", blogs=blogs, query=query, categories=categories, current_category=category)

@app.route("/blog/<int:id>")
def show_blog(id):
    # --- すべてのブログデータを読み込み ---
    with open("static/data/blogs.json", encoding="utf-8") as f:
        blogs = json.load(f)
    blog = next((b for b in blogs if b["id"] == id), None)

    if not blog:
        return render_template("404.html"), 404

    # --- 本文データの扱い ---
    if blog.get("body"):
        content = blog["body"]
    else:
        file_path = blog.get("file")
        if file_path and os.path.exists(f"templates/{file_path}"):
            with open(f"templates/{file_path}", encoding="utf-8") as f:
                content = f.read()
        else:
            content = "<p>この記事の内容は準備中です。</p>"
        blog["body"] = content

    # --- コメント・いいねデータ読み込み ---
    comments_data = load_comments()
    comments = comments_data.get(str(id), [])

    likes_data = load_likes()
    like_count = likes_data.get(str(id), 0)

    # --- 関連ブログ抽出（タグ → カテゴリ の優先順） ---
    related_blogs = []
    if "tags" in blog and blog["tags"]:
        related_blogs = [
            b for b in blogs
            if b["id"] != id and any(tag in b.get("tags", []) for tag in blog["tags"])
        ][:5]
    elif "category" in blog:
        related_blogs = [
            b for b in blogs
            if b["id"] != id and b.get("category") == blog["category"]
        ][:5]

    # --- レンダリング ---
    return render_template(
        "blog_detail.html",
        blog=blog,
        comments=comments,
        like_count=like_count,
        related_blogs=related_blogs
    )


@app.route("/blog/<int:id>/comment", methods=["POST"])
def add_comment(id):
    name = request.form.get("name", "").strip() or "ゲスト"
    body = request.form.get("body", "").strip()

    # 空コメントは無視して戻る
    if not body:
        return redirect(url_for("show_blog", id=id))

    comments_data = load_comments()
    comments = comments_data.get(str(id), [])

    # シンプルな連番ID
    if comments:
        max_id = max(c.get("id", 0) for c in comments)
        next_id = max_id + 1
    else:
        next_id = 1

    comments.append({
        "id": next_id,
        "name": name,
        "body": body,
        "created_at": datetime.now().strftime("%Y/%m/%d %H:%M"),
    })

    comments_data[str(id)] = comments
    save_comments(comments_data)

    return redirect(url_for("show_blog", id=id))


@app.route("/news/<int:id>")
def show_news(id):
    path = f"templates/news/news_{id}.html"
    if not os.path.exists(path):
        return render_template("404.html"), 404
    return send_from_directory("templates/news", f"news_{id}.html")

# ===================================================
# ✅ トップ・404
# ===================================================
@app.route("/")
def index():
    with open("static/data/blogs.json", encoding="utf-8") as f:
        blogs = json.load(f)
    latest_blogs = sorted(blogs, key=lambda x: x["id"], reverse=True)[:3]

    if os.path.exists("static/data/news.json"):
        with open("static/data/news.json", encoding="utf-8") as f:
            news_list = json.load(f)
        latest_news = sorted(news_list, key=lambda x: x["id"], reverse=True)[:3]
    else:
        latest_news = []

    with open("static/data/schedule.json", encoding="utf-8") as f:
        schedule = json.load(f)
    today = datetime.now().strftime("%Y-%m-%d")
    upcoming = [s for s in schedule if s["date"] >= today][:7]

    return render_template("index.html", latest_blogs=latest_blogs, latest_news=latest_news, schedule=upcoming, today=today)

# ===================================================
# ✅ 動的 Sitemap.xml
# ===================================================
@app.route("/sitemap.xml")
def sitemap():
    # --- 固定ページ ---
    static_urls = [
        {"loc": "https://karin-website.onrender.com/", "changefreq": "daily"},
        {"loc": "https://karin-website.onrender.com/treatment"},
        {"loc": "https://karin-website.onrender.com/price"},
        {"loc": "https://karin-website.onrender.com/contact"},
        {"loc": "https://karin-website.onrender.com/form"},
        {"loc": "https://karin-website.onrender.com/login"},
        {"loc": "https://karin-website.onrender.com/register"},
        {"loc": "https://karin-website.onrender.com/blog"},
        {"loc": "https://karin-website.onrender.com/news"},
    ]

    pages = []

    # 固定ページの登録
    for url in static_urls:
        pages.append(f"""
        <url>
            <loc>{url['loc']}</loc>
            <changefreq>{url.get('changefreq', 'weekly')}</changefreq>
        </url>
        """)

    # --- 動的：ブログ ---
    if os.path.exists("static/data/blogs.json"):
        with open("static/data/blogs.json", encoding="utf-8") as f:
            blogs = json.load(f)
        for b in blogs:
            pages.append(f"""
            <url>
                <loc>https://karin-website.onrender.com/blog/{b['id']}</loc>
                <changefreq>weekly</changefreq>
            </url>
            """)

    # --- 動的：ニュース ---
    if os.path.exists("static/data/news.json"):
        with open("static/data/news.json", encoding="utf-8") as f:
            news = json.load(f)
        for n in news:
            pages.append(f"""
            <url>
                <loc>https://karin-website.onrender.com/news/{n['id']}</loc>
                <changefreq>weekly</changefreq>
            </url>
            """)

    # XML生成
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        {''.join(pages)}
    </urlset>
    """

    return Response(xml, mimetype='application/xml')


# =====================================
# ▼ コメント＆いいねAPI（ブログ用）
# =====================================

COMMENTS_PATH = "static/data/blog_comments.json"
LIKES_PATH = "static/data/blog_likes.json"

# --- コメントデータ読み込み ---
def load_comments():
    if os.path.exists(COMMENTS_PATH):
        with open(COMMENTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}

# --- コメント保存 ---
def save_comments(data):
    with open(COMMENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- いいねデータ読み込み ---
def load_likes():
    if os.path.exists(LIKES_PATH):
        with open(LIKES_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}

# --- いいね保存 ---
def save_likes(data):
    with open(LIKES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --- コメント送信 ---
@app.route("/api/comment/<int:blog_id>", methods=["POST"])
def api_comment(blog_id):
    name = request.form.get("name", "匿名")
    text = request.form.get("text", "").strip()
    if not text:
        return {"error": "コメントが空です"}, 400

    comments = load_comments()
    if str(blog_id) not in comments:
        comments[str(blog_id)] = []

    comments[str(blog_id)].append({"name": name, "text": text})
    # 最新5件のみ保持
    comments[str(blog_id)] = comments[str(blog_id)][-5:]
    save_comments(comments)

    return {"success": True, "comments": comments[str(blog_id)]}


# --- いいね処理 ---
@app.route("/api/like/<int:blog_id>", methods=["POST"])
def api_like(blog_id):
    data = load_likes()
    blog_key = str(blog_id)

    # 現在のいいね数を取得
    current_count = data.get(blog_key, 0)

    # リクエストからトグル状態を受け取る
    liked = request.form.get("liked", "false") == "true"

    # 増減処理（最小値0）
    if liked:
        current_count += 1
    else:
        current_count = max(0, current_count - 1)

    # 保存
    data[blog_key] = current_count
    save_likes(data)

    return {"success": True, "like_count": current_count}


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

# ===================================================
# ✅ 起動
# ===================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
