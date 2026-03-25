# content_gui_ctk_supabase.py
# ---------------------------------------------------------------
# KARiN. Content Manager (Blogs / News / Mypage) - Supabase 完全移行版
#
# 依存:
#   pip install customtkinter supabase-py
#
# 必要な環境変数:
#   SUPABASE_SERVICE_ROLE_KEY  … Supabase の Service Role キー
#
# Supabase 前提:
#   blogs テーブル
#   news  テーブル
#   comments テーブル（後でコメント管理UIで使用）
#   storage バケット: blog-images（public = true）
#
# JSON で管理するもの（従来どおり維持）:
#   static/data/mypage_videos.json
#   static/data/mypage_articles.json
#   static/data/mypage_news.json
#
# ---------------------------------------------------------------

import os
import json
import shutil
import time
import mimetypes
import uuid
import re
from datetime import datetime, timedelta, timezone
import webbrowser
from tkinter import messagebox, filedialog

import customtkinter as ctk

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


def _textarea_body_double_newlines_to_br(body_raw):
    """
    ブログ・ニュース共通（app._textarea_body_double_newlines_to_br と同じ）。
    連続 n 改行に対し <br> を (n - 1) 個。単独改行はそのまま。
    """
    if body_raw is None:
        return ""
    return re.sub(
        r"\n{2,}",
        lambda m: "<br>" * (len(m.group(0)) - 1),
        body_raw,
    )


# =========================
# タイムゾーン (JST)
# =========================
JST = timezone(timedelta(hours=9))

# =========================
# Supabase 接続設定
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # ← これだけ使う

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError(
        "環境変数 SUPABASE_URL または SUPABASE_SERVICE_KEY が設定されていません。\n"
        ".env に以下を記載してください。\n"
        'SUPABASE_URL="xxxx"\n'
        'SUPABASE_SERVICE_KEY="service_role_key"\n'
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# =========================
# パス設定
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static/images/blogs")


# =========================
# 外観・基本ウィンドウ
# =========================
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

root = ctk.CTk()
root.title("🪷 KARiN. Content Manager (Supabase版)")
root.geometry("760x980")
root.minsize(680, 820)
root.configure(fg_color="#fafafa")

# =========================
# パス設定（JSON維持部分）
# =========================
MYPAGE_VIDEOS   = "static/data/mypage_videos.json"
MYPAGE_ARTICLES = "static/data/mypage_articles.json"
MYPAGE_NEWS     = "static/data/mypage_news.json"

for path in [
    os.path.dirname(MYPAGE_VIDEOS),
    os.path.dirname(MYPAGE_ARTICLES),
    os.path.dirname(MYPAGE_NEWS),
]:
    if path and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

# 🔵 本番URL（プレビューで開く先）
BASE_URL = "https://karin-sb.jp"

# =========================
# 共通ユーティリティ
# =========================
def today():
    return datetime.now(JST).strftime("%Y-%m-%d")

def now_iso():
    return datetime.now(JST).isoformat()

def load_json(file):
    """マイページ系の JSON 読み込み専用"""
    try:
        if os.path.exists(file):
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        messagebox.showerror("読み込みエラー", f"{file}\n{e}")
    return []

def save_json(file, data_list):
    """マイページ系の JSON 保存専用"""
    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        messagebox.showerror("保存エラー", f"{file}\n{e}")

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

# =========================
# Supabase ヘルパー
# =========================
def upload_image_to_supabase(file_path: str, bucket="blog-images") -> str:
    """
    画像を Supabase Storage にアップロードし、public URL を返す。
    """
    if not file_path:
        return ""

    file_name = os.path.basename(file_path)
    # 重複を避けるため uuid 付与
    ext = os.path.splitext(file_name)[1].lower()
    safe_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = safe_name

    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    with open(file_path, "rb") as f:
        file_data = f.read()

    try:
        supabase.storage.from_(bucket).upload(
            path=storage_path,
            file=file_data,
            file_options={"content-type": mime_type}
        )
    except Exception as e:
        messagebox.showerror("画像アップロードエラー", f"Storage へのアップロードに失敗しました。\n{e}")
        raise

    public_url = supabase.storage.from_(bucket).get_public_url(storage_path)
    return public_url

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
        query = supabase.table(table).select("id, slug").eq("slug", slug)
        if current_id is not None:
            query = query.neq("id", current_id)
        res = query.execute()
        if not res.data:
            break
        slug = f"{base}-{counter}"
        counter += 1

    return slug

def fetch_articles_from_supabase(mode="public", search_query=""):
    """
    blogs + news を Supabase から取得して一覧用のリストに整形。
    mode: "public" or "draft"
    search_query: 検索クエリ（タイトル/カテゴリ/タグ/本文に部分一致）
    戻り値: list of dicts
      {
        "kind": "blog" or "news",
        "id": int,
        "title": str,
        "date": str,
        "draft": bool,
        "category": str,
        "tags": list[str],
        "body": str
      }
    """
    articles = []

    # blogs
    try:
        res_b = supabase.table("blogs").select("*").order("created_at", desc=True).execute()
        for row in res_b.data or []:
            rec = {
                "kind": "blog",
                "id": row.get("id"),
                "title": row.get("title", ""),
                "date": row.get("date", "") or row.get("created_at", "")[:10],
                "draft": bool(row.get("draft", False)),
                "category": row.get("category", "") or "",
                "tags": row.get("tags", []) or [],
                "body": row.get("body", "") or ""
            }
            articles.append(rec)
    except Exception as e:
        messagebox.showerror("エラー", f"blogs の取得に失敗しました。\n{e}")

    # news
    try:
        res_n = supabase.table("news").select("*").order("created_at", desc=True).execute()
        for row in res_n.data or []:
            rec = {
                "kind": "news",
                "id": row.get("id"),
                "title": row.get("title", ""),
                "date": row.get("created_at", "")[:10],
                "draft": bool(row.get("draft", False)),
                "category": row.get("category", "") or "",
                "tags": [],   # news には tags カラムなし（必要なら追加可）
                "body": row.get("body", "") or ""
            }
            articles.append(rec)
    except Exception as e:
        messagebox.showerror("エラー", f"news の取得に失敗しました。\n{e}")

    # mode で絞り込み
    filtered = []
    for a in articles:
        if mode == "public" and a["draft"]:
            continue
        if mode == "draft" and not a["draft"]:
            continue
        filtered.append(a)

    # 検索クエリでフィルタ
    q = (search_query or "").strip().lower()
    if q:
        result = []
        for a in filtered:
            haystack = " ".join([
                a["title"],
                a["date"],
                a["category"],
                ",".join(a["tags"]),
                a["body"],
            ]).lower()
            if q in haystack:
                result.append(a)
        filtered = result

    # 日付でソート（文字列ベースだが YYYY-MM-DD 前提）
    filtered.sort(key=lambda x: x["date"], reverse=True)
    return filtered

def fetch_single_article(kind: str, article_id: int) -> dict | None:
    """Supabase から単一記事を取得"""
    table = "blogs" if kind == "blog" else "news"
    try:
        res = supabase.table(table).select("*").eq("id", article_id).execute()
        if not res.data:
            return None
        return res.data[0]
    except Exception as e:
        messagebox.showerror("エラー", f"{table} の記事取得に失敗しました。\n{e}")
        return None

def delete_article_from_supabase(kind: str, article_id: int):
    """Supabase から記事を完全削除"""
    table = "blogs" if kind == "blog" else "news"
    try:
        supabase.table(table).delete().eq("id", article_id).execute()
    except Exception as e:
        messagebox.showerror("削除エラー", f"{table} の削除に失敗しました。\n{e}")

# =====================================================
# ✏ ブログ / お知らせ 編集ウィンドウ（Supabase版）
# =====================================================
def open_edit(kind, id):
    table = "blogs" if kind == "blog" else "news"
    row = fetch_single_article(kind, id)
    if not row:
        messagebox.showerror("エラー", "記事が見つかりません（Supabase）")
        return

    win = ctk.CTkToplevel(root)
    win.title(f"✏ 編集: {row.get('title','')}")
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
    ent_title.insert(0, row.get("title",""))
    ent_title.grid(row=1, column=0, sticky="w", padx=16)

    # slug
    ctk.CTkLabel(frm, text="URLスラッグ（任意・自動生成済み）", text_color="#1e3a5f").grid(
        row=2, column=0, sticky="w", padx=16, pady=(12,4)
    )
    ent_slug = ctk.CTkEntry(frm, width=620)
    ent_slug.insert(0, row.get("slug",""))
    ent_slug.grid(row=3, column=0, sticky="w", padx=16)

    # 導入文（blogsのみ）
    row_idx = 4
    if kind == "blog":
        ctk.CTkLabel(frm, text="導入文（meta説明）", text_color="#1e3a5f").grid(
            row=row_idx, column=0, sticky="w", padx=16, pady=(12,4)
        )
        ent_excerpt = ctk.CTkEntry(frm, width=620)
        ent_excerpt.insert(0, row.get("excerpt",""))
        ent_excerpt.grid(row=row_idx+1, column=0, sticky="w", padx=16)
        row_idx += 2
    else:
        ent_excerpt = None

    # サムネイル（URL）
    ctk.CTkLabel(frm, text="サムネイル画像（Storage URL）", text_color="#1e3a5f").grid(
        row=row_idx, column=0, sticky="w", padx=16, pady=(12,4)
    )
    thumb_url_var = ctk.StringVar(value=row.get("image",""))
    ent_thumb = ctk.CTkEntry(frm, width=620, textvariable=thumb_url_var)
    ent_thumb.grid(row=row_idx+1, column=0, sticky="w", padx=16, pady=(0,4))

    def choose_image_edit():
        file_path = filedialog.askopenfilename(
            title="サムネイル画像を選択",
            filetypes=[("画像ファイル", "*.jpg *.jpeg *.png *.webp")]
        )
        if not file_path:
            return
        try:
            url = upload_image_to_supabase(file_path, bucket="blog-images")
            thumb_url_var.set(url)
            messagebox.showinfo("アップロード完了", f"画像をアップロードしました。\n{url}")
        except Exception:
            # upload_image_to_supabase 内でエラー表示済み
            pass

    choose_btn = ctk.CTkButton(
        frm,
        text="📁 画像を選択してアップロード",
        command=choose_image_edit,
        fg_color="#1e3a5f",
        hover_color="#16304A",
        text_color="white",
        corner_radius=20,
        width=200,
        height=38
    )
    choose_btn.grid(row=row_idx+2, column=0, sticky="w", padx=16, pady=(6, 10))
    row_idx += 3

    # カテゴリ
    ctk.CTkLabel(
        frm,
        text="カテゴリ（例：健康、美容、トレーニング）",
        text_color="#1e3a5f"
    ).grid(row=row_idx, column=0, sticky="w", padx=16, pady=(10,4))
    ent_category = ctk.CTkEntry(frm, width=620)
    ent_category.insert(0, row.get("category",""))
    ent_category.grid(row=row_idx+1, column=0, sticky="w", padx=16)
    row_idx += 2

    # タグ（blogsのみ）
    if kind == "blog":
        ctk.CTkLabel(
            frm,
            text="タグ（カンマ区切りで複数入力可）",
            text_color="#1e3a5f"
        ).grid(row=row_idx, column=0, sticky="w", padx=16, pady=(12,4))
        ent_tags = ctk.CTkEntry(frm, width=620)
        tags_list = row.get("tags", []) or []
        ent_tags.insert(0, ", ".join(tags_list))
        ent_tags.grid(row=row_idx+1, column=0, sticky="w", padx=16)
        row_idx += 2
    else:
        ent_tags = None

    # 下書き
    draft_var = ctk.BooleanVar(value=bool(row.get("draft", False)))
    ctk.CTkCheckBox(
        frm,
        text="非公開（下書き）",
        variable=draft_var,
        text_color="#1e3a5f"
    ).grid(row=row_idx, column=0, sticky="w", padx=16, pady=(10,0))
    row_idx += 1

    # 本文
    _body_lbl = (
        "本文（HTML可。タグ間の1行改行はそのまま。段落の空けは空行＝Enter2回以上→<br>）"
        if kind == "blog"
        else "本文（プレーンテキスト。行の区切りは空行＝Enter2回以上で<br>／連続n改行は<br>がn−1個）"
    )
    ctk.CTkLabel(
        frm,
        text=_body_lbl,
        text_color="#1e3a5f"
    ).grid(row=row_idx, column=0, sticky="w", padx=16, pady=(12,4))
    row_idx += 1

    txt_body = ctk.CTkTextbox(frm, height=360, corner_radius=14)

    raw_body = row.get("body", "") or ""
    body_for_edit = re.sub(
        r"<\s*br\s*/?\s*>", "\n", raw_body, flags=re.IGNORECASE
    )
    if not body_for_edit.strip():
        txt_body.insert("1.0", "ここに本文を入力してください")
        txt_body.configure(text_color="#999999")
        placeholder = True
    else:
        txt_body.insert("1.0", body_for_edit)
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
    txt_body.grid(row=row_idx, column=0, sticky="we", padx=16, pady=(0,16))
    frm.grid_columnconfigure(0, weight=1)

    def do_save():
        # 入力値取得
        title = ent_title.get().strip()
        if not title:
            messagebox.showwarning("未入力", "タイトルを入力してください。")
            return

        slug_input = ent_slug.get().strip()
        if slug_input:
            slug = generate_unique_slug(table, slug_input, current_id=id)
        else:
            # タイトルから再生成
            slug = generate_unique_slug(table, title, current_id=id)

        category = ent_category.get().strip()
        image_url = thumb_url_var.get().strip()
        draft_flag = bool(draft_var.get())

        if kind == "blog":
            excerpt = ent_excerpt.get().strip() if ent_excerpt else ""
            tags_raw = ent_tags.get() if ent_tags else ""
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        else:
            excerpt = None
            tags = None

        raw_body = txt_body.get("1.0", "end-1c")
        if "ここに本文を入力してください" in raw_body and raw_body.strip() == "ここに本文を入力してください":
            body_html = "<p>(本文未入力)</p>"
        else:
            rb = raw_body.strip()
            if not rb:
                body_html = "<p>(本文未入力)</p>"
            else:
                body_html = _textarea_body_double_newlines_to_br(rb)

        # Supabase UPDATE
        update_data = {
            "title": title,
            "slug": slug,
            "image": image_url,
            "category": category,
            "body": body_html,
            "draft": draft_flag,
            "updated_at": now_iso(),
        }

        if kind == "blog":
            update_data["excerpt"] = excerpt
            update_data["tags"] = tags

        try:
            supabase.table(table).update(update_data).eq("id", id).execute()
        except Exception as e:
            messagebox.showerror("エラー", f"Supabase更新エラー:\n{e}")
            return

        messagebox.showinfo("保存", "記事を更新しました。")

        # 少し待ってプレビューを開く（※まだ Flask 側は /blog/<id> ルート前提）
        time.sleep(2)
        try:
            if kind == "blog":
                # TODO: Flask 側のルートを /blog/<slug> に変更したらここも差し替える
                webbrowser.open(f"{BASE_URL}/blog/{slug}")
            else:
                webbrowser.open(f"{BASE_URL}/news/{slug}")
        except Exception as e:
            print("ブラウザオープン失敗:", e)

    footer = ctk.CTkFrame(win, fg_color="#fafafa")
    footer.pack(fill="x", padx=20, pady=(8, 16))
    add_main_button(footer, "💾 投稿 / 保存", do_save)

# =====================================================
# 📚 一覧（ブログ + お知らせ）Supabase版
# =====================================================
def open_list(mode="public"):
    """
    ブログ/ニュース 一覧 + 検索機能。
    Supabase から blogs/news を取得して表示。
    """
    win = ctk.CTkToplevel(root)
    win.title("📚 記事一覧 (Supabase)")
    win.geometry("900x860")
    win.configure(fg_color="#fafafa")

    # ヘッダー
    top = ctk.CTkFrame(win, fg_color="#fafafa")
    top.pack(fill="x", padx=18, pady=(16,8))
    ctk.CTkLabel(
        top,
        text=("📚 公開中の記事一覧" if mode=="public" else "📝 下書き一覧"),
        font=("Noto Sans JP", 18, "bold"),
        text_color="#1e3a5f"
    ).pack(side="left")

    # 検索バー
    search_frame = ctk.CTkFrame(win, fg_color="#fafafa")
    search_frame.pack(fill="x", padx=18, pady=(4,4))
    ctk.CTkLabel(
        search_frame,
        text="検索（タイトル / カテゴリ / タグ / 本文）",
        text_color="#1e3a5f"
    ).pack(anchor="w", padx=4)
    search_var = ctk.StringVar()
    search_entry = ctk.CTkEntry(search_frame, textvariable=search_var, width=520)
    search_entry.pack(side="left", padx=(4,8), pady=(4,8))
    def on_search():
        draw_rows()
    search_btn = ctk.CTkButton(
        search_frame,
        text="🔍 検索",
        command=on_search,
        fg_color="#1e3a5f",
        hover_color="#16304A",
        text_color="white",
        corner_radius=18,
        width=80,
        height=36
    )
    search_btn.pack(side="left", padx=4, pady=(4,8))

    # 一覧フレーム
    frame = ctk.CTkScrollableFrame(
        win, width=860, height=700,
        fg_color="#f7f7f7", corner_radius=18
    )
    frame.pack(fill="both", expand=True, padx=18, pady=(4,18))

    def draw_rows():
        for child in frame.winfo_children():
            child.destroy()

        q = search_var.get()
        data = fetch_articles_from_supabase(mode=mode, search_query=q)

        for a in data:
            kind = a["kind"]
            i    = a["id"]
            t    = a["title"]
            d    = a["date"]
            dr   = a["draft"]
            cat  = a["category"]

            row = ctk.CTkFrame(frame, fg_color="white", corner_radius=18)
            row.pack(fill="x", padx=12, pady=6)

            row.grid_columnconfigure(0, weight=1)
            row.grid_columnconfigure(1, weight=0)
            row.grid_columnconfigure(2, weight=0)

            status = "📝下書き" if dr else "📢公開"
            label_text = f"{status}｜{kind.upper()}｜{d}｜{t}"
            if cat:
                label_text += f"｜[{cat}]"

            label = ctk.CTkLabel(
                row,
                text=label_text,
                text_color="#1e3a5f",
                anchor="w",
                justify="left",
                wraplength=620
            )
            label.grid(row=0, column=0, padx=14, pady=10, sticky="w")

            edit_btn = ctk.CTkButton(
                row,
                text="✏ 編集",
                command=lambda k=kind, i=i: open_edit(k, i),
                fg_color="#1e3a5f", hover_color="#16304A", text_color="white",
                corner_radius=14, width=90, height=40
            )
            edit_btn.grid(row=0, column=1, padx=(8, 6), pady=8, sticky="e")

            def do_delete_article(k=kind, i=i, row_widget=row):
                if not messagebox.askyesno("確認", "この記事を完全削除しますか？\n（元には戻せません）"):
                    return
                delete_article_from_supabase(k, i)
                row_widget.destroy()

            del_btn = ctk.CTkButton(
                row,
                text="🗑 削除",
                command=do_delete_article,
                fg_color="#ff8a8a", hover_color="#ff9d9d", text_color="white",
                corner_radius=14, width=90, height=40
            )
            del_btn.grid(row=0, column=2, padx=(0, 12), pady=8, sticky="e")

    draw_rows()

# =====================================================
# 🆕 新規ブログ / お知らせ 作成（Supabase版）
# =====================================================
def new_post(kind="blog"):
    """
    blogs / news 新規投稿。
    kind: "blog" or "news"
    """
    table = "blogs" if kind == "blog" else "news"
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

    # slug
    ctk.CTkLabel(body, text="URLスラッグ（空欄なら自動生成）", text_color="#1e3a5f").grid(
        row=2, column=0, sticky="w", padx=16, pady=(12,4)
    )
    ent_slug = ctk.CTkEntry(body, width=620)
    ent_slug.grid(row=3, column=0, sticky="w", padx=16)

    row_idx = 4

    # 導入文（blog のみ）
    if kind == "blog":
        ctk.CTkLabel(body, text="導入文（meta説明）", text_color="#1e3a5f").grid(
            row=row_idx, column=0, sticky="w", padx=16, pady=(12,4)
        )
        ent_excerpt = ctk.CTkEntry(body, width=620)
        ent_excerpt.grid(row=row_idx+1, column=0, sticky="w", padx=16)
        row_idx += 2
    else:
        ent_excerpt = None

    # サムネイル（Storage アップロード）
    ctk.CTkLabel(body, text="サムネイル画像（任意）", text_color="#1e3a5f").grid(
        row=row_idx, column=0, sticky="w", padx=16, pady=(12,4)
    )
    thumb_url_var = ctk.StringVar(value="")
    ent_thumb = ctk.CTkEntry(body, width=620, textvariable=thumb_url_var)
    ent_thumb.grid(row=row_idx+1, column=0, sticky="w", padx=16)
    row_idx += 2

    def choose_image_new():
        file_path = filedialog.askopenfilename(
            title="サムネイル画像を選択",
            filetypes=[("画像ファイル", "*.jpg *.jpeg *.png *.webp")]
        )
        if not file_path:
            return
        try:
            url = upload_image_to_supabase(file_path, bucket="blog-images")
            thumb_url_var.set(url)
            messagebox.showinfo("アップロード完了", f"画像をアップロードしました。\n{url}")
        except Exception:
            pass

    choose_btn = ctk.CTkButton(
        body,
        text="📁 画像を選択してアップロード",
        command=choose_image_new,
        fg_color="#1e3a5f",
        hover_color="#16304A",
        text_color="white",
        corner_radius=22,
        width=240,
        height=46
    )
    choose_btn.grid(row=row_idx, column=0, sticky="w", padx=16, pady=(8, 14))
    row_idx += 1

    # カテゴリ
    ctk.CTkLabel(
        body,
        text="カテゴリ（例：健康、美容、トレーニング）",
        text_color="#1e3a5f"
    ).grid(row=row_idx, column=0, sticky="w", padx=16, pady=(10,4))
    ent_category = ctk.CTkEntry(body, width=620)
    ent_category.grid(row=row_idx+1, column=0, sticky="w", padx=16)
    row_idx += 2

    # タグ（blog のみ）
    if kind == "blog":
        ctk.CTkLabel(
            body,
            text="タグ（カンマ区切りで複数入力可）",
            text_color="#1e3a5f"
        ).grid(row=row_idx, column=0, sticky="w", padx=16, pady=(12,4))
        ent_tags = ctk.CTkEntry(body, width=620)
        ent_tags.grid(row=row_idx+1, column=0, sticky="w", padx=16)
        row_idx += 2
    else:
        ent_tags = None

    # 下書き
    draft = ctk.BooleanVar(value=False)
    ctk.CTkCheckBox(
        body,
        text="非公開（下書き）",
        variable=draft,
        text_color="#1e3a5f"
    ).grid(row=row_idx, column=0, sticky="w", padx=16, pady=(10,2))
    row_idx += 1

    body.grid_columnconfigure(0, weight=1)

    # 本文
    _new_body_lbl = (
        "本文（HTML可。タグ間の1行改行はそのまま。段落の空けは空行＝Enter2回以上→<br>）"
        if kind == "blog"
        else "本文（プレーンテキスト。行の区切りは空行＝Enter2回以上で<br>／連続n改行は<br>がn−1個）"
    )
    ctk.CTkLabel(
        body,
        text=_new_body_lbl,
        text_color="#1e3a5f"
    ).grid(row=row_idx, column=0, sticky="w", padx=16, pady=(12,4))
    row_idx += 1

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
    txt_body.grid(row=row_idx, column=0, sticky="we", padx=16, pady=(0,16))
    body.grid_columnconfigure(0, weight=1)

    def do_save():
        title = ent_title.get().strip()
        if not title:
            messagebox.showwarning("未入力", "タイトルを入力してください。")
            return

        slug_input = ent_slug.get().strip()
        if slug_input:
            slug = generate_unique_slug(table, slug_input)
        else:
            slug = generate_unique_slug(table, title)

        body_raw = txt_body.get("1.0", "end-1c").strip()
        if not body_raw or body_raw == placeholder_text:
            body_html = "<p>(本文未入力)</p>"
        else:
            body_html = _textarea_body_double_newlines_to_br(body_raw)

        image_url = thumb_url_var.get().strip()
        category = ent_category.get().strip()
        is_draft = bool(draft.get())

        if kind == "blog":
            excerpt = ent_excerpt.get().strip() if ent_excerpt else ""
            tags_raw = ent_tags.get() if ent_tags else ""
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        else:
            excerpt = None
            tags = None

        insert_data = {
            "title": title,
            "slug": slug,
            "image": image_url,
            "category": category,
            "body": body_html,
            "draft": is_draft,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }

        if kind == "blog":
            insert_data["excerpt"] = excerpt
            insert_data["tags"] = tags
            insert_data["date"] = today()  # 既存構造との整合性のため残す

        try:
            res = supabase.table(table).insert(insert_data).execute()
        except Exception as e:
            messagebox.showerror("保存エラー", f"{table} への保存に失敗しました。\n{e}")
            return

        messagebox.showinfo("保存完了", "投稿を保存しました。")
        nid = res.data[0]["id"]

        # プレビュー（※現状の Flask ルートに合わせて /blog/<id> を維持）
        time.sleep(2)
        try:
            if kind == "blog":
                webbrowser.open(f"{BASE_URL}/blog/{slug}")
            else:
                webbrowser.open(f"{BASE_URL}/news/{slug}")
        except Exception as e:
            print("ブラウザオープン失敗:", e)

    footer = ctk.CTkFrame(win, fg_color="#fafafa")
    footer.pack(fill="x", padx=20, pady=(8, 16))
    add_main_button(footer, "💾 投稿 / 保存", do_save)

# =====================================================
# 🔒 マイページ（動画 / 記事 / 会員ニュース）
#  ※ここは現状どおり JSON 管理を継続
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
    text="🪷 KARiN. Content Manager (Supabase)",
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
    text="📚 ブログ / 🗞️ お知らせ（Supabase管理）",
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
