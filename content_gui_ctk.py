# content_gui_ctk.py  — KARiN. Content Manager (Blogs / News / Mypage)
# ---------------------------------------------------------------
# 依存: customtkinter (pip install customtkinter)
# パス前提:
#   static/data/blogs.json
#   static/data/news.json
#   templates/blog_detail.html
#   templates/news_detail.html
#   static/images/blogs/   （ブログ用サムネ）
#   static/data/mypage_videos.json
#   static/data/mypage_articles.json
#   static/data/mypage_news.json
#   backups/               （自動バックアップ保存先）
# ---------------------------------------------------------------

import customtkinter as ctk
import json, os, shutil
from datetime import datetime
from tkinter import messagebox
from tkinter import filedialog
import uuid
import webbrowser  # 🔵 投稿/編集後にブラウザを開く
import time
from supabase import create_client, Client

SUPABASE_URL = "https://pmuvlinhusxesmhwsxtz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBtdXZsaW5odXN4ZXNtaHdzeHR6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM3OTA1ODAsImV4cCI6MjA3OTM2NjU4MH0.efXpBSYXAqMqvYnQQX1CUSnaymft7j_HzXZX6bHCXHA"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# =========================
# 外観・基本ウィンドウ
# =========================
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

root = ctk.CTk()
root.title("🪷 KARiN. Content Manager")
root.geometry("760x980")
root.minsize(680, 820)
root.configure(fg_color="#fafafa")

# =========================
# パス設定
# =========================
NEWS_JSON = "static/data/news.json"
NEWS_DIR  = "templates/news"
BLOG_JSON = "static/data/blogs.json"
BLOG_DIR  = "templates/blogs"
IMG_DIR   = "static/images/blogs"
BACKUP_DIR= "backups"

MYPAGE_VIDEOS   = "static/data/mypage_videos.json"
MYPAGE_ARTICLES = "static/data/mypage_articles.json"
MYPAGE_NEWS     = "static/data/mypage_news.json"

# 🔵 本番URL（プレビューで開く先）
BASE_URL = "https://karin-website.onrender.com"

for path in [NEWS_DIR, BLOG_DIR, IMG_DIR, BACKUP_DIR,
             os.path.dirname(NEWS_JSON), os.path.dirname(BLOG_JSON),
             os.path.dirname(MYPAGE_VIDEOS)]:
    if path and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

# =========================
# 共通ユーティリティ
# =========================
def load_json(file):
    try:
        if os.path.exists(file):
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        messagebox.showerror("読み込みエラー", f"{file}\n{e}")
    return []

def save_json(file, data_list):
    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        messagebox.showerror("保存エラー", f"{file}\n{e}")

def get_thumbnails():
    if not os.path.exists(IMG_DIR):
        return []
    return [
        f for f in os.listdir(IMG_DIR)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ]

def select_and_copy_image():
    """GUIから画像を選択 → static/images/blogs にコピーしてファイル名を返す"""
    file_path = filedialog.askopenfilename(
        title="サムネイル画像を選択",
        filetypes=[("画像ファイル", "*.jpg *.jpeg *.png *.webp")]
    )
    if not file_path:
        return None

    ext = os.path.splitext(file_path)[1].lower()
    new_name = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(IMG_DIR, new_name)

    try:
        shutil.copy(file_path, dest_path)
        return new_name
    except Exception as e:
        messagebox.showerror("コピー失敗", f"画像の保存に失敗しました\n{e}")
        return None

def backup_file(src, kind, id):
    """旧：静的HTMLバックアップ用。ファイルがあれば backups フォルダに控えだけ取る。"""
    if os.path.exists(src):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy(src, f"{BACKUP_DIR}/{kind}_{id}_{ts}.html")

def new_id(data_list):
    return (max([x["id"] for x in data_list]) + 1) if data_list else 1

def today():
    return datetime.now().strftime("%Y-%m-%d")

# =========================
# ボタン: 白×角丸×軽い立体感
# =========================
def add_main_button(parent, label, cmd, color="#1e3a5f"):
    wrap = ctk.CTkFrame(parent, fg_color="#fafafa", corner_radius=0)
    wrap.pack(pady=10, fill="x", padx=90)

    shadow = ctk.CTkFrame(
        wrap,
        fg_color="#e9e9e9",
        corner_radius=28,
        height=52
    )
    shadow.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.98, y=6)

    btn = ctk.CTkButton(
        wrap, text=label, command=cmd,
        fg_color="white", hover_color="#f3f3f3", text_color=color,
        corner_radius=28, border_color="#dddddd", border_width=1,
        height=52, font=("Noto Sans JP", 15, "bold")
    )
    btn.pack(fill="x", padx=6)
    return btn

def add_small_chip(parent, text, fg="#1e3a5f"):
    chip = ctk.CTkLabel(
        parent, text=text, text_color=fg,
        fg_color="#eef2f5", corner_radius=12,
        font=("Noto Sans JP", 12, "bold"), padx=10, pady=6
    )
    chip.pack(side="left", padx=6, pady=6)
    return chip

# =====================================================
# ✏ ブログ / お知らせの編集ウィンドウ（共通）
# =====================================================
def open_edit(kind, id):
    data_file = BLOG_JSON if kind == "blog" else NEWS_JSON
    folder    = BLOG_DIR if kind == "blog" else NEWS_DIR
    filename  = f"{kind}_{id}.html"

    lst = load_json(data_file)
    a = next((x for x in lst if x["id"] == id), None)
    if not a:
        messagebox.showerror("エラー", "記事が見つかりません")
        return

    win = ctk.CTkToplevel(root)
    win.title(f"✏ 編集: {a['title']}")
    win.geometry("720x920")
    win.configure(fg_color="#fafafa")

    head = ctk.CTkFrame(win, fg_color="#fafafa")
    head.pack(fill="x", padx=20, pady=(15,5))
    ctk.CTkLabel(
        head,
        text=("ブログ編集" if kind=="blog" else "お知らせ編集"),
        font=("Noto Sans JP", 18, "bold"),
        text_color="#1e3a5f"
    ).pack(side="left")

    frm = ctk.CTkScrollableFrame(win, fg_color="#f7f7f7", corner_radius=18)
    frm.pack(fill="both", expand=True, padx=20, pady=10)

    # タイトル
    ctk.CTkLabel(frm, text="タイトル", text_color="#1e3a5f").grid(
        row=0, column=0, sticky="w", padx=16, pady=(12,4)
    )
    ent_title = ctk.CTkEntry(frm, width=620)
    ent_title.insert(0, a.get("title",""))
    ent_title.grid(row=1, column=0, sticky="w", padx=16)

    # 導入文
    ctk.CTkLabel(frm, text="導入文（meta説明）", text_color="#1e3a5f").grid(
        row=2, column=0, sticky="w", padx=16, pady=(12,4)
    )
    ent_excerpt = ctk.CTkEntry(frm, width=620)
    ent_excerpt.insert(0, a.get("excerpt",""))
    ent_excerpt.grid(row=3, column=0, sticky="w", padx=16)

    # サムネ
    ctk.CTkLabel(frm, text="サムネイル（任意）", text_color="#1e3a5f").grid(
        row=4, column=0, sticky="w", padx=16, pady=(12,4)
    )
    thumb_var = ctk.StringVar(value=a.get("image","") or "（なし）")
    ctk.CTkOptionMenu(
        frm,
        values=["（なし）"]+get_thumbnails(),
        variable=thumb_var,
        width=620
    ).grid(row=5, column=0, sticky="w", padx=16)

    def choose_image_edit():
        new_img = select_and_copy_image()
        if new_img:
            thumb_var.set(new_img)
            messagebox.showinfo("追加完了", f"画像を追加しました:\n{new_img}")

    choose_btn = ctk.CTkButton(
        frm,
        text="📁 画像を選択して追加",
        command=choose_image_edit,
        fg_color="#1e3a5f",
        hover_color="#16304A",
        text_color="white",
        corner_radius=20,
        width=200,
        height=38
    )
    choose_btn.grid(row=6, column=0, sticky="w", padx=16, pady=(6, 10))

    # カテゴリ
    ctk.CTkLabel(
        frm,
        text="カテゴリ（例：健康、美容、トレーニング）",
        text_color="#1e3a5f"
    ).grid(row=7, column=0, sticky="w", padx=16, pady=(10,4))
    ent_category = ctk.CTkEntry(frm, width=620)
    ent_category.insert(0, a.get("category", ""))
    ent_category.grid(row=8, column=0, sticky="w", padx=16)

    # タグ
    ctk.CTkLabel(
        frm,
        text="タグ（カンマ区切りで複数入力可）",
        text_color="#1e3a5f"
    ).grid(row=9, column=0, sticky="w", padx=16, pady=(12,4))
    ent_tags = ctk.CTkEntry(frm, width=620)
    ent_tags.insert(0, ", ".join(a.get("tags", [])))
    ent_tags.grid(row=10, column=0, sticky="w", padx=16)

    # 下書き
    draft_var = ctk.BooleanVar(value=a.get("draft", False))
    ctk.CTkCheckBox(
        frm,
        text="非公開（下書き）",
        variable=draft_var,
        text_color="#1e3a5f"
    ).grid(row=11, column=0, sticky="w", padx=16, pady=(10,0))

    # 本文
    ctk.CTkLabel(
        frm,
        text="本文（HTML可 / 改行は自動で<br>に変換）",
        text_color="#1e3a5f"
    ).grid(row=12, column=0, sticky="w", padx=16, pady=(12,4))
    txt_body = ctk.CTkTextbox(frm, height=360, corner_radius=14)

    body_text = a.get("body", "").strip()
    if not body_text:
        txt_body.insert("1.0", "ここに本文を入力してください")
        txt_body.configure(text_color="#999999")
        placeholder = True
    else:
        txt_body.insert("1.0", body_text)
        placeholder = False

    def clear_placeholder(event):
        nonlocal placeholder
        if placeholder:
            txt_body.delete("1.0", "end")
            txt_body.configure(text_color="#000000")
            placeholder = False

    def restore_placeholder(event):
        nonlocal placeholder
        if txt_body.get("1.0", "end-1c").strip() == "":
            txt_body.insert("1.0", "ここに本文を入力してください")
            txt_body.configure(text_color="#999999")
            placeholder = True

    txt_body.bind("<FocusIn>", clear_placeholder)
    txt_body.bind("<FocusOut>", restore_placeholder)
    txt_body.grid(row=13, column=0, sticky="we", padx=16, pady=(0,16))
    frm.grid_columnconfigure(0, weight=1)

    def do_save():
        print("編集保存スタート")

        a["title"]    = ent_title.get().strip()
        a["excerpt"]  = ent_excerpt.get().strip()
        a["category"] = ent_category.get().strip()
        a["tags"]     = [t.strip() for t in ent_tags.get().split(",") if t.strip()]
        a["image"]    = "" if thumb_var.get()=="（なし）" else thumb_var.get()
        a["draft"]    = bool(draft_var.get())

        raw_body = txt_body.get("1.0", "end-1c").strip()
        a["body"] = raw_body

        # JSON保存用本文
        if not raw_body or "ここに本文を入力してください" in raw_body:
            body_html = "<p>(本文未入力)</p>"
        else:
            body_html = raw_body.replace("\n", "<br>")

        save_json(data_file, lst)

        messagebox.showinfo("保存", "更新しました。")
        print("編集保存完了")

        # 3秒待機
        time.sleep(3)

        # 🔵 投稿/編集後は本番URLでプレビュー
        try:
            if kind == "blog":
                webbrowser.open(f"{BASE_URL}/blog/{id}")
            else:
                webbrowser.open(f"{BASE_URL}/news/{id}")
        except Exception as e:
            print("ブラウザオープン失敗:", e)

    footer = ctk.CTkFrame(win, fg_color="#fafafa")
    footer.pack(fill="x", padx=20, pady=(8, 16))
    add_main_button(footer, "💾 投稿 / 保存", do_save)




# =====================================================
# 📚 一覧（ブログ + お知らせ）
# =====================================================
def delete_article(kind, id):
    data_file = BLOG_JSON if kind == "blog" else NEWS_JSON

    lst = load_json(data_file)
    lst = [x for x in lst if x["id"] != id]
    save_json(data_file, lst)


def open_list(mode="public"):
    """ブログ/ニュース 一覧。右端に編集/削除を揃えて表示。"""
    win = ctk.CTkToplevel(root)
    win.title("📚 記事一覧")
    win.geometry("860x820")
    win.configure(fg_color="#fafafa")

    top = ctk.CTkFrame(win, fg_color="#fafafa")
    top.pack(fill="x", padx=18, pady=(16,8))
    ctk.CTkLabel(
        top,
        text=("📚 公開中の記事一覧" if mode=="public" else "📝 下書き一覧"),
        font=("Noto Sans JP", 18, "bold"),
        text_color="#1e3a5f"
    ).pack(side="left")

    frame = ctk.CTkScrollableFrame(
        win, width=820, height=680,
        fg_color="#f7f7f7", corner_radius=18
    )
    frame.pack(fill="both", expand=True, padx=18, pady=(4,18))

    data=[]
    for f,kind in [(BLOG_JSON,"blog"),(NEWS_JSON,"news")]:
        for x in load_json(f):
            data.append((
                kind,
                x["id"],
                x.get("title",""),
                x.get("date",""),
                bool(x.get("draft",False))
            ))

    data.sort(key=lambda t: t[3], reverse=True)

    for k,i,t,d,dr in data:
        if (mode=="public" and dr) or (mode=="draft" and not dr):
            continue
        row = ctk.CTkFrame(frame, fg_color="white", corner_radius=18)
        row.pack(fill="x", padx=12, pady=6)

        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=0)
        row.grid_columnconfigure(2, weight=0)

        status = "📝下書き" if dr else "📢公開"
        label = ctk.CTkLabel(
            row,
            text=f"{status}｜{k.upper()}｜{d}｜{t}",
            text_color="#1e3a5f",
            anchor="w",
            justify="left",
            wraplength=560
        )
        label.grid(row=0, column=0, padx=14, pady=10, sticky="w")

        edit_btn = ctk.CTkButton(
            row,
            text="✏ 編集",
            command=lambda k=k, i=i: open_edit(k, i),
            fg_color="#1e3a5f", hover_color="#16304A", text_color="white",
            corner_radius=14, width=90, height=40
        )
        edit_btn.grid(row=0, column=1, padx=(8, 6), pady=8, sticky="e")

        del_btn = ctk.CTkButton(
            row,
            text="🗑 削除",
            command=lambda k=k, i=i, w=row: (delete_article(k, i), w.destroy()),
            fg_color="#ff8a8a", hover_color="#ff9d9d", text_color="white",
            corner_radius=14, width=90, height=40
        )
        del_btn.grid(row=0, column=2, padx=(0, 12), pady=8, sticky="e")

# =====================================================
# 🆕 新規ブログ / お知らせ 作成
# =====================================================
def new_post(kind="blog"):
    data_file = BLOG_JSON if kind == "blog" else NEWS_JSON
    title_txt = "📝 新規ブログ投稿" if kind == "blog" else "🗞️ 新規お知らせ投稿"

    win = ctk.CTkToplevel(root)
    win.title(title_txt)
    win.geometry("720x900")
    win.configure(fg_color="#fafafa")

    ctk.CTkLabel(
        win,
        text=title_txt,
        font=("Noto Sans JP",20,"bold"),
        text_color="#1e3a5f"
    ).pack(pady=(14,6))

    body = ctk.CTkScrollableFrame(win, fg_color="#f7f7f7", corner_radius=18)
    body.pack(fill="both", expand=True, padx=20, pady=(4,0))

    # タイトル
    ctk.CTkLabel(body, text="タイトル", text_color="#1e3a5f").grid(
        row=0, column=0, sticky="w", padx=16, pady=(12,4)
    )
    ent_title = ctk.CTkEntry(body, width=620)
    ent_title.grid(row=1, column=0, sticky="w", padx=16)

    # 導入文
    ctk.CTkLabel(body, text="導入文（meta説明）", text_color="#1e3a5f").grid(
        row=2, column=0, sticky="w", padx=16, pady=(12,4)
    )
    ent_excerpt = ctk.CTkEntry(body, width=620)
    ent_excerpt.grid(row=3, column=0, sticky="w", padx=16)

    # サムネイル選択
    ctk.CTkLabel(body, text="サムネイル（任意）", text_color="#1e3a5f").grid(
        row=4, column=0, sticky="w", padx=16, pady=(12,4)
    )
    thumb = ctk.StringVar(value="（なし）")
    ctk.CTkOptionMenu(
        body,
        values=["（なし）"] + get_thumbnails(),
        variable=thumb,
        width=620
    ).grid(row=5, column=0, sticky="w", padx=16)

    def choose_image_new():
        new_img = select_and_copy_image()
        if new_img:
            thumb.set(new_img)
            messagebox.showinfo("追加完了", f"画像を追加しました:\n{new_img}")

    choose_btn = ctk.CTkButton(
        body,
        text="📁 画像を選択して追加",
        command=choose_image_new,
        fg_color="#1e3a5f",
        hover_color="#16304A",
        text_color="white",
        corner_radius=22,
        width=240,
        height=46
    )
    choose_btn.grid(row=6, column=0, sticky="w", padx=16, pady=(8, 14))

    # カテゴリ
    ctk.CTkLabel(
        body,
        text="カテゴリ（例：健康、美容、トレーニング）",
        text_color="#1e3a5f"
    ).grid(row=7, column=0, sticky="w", padx=16, pady=(10,4))
    ent_category = ctk.CTkEntry(body, width=620)
    ent_category.grid(row=8, column=0, sticky="w", padx=16)

    # タグ
    ctk.CTkLabel(
        body,
        text="タグ（カンマ区切りで複数入力可）",
        text_color="#1e3a5f"
    ).grid(row=9, column=0, sticky="w", padx=16, pady=(12,4))
    ent_tags = ctk.CTkEntry(body, width=620)
    ent_tags.grid(row=10, column=0, sticky="w", padx=16)

    # 下書き
    draft = ctk.BooleanVar(value=False)
    ctk.CTkCheckBox(
        body,
        text="非公開（下書き）",
        variable=draft,
        text_color="#1e3a5f"
    ).grid(row=11, column=0, sticky="w", padx=16, pady=(10,2))

    body.grid_columnconfigure(0, weight=1)

    # 本文
    ctk.CTkLabel(
        body,
        text="本文（HTML可 / 改行は自動で<br>に変換）",
        text_color="#1e3a5f"
    ).grid(row=12, column=0, sticky="w", padx=16, pady=(12,4))
    txt_body = ctk.CTkTextbox(body, height=360, corner_radius=14)
    placeholder_text = "ここに本文を入力してください。"
    txt_body.insert("1.0", placeholder_text)
    txt_body.configure(text_color="#888")

    def clear_placeholder(event):
        if txt_body.get("1.0", "end-1c") == placeholder_text:
            txt_body.delete("1.0", "end")
            txt_body.configure(text_color="#000")

    def restore_placeholder(event):
        if not txt_body.get("1.0", "end-1c").strip():
            txt_body.insert("1.0", placeholder_text)
            txt_body.configure(text_color="#888")

    txt_body.bind("<FocusIn>", clear_placeholder)
    txt_body.bind("<FocusOut>", restore_placeholder)
    txt_body.grid(row=13, column=0, sticky="we", padx=16, pady=(0,16))
    body.grid_columnconfigure(0, weight=1)

    def do_save():
        title = ent_title.get().strip()
        if not title:
            messagebox.showwarning("未入力", "タイトルを入力してください。")
            return

        body_raw = txt_body.get("1.0", "end-1c").strip()

        if body_raw.startswith("<h1"):
            end = body_raw.find("</h1>")
            if end != -1:
                body_raw = body_raw[end+5:].lstrip()

        if not body_raw or "ここに本文を入力してください" in body_raw:
            body_html = "<p>(本文未入力)</p>"
        else:
            body_html = body_raw.replace("\n", "<br>")

        # Supabase INSERT --------------------------
        res = supabase.table("blogs").insert({
            "title": title,
            "excerpt": ent_excerpt.get().strip(),
            "date": today(),
            "image": "" if thumb.get() == "（なし）" else thumb.get(),
            "category": ent_category.get().strip(),
            "tags": [t.strip() for t in ent_tags.get().split(",") if t.strip()],
            "body": body_html,
            "draft": bool(draft.get())
        }).execute()

        messagebox.showinfo("保存完了", "投稿を保存しました。")

        # 追加されたレコードの ID を取得
        nid = res.data[0]["id"]

        # プレビューを開く
        time.sleep(2)
        webbrowser.open(f"https://karin-website.onrender.com/blog/{nid}")

    footer = ctk.CTkFrame(win, fg_color="#fafafa")
    footer.pack(fill="x", padx=20, pady=(8, 16))
    add_main_button(footer, "💾 投稿 / 保存", do_save)





# =====================================================
# 🔒 マイページ（動画 / 記事 / 会員ニュース）
# =====================================================
def mp_new(kind="video"):
    """マイページ用の新規追加（動画/記事/会員向けお知らせ）"""
    mapping = {
        "video":   ("🎥 セルフケア動画の追加", MYPAGE_VIDEOS),
        "article": ("📰 限定記事の追加",     MYPAGE_ARTICLES),
        "mnews":   ("📢 会員向けお知らせの追加", MYPAGE_NEWS),
    }
    title_txt, data_file = mapping[kind]

    win = ctk.CTkToplevel(root)
    win.title(title_txt)
    win.geometry("720x720")
    win.configure(fg_color="#fafafa")

    ctk.CTkLabel(
        win,
        text=title_txt,
        font=("Noto Sans JP",20,"bold"),
        text_color="#1e3a5f"
    ).pack(pady=(14,6))

    body = ctk.CTkFrame(win, fg_color="#f7f7f7", corner_radius=18)
    body.pack(fill="both", expand=True, padx=20, pady=(4,18))

    row = 0
    ctk.CTkLabel(body, text="タイトル", text_color="#1e3a5f").grid(
        row=row, column=0, sticky="w", padx=16, pady=(14,4)
    ); row+=1
    ent_title = ctk.CTkEntry(body, width=620)
    ent_title.grid(row=row, column=0, sticky="w", padx=16); row+=1

    if kind in ("video","article"):
        ctk.CTkLabel(body, text="URL（YouTube/記事など）", text_color="#1e3a5f").grid(
            row=row, column=0, sticky="w", padx=16, pady=(12,4)
        ); row+=1
        ent_url = ctk.CTkEntry(body, width=620)
        ent_url.grid(row=row, column=0, sticky="w", padx=16); row+=1
    else:
        ent_url = None

    ctk.CTkLabel(
        body,
        text=("説明（任意）" if kind!="mnews" else "本文/説明"),
        text_color="#1e3a5f"
    ).grid(row=row, column=0, sticky="w", padx=16, pady=(12,4)); row+=1
    txt_desc = ctk.CTkTextbox(body, height=220, corner_radius=14)
    txt_desc.grid(row=row, column=0, sticky="we", padx=16); row+=1

    ctk.CTkLabel(body, text="日付（自動入力可）", text_color="#1e3a5f").grid(
        row=row, column=0, sticky="w", padx=16, pady=(12,4)
    ); row+=1
    ent_date = ctk.CTkEntry(body, width=240, placeholder_text="YYYY-MM-DD")
    ent_date.insert(0, today())
    ent_date.grid(row=row, column=0, sticky="w", padx=16); row+=1

    body.grid_columnconfigure(0, weight=1)

    def do_save():
        title = ent_title.get().strip()
        if not title:
            messagebox.showwarning("未入力", "タイトルは必須です。")
            return

        rec = {
            "title": title,
            "desc": txt_desc.get("1.0","end").strip(),
            "date": ent_date.get().strip()
        }
        if ent_url is not None:
            rec["url"] = ent_url.get().strip()

        data = load_json(data_file)
        data.append(rec)

        try:
            data.sort(key=lambda x: x.get("date",""), reverse=True)
        except Exception:
            pass

        save_json(data_file, data)
        messagebox.showinfo("保存", "マイページデータを保存しました。")

    add_main_button(win, "💾 追加を保存", do_save)

def mp_list(kind="video"):
    """マイページ用の一覧（編集/削除）"""
    mapping = {
        "video":   ("🎥 セルフケア動画 一覧", MYPAGE_VIDEOS,   ["title","url","desc","date"]),
        "article": ("📰 限定記事 一覧",     MYPAGE_ARTICLES, ["title","url","desc","date"]),
        "mnews":   ("📢 会員向けお知らせ 一覧", MYPAGE_NEWS,     ["title","desc","date"]),
    }
    title_txt, data_file, keys = mapping[kind]

    win = ctk.CTkToplevel(root)
    win.title(title_txt)
    win.geometry("860x820")
    win.configure(fg_color="#fafafa")

    ctk.CTkLabel(
        win,
        text=title_txt,
        font=("Noto Sans JP",18,"bold"),
        text_color="#1e3a5f"
    ).pack(pady=(16,8))

    frame = ctk.CTkScrollableFrame(
        win, width=820, height=700,
        fg_color="#f7f7f7", corner_radius=18
    )
    frame.pack(fill="both", expand=True, padx=18, pady=(4,18))

    data = load_json(data_file)
    try:
        data.sort(key=lambda x: x.get("date",""), reverse=True)
    except Exception:
        pass

    def draw_rows():
        for child in frame.winfo_children():
            child.destroy()

        for idx, rec in enumerate(data):
            row = ctk.CTkFrame(frame, fg_color="white", corner_radius=18)
            row.pack(fill="x", padx=12, pady=6)

            row.grid_columnconfigure(0, weight=1)
            row.grid_columnconfigure(1, weight=0)
            row.grid_columnconfigure(2, weight=0)

            title = rec.get("title","（無題）")
            date  = rec.get("date","")
            kind_label = {"video":"VIDEO", "article":"ARTICLE", "mnews":"NEWS"}[kind]
            header = f"{kind_label}｜{date}｜{title}"

            lbl = ctk.CTkLabel(
                row,
                text=header,
                text_color="#1e3a5f",
                anchor="w",
                justify="left",
                wraplength=560
            )
            lbl.grid(row=0, column=0, padx=14, pady=10, sticky="w")

            def do_edit(i=idx):
                ew = ctk.CTkToplevel(win)
                ew.title("✏ 編集")
                ew.geometry("640x640")
                ew.configure(fg_color="#fafafa")

                frm = ctk.CTkScrollableFrame(
                    ew,
                    fg_color="#f7f7f7",
                    corner_radius=18,
                    width=600,
                    height=520
                )
                frm.pack(fill="both", expand=True, padx=16, pady=16)

                entries = {}
                r = 0
                for k in keys:
                    ctk.CTkLabel(
                        frm,
                        text=k.upper(),
                        text_color="#1e3a5f"
                    ).grid(row=r, column=0, sticky="w", padx=12, pady=(12,4)); r+=1

                    if k == "desc":
                        tb = ctk.CTkTextbox(frm, height=240, corner_radius=12)
                        tb.insert("1.0", rec.get(k,""))
                        tb.grid(row=r, column=0, sticky="we", padx=12); r+=1
                        entries[k] = tb
                    else:
                        en = ctk.CTkEntry(frm)
                        en.insert(0, rec.get(k,""))
                        en.grid(row=r, column=0, sticky="we", padx=12); r+=1
                        entries[k] = en

                frm.grid_columnconfigure(0, weight=1)

                def save_edit():
                    for k in keys:
                        if k == "desc":
                            rec[k] = entries[k].get("1.0","end").strip()
                        else:
                            rec[k] = entries[k].get().strip()

                    try:
                        data.sort(key=lambda x: x.get("date",""), reverse=True)
                    except Exception:
                        pass
                    save_json(data_file, data)
                    messagebox.showinfo("保存", "更新しました。")
                    ew.destroy()
                    draw_rows()

                add_main_button(ew, "💾 更新を保存", save_edit)

            def do_delete(i=idx, row_widget=row):
                if not messagebox.askyesno("確認", "この項目を削除しますか？"):
                    return
                data.pop(i)
                save_json(data_file, data)
                row_widget.destroy()

            edit_btn = ctk.CTkButton(
                row,
                text="✏ 編集",
                command=do_edit,
                fg_color="#1e3a5f",
                hover_color="#16304A",
                text_color="white",
                corner_radius=14, width=90, height=40
            )
            edit_btn.grid(row=0, column=1, padx=(8, 6), pady=8, sticky="e")

            del_btn = ctk.CTkButton(
                row,
                text="🗑 削除",
                command=do_delete,
                fg_color="#ff8a8a",
                hover_color="#ff9d9d",
                text_color="white",
                corner_radius=14, width=90, height=40
            )
            del_btn.grid(row=0, column=2, padx=(0, 12), pady=8, sticky="e")

    draw_rows()

# =====================================================
# メイン UI
# =====================================================
header = ctk.CTkFrame(root, fg_color="#fafafa")
header.pack(fill="x", padx=20, pady=(20,6))
ctk.CTkLabel(
    header,
    text="🪷 KARiN. Content Manager",
    font=("Noto Sans JP", 22, "bold"),
    text_color="#1e3a5f"
).pack(side="left")

chipbar = ctk.CTkFrame(root, fg_color="#fafafa")
chipbar.pack(fill="x", padx=24, pady=(0,4))
add_small_chip(chipbar, "白ボタン=追加/実行")
add_small_chip(chipbar, "ネイビーボタン=編集/保存", "#16304A")
add_small_chip(chipbar, "赤ボタン=削除", "#b94a48")

# ---- ブログ/お知らせ 管理 ----
sec1 = ctk.CTkFrame(root, fg_color="#fafafa", corner_radius=0)
sec1.pack(fill="x", padx=12, pady=(6,2))
ctk.CTkLabel(
    sec1,
    text="📚 ブログ / 🗞️ お知らせ",
    font=("Noto Sans JP", 18, "bold"),
    text_color="#1e3a5f"
).pack(anchor="w", padx=12, pady=(6,2))

add_main_button(root, "🆕 新規ブログ投稿",        lambda: new_post("blog"))
add_main_button(root, "🗞️ 新規お知らせ投稿",    lambda: new_post("news"))
add_main_button(root, "📚 公開中の記事一覧（検索/編集/削除）", lambda: open_list("public"))
add_main_button(root, "📝 下書き一覧（公開前の記事）",       lambda: open_list("draft"))

# ---- マイページ 管理 ----
sec2 = ctk.CTkFrame(root, fg_color="#fafafa", corner_radius=0)
sec2.pack(fill="x", padx=12, pady=(18,2))
ctk.CTkLabel(
    sec2,
    text="🔒 会員マイページ 管理（セルフケア動画 / 限定記事 / 会員向けお知らせ）",
    font=("Noto Sans JP", 18, "bold"),
    text_color="#1e3a5f"
).pack(anchor="w", padx=12, pady=(6,2))

add_main_button(root, "🎥 セルフケア動画を追加", lambda: mp_new("video"))
add_main_button(root, "📰 限定記事を追加",     lambda: mp_new("article"))
add_main_button(root, "📢 会員向けお知らせを追加", lambda: mp_new("mnews"))

add_main_button(root, "🎥 セルフケア動画 一覧（編集/削除）", lambda: mp_list("video"))
add_main_button(root, "📰 限定記事 一覧（編集/削除）",     lambda: mp_list("article"))
add_main_button(root, "📢 会員向けお知らせ 一覧（編集/削除）", lambda: mp_list("mnews"))

# 終了ボタン
add_main_button(root, "❌ 終了", root.destroy, color="#a83b3b")

root.mainloop()
