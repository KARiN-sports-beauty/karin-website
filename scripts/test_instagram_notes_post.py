#!/usr/bin/env python3
"""KARiN.NOTES の Instagram 投稿。Meta API へは送らない。"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app as appmod
import external_posts
import instagram_graph
from meta_graph import MetaGraphTimeout

FAILED = 0
PASSED = 0
NOW = "2026-11-20T13:00:00+09:00"
TOKEN = "EAAtestsecretvalue000000000000"
PAGE_TOKEN = "EAApageaccesssecretvalue0000000"
PAGE_ID = "61595470022494"
IG_USER = "17841400000000000"
CREATION_ID = "17890000000000001"
MEDIA_ID = "17890000000000099"
MEDIA_ID_NEW = "17890000000000100"
PARENT_ID = "17892000000000001"
IMAGE = "/static/images/notes/a.jpg"
PUBLIC_IMAGE = "https://karin-sb.jp/static/images/notes/a.jpg"
PUBLIC_IMAGE_B = "https://karin-sb.jp/static/images/notes/b.jpg"


def report(ok, name, detail=""):
    global FAILED, PASSED
    if ok:
        PASSED += 1
        print(f"PASS: {name}")
    else:
        FAILED += 1
        print(f"FAIL: {name} {detail}")


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, db):
        self.db = db
        self.filters = []
        self.op = None
        self.payload = None

    def update(self, fields):
        self.op = "update"
        self.payload = dict(fields)
        return self

    def insert(self, fields):
        self.op = "insert"
        self.payload = dict(fields)
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def in_(self, key, values):
        self.filters.append(("in", key, list(values)))
        return self

    def execute(self):
        if self.op == "insert":
            self.db.events.append(dict(self.payload))
            return Result([dict(self.payload)])
        if self.op != "update":
            raise AssertionError(self.op)
        for kind, key, value in self.filters:
            current = self.db.row.get(key)
            if kind == "eq" and current != value:
                return Result([])
            if kind == "in" and current not in value:
                return Result([])
        self.db.row.update(self.payload)
        self.db.updates.append(dict(self.payload))
        return Result([dict(self.db.row)])


class FakeDB:
    def __init__(self, row):
        self.row = dict(row)
        self.events = []
        self.updates = []

    def table(self, name):
        return Query(self)


def _assert_no_secret(url, body=None):
    text = url or ""
    if TOKEN in text or PAGE_TOKEN in text:
        raise AssertionError("secret in url")
    if "access_token=" in text.lower():
        raise AssertionError("token query")
    if body and "access_token" in body:
        raise AssertionError("token in body")


class AccountsHttp:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = []

    def __call__(self, url, *, access_token, params=None):
        self.calls.append({"url": url, "params": dict(params or {}), "token": access_token})
        _assert_no_secret(url)
        if access_token != TOKEN:
            raise AssertionError("accounts must use system token")
        if self.mode == "timeout":
            raise MetaGraphTimeout()
        if self.mode == "denied":
            return 403, {"error": {"message": f"Bearer {TOKEN}", "code": 200}}
        if self.mode == "empty":
            return 200, {"data": []}
        if self.mode == "other_page":
            return 200, {"data": [{"id": "999999", "access_token": PAGE_TOKEN}]}
        if "/me/accounts" not in (url or ""):
            raise AssertionError("accounts url")
        return 200, {"data": [{"id": PAGE_ID, "access_token": PAGE_TOKEN}]}


class MediaHttp:
    def __init__(
        self,
        create="ok",
        publish="ok",
        create_id=CREATION_ID,
        media_id=MEDIA_ID,
        parent="ok",
        child_fail_at=None,
    ):
        self.create = create
        self.publish = publish
        self.create_id = create_id
        self.media_id = media_id
        self.parent = parent
        self.child_fail_at = child_fail_at
        self.calls = []
        self.last_create = None
        self.last_publish = None
        self.last_parent = None
        self.child_ids = []

    def __call__(self, url, *, access_token, body):
        self.calls.append({"url": url, "body": dict(body or {})})
        _assert_no_secret(url, body)
        if access_token != PAGE_TOKEN:
            raise AssertionError("instagram must use page token")
        if url.endswith("/media_publish"):
            self.last_publish = dict(body or {})
            return self._publish()
        if url.endswith("/media"):
            self.last_create = dict(body or {})
            return self._create()
        raise AssertionError("unexpected post url")

    def _fail_create(self, mode):
        if mode == "timeout":
            raise MetaGraphTimeout()
        if mode == "server":
            return 500, {"error": {"message": f"Bearer {PAGE_TOKEN}", "code": 1}}
        if mode == "denied":
            return 403, {"error": {"message": f"Invalid OAuth access token {PAGE_TOKEN}", "code": 190}}
        if mode == "photo_video":
            ig_token = (
                "L3N0YXRpYy9pbWFnZXMvbm90ZXMvc3RyZXRjaC1wb2xlLXBvc3R1cmUu"
                "44K144Og44ON44Kk44OrLmpwZw"
            )
            return 400, {
                "error": {
                    "message": "Only photo or video can be accepted as media type.",
                    "type": "OAuthException",
                    "code": 9004,
                    "error_subcode": 2207052,
                    "error_user_title": "Media download has failed",
                    "error_user_msg": (
                        "The media could not be fetched from this URI: "
                        f"https://karin-sb.jp/ig-media/{ig_token}.jpg"
                    ),
                    "fbtrace_id": "AaBbCcDdEeFfGgHhIiJjKk",
                }
            }
        if mode == "noid":
            return 200, {"success": True}
        if mode == "skip":
            raise AssertionError("create should not be called")
        return None

    def _create(self):
        payload = dict(self.last_create or {})
        if str(payload.get("is_carousel_item") or "").lower() == "true":
            next_index = len(self.child_ids) + 1
            if self.child_fail_at == next_index:
                failed = self._fail_create(self.create)
                if failed is not None:
                    return failed
            child_id = f"17891{next_index:012d}"
            self.child_ids.append(child_id)
            return 200, {"id": child_id}
        if str(payload.get("media_type") or "").upper() == "CAROUSEL":
            self.last_parent = payload
            failed = self._fail_create(self.parent)
            if failed is not None:
                return failed
            return 200, {"id": PARENT_ID}
        failed = self._fail_create(self.create)
        if failed is not None:
            return failed
        return 200, {"id": self.create_id}

    def _publish(self):
        if self.publish == "timeout":
            raise MetaGraphTimeout()
        if self.publish == "server":
            return 500, {"error": {"message": f"Bearer {PAGE_TOKEN}", "code": 1}}
        if self.publish == "denied":
            return 400, {"error": {"message": f"Invalid OAuth access token {PAGE_TOKEN}", "code": 190}}
        if self.publish == "noid":
            return 200, {"success": True}
        if self.publish == "skip":
            raise AssertionError("publish should not be called")
        return 200, {"id": self.media_id}


class StatusHttp:
    def __init__(self, mode="FINISHED", by_id=None):
        self.mode = mode
        self.by_id = dict(by_id or {})
        self.calls = []

    def __call__(self, url, *, access_token, params=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        _assert_no_secret(url)
        if access_token != PAGE_TOKEN:
            raise AssertionError("status must use page token")
        found = ""
        for part in (url or "").split("/"):
            token = part.split("?")[0]
            if token.isdigit() and 5 <= len(token) <= 32:
                found = token
        if not found:
            raise AssertionError("status url")
        mode = self.by_id.get(found, self.mode)
        if mode == "timeout":
            raise MetaGraphTimeout()
        if mode == "IN_PROGRESS":
            return 200, {"status_code": "IN_PROGRESS"}
        if mode == "ERROR":
            return 200, {"status_code": "ERROR"}
        if mode == "denied":
            return 400, {"error": {"message": f"Bearer {PAGE_TOKEN}"}}
        return 200, {"status_code": "FINISHED"}


def sample_record(**overrides):
    row = {
        "id": "ig-1",
        "source_kind": "notes_article",
        "blog_id": "12",
        "channel": "instagram",
        "gbp_profile": None,
        "status": "draft",
        "body": "KARiN.NOTESの記事です。\nhttps://karin-sb.jp/blog/sample",
        "link_url": "https://karin-sb.jp/blog/sample",
        "image_url": IMAGE,
        "external_id": None,
        "posted_at": None,
        "error_message": None,
    }
    row.update(overrides)
    return row


def sample_config(**overrides):
    config = {
        "access_token": TOKEN,
        "page_id": PAGE_ID,
        "ig_user_id": IG_USER,
    }
    config.update(overrides)
    return config


def secrets_absent(*texts):
    blob = "\n".join(text or "" for text in texts)
    return TOKEN not in blob and PAGE_TOKEN not in blob and "EAAtest" not in blob and "EAApage" not in blob


def run_create(record, post_http, *, config=None, accounts=None, status=None, **kwargs):
    db = FakeDB(record)
    accounts_http = accounts if accounts is not None else AccountsHttp("ok")
    status_http = status if status is not None else StatusHttp("FINISHED")
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        result = instagram_graph.perform_notes_instagram_create(
            db,
            record,
            config=config or sample_config(),
            post_exchange=post_http,
            accounts_exchange=accounts_http,
            get_exchange=status_http,
            now=NOW,
            staff_id="staff-1",
            sleep_fn=lambda _: None,
            max_wait_seconds=kwargs.get("max_wait_seconds", 0),
            poll_interval_seconds=kwargs.get("poll_interval_seconds", 2),
        )
    log = stdout.getvalue()
    if not secrets_absent(log):
        raise AssertionError("secret in log")
    stored = " ".join(
        [
            str(db.row.get("error_message") or ""),
            " ".join(str(item.get("detail") or "") for item in db.events),
        ]
    )
    if not secrets_absent(stored):
        raise AssertionError("secret in db")
    return result, db, log, accounts_http, status_http


def test_instagram_caption_spaces():
    article_url = "https://karin-sb.jp/blog/stretch-pole-posture"
    stretch_html = (
        "<p>「猫背が気になる」「姿勢を良くしたい」と思ったとき、"
        "ストレッチポールを使ったことがある方も多いのではないでしょうか。</p>"
        "<p>ストレッチポールは、ただ上に寝ているだけでも身体をリラックスさせるきっかけになりますが、"
        "そこから<strong>身体を実際に動かしてみること</strong>も大切です。</p>"
        "<p>今回は、ストレッチポールを使って肩まわりや肩甲骨を動かしながら、"
        "姿勢の変化を感じていく基本的なエクササイズを紹介します。</p>"
        "<p>ポイントは、最初から「姿勢を良くしよう」と頑張ることではありません。</p>"
        "<p><strong>寝る → 感じる → 動かす → もう一度寝る → 変化を感じる。</strong></p>"
        "<p>ただ、ストレッチポールに乗っただけで姿勢が変わるわけではありません。</p>"
        "<p>いきなりエクササイズを始めるのではなく、まずは床に仰向けになってみましょう。</p>"
        "<p>それぞれの動きは<strong>10回程度</strong>を目安に行ってみましょう。</p>"
        "<h2>まとめ｜ストレッチポールで身体の変化を感じてみよう</h2>"
        "<p>「姿勢を良くしなければ」と頑張るのではなく、まずは自分の身体がどう動いて、"
        "どう変化するのかを感じてみるところから始めてみましょう。</p>"
    )
    stretch_text = external_posts.starter_body(
        "instagram",
        "ストレッチポールで姿勢改善？自宅でできる基本エクササイズ",
        "ストレッチポールを使って、猫背や姿勢が気になる方でも自宅でできる基本エクササイズを紹介します。",
        article_url,
        body=stretch_html,
        tags=["セルフケア", "運動"],
    )
    report(
        "そこから身体を実際に動かしてみることも大切です。" in stretch_text,
        "ストレッチポール記事の強調タグ由来の半角スペースを除く",
        stretch_text,
    )
    report(
        "そこから 身体" not in stretch_text and "こと も大切" not in stretch_text,
        "日本語の文字と助詞の間に半角スペースを残さない",
        stretch_text,
    )
    report(
        not any(line.startswith("・") for line in stretch_text.splitlines()),
        "Instagram初期文面は箇条書きにしない",
        stretch_text,
    )
    report("…" not in stretch_text, "Instagram初期文面は途中で切らない")
    report(
        stretch_text.count("ストレッチポールを使って、猫背や姿勢が気になる方でも自宅でできる基本エクササイズを紹介します") == 1,
        "冒頭の概要と同じ説明を本文で繰り返さない",
    )
    report(
        "今回は、ストレッチポールを使って肩まわりや肩甲骨を動かしながら" not in stretch_text,
        "記事冒頭の紹介文を本文へ重ねない",
        stretch_text,
    )
    report(
        "床に仰向け" in stretch_text or "10回程度" in stretch_text,
        "記事の具体的な実践内容を自然な文章として残す",
        stretch_text,
    )
    report("→" not in stretch_text and "➡" not in stretch_text, "矢印の手順書きを投稿文に入れない", stretch_text)
    report(stretch_text.count("頑張") == 1, "同じ考え方を複数の段落で繰り返さない", stretch_text)
    report(
        "始めてみましょう" in stretch_text or "頑張ることではありません" in stretch_text,
        "実践するときの考え方を締めとして残す",
        stretch_text,
    )
    report(
        stretch_text.count("\n\n") >= 3,
        "要点を自然な段落としてつなぐ",
        stretch_text,
    )
    report(
        "詳しくはプロフィールのリンクから、KARiN.NOTESをご覧ください。" in stretch_text,
        "スペース修正後もプロフィール誘導を維持する",
    )
    report("#セルフケア" in stretch_text and "#運動" in stretch_text, "スペース修正後も記事タグのハッシュタグを維持する")
    report(
        4 <= stretch_text.count("#") <= 5,
        "記事のテーマからハッシュタグを5個程度付ける",
        str(stretch_text.count("#")),
    )
    report("#ストレッチポール" in stretch_text, "タイトルや本文に出るテーマをハッシュタグにする")

    unit_html = (
        "<p>歩幅の目安は 10 cm です。</p>"
        "<p>BCAA 5 g を目安にします。</p>"
        "<p>回数は<strong>10回程度</strong>です。</p>"
    )
    unit_text = external_posts.starter_body(
        "instagram",
        "単位の話",
        "数値と単位のスペースを確認します。",
        article_url,
        body=unit_html,
        tags=["運動"],
    )
    report("10 cm" in unit_text, "数値とラテン単位の半角スペースは残す", unit_text)
    report("BCAA 5 g" in unit_text, "英数字の半角スペースは残す", unit_text)
    report("回数は10回程度です。" in unit_text, "数値に付く日本語は自然につなげる", unit_text)
    report("https://karin-sb.jp/blog/stretch-pole-posture" not in unit_text, "Instagram初期文面に記事URLを入れない")


def test_caption_and_images():
    article_url = "https://karin-sb.jp/blog/kata"
    ig_text = external_posts.starter_body(
        "instagram",
        "肩の話",
        "つながって見る",
        article_url,
        body="<p>つながって見る</p><p>肩だけでなく、背中や腕の使い方も関係します。</p>",
        tags=["肩こり", "整体", "肩こり"],
    )
    report(article_url not in ig_text, "Instagram初期文面に記事URLを入れない")
    report("肩の話" in ig_text and "つながって見る" in ig_text, "Instagram初期文面はタイトルと概要を使う")
    report("背中や腕の使い方も関係します" in ig_text, "Instagram初期文面は本文の要点を足す")
    report(ig_text.count("つながって見る") == 1, "導入と本文抜粋を重複させない")
    report("…" not in ig_text, "Instagram初期文面は途中で切らない")
    report(ig_text.rstrip().endswith("整体") or "ご覧ください。" in ig_text, "自然な文末で終わる")
    report(
        "詳しくはプロフィールのリンクから、KARiN.NOTESをご覧ください。" in ig_text,
        "Instagram初期文面の末尾はプロフィール誘導",
    )
    report("#肩こり" in ig_text and "#整体" in ig_text, "Instagram初期文面は記事タグからハッシュタグを付ける")
    report(ig_text.count("#肩こり") == 1, "同じハッシュタグは重複しない")
    long_html = (
        "<h2>身体はつながっている</h2>"
        "<p>痛い場所だけを見るのではなく、全身の使い方から考えます。</p>"
        "<h2>日常の動き</h2>"
        "<p>同じ姿勢が続くと、肩だけでなく背中や股関節にも負担が集まります。</p>"
        "<h2>整え方</h2>"
        "<p>まず呼吸と胸の動きを確認し、そのあと肩まわりをゆるめていきます。</p>"
    )
    long_text = external_posts.starter_body(
        "instagram",
        "肩のつらさを、肩だけで見ない",
        "肩のつらさは、肩だけの問題ではないことがあります。",
        article_url,
        body=long_html,
        tags=["肩こり", "身体のつながり", "整体", "不要タグ", "別タグ", "さらに"],
    )
    report(article_url not in long_text, "長い記事でも記事URLを入れない")
    report("…" not in long_text, "長い記事でも文の途中で切らない")
    report(
        not any(line.startswith("・") for line in long_text.splitlines()),
        "長い記事でも箇条書きにせず文章でつなぐ",
        long_text,
    )
    report(
        "全身の使い方から考えます。" in long_text
        and "負担が集まります。" in long_text
        and "ゆるめていきます。" in long_text,
        "見出し配下の具体的な内容を自然な文末のまま残す",
    )
    report(long_text.count("肩だけの問題ではないことがあります") == 1, "概要を本文ポイントと重複させない")
    report(long_text.count("#") <= 5, "ハッシュタグは記事タグから絞る", str(long_text.count("#")))
    report(
        long_text.index("詳しくはプロフィールのリンクから、KARiN.NOTESをご覧ください。")
        < long_text.find("#肩こり"),
        "誘導文のあとにハッシュタグを置く",
    )
    fb_text = external_posts.starter_body("facebook", "肩の話", "つながって見る", article_url)
    gbp_text = external_posts.starter_body("gbp_tokyo", "肩の話", "つながって見る", article_url)
    report(article_url not in fb_text and article_url in gbp_text, "FacebookとGBPの初期文面ルールは変えない")
    report("詳しくはプロフィールのリンクから、KARiN.NOTESをご覧ください。" not in fb_text, "Facebook初期文面にInstagram誘導を入れない")

    saved = external_posts.starter_body("instagram", "別タイトル", "別概要", article_url)
    report("別タイトル" in saved, "未保存の初期生成は呼び出した材料だけを使う")

    candidates = external_posts.instagram_article_image_candidates(
        "/static/images/notes/thumb.jpg",
        '<p>本文</p><img src="/static/images/notes/body.jpg" alt="a">'
        '<img src="/static/images/notes/skip.png">'
        '<img src="/static/images/notes/thumb.jpg">',
    )
    urls = [item["url"] for item in candidates]
    report(
        urls == [
            "https://karin-sb.jp/static/images/notes/thumb.jpg",
            "https://karin-sb.jp/static/images/notes/body.jpg",
        ],
        "記事候補はサムネイルと本文JPEGだけで、重複とPNGは除く",
        str(urls),
    )
    report(candidates[0]["location"] == "thumbnail" and candidates[1]["location"] == "body", "記事候補の出所が分かる")

    tmp = tempfile.mkdtemp()
    try:
        notes = os.path.join(tmp, "notes")
        dedicated = os.path.join(notes, "instagram")
        os.makedirs(dedicated)
        open(os.path.join(notes, "keep.jpg"), "w").close()
        open(os.path.join(notes, "skip.png"), "w").close()
        open(os.path.join(dedicated, "special.jpeg"), "w").close()
        open(os.path.join(tmp, "leftover.jpg"), "w").close()
        open(os.path.join(tmp, "treatment.jpg"), "w").close()
        listed = appmod.list_instagram_server_images(images_root=tmp)
        names = [item["name"] for item in listed]
        locations = {item["name"]: item["location"] for item in listed}
        report("keep.jpg" in names and "special.jpeg" in names and "leftover.jpg" in names, "サーバー候補はnotesと専用フォルダと未移動JPEG")
        report("skip.png" not in names and "treatment.jpg" not in names, "サーバー候補からPNGとサイト用画像を除く")
        report(locations.get("special.jpeg") == "instagram" and locations.get("keep.jpg") == "notes", "サーバー候補の場所が分かる")
    finally:
        shutil.rmtree(tmp)

    one = "/static/images/notes/a.jpg"
    parsed_one = external_posts.parse_instagram_image_urls(one)
    report(
        parsed_one == [PUBLIC_IMAGE],
        "既存の1枚image_urlを公開httpsとして読む",
        str(parsed_one),
    )
    two_saved = PUBLIC_IMAGE + "\nhttps://karin-sb.jp/static/images/notes/b.jpg"
    parsed_two = external_posts.parse_instagram_image_urls(two_saved)
    report(
        parsed_two == [PUBLIC_IMAGE, "https://karin-sb.jp/static/images/notes/b.jpg"],
        "改行区切りの複数URLを順に読む",
        str(parsed_two),
    )
    report(
        external_posts.parse_instagram_image_urls(two_saved + "\n" + PUBLIC_IMAGE)
        == [PUBLIC_IMAGE, "https://karin-sb.jp/static/images/notes/b.jpg"],
        "同じ画像は保存時も重複しない",
    )
    cleaned = external_posts.clean_instagram_image_refs([one, "/static/images/notes/b.jpg"])
    report(
        cleaned == PUBLIC_IMAGE + "\nhttps://karin-sb.jp/static/images/notes/b.jpg",
        "Instagram保存は公開httpsを改行でつなぐ",
        cleaned,
    )
    report(external_posts.clean_image_ref(one) == one, "GBP/Facebook用のclean_image_refは1枚のまま")
    empty_error = ""
    try:
        external_posts.clean_instagram_image_refs("")
    except ValueError as exc:
        empty_error = str(exc)
    report("1枚以上" in empty_error, "0枚はInstagram保存できない", empty_error)
    png_error = ""
    try:
        external_posts.clean_instagram_image_refs("/static/images/notes/a.png")
    except ValueError as exc:
        png_error = str(exc)
    report("JPEG" in png_error, "PNGはInstagram保存できない", png_error)
    many = [f"/static/images/notes/{index}.jpg" for index in range(11)]
    many_error = ""
    try:
        external_posts.clean_instagram_image_refs(many)
    except ValueError as exc:
        many_error = str(exc)
    report("10枚以内" in many_error, "11枚はInstagram保存できない", many_error)
    long_urls = [
        f"https://karin-sb.jp/static/images/notes/{'a' * 180}{index}.jpg"
        for index in range(10)
    ]
    joined_long = external_posts.clean_instagram_image_refs(long_urls)
    report(
        len(joined_long) > 2000 and joined_long.count("\n") == 9,
        "Instagramだけ2000文字を超える複数URLを保存できる",
        str(len(joined_long)),
    )

    instagram = external_posts.get_target("instagram")
    facebook = external_posts.get_target("facebook")
    tokyo = external_posts.get_target("gbp_tokyo")
    preview_one = appmod._instagram_post_preview(instagram, "本文", one)
    report(preview_one and preview_one["ok"], "1枚のInstagram確認は従来どおり送れる")
    preview_two = appmod._instagram_post_preview(instagram, "本文", cleaned)
    report(
        preview_two
        and preview_two["ok"]
        and preview_two.get("image_urls") == [PUBLIC_IMAGE, PUBLIC_IMAGE_B]
        and "CAROUSEL" in preview_two["payload_text"],
        "2枚はカルーセルとして確認できる",
        str((preview_two or {}).get("errors")),
    )
    report(appmod._instagram_post_preview(facebook, "本文", one) is None, "FacebookにInstagram確認は出ない")
    report(
        appmod._instagram_saved_matches(
            {"body": "本文", "link_url": article_url, "image_url": one},
            "本文",
            article_url,
            PUBLIC_IMAGE,
        ),
        "1枚の相対パスと公開httpsは同じ保存内容として扱う",
    )
    report(
        appmod._instagram_saved_matches(
            {"body": "本文", "link_url": article_url, "image_url": cleaned},
            "本文",
            article_url,
            [one, "/static/images/notes/b.jpg"],
        ),
        "複数画像も正規化して保存内容と照合する",
    )
    ig_blog = {
        "id": "12",
        "title": "肩の話",
        "slug": "kata",
        "excerpt": "つながって見る",
        "body": "<p>肩だけでなく、背中も見ます。</p><img src='/static/images/notes/body.jpg'>",
        "image": "/static/images/notes/a.jpg",
        "tags_list": ["肩こり"],
    }
    fresh = appmod._external_post_form_values(ig_blog, instagram, None)
    report("肩の話" in fresh["body"] and "つながって見る" in fresh["body"], "未保存フォームはタイトルと概要を使う")
    report(article_url not in fresh["body"], "未保存のInstagram投稿文に記事URLを入れない", fresh["body"])
    report("#肩こり" in fresh["body"], "未保存のInstagram投稿文にハッシュタグを付ける")
    report(fresh["image_url"] == PUBLIC_IMAGE, "未保存のInstagram画像は記事サムネイルのJPEG", fresh["image_url"])
    kept = appmod._external_post_form_values(
        ig_blog,
        instagram,
        {"status": "draft", "body": "保存済みの文", "link_url": article_url, "image_url": one},
    )
    report(kept["body"] == "保存済みの文", "保存済みのInstagram投稿文は初期生成で上書きしない")
    report(kept["image_url"] == PUBLIC_IMAGE, "保存済みの1枚画像は公開httpsで再表示する")
    generated = appmod._notes_instagram_new_draft(ig_blog)
    report(
        generated == external_posts.starter_body(
            "instagram",
            ig_blog["title"],
            ig_blog["excerpt"],
            "",
            body=ig_blog["body"],
            tags=ig_blog["tags_list"],
        ),
        "新しい下書きは starter_body と同じ文章になる",
    )
    report(generated != kept["body"] and "肩の話" in generated, "新しい下書きは保存済み文面と区別できる")
    report(kept["body"] == "保存済みの文", "GETの保存済み投稿文は初期生成で上書きしない")
    shown = appmod._notes_instagram_apply_new_draft(kept, generated)
    report(shown["body"] == generated, "新しい下書きは投稿文欄へ入れる")
    report(kept["body"] == "保存済みの文", "生成だけでは元のフォーム値は変えない")
    report(
        appmod._notes_instagram_apply_new_draft(kept, "") is kept,
        "生成文が空なら投稿文欄は変えない",
    )
    report(
        not appmod._instagram_saved_matches(
            {"body": "保存済みの文", "link_url": article_url, "image_url": one},
            shown["body"],
            article_url,
            one,
        ),
        "未保存の新しい下書きでは送信照合に通らない",
    )
    gbp_fresh = appmod._external_post_form_values(ig_blog, tokyo, None)
    report(article_url in gbp_fresh["body"] or "/blog/kata" in gbp_fresh["link_url"], "GBPの未保存文面は従来どおり記事へ案内する")
    report("詳しくはプロフィールのリンクから、KARiN.NOTESをご覧ください。" not in gbp_fresh["body"], "GBP文面にInstagram誘導を入れない")
    fb_fresh = appmod._external_post_form_values(ig_blog, facebook, None)
    report("詳しくはプロフィールのリンクから、KARiN.NOTESをご覧ください。" not in fb_fresh["body"], "Facebook文面にInstagram誘導を入れない")
    report(
        appmod._facebook_post_preview(instagram, "本文", article_url) is None
        and appmod._gbp_post_preview(instagram, "本文", article_url, cleaned, notes_create=True) is None,
        "Instagram画面にFacebookとGBPの送信確認は出ない",
    )


def carousel_record(count=2, **overrides):
    urls = [f"https://karin-sb.jp/static/images/notes/{index}.jpg" for index in range(count)]
    return sample_record(image_url="\n".join(urls), **overrides)


def media_calls(post_http, **required):
    found = []
    for call in post_http.calls:
        body = call.get("body") or {}
        if all(body.get(key) == value for key, value in required.items()):
            found.append(body)
    return found


def test_carousel():
    two_http = MediaHttp()
    two_result, two_db, _two_log, _acc, two_status = run_create(carousel_record(2), two_http)
    child_payloads = media_calls(two_http, is_carousel_item="true")
    report(two_result["ok"] and two_db.row["status"] == "posted", "2枚カルーセルは公開成功で posted")
    report(two_db.row["external_id"] == MEDIA_ID, "カルーセル成功時はメディアIDを保存する")
    report(
        [item.get("image_url") for item in child_payloads]
        == [
            "https://karin-sb.jp/static/images/notes/0.jpg",
            "https://karin-sb.jp/static/images/notes/1.jpg",
        ]
        and all("caption" not in item for item in child_payloads)
        and all(item.get("media_type") == "IMAGE" for item in child_payloads),
        "子コンテナは選択順の画像だけで、captionを付けない",
        str([item.get("image_url") for item in child_payloads]),
    )
    report(
        two_http.last_parent
        == {
            "media_type": "CAROUSEL",
            "children": f"{two_http.child_ids[0]},{two_http.child_ids[1]}",
            "caption": sample_record()["body"],
        },
        "親コンテナは子IDを同じ順で渡し、captionを付ける",
        str(two_http.last_parent),
    )
    report(two_http.last_publish == {"creation_id": PARENT_ID}, "カルーセルは親IDを公開する")
    report(
        len(two_http.calls) == 4 and len(two_status.calls) == 3,
        "2枚は子2・親1・公開1と、完了確認3回",
        str((len(two_http.calls), len(two_status.calls))),
    )

    ten_http = MediaHttp()
    ten_result, ten_db, _ten_log, _acc, ten_status = run_create(carousel_record(10), ten_http)
    ten_children = media_calls(ten_http, is_carousel_item="true")
    report(ten_result["ok"] and ten_db.row["status"] == "posted", "10枚カルーセルも公開できる")
    report(len(ten_children) == 10 and len(ten_http.child_ids) == 10, "10枚は子コンテナを10個作る")
    report(
        ten_http.last_parent.get("children") == ",".join(ten_http.child_ids),
        "10枚でも投稿順を維持する",
        str(ten_http.last_parent),
    )
    report(
        len(ten_http.calls) == 12 and len(ten_status.calls) == 11,
        "10枚は子10・親1・公開1と、完了確認11回",
        str((len(ten_http.calls), len(ten_status.calls))),
    )

    child_denied = MediaHttp(create="denied", child_fail_at=2, parent="skip", publish="skip")
    denied_result, denied_db, _log, _acc, denied_status = run_create(carousel_record(2), child_denied)
    report(not denied_result["ok"] and denied_db.row["status"] == "failed", "子コンテナの4xxは failed")
    report(
        child_denied.last_parent is None and child_denied.last_publish is None,
        "子の失敗では親も公開もしない",
    )

    child_timeout = MediaHttp(create="timeout", child_fail_at=2, parent="skip", publish="skip")
    cto_result, cto_db, _log, _acc, cto_status = run_create(carousel_record(2), child_timeout)
    report(not cto_result["ok"] and cto_db.row["status"] == "unknown", "子コンテナ作成のタイムアウトは unknown")
    report("自動再送しません" in (cto_result["message"] or ""), "子のタイムアウトは自動再送しない")
    report(child_timeout.last_parent is None and child_timeout.last_publish is None, "子のタイムアウトでは公開しない")

    error_status = StatusHttp("FINISHED", by_id={"17891000000000002": "ERROR"})
    error_http = MediaHttp(parent="skip", publish="skip")
    error_result, error_db, _log, _acc, _st = run_create(
        carousel_record(2), error_http, status=error_status
    )
    report(not error_result["ok"] and error_db.row["status"] == "failed", "子コンテナのERRORは failed")
    report(error_http.last_parent is None and error_http.last_publish is None, "子のERRORでは親を作らない")

    wait_status = StatusHttp("FINISHED", by_id={"17891000000000002": "IN_PROGRESS"})
    wait_http = MediaHttp(parent="skip", publish="skip")
    wait_result, wait_db, _log, _acc, _st = run_create(
        carousel_record(2),
        wait_http,
        status=wait_status,
        max_wait_seconds=0,
    )
    report(not wait_result["ok"] and wait_db.row["status"] == "unknown", "子コンテナの処理タイムアウトは unknown")
    report(wait_http.last_publish is None, "子の待機タイムアウトでは公開しない")

    parent_denied = MediaHttp(parent="denied", publish="skip")
    pd_result, pd_db, _log, _acc, _st = run_create(carousel_record(2), parent_denied)
    report(not pd_result["ok"] and pd_db.row["status"] == "failed", "親コンテナの4xxは failed")
    report(parent_denied.last_publish is None and len(parent_denied.child_ids) == 2, "親の失敗では公開せず、子は作っている")

    parent_timeout = MediaHttp(parent="timeout", publish="skip")
    pto_result, pto_db, _log, _acc, _st = run_create(carousel_record(2), parent_timeout)
    report(not pto_result["ok"] and pto_db.row["status"] == "unknown", "親コンテナ作成のタイムアウトは unknown")
    report(parent_timeout.last_publish is None, "親のタイムアウトでは公開しない")

    parent_wait = StatusHttp("FINISHED", by_id={PARENT_ID: "IN_PROGRESS"})
    pw_http = MediaHttp(publish="skip")
    pw_result, pw_db, _log, _acc, _st = run_create(
        carousel_record(2),
        pw_http,
        status=parent_wait,
        max_wait_seconds=0,
    )
    report(not pw_result["ok"] and pw_db.row["status"] == "unknown", "親コンテナの処理タイムアウトは unknown")
    report(pw_http.last_publish is None, "親の待機タイムアウトでは公開しない")

    posted_http = MediaHttp(media_id=MEDIA_ID_NEW)
    posted_result, posted_db, _log, _acc, _st = run_create(
        carousel_record(2, status="posted", external_id=MEDIA_ID, posted_at=NOW),
        posted_http,
    )
    posted_started = " ".join(
        item.get("detail") or "" for item in posted_db.events if item.get("event") == "submit_started"
    )
    report(posted_result["ok"] and posted_db.row["external_id"] == MEDIA_ID_NEW, "カルーセルの投稿済からも明示再投稿できる")
    report(MEDIA_ID in posted_started, "カルーセル再投稿でも前回IDは履歴に残る")

    unknown_http = MediaHttp(media_id=MEDIA_ID_NEW)
    unknown_result, unknown_db, _log, _acc, _st = run_create(
        carousel_record(2, status="unknown", external_id=MEDIA_ID, posted_at=NOW),
        unknown_http,
    )
    report(
        unknown_result["ok"] and unknown_db.row["external_id"] == MEDIA_ID_NEW,
        "カルーセルのunknownも明示操作のときだけ再投稿する",
    )

    posting_http = MediaHttp(parent="skip", publish="skip")
    posting_acc = AccountsHttp("ok")
    posting_result, posting_db, _log, posting_acc, _st = run_create(
        carousel_record(2, status="posting", external_id=MEDIA_ID, posted_at=NOW),
        posting_http,
        accounts=posting_acc,
    )
    report(
        not posting_result["ok"] and posting_http.calls == [] and posting_acc.calls == [],
        "カルーセルも posting 中は再送しない",
    )

    facebook_http = MediaHttp(parent="skip", publish="skip")
    facebook_acc = AccountsHttp("ok")
    facebook_result, facebook_db, _log, facebook_acc, facebook_st = run_create(
        carousel_record(2, channel="facebook"),
        facebook_http,
        accounts=facebook_acc,
    )
    report(
        not facebook_result["ok"] and facebook_http.calls == [] and facebook_acc.calls == [],
        "Facebookの行はカルーセル送信しない",
    )
    report(facebook_db.row["channel"] == "facebook" and facebook_db.row["status"] == "draft", "Facebookの状態は変えない")

    gbp_http = MediaHttp(parent="skip", publish="skip")
    gbp_acc = AccountsHttp("ok")
    gbp_result, gbp_db, _log, gbp_acc, gbp_st = run_create(
        carousel_record(2, channel="gbp"),
        gbp_http,
        accounts=gbp_acc,
    )
    report(not gbp_result["ok"] and gbp_http.calls == [] and gbp_acc.calls == [], "GBPの行はカルーセル送信しない")

    with appmod.app.test_request_context("/admin/blogs/12/posts/instagram"):
        send_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog={"id": 12, "title": "公開記事", "slug": "live-one"},
            target=external_posts.get_target("instagram"),
            form={
                "body": "本文",
                "link_url": "https://karin-sb.jp/blog/a",
                "image_url": f"{PUBLIC_IMAGE}\n{PUBLIC_IMAGE_B}",
                "status_label": "下書き保存",
            },
            events=[],
            instagram_preview=appmod._instagram_post_preview(
                external_posts.get_target("instagram"),
                "本文",
                f"{PUBLIC_IMAGE}\n{PUBLIC_IMAGE_B}",
            ),
            instagram_action="send",
            instagram_send_label="この内容をInstagramに投稿する",
        )
    report(
        "この内容をInstagramに投稿する" in send_html
        and "カルーセル 2枚" in send_html
        and "1枚目が表紙" in send_html
        and "この内容をFacebookに投稿する" not in send_html,
        "2枚保存後もInstagram投稿ボタンを出す",
    )


def test_instagram_graph_fetch_url():
    ascii_url = instagram_graph.instagram_graph_image_url(IMAGE)
    report(ascii_url == PUBLIC_IMAGE, "ASCIIファイルは /static/ のままGraphへ渡す", ascii_url)

    japanese = "/static/images/notes/stretch-pole-posture.サムネイル.jpg"
    fetch_url = instagram_graph.instagram_graph_image_url(japanese)
    report(
        fetch_url.startswith("https://karin-sb.jp/ig-media/")
        and fetch_url.endswith(".jpg")
        and fetch_url.isascii()
        and "%" not in fetch_url,
        "日本語ファイル名はASCIIの /ig-media/ URLにする",
        fetch_url,
    )
    token = fetch_url.rsplit("/", 1)[-1].removesuffix(".jpg")
    restored = instagram_graph.static_path_from_ig_media_token(token)
    report(restored == japanese, "ig-mediaトークンは元のstaticパスに戻せる", restored)
    local = instagram_graph.local_path_from_ig_media_token(token)
    report(bool(local) and os.path.isfile(local), "ig-mediaトークンは実ファイルを指す")

    child = instagram_graph.build_instagram_child_payload(japanese)
    report(
        child.get("image_url") == fetch_url
        and child.get("is_carousel_item") == "true"
        and child.get("media_type") == "IMAGE"
        and "caption" not in child,
        "カルーセル子はIMAGEとASCII取得URLだけ送る",
        str(child),
    )
    single = instagram_graph.build_instagram_media_payload("本文", japanese)
    report(
        single.get("image_url") == fetch_url
        and single.get("media_type") == "IMAGE"
        and single.get("caption") == "本文",
        "単一画像も日本語ファイルは /ig-media/ にする",
        str(single),
    )

    saved = instagram_graph.public_instagram_image_url(japanese)
    preview = instagram_graph.instagram_preview("本文", japanese)
    report(
        preview["ok"] and saved in preview["payload_text"] and "/ig-media/" not in preview["payload_text"],
        "確認画面は保存用の公開URLのままにする",
    )

    traversal = instagram_graph.ig_media_token_from_static_path("/static/../instagram_graph.py")
    report(not traversal, "static外のパスはig-mediaトークンにしない")
    report(instagram_graph.local_path_from_ig_media_token("not-valid") is None, "不正トークンはファイルを返さない")
    report(
        instagram_graph.local_path_from_ig_media_token(
            instagram_graph.ig_media_token_from_static_path("/static/images/notes/missing-ig-test.jpg")
        )
        is None,
        "存在しないJPEGはig-mediaで開けない",
    )

    client = appmod.app.test_client()
    response = client.get(f"/ig-media/{token}.jpg")
    report(
        response.status_code == 200
        and response.mimetype == "image/jpeg"
        and (response.data or b"").startswith(b"\xff\xd8"),
        "ig-mediaは認証なしでJPEGを返す",
        str(response.status_code),
    )
    missing = client.get("/ig-media/not-valid.jpg")
    report(missing.status_code == 404, "不正なig-mediaは404")


def test_instagram_media_access_log():
    japanese = "/static/images/notes/stretch-pole-posture.サムネイル.jpg"
    fetch_url = instagram_graph.instagram_graph_image_url(japanese)
    token = fetch_url.rsplit("/", 1)[-1].removesuffix(".jpg")
    local = instagram_graph.local_path_from_ig_media_token(token)
    size = os.path.getsize(local)
    client = appmod.app.test_client()
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        response = client.get(
            f"/ig-media/{token}.jpg",
            headers={
                "User-Agent": "facebookexternalhit/1.1",
                "Authorization": f"Bearer {TOKEN}",
            },
        )
    log = stdout.getvalue()
    report(response.status_code == 200, "アクセスログ用の200はJPEGを返す")
    report(
        "Instagram画像GET" in log
        and "status=200" in log
        and f"bytes={size}" in log
        and "facebookexternalhit/1.1" in log
        and "time=" in log
        and "T" in log
        and "Z" in log,
        "200のアクセスログは時刻・status・bytes・UA",
        log.strip(),
    )
    report(
        token not in log
        and "stretch-pole-posture" not in log
        and "サムネイル" not in log
        and "/ig-media/" not in log
        and TOKEN not in log
        and "Bearer" not in log
        and "Authorization" not in log
        and "Cookie" not in log,
        "アクセスログにトークン・パス・ファイル名・秘密情報を出さない",
        log.strip(),
    )

    stdout_404 = io.StringIO()
    with redirect_stdout(stdout_404):
        missing = client.get(
            "/ig-media/not-valid.jpg",
            headers={"User-Agent": "Facebot"},
        )
    log_404 = stdout_404.getvalue()
    report(missing.status_code == 404, "アクセスログ用の404も返す")
    report(
        "Instagram画像GET" in log_404
        and "status=404" in log_404
        and "bytes=0" in log_404
        and "Facebot" in log_404
        and "not-valid" not in log_404
        and "/ig-media/" not in log_404,
        "404も時刻・status・bytes・UAを記録し、トークン相当は出さない",
        log_404.strip(),
    )

    long_ua = "A" * 80 + "B" * 80
    stdout_ua = io.StringIO()
    with redirect_stdout(stdout_ua):
        client.get("/ig-media/not-valid.jpg", headers={"User-Agent": long_ua})
    ua_part = stdout_ua.getvalue().split(" ua=", 1)[-1].strip()
    report(
        "\n" not in ua_part and len(ua_part) == 120 and ua_part == ("A" * 80 + "B" * 40),
        "User-Agentは120文字で切る",
        ua_part,
    )
    report(appmod._instagram_media_ua("foo\r\nbar") == "foo bar", "User-Agentの改行は空白にまとめる")


def test_instagram_failure_diag():
    ig_token = (
        "L3N0YXRpYy9pbWFnZXMvbm90ZXMvc3RyZXRjaC1wb2xlLXBvc3R1cmUu"
        "44K144Og44ON44Kk44OrLmpwZw"
    )
    raw = f"https://karin-sb.jp/ig-media/{ig_token}.jpg"
    report(
        instagram_graph.instagram_diag_url(raw) == "https://karin-sb.jp/ig-media/[token].jpg",
        "診断用URLはig-mediaトークンを伏せる",
        instagram_graph.instagram_diag_url(raw),
    )
    report(
        instagram_graph.instagram_diag_url(PUBLIC_IMAGE) == PUBLIC_IMAGE,
        "診断用URLはASCIIの /static/ パスを残す",
    )
    report(
        instagram_graph.instagram_diag_url(raw + "?access_token=" + TOKEN)
        == "https://karin-sb.jp/ig-media/[token].jpg",
        "診断用URLからクエリは落とす",
    )

    http = MediaHttp(create="photo_video", child_fail_at=1, parent="skip", publish="skip")
    result, db, log, _acc, status = run_create(carousel_record(5), http)
    failed = [item for item in db.events if item.get("event") == "failed"]
    detail = (failed[-1].get("detail") if failed else "") or ""
    user_error = db.row.get("error_message") or ""
    report(not result["ok"] and db.row["status"] == "failed", "1枚目の子コンテナ400は failed")
    report(
        user_error == "投稿失敗 HTTP 400 Only photo or video can be accepted as media type.",
        "ユーザー向けエラーは従来の短文のまま",
        user_error,
    )
    report("code=" not in user_error and "fbtrace_id=" not in user_error, "ユーザー向けエラーに診断項目を混ぜない")
    report(
        "code=9004" in detail
        and "error_subcode=2207052" in detail
        and "error_user_title=Media download has failed" in detail
        and "error_user_msg=" in detail
        and "fbtrace_id=AaBbCcDdEeFfGgHhIiJjKk" in detail,
        "失敗履歴にMetaのcode/subcode/user文/fbtraceを残す",
        detail,
    )
    report(
        "step=carousel_item" in detail
        and "is_carousel_item=true" in detail
        and "media_type=IMAGE" in detail
        and "image_url=https://karin-sb.jp/static/images/notes/0.jpg" in detail,
        "失敗履歴に1枚目へ送った送信パラメータを残す",
        detail,
    )
    report(
        "ig-media/[token].jpg" in detail
        and ig_token not in detail
        and ig_token not in log
        and TOKEN not in detail
        and PAGE_TOKEN not in detail,
        "診断ログのig-mediaトークンと秘密情報を伏せる",
    )
    report(
        "code=9004" in log
        and "step=carousel_item" in log
        and secrets_absent(log, user_error, detail),
        "stdoutにも同じ診断を出し、トークンは出さない",
    )
    report(http.last_parent is None and http.last_publish is None and status.calls == [], "1枚目失敗では親も公開もしない")
    report((result.get("message") or "") == user_error, "画面へ返す失敗文も短文のまま")


def main():
    test_caption_and_images()
    test_instagram_caption_spaces()
    test_carousel()
    test_instagram_graph_fetch_url()
    test_instagram_media_access_log()
    test_instagram_failure_diag()
    converted = instagram_graph.public_instagram_image_url(IMAGE)
    report(converted == PUBLIC_IMAGE, "相対パスは公開httpsに変換する", converted)
    report(
        instagram_graph.public_instagram_image_url("static/images/notes/a.jpg") == PUBLIC_IMAGE,
        "static/ からも公開httpsにする",
    )
    report(
        instagram_graph.public_instagram_image_url(PUBLIC_IMAGE) == PUBLIC_IMAGE,
        "既にあるhttpsは維持する",
    )
    report(
        instagram_graph.public_instagram_image_url("http://karin-sb.jp/static/images/notes/a.jpg") == PUBLIC_IMAGE,
        "公式サイトのhttpはhttpsにする",
    )
    report(not instagram_graph.public_instagram_image_url("http://example.com/a.jpg"), "他サイトのhttpは使わない")
    report(not instagram_graph.public_instagram_image_url("/images/notes/a.jpg"), "static以外の相対パスは使わない")
    encoded = instagram_graph.public_instagram_image_url("/static/images/notes/pole.サムネイル.jpg")
    report(
        encoded == "https://karin-sb.jp/static/images/notes/pole.%E3%82%B5%E3%83%A0%E3%83%8D%E3%82%A4%E3%83%AB.jpg",
        "日本語ファイル名はパーセントエンコードする",
        encoded,
    )

    preview = instagram_graph.instagram_preview("本文", IMAGE)
    report(preview["ok"] and "本文" in preview["payload_text"] and PUBLIC_IMAGE in preview["payload_text"], "確認画面はキャプションと画像URL")
    report("access_token" not in preview["payload_text"] and TOKEN not in preview["payload_text"], "確認画面にトークンを出さない")
    report(not instagram_graph.instagram_preview("本文", "http://example.com/a.jpg")["ok"], "https以外の画像は確認できない")
    report(not instagram_graph.instagram_preview("本文", "/static/images/notes/a.webp")["ok"], "WebPは確認できない")
    report(not instagram_graph.instagram_preview("本文", "/static/images/notes/a.png")["ok"], "PNGは確認できない")
    report(not instagram_graph.instagram_preview("本文", "")["ok"], "画像なしは確認できない")
    long_caption = "あ" * 2201
    report(not instagram_graph.instagram_preview(long_caption, IMAGE)["ok"], "2201文字は送れない")
    report(instagram_graph.instagram_preview("あ" * 2200, IMAGE)["ok"], "2200文字は確認できる")

    payload = instagram_graph.build_instagram_media_payload("本文", IMAGE)
    report(
        payload == {"image_url": PUBLIC_IMAGE, "caption": "本文", "media_type": "IMAGE"},
        "単一画像の送信はIMAGEのimage_urlとcaption",
    )

    url = instagram_graph.instagram_media_url(IG_USER)
    report(
        url == f"https://graph.facebook.com/v27.0/{IG_USER}/media" and "access_token" not in url,
        "コンテナURLはv27.0でトークンを含まない",
        url,
    )
    publish = instagram_graph.instagram_publish_url(IG_USER)
    report(
        publish == f"https://graph.facebook.com/v27.0/{IG_USER}/media_publish" and "access_token" not in publish,
        "公開URLはv27.0でトークンを含まない",
    )

    missing = instagram_graph.missing_instagram_env({"access_token": "", "page_id": "", "ig_user_id": ""})
    report(
        missing == [
            "FACEBOOK_SYSTEM_USER_ACCESS_TOKEN",
            "FACEBOOK_PAGE_ID",
            "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        ],
        "不足している環境変数名だけ返す",
        str(missing),
    )
    loaded = instagram_graph.load_instagram_config(
        {
            "FACEBOOK_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
            "FACEBOOK_PAGE_ID": PAGE_ID,
            "INSTAGRAM_BUSINESS_ACCOUNT_ID": IG_USER,
        }
    )
    report(
        loaded["ig_user_id"] == IG_USER and loaded["page_id"] == PAGE_ID,
        "Instagram設定は3つの環境変数を読む",
    )

    post_http = MediaHttp()
    result, db, log, accounts, status = run_create(sample_record(), post_http)
    report(result["ok"] and db.row["status"] == "posted", "公開成功で posted")
    report(db.row["external_id"] == MEDIA_ID and db.row["posted_at"] == NOW, "InstagramメディアIDと投稿日時を保存")
    report(
        post_http.last_create
        == {
            "image_url": PUBLIC_IMAGE,
            "caption": sample_record()["body"],
            "media_type": "IMAGE",
        }
        and post_http.last_publish == {"creation_id": CREATION_ID},
        "コンテナ作成のあと media_publish する",
    )
    report(len(post_http.calls) == 2 and len(status.calls) == 1, "作成・確認・公開の順で1回ずつ")
    report(accounts.calls and accounts.calls[0]["token"] == TOKEN, "Pageトークン取得はシステムユーザートークン")
    report(all(call["body"].get("access_token") is None for call in post_http.calls), "POST本文にトークンを入れない")
    report(secrets_absent(log) and "Instagram投稿" in log, "成功時のログにトークンがない")
    events = [item.get("event") for item in db.events]
    report(events == ["submit_started", "succeeded"], "成功時は開始と成功の履歴")

    denied = MediaHttp(create="denied")
    denied_result, denied_db, denied_log, _acc, denied_status = run_create(sample_record(), denied)
    report(not denied_result["ok"] and denied_db.row["status"] == "failed", "コンテナ作成の4xxは failed")
    report(denied.last_publish is None and denied_status.calls == [], "作成失敗では公開しない")
    report(denied_db.row["external_id"] is None, "失敗では投稿済にしない")
    report(secrets_absent(denied_log, denied_db.row.get("error_message")), "4xxの保存とログにトークンがない")

    error_status = StatusHttp("ERROR")
    error_http = MediaHttp(publish="skip")
    error_result, error_db, _error_log, _acc, error_st = run_create(
        sample_record(), error_http, status=error_status
    )
    report(not error_result["ok"] and error_db.row["status"] == "failed", "コンテナ処理ERRORは failed")
    report(error_http.last_publish is None, "ERRORでは media_publish しない")
    report("画像の処理に失敗" in (error_result["message"] or ""), "ERRORは明確な失敗として案内する")

    wait_http = MediaHttp(publish="skip")
    wait_status = StatusHttp("IN_PROGRESS")
    wait_result, wait_db, _wait_log, _acc, wait_st = run_create(
        sample_record(),
        wait_http,
        status=wait_status,
        max_wait_seconds=0,
    )
    report(not wait_result["ok"] and wait_db.row["status"] == "unknown", "コンテナ処理タイムアウトは unknown")
    report(wait_http.last_publish is None, "待機タイムアウトでは公開しない")
    report("自動再送しません" in (wait_result["message"] or ""), "待機タイムアウトは自動再送しない")

    create_timeout = MediaHttp(create="timeout", publish="skip")
    cto_result, cto_db, _cto_log, _acc, cto_st = run_create(sample_record(), create_timeout)
    report(not cto_result["ok"] and cto_db.row["status"] == "unknown", "コンテナ作成タイムアウトは unknown")
    report(cto_st.calls == [] and create_timeout.last_publish is None, "作成タイムアウトでは確認も公開もしない")

    pub_denied = MediaHttp(publish="denied")
    pd_result, pd_db, pd_log, _acc, _st = run_create(sample_record(), pub_denied)
    report(not pd_result["ok"] and pd_db.row["status"] == "failed", "media_publish失敗は failed")
    report(secrets_absent(pd_log, pd_db.row.get("error_message")), "公開失敗の記録にトークンがない")

    pub_timeout = MediaHttp(publish="timeout")
    pto_result, pto_db, _pto_log, _acc, _st = run_create(sample_record(), pub_timeout)
    report(not pto_result["ok"] and pto_db.row["status"] == "unknown", "media_publishタイムアウトは unknown")
    report("自動再送しません" in (pto_result["message"] or ""), "公開タイムアウトは自動再送しない")

    noid = MediaHttp(publish="noid")
    noid_result, noid_db, _noid_log, _acc, _st = run_create(sample_record(), noid)
    report(not noid_result["ok"] and noid_db.row["status"] == "unknown", "公開応答にIDが無いと unknown")

    mismatch = AccountsHttp("other_page")
    mm_http = MediaHttp(publish="skip")
    mm_result, mm_db, mm_log, mm_acc, mm_st = run_create(
        sample_record(), mm_http, accounts=mismatch
    )
    report(not mm_result["ok"] and mm_http.calls == [] and mm_st.calls == [], "FacebookページIDが違うときは投稿しない")
    report(mm_db.row["status"] == "failed", "ページ不一致は failed に記録する")
    report("FACEBOOK_PAGE_ID" in (mm_result["message"] or "") and secrets_absent(mm_log), "不一致の失敗文にトークンがない")

    missing_http = MediaHttp(publish="skip")
    missing_acc = AccountsHttp("ok")
    missing_result, missing_db, missing_log, missing_acc, missing_st = run_create(
        sample_record(),
        missing_http,
        config={"access_token": "", "page_id": "", "ig_user_id": ""},
        accounts=missing_acc,
    )
    report(not missing_result["ok"] and missing_http.calls == [] and missing_acc.calls == [], "環境変数不足では送信しない")
    report(missing_db.row["status"] == "draft" and not missing_db.updates, "設定不足では状態を変えない")
    report("設定が不足" in (missing_result["message"] or "") and secrets_absent(missing_log), "設定不足の文言にトークンがない")

    no_image = MediaHttp(publish="skip")
    ni_result, ni_db, _ni_log, ni_acc, ni_st = run_create(
        sample_record(image_url=""),
        no_image,
    )
    report(not ni_result["ok"] and no_image.calls == [] and ni_acc.calls == [], "画像なしでは送信しない")
    report(ni_db.row["status"] == "failed", "画像なしは failed")

    posted_http = MediaHttp(media_id=MEDIA_ID_NEW)
    posted_result, posted_db, _posted_log, posted_acc, posted_st = run_create(
        sample_record(status="posted", external_id=MEDIA_ID, posted_at=NOW),
        posted_http,
    )
    posted_started = " ".join(
        item.get("detail") or "" for item in posted_db.events if item.get("event") == "submit_started"
    )
    report(posted_result["ok"] and len(posted_http.calls) == 2, "posted は明示操作で新規投稿できる")
    report(
        posted_db.row["external_id"] == MEDIA_ID_NEW
        and MEDIA_ID in posted_started
        and MEDIA_ID_NEW not in posted_started,
        "再投稿開始時は前回IDを履歴に残し、成功時だけ最新IDへ更新する",
        posted_started,
    )

    unknown_http = MediaHttp(media_id=MEDIA_ID_NEW)
    unknown_result, unknown_db, _unknown_log, _acc, _st = run_create(
        sample_record(status="unknown", external_id=MEDIA_ID, posted_at=NOW),
        unknown_http,
    )
    unknown_started = " ".join(
        item.get("detail") or "" for item in unknown_db.events if item.get("event") == "submit_started"
    )
    report(unknown_result["ok"] and len(unknown_http.calls) == 2, "unknown は明示操作で新規投稿できる")
    report(
        unknown_db.row["external_id"] == MEDIA_ID_NEW and MEDIA_ID in unknown_started,
        "unknown の再投稿成功でも前回IDは履歴に残り、最新IDへ更新する",
        unknown_started,
    )

    posting_http = MediaHttp()
    posting_acc = AccountsHttp("ok")
    posting_result, posting_db, _posting_log, posting_acc, posting_st = run_create(
        sample_record(status="posting", external_id=MEDIA_ID, posted_at=NOW),
        posting_http,
        accounts=posting_acc,
    )
    report(
        not posting_result["ok"] and posting_http.calls == [] and posting_acc.calls == [],
        "posting は再送できない",
    )
    report(
        posting_db.row["status"] == "posting" and posting_db.row["external_id"] == MEDIA_ID,
        "posting の状態と投稿IDは変えない",
    )

    denied_posted = MediaHttp(create="denied")
    dp_result, dp_db, _dp_log, _acc, _st = run_create(
        sample_record(status="posted", external_id=MEDIA_ID, posted_at=NOW),
        denied_posted,
    )
    report(
        not dp_result["ok"]
        and dp_db.row["status"] == "failed"
        and dp_db.row["external_id"] == MEDIA_ID
        and dp_db.row["posted_at"] == NOW,
        "再投稿が4xxでも前回の投稿IDは残す",
    )

    timeout_posted = MediaHttp(publish="timeout")
    tp_result, tp_db, _tp_log, _acc, _st = run_create(
        sample_record(status="posted", external_id=MEDIA_ID, posted_at=NOW),
        timeout_posted,
    )
    report(
        not tp_result["ok"]
        and tp_db.row["status"] == "unknown"
        and tp_db.row["external_id"] == MEDIA_ID,
        "再投稿が結果不明でも前回の投稿IDは残す",
    )

    failed_http = MediaHttp()
    failed_result, failed_db, _failed_log, _acc, _st = run_create(sample_record(status="failed"), failed_http)
    report(failed_result["ok"] and failed_db.row["status"] == "posted", "failed は再送できる")

    facebook_http = MediaHttp(publish="skip")
    facebook_acc = AccountsHttp("ok")
    facebook_result, facebook_db, _fb_log, facebook_acc, facebook_st = run_create(
        sample_record(channel="facebook"),
        facebook_http,
        accounts=facebook_acc,
    )
    report(
        not facebook_result["ok"] and facebook_http.calls == [] and facebook_acc.calls == [],
        "Facebookの行はInstagram送信しない",
    )
    report(facebook_db.row["channel"] == "facebook" and facebook_db.row["status"] == "draft", "Facebookの状態は変えない")

    gbp_http = MediaHttp(publish="skip")
    gbp_result, gbp_db, _gbp_log, gbp_acc, gbp_st = run_create(
        sample_record(channel="gbp", gbp_profile="tokyo"),
        gbp_http,
    )
    report(not gbp_result["ok"] and gbp_http.calls == [] and gbp_acc.calls == [], "GBPの行はInstagram送信しない")

    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": CREATION_ID}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    original_post = instagram_graph.requests.post
    instagram_graph.requests.post = fake_post
    try:
        status, body = instagram_graph.instagram_post_exchange(
            instagram_graph.instagram_media_url(IG_USER),
            access_token=PAGE_TOKEN,
            body=payload,
        )
    finally:
        instagram_graph.requests.post = original_post
    header_auth = (captured.get("headers") or {}).get("Authorization") or ""
    report(
        status == 200
        and body == {"id": CREATION_ID}
        and TOKEN not in (captured.get("url") or "")
        and PAGE_TOKEN not in (captured.get("url") or "")
        and "access_token" not in (captured.get("data") or {})
        and header_auth.startswith("Bearer ")
        and captured.get("timeout") == 30,
        "実送信口はヘッダー認証で、クエリと本文にトークンを置かない",
    )

    captured_get = {}

    class FakeGetResponse:
        status_code = 200

        def json(self):
            return {"status_code": "FINISHED"}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured_get["url"] = url
        captured_get["params"] = params
        captured_get["headers"] = headers
        captured_get["timeout"] = timeout
        return FakeGetResponse()

    original_get = instagram_graph.requests.get
    instagram_graph.requests.get = fake_get
    try:
        status, body = instagram_graph.instagram_get_exchange(
            instagram_graph.instagram_container_url(CREATION_ID),
            access_token=PAGE_TOKEN,
            params={"fields": "status_code"},
        )
    finally:
        instagram_graph.requests.get = original_get
    get_auth = (captured_get.get("headers") or {}).get("Authorization") or ""
    report(
        status == 200
        and "access_token" not in (captured_get.get("params") or {})
        and get_auth.startswith("Bearer ")
        and captured_get.get("params") == {"fields": "status_code"},
        "コンテナ確認もヘッダー認証で、クエリにトークンを置かない",
    )

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
