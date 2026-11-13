#!/usr/bin/env python3
"""外部投稿の表示・保存・未接続。Google API も本番投稿もしない。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import external_posts
import gbp_read
from external_posts import ExternalPostNotConnected

FAILED = 0
PASSED = 0


def report(ok, name, detail=""):
    global FAILED, PASSED
    if ok:
        PASSED += 1
        print(f"PASS: {name}")
    else:
        FAILED += 1
        print(f"FAIL: {name} {detail}")


def main():
    keys = [item["key"] for item in external_posts.EXTERNAL_POST_TARGETS]
    report(
        keys == ["gbp_tokyo", "gbp_fukuoka", "instagram", "facebook"],
        "投稿先は4つで、東京と福岡は別",
        str(keys),
    )
    tokyo = external_posts.get_target("gbp_tokyo")
    fukuoka = external_posts.get_target("gbp_fukuoka")
    report(tokyo["gbp_profile"] == "tokyo" and fukuoka["gbp_profile"] == "fukuoka", "GBPプロフィール")
    report(external_posts.get_target("instagram")["gbp_profile"] is None, "InstagramにGBPプロフィールは無い")

    posted = external_posts.article_button_view(tokyo, {"status": "posted"})
    report(posted["label"] == "✓ GBP東京済" and posted["css_class"] == "is-posted", "投稿済は文字とクラス")
    failed = external_posts.article_button_view(fukuoka, {"status": "failed"})
    report(failed["label"] == "GBP福岡 失敗" and failed["css_class"] == "is-failed", "失敗は文字で分かる")
    fresh = external_posts.article_button_view(tokyo, None)
    report(fresh["label"] == "GBP東京" and fresh["css_class"] == "", "未投稿のラベル")
    saved = external_posts.article_button_view(
        external_posts.get_target("instagram"), {"status": "draft"}
    )
    report(saved["label"] == "Instagram 保存済", "保存済は投稿済ではない")

    bodies = {
        key: external_posts.starter_body(key, "肩の話", "つながって見る", "https://karin-sb.jp/blog/kata")
        for key in keys
    }
    report(len(set(bodies.values())) == 4, "初期文面は投稿先ごとに異なる")
    report("東京で施術" in bodies["gbp_tokyo"] and "福岡で施術" in bodies["gbp_fukuoka"], "GBPは地域が違う")
    report("料金" not in "".join(bodies.values()), "初期文面に料金を作らない")

    fields, reason = external_posts.prepare_notes_save(
        None, tokyo, 12, "本文", "https://karin-sb.jp/blog/kata", "/static/images/a.jpg", "staff-1", "2026-10-05T10:00:00+09:00"
    )
    report(reason is None and fields["fields"]["status"] == "draft", "保存は draft")
    report(fields["fields"]["posted_at"] is None and fields["fields"]["external_id"] is None, "保存では受付IDを書かない")
    report(fields["fields"]["gbp_profile"] == "tokyo" and fields["event"]["event"] == "edited", "東京行と履歴イベント")
    report("succeeded" not in fields["event"]["event"], "保存履歴は成功イベントではない")

    locked, lock_reason = external_posts.prepare_notes_save(
        {"status": "posted", "id": "x", "external_id": "accounts/1/locations/2/localPosts/3", "posted_at": "2026-10-05T10:00:00+09:00"},
        tokyo,
        12,
        "本文",
        "",
        "",
        "staff-1",
        "2026-10-05T10:00:00+09:00",
    )
    report(
        lock_reason is None
        and locked["fields"]["status"] == "posted"
        and locked["fields"]["external_id"] == "accounts/1/locations/2/localPosts/3",
        "GBP投稿済の保存は状態と投稿IDを残す",
        str(lock_reason),
    )
    ig_locked, ig_reason = external_posts.prepare_notes_save(
        {"status": "posted", "id": "x"},
        external_posts.get_target("instagram"),
        12,
        "本文",
        "",
        "",
        "staff-1",
        "2026-10-05T10:00:00+09:00",
    )
    report(ig_locked is None and ig_reason, "Instagram投稿済は上書きしない", str(ig_reason))

    raised = False
    try:
        external_posts.publish_external_post("gbp_tokyo", body="本文")
    except ExternalPostNotConnected:
        raised = True
    report(raised, "送信口は未接続の例外")

    app_src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    report("publish_external_post" not in app_src, "管理ルートは送信口を呼ばない")
    report("def build_gbp_schedule_entries" in app_src, "予定組み立て関数は残っている")

    import app as appmod

    draft_blog = {
        "id": 3,
        "title": "下書き",
        "slug": "draft-one",
        "draft": True,
        "excerpt": "",
        "body": "",
        "category": "",
        "article_type": "standard",
        "external_post_buttons": [
            external_posts.article_button_view(item, None) for item in external_posts.EXTERNAL_POST_TARGETS
        ],
    }
    live_blog = dict(draft_blog)
    live_blog.update({"id": 12, "title": "公開記事", "slug": "live-one", "draft": False})
    live_blog["external_post_buttons"] = [
        external_posts.article_button_view(
            external_posts.EXTERNAL_POST_TARGETS[0], {"status": "posted"}
        ),
        external_posts.article_button_view(external_posts.EXTERNAL_POST_TARGETS[1], None),
        external_posts.article_button_view(
            external_posts.EXTERNAL_POST_TARGETS[2], {"status": "draft"}
        ),
        external_posts.article_button_view(
            external_posts.EXTERNAL_POST_TARGETS[3], {"status": "failed"}
        ),
    ]
    with appmod.app.test_request_context("/admin/blogs"):
        draft_html = appmod.render_template(
            "admin_blogs.html",
            blogs=[draft_blog],
            article_type_labels=appmod.ARTICLE_TYPE_LABELS,
        )
        live_html = appmod.render_template(
            "admin_blogs.html",
            blogs=[live_blog],
            article_type_labels=appmod.ARTICLE_TYPE_LABELS,
        )
        service_html = appmod.render_template(
            "admin_gbp_services.html",
            area="fukuoka",
            area_label="福岡",
            services=[
                {
                    "key": item["key"],
                    "label": item["label"],
                    "note": item["note"],
                    "status_label": "未投稿",
                }
                for item in external_posts.GBP_SERVICE_CATALOG
            ],
        )
        preview_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog=live_blog,
            target=tokyo,
            form={"body": "下書き文", "link_url": "https://example.com", "image_url": "", "status_label": "未投稿"},
            events=[],
        )
        gbp_ok = appmod.gbp_local_post.build_standard_post("本文", "https://karin-sb.jp/")
        gbp_ok["payload_text"] = appmod.gbp_local_post.payload_text(gbp_ok["payload"])
        gbp_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog=live_blog,
            target=tokyo,
            form={"body": "本文", "link_url": "https://karin-sb.jp/", "image_url": "", "status_label": "未投稿"},
            events=[],
            gbp_preview=gbp_ok,
        )
        gbp_bad = appmod.gbp_local_post.build_standard_post("本文", "https://karin-sb.jp/", "/static/images/a.jpg")
        gbp_bad["payload_text"] = ""
        gbp_bad_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog=live_blog,
            target=tokyo,
            form={"body": "本文", "link_url": "https://karin-sb.jp/", "image_url": "/static/images/a.jpg", "status_label": "未投稿"},
            events=[],
            gbp_preview=gbp_bad,
        )
        send_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog=live_blog,
            target=tokyo,
            form={"body": "本文", "link_url": "https://karin-sb.jp/", "image_url": "", "status_label": "確認済"},
            events=[],
            gbp_preview=gbp_ok,
            gbp_action="send",
            gbp_locked=False,
        )
        check_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog=live_blog,
            target=tokyo,
            form={"body": "本文", "link_url": "https://karin-sb.jp/", "image_url": "", "status_label": "要確認"},
            events=[],
            gbp_preview=gbp_ok,
            gbp_action="send",
            gbp_locked=False,
            gbp_send_label="重複の可能性があることを理解して再投稿する",
            gbp_repost_warning=True,
        )
        instagram_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog=live_blog,
            target=external_posts.get_target("instagram"),
            form={"body": "本文", "link_url": "https://karin-sb.jp/", "image_url": "", "status_label": "未投稿"},
            events=[],
        )
        facebook = external_posts.get_target("facebook")
        facebook_preview = appmod._facebook_post_preview(facebook, "本文", "https://karin-sb.jp/blog/a")
        facebook_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog=live_blog,
            target=facebook,
            form={"body": "本文", "link_url": "https://karin-sb.jp/blog/a", "image_url": "", "status_label": "下書き保存"},
            events=[],
            facebook_preview=facebook_preview,
            facebook_action="send",
            facebook_send_label="この内容をFacebookに投稿する",
        )
        facebook_locked_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog=live_blog,
            target=facebook,
            form={"body": "本文", "link_url": "https://karin-sb.jp/blog/a", "image_url": "", "status_label": "投稿済"},
            events=[],
            facebook_preview=facebook_preview,
            facebook_action=None,
        )
    report("is-disabled" in draft_html and "/posts/gbp_tokyo" not in draft_html, "下書きの外部投稿はリンクではない")
    report('href="/admin/blogs/12/posts/gbp_tokyo"' in live_html, "公開記事からGBP東京へ進める")
    report('href="/admin/blogs/12/posts/gbp_fukuoka"' in live_html, "公開記事からGBP福岡へ進める")
    report("✓ GBP東京済" in live_html and "Instagram 保存済" in live_html and "Facebook 失敗" in live_html, "カードに状態の文字")
    report("トレーニング・リコンディショニング" in service_html and "area=tokyo" in service_html and "area=fukuoka" in service_html, "サービス画面は1画面で地域を切り替える")
    report("<form" not in service_html, "サービス画面に送信フォームは無い")
    report(
        "この内容を保存" in preview_html
        and 'action="/admin/blogs/12/posts/gbp_tokyo"' in preview_html
        and "GBPへの送信はこの画面のボタンで行います" in preview_html,
        "確認画面は管理画面への保存まで",
    )
    report(
        "自動で送り直しません" in gbp_html
        and "この内容を確認済にする" not in gbp_html
        and "この内容をGoogleに投稿する" not in gbp_html
        and "mybusiness.googleapis.com" not in gbp_html,
        "操作を選んでいない画面には送信ボタンが無い",
    )
    report("この内容をGoogleに投稿する" in send_html and "GBPへの送信はこの画面のボタンで行います" in send_html, "送信操作がある画面に送信ボタンがある")
    report(
        "Google側の投稿を確認する" not in check_html
        and "重複の可能性があることを理解して再投稿する" in check_html
        and "再投稿すると重複する場合があります" in check_html,
        "結果不明の画面は確認検索せず、重複注意つきで再投稿できる",
    )
    report("投稿結果を確定できないため、新規送信を停止中" not in send_html, "送信できる画面は送信停止の表示を出さない")
    report("この内容をGoogleに投稿する" not in gbp_bad_html and "公開された https" in gbp_bad_html, "不正な画像では送信できない")
    report(
        "サーバー内の画像から選択" not in gbp_html
        and 'id="blog-thumb-image-input"' not in gbp_html
        and "初期値は記事のサムネイルです" not in gbp_html
        and ">画像<" not in gbp_html,
        "GBP画面に画像選択欄が残っていない",
    )
    report(
        "サーバー内の画像から選択" in instagram_html and 'id="blog-thumb-image-input"' in instagram_html,
        "Instagram画面の画像欄は残っている",
    )
    report(
        "この内容をFacebookに投稿する" not in instagram_html
        and "保存した内容だけをFacebookへ投稿できます" not in instagram_html,
        "Instagram画面にFacebook送信ボタンは無い",
    )
    report(
        "この内容をFacebookに投稿する" not in send_html
        and "この内容をGoogleに投稿する" in send_html,
        "GBP送信画面にFacebook送信ボタンは無い",
    )
    report(
        'name="action" value="save"' in facebook_html
        and "この内容をFacebookに投稿する" in facebook_html
        and "message:" in facebook_html
        and "https://karin-sb.jp/blog/a" in facebook_html
        and "保存した内容だけをFacebookへ投稿できます" in facebook_html,
        "Facebook画面は保存と送信を分け、本文とリンクを確認できる",
    )
    report(
        "この内容をFacebookに投稿する" not in facebook_locked_html
        and "投稿済みと成否未確認は再送しません" in facebook_locked_html,
        "Facebookの投稿済画面は送信できない",
    )
    report(
        appmod._facebook_post_preview(external_posts.get_target("instagram"), "本文", "https://karin-sb.jp/blog/a") is None
        and appmod._facebook_post_preview(tokyo, "本文", "https://karin-sb.jp/") is None,
        "InstagramとGBPにFacebook確認は出ない",
    )
    report(
        appmod._notes_facebook_screen_action(facebook, {"status": "draft", "id": "1"}, facebook_preview) == "send"
        and appmod._notes_facebook_screen_action(facebook, {"status": "failed", "id": "1"}, facebook_preview) == "send"
        and appmod._notes_facebook_screen_action(facebook, {"status": "posted", "id": "1"}, facebook_preview) is None
        and appmod._notes_facebook_screen_action(facebook, {"status": "unknown", "id": "1"}, facebook_preview) is None
        and appmod._notes_facebook_screen_action(external_posts.get_target("instagram"), {"status": "draft", "id": "1"}, facebook_preview) is None,
        "Facebookは下書きと失敗だけ送信でき、Instagramは対象外",
    )
    report(appmod.gbp_period_key(2026, 10, "H1") == "2026-10-H1", "半月キーは従来どおり")

    pole_blog = {
        "id": "blog-stretch",
        "title": "ストレッチポール",
        "slug": "stretch-pole-posture",
        "excerpt": "姿勢",
        "image": "/static/images/blogs/pole.jpg",
    }
    tokyo_existing = {
        "id": "row-tokyo",
        "status": "draft",
        "body": "東京向け保存文",
        "link_url": "http://karin-sb.jp/blog/stretch-pole-posture",
        "image_url": "/static/images/blogs/pole.jpg",
        "gbp_profile": "tokyo",
    }
    fukuoka_existing = {
        "id": "row-fukuoka",
        "status": "draft",
        "body": "福岡向け保存文",
        "link_url": "https://karin-sb.jp/blog/stretch-pole-posture",
        "image_url": "",
        "gbp_profile": "fukuoka",
    }
    tokyo_form = appmod._external_post_form_values(pole_blog, tokyo, tokyo_existing)
    fukuoka_form = appmod._external_post_form_values(pole_blog, fukuoka, fukuoka_existing)
    fresh_form = appmod._external_post_form_values(pole_blog, tokyo, None)
    report(
        fresh_form["image_url"] == "https://karin-sb.jp/static/images/blogs/pole.jpg",
        "未保存のGBP画像は記事サムネイル",
        fresh_form["image_url"],
    )
    report(
        appmod._gbp_https_asset_url("/static/images/notes/a.jpg") == "https://karin-sb.jp/static/images/notes/a.jpg",
        "サーバー内パスはGBP用httpsになる",
        appmod._gbp_https_asset_url("/static/images/notes/a.jpg"),
    )
    report(tokyo_form["body"] == "東京向け保存文", "東京の保存文を再表示する")
    report(fukuoka_form["body"] == "福岡向け保存文", "福岡の保存文を再表示する")
    report(
        tokyo_form["link_url"] == "https://karin-sb.jp/blog/stretch-pole-posture",
        "東京の保存リンクはhttpsで再表示する",
        tokyo_form["link_url"],
    )
    report(
        tokyo_form["image_url"] == "https://karin-sb.jp/static/images/blogs/pole.jpg",
        "東京の保存画像は公開httpsで再表示する",
        tokyo_form["image_url"],
    )
    report(fukuoka_form["image_url"] == "", "福岡で空保存した画像は空のまま")
    tokyo_preview = appmod._gbp_post_preview(
        tokyo, tokyo_form["body"], tokyo_form["link_url"], tokyo_form["image_url"], notes_create=True
    )
    fukuoka_preview = appmod._gbp_post_preview(
        fukuoka, fukuoka_form["body"], fukuoka_form["link_url"], fukuoka_form["image_url"], notes_create=True
    )
    report(tokyo_preview["ok"] is True and fukuoka_preview["ok"] is True, "保存した東京・福岡の内容は確認済に進める")
    with appmod.app.test_request_context("/admin/blogs/blog-stretch/posts/gbp_tokyo"):
        tokyo_saved_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog=pole_blog,
            target=tokyo,
            form=tokyo_form,
            events=[],
            gbp_preview=tokyo_preview,
            gbp_action=appmod._notes_gbp_screen_action(tokyo, tokyo_existing, tokyo_preview),
            gbp_locked=False,
            gbp_send_label=appmod._notes_gbp_send_label(tokyo_existing.get("status")),
        )
        fukuoka_saved_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog=pole_blog,
            target=fukuoka,
            form=fukuoka_form,
            events=[],
            gbp_preview=fukuoka_preview,
            gbp_action=appmod._notes_gbp_screen_action(fukuoka, fukuoka_existing, fukuoka_preview),
            gbp_locked=False,
            gbp_send_label=appmod._notes_gbp_send_label(fukuoka_existing.get("status")),
        )
    report(
        "東京向け保存文" in tokyo_saved_html
        and "https://karin-sb.jp/blog/stretch-pole-posture" in tokyo_saved_html
        and "サーバー内の画像から選択" not in tokyo_saved_html
        and "この内容をGoogleに投稿する" in tokyo_saved_html
        and "この内容を確認済にする" not in tokyo_saved_html,
        "東京の保存内容から新規投稿できる",
    )
    report(
        "福岡向け保存文" in fukuoka_saved_html
        and "この内容をGoogleに投稿する" in fukuoka_saved_html
        and "この内容を確認済にする" not in fukuoka_saved_html,
        "福岡の保存内容から新規投稿できる",
    )
    ascii_thumb = "https://karin-sb.jp/static/images/notes/stretch-pole-posture-thumbnail.jpg"
    article_url = "https://karin-sb.jp/blog/stretch-pole-posture"
    notes_preview = appmod._gbp_post_preview(
        tokyo,
        "ストレッチポール\n" + article_url,
        article_url,
        ascii_thumb,
        notes_create=True,
    )
    report(
        notes_preview["ok"]
        and notes_preview["payload"]["callToAction"]["url"] == article_url
        and "media" not in notes_preview["payload"]
        and notes_preview["payload"]["summary"] == "ストレッチポール\n" + article_url
        and "](" not in notes_preview["payload_text"]
        and "[https://" not in notes_preview["payload_text"],
        "NOTES確認JSONは文章とリンクだけでmediaを付けない",
        notes_preview.get("payload_text") or "",
    )
    md_article = "[" + article_url + "](" + article_url + ")"
    md_thumb = "[" + ascii_thumb + "](" + ascii_thumb + ")"
    notes_md_preview = appmod._gbp_post_preview(
        tokyo,
        "ストレッチポール\n" + md_article,
        md_article,
        md_thumb,
        notes_create=True,
    )
    report(
        notes_md_preview["ok"]
        and notes_md_preview["payload"]["callToAction"]["url"] == article_url
        and "media" not in notes_md_preview["payload"]
        and notes_md_preview["payload"]["summary"] == "ストレッチポール\n" + article_url,
        "NOTES確認はMarkdownリンクを生のhttpsに戻し、mediaは付けない",
        notes_md_preview.get("payload_text") or "",
    )
    service_md_preview = appmod._gbp_post_preview(tokyo, "本文", md_article, md_thumb)
    report(not service_md_preview["ok"], "従来の確認はMarkdown URLを送らない")
    with appmod.app.test_request_context("/admin/blogs/blog-stretch/posts/gbp_tokyo"):
        notes_preview_html = appmod.render_template(
            "admin_blog_external_post.html",
            blog=pole_blog,
            target=tokyo,
            form={
                "body": "ストレッチポール\n" + article_url,
                "link_url": article_url,
                "image_url": ascii_thumb,
                "status_label": "未投稿",
            },
            events=[],
            gbp_preview=notes_preview,
        )
    preview_json = notes_preview_html.split("<pre", 1)[1].split("</pre>", 1)[0]
    report(
        "https://karin-sb.jp/blog/stretch-pole-posture" in preview_json
        and "media" not in preview_json
        and "サーバー内の画像から選択" not in notes_preview_html
        and "](" not in preview_json
        and "[https://" not in preview_json,
        "管理画面の送信内容確認は文章とリンクだけで画像欄が無い",
        preview_json,
    )
    no_media = appmod._gbp_post_preview(
        tokyo, "本文だけ", article_url, ascii_thumb, notes_create=True
    )
    report(
        no_media["ok"] and "media" not in no_media["payload"],
        "保存済み画像があってもNOTES確認JSONはmediaを付けない",
        str(no_media.get("payload")),
    )
    tokyo_confirm, tokyo_confirm_reason = external_posts.prepare_notes_confirm(
        tokyo_existing,
        tokyo,
        tokyo_form["body"],
        tokyo_form["link_url"],
        tokyo_form["image_url"],
        "staff-1",
        "2026-10-20T11:00:00+09:00",
    )
    fukuoka_confirm, fukuoka_confirm_reason = external_posts.prepare_notes_confirm(
        fukuoka_existing,
        fukuoka,
        fukuoka_form["body"],
        fukuoka_form["link_url"],
        fukuoka_form["image_url"],
        "staff-1",
        "2026-10-20T11:00:00+09:00",
    )
    report(
        tokyo_confirm_reason is None
        and fukuoka_confirm_reason is None
        and tokyo_confirm["fields"]["status"] == "ready"
        and fukuoka_confirm["fields"]["status"] == "ready"
        and tokyo_confirm["fields"]["gbp_profile"] == "tokyo"
        and fukuoka_confirm["fields"]["gbp_profile"] == "fukuoka"
        and tokyo_confirm["event"]["event"] == "confirmed"
        and fukuoka_confirm["event"]["event"] == "confirmed",
        "確認操作で東京と福岡を確認済にする",
    )
    report(
        "外部サービスへは投稿していません" in tokyo_confirm["event"]["detail"]
        and "succeeded" not in tokyo_confirm["event"]["event"],
        "確認済への遷移だけではGoogleへ送信しない",
    )
    report(appmod._gbp_screen_action(tokyo, tokyo_existing, tokyo_preview) is None, "サービス用の画面操作は下書きを送信にしない")
    ready_row = dict(tokyo_existing, status="ready")
    report(appmod._gbp_screen_action(tokyo, ready_row, tokyo_preview) == "send", "サービス用の画面操作は確認済だけ送信になる")
    report(appmod._notes_gbp_screen_action(tokyo, tokyo_existing, tokyo_preview) == "send", "NOTESの下書きは新規投稿できる")
    report(appmod._notes_gbp_screen_action(tokyo, dict(tokyo_existing, status="posted"), tokyo_preview) == "send", "NOTESの投稿済からも新規投稿できる")
    report(appmod._notes_gbp_screen_action(tokyo, dict(tokyo_existing, status="unknown"), tokyo_preview) == "send", "NOTESの結果不明は明示再投稿できる")
    report(appmod._notes_gbp_screen_action(tokyo, dict(tokyo_existing, status="failed"), tokyo_preview) == "send", "NOTESの失敗は再投稿できる")
    report(appmod._notes_gbp_screen_action(tokyo, dict(tokyo_existing, status="posting"), tokyo_preview) is None, "NOTESの送信中は重ねて送らない")
    draft_plan, draft_reason = appmod.gbp_local_post.begin_notes_gbp_submit(
        {
            "id": "row-tokyo",
            "status": "draft",
            "gbp_profile": "tokyo",
            "body": tokyo_form["body"],
            "link_url": tokyo_form["link_url"],
            "image_url": tokyo_form["image_url"],
        },
        "2026-10-20T11:00:00+09:00",
    )
    report(draft_plan is None and "確認済み" in (draft_reason or ""), "未確認の投稿は送信できない", str(draft_reason))
    unknown_plan, unknown_reason = appmod.gbp_local_post.begin_notes_gbp_submit(
        {"id": "row-tokyo", "status": "unknown", "gbp_profile": "tokyo", "external_id": "accounts/1/locations/2/localPosts/3"},
        "2026-10-20T11:00:00+09:00",
    )
    report(unknown_plan is None and unknown_reason, "成否未確認は再送しない", str(unknown_reason))

    tokyo_screen, tokyo_reason = external_posts.resolve_service_screen("tokyo", "acupuncture")
    fukuoka_screen, fukuoka_reason = external_posts.resolve_service_screen("fukuoka", "acupuncture")
    report(tokyo_reason is None and fukuoka_reason is None, "鍼灸の東京と福岡は開ける")
    report(
        tokyo_screen["gbp_profile"] == "tokyo"
        and fukuoka_screen["gbp_profile"] == "fukuoka"
        and tokyo_screen["service"]["key"] == "acupuncture"
        and fukuoka_screen["service"]["key"] == "acupuncture",
        "同じ鍼灸でも地域は別の投稿対象",
    )
    missing, missing_reason = external_posts.resolve_service_screen("osaka", "acupuncture")
    unknown, unknown_reason = external_posts.resolve_service_screen("fukuoka", "unknown")
    report(missing is None and unknown is None and missing_reason and unknown_reason, "不正な地域とサービスは拒否する")

    tokyo_save, tokyo_save_reason = external_posts.prepare_service_save(
        None, "tokyo", "acupuncture", "本文", "https://karin-sb.jp/tokyo/shinkyu", "", "staff-1", "2026-10-19T10:00:00+09:00"
    )
    fukuoka_save, fukuoka_save_reason = external_posts.prepare_service_save(
        None, "fukuoka", "acupuncture", "本文", "https://karin-sb.jp/fukuoka/shinkyu", "", "staff-1", "2026-10-19T10:00:00+09:00"
    )
    report(
        tokyo_save_reason is None
        and fukuoka_save_reason is None
        and tokyo_save["fields"]["source_kind"] == "service"
        and tokyo_save["fields"]["gbp_profile"] == "tokyo"
        and fukuoka_save["fields"]["gbp_profile"] == "fukuoka"
        and tokyo_save["fields"]["status"] == "draft",
        "サービス保存は地域ごとに別行で、下書きのまま",
    )
    revised, revise_reason = external_posts.prepare_service_revision(
        {
            "id": "row-1",
            "source_kind": "service",
            "channel": "gbp",
            "gbp_profile": "fukuoka",
            "service_key": "acupuncture",
            "status": "posted",
            "external_id": "accounts/1/locations/2/localPosts/3",
            "posted_at": "2026-10-19T10:00:00+09:00",
        },
        "fukuoka",
        "acupuncture",
        "更新後",
        "https://karin-sb.jp/fukuoka/shinkyu",
        "",
        "staff-1",
        "2026-10-19T11:00:00+09:00",
    )
    report(
        revise_reason is None
        and revised["fields"]["external_id"] == "accounts/1/locations/2/localPosts/3"
        and revised["fields"]["status"] == "ready"
        and revised["fields"]["gbp_profile"] == "fukuoka",
        "投稿済みの更新でも投稿IDと福岡を残す",
        str(revise_reason),
    )
    mixed, mixed_reason = external_posts.prepare_service_save(
        {"id": "row-1", "source_kind": "service", "channel": "gbp", "gbp_profile": "tokyo", "service_key": "acupuncture", "status": "draft"},
        "fukuoka",
        "acupuncture",
        "本文",
        "https://karin-sb.jp/fukuoka/shinkyu",
        "",
        "staff-1",
        "2026-10-19T10:00:00+09:00",
    )
    report(mixed is None and mixed_reason, "東京の記録を福岡として保存しない", str(mixed_reason))

    with appmod.app.test_request_context("/admin/gbp/services"):
        tokyo_list = appmod.render_template(
            "admin_gbp_services.html",
            area="tokyo",
            area_label="東京",
            services=[
                {
                    "key": item["key"],
                    "label": item["label"],
                    "note": item["note"],
                    "status_label": "未投稿",
                }
                for item in external_posts.GBP_SERVICE_CATALOG
            ],
        )
        tokyo_detail = appmod.render_template(
            "admin_gbp_service_post.html",
            screen=tokyo_screen,
            form={"body": "東京の鍼灸", "link_url": "https://karin-sb.jp/tokyo/shinkyu", "image_url": "", "status_label": "未投稿"},
            events=[],
            gbp_preview=None,
            gbp_locked=False,
        )
        fukuoka_detail = appmod.render_template(
            "admin_gbp_service_post.html",
            screen=fukuoka_screen,
            form={"body": "福岡の鍼灸", "link_url": "https://karin-sb.jp/fukuoka/shinkyu", "image_url": "", "status_label": "未投稿"},
            events=[],
            gbp_preview={"ok": True, "payload_text": '{"summary":"本文"}', "errors": []},
            gbp_locked=False,
        )
        send_detail = appmod.render_template(
            "admin_gbp_service_post.html",
            screen=fukuoka_screen,
            form={"body": "福岡の鍼灸", "link_url": "https://karin-sb.jp/fukuoka/shinkyu", "image_url": "", "status_label": "確認済・未投稿"},
            events=[],
            gbp_preview={"ok": True, "payload_text": '{"summary":"本文"}', "errors": []},
            gbp_action="send",
            gbp_locked=False,
        )
        check_detail = appmod.render_template(
            "admin_gbp_service_post.html",
            screen=fukuoka_screen,
            form={"body": "福岡の鍼灸", "link_url": "https://karin-sb.jp/fukuoka/shinkyu", "image_url": "", "status_label": "要確認"},
            events=[],
            gbp_preview={"ok": True, "payload_text": '{"summary":"本文"}', "errors": []},
            gbp_action="check",
            gbp_locked=True,
        )
    report('href="/admin/gbp/services/tokyo/acupuncture"' in tokyo_list, "東京の鍼灸カードから東京の画面へ進める")
    report('href="/admin/gbp/services/fukuoka/acupuncture"' in service_html, "福岡の鍼灸カードから福岡の画面へ進める")
    report(
        'action="/admin/gbp/services/tokyo/acupuncture"' in tokyo_detail
        and "対象地域: 東京" in tokyo_detail
        and "サービス: 鍼灸" in tokyo_detail
        and "この内容をGoogleに投稿する" not in tokyo_detail,
        "東京鍼灸の確認画面は東京のまま、送信ボタンは無い",
    )
    report(
        'action="/admin/gbp/services/fukuoka/acupuncture"' in fukuoka_detail
        and "対象地域: 福岡" in fukuoka_detail
        and "この内容を確認済にする" in fukuoka_detail
        and "この内容をGoogleに投稿する" not in fukuoka_detail
        and "mybusiness.googleapis.com" not in fukuoka_detail,
        "未確認の福岡画面に送信ボタンは無い",
    )
    report(
        "この内容をGoogleに投稿する" in send_detail
        and "この内容を保存" in send_detail
        and "対象地域: 福岡" in send_detail,
        "確認済の福岡画面だけ送信ボタンがある",
    )
    report(
        "Google側の投稿を確認する" in check_detail
        and "この内容をGoogleに投稿する" not in check_detail
        and "投稿結果を確定できないため、新規送信を停止中" in check_detail,
        "結果不明の画面は確認だけで再送しない",
    )

    with appmod.app.test_client() as client:
        locked = client.get("/admin/gbp/services/fukuoka/acupuncture")
        location = locked.headers.get("Location") or ""
        report(locked.status_code in (301, 302) and "login" in location, "未ログインはサービス画面を開けない", location)
        send_try = client.post("/admin/gbp/services/fukuoka/acupuncture", data={"action": "send", "body": "本文"})
        send_location = send_try.headers.get("Location") or ""
        report(send_try.status_code in (301, 302) and "login" in send_location, "未ログインの送信操作も開けない")

    rules = [rule.rule for rule in appmod.app.url_map.iter_rules() if rule.endpoint == "admin_gbp_service_post"]
    report("/admin/gbp/services/<area>/<service_key>" in rules, "サービス確認のルートがある")
    service_src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    report("mode=\"send\"" in service_src and "admin_gbp_service_post" in service_src, "サービス画面は既存の送信処理を使う")
    report(
        appmod._safe_gbp_exception_text(ValueError("保存に失敗しました")) == "保存に失敗しました"
        and appmod._safe_gbp_exception_text(RuntimeError("Bearer ya29.secret")) == "redacted"
        and appmod._safe_gbp_exception_text(RuntimeError("refresh_token=abc")) == "redacted",
        "送信例外のログはクラス名用に安全な文言だけ残す",
    )
    report(getattr(appmod, "gbp_read", None) is gbp_read, "送信共通処理は既存のgbp_readを使う")
    report(
        callable(getattr(appmod.gbp_read, "load_gbp_read_config", None))
        and callable(getattr(appmod.gbp_read, "requests_exchange", None)),
        "送信共通処理が使う読み取り関数は実在する",
    )
    sent = {}
    original_send = appmod.gbp_local_post.perform_notes_gbp_send
    original_load = appmod.gbp_read.load_gbp_read_config
    try:
        appmod.gbp_read.load_gbp_read_config = lambda: {"locations": {"fukuoka": "locations/test"}}
        appmod.gbp_local_post.perform_notes_gbp_send = lambda *args, **kwargs: sent.update(kwargs) or {
            "ok": True,
            "message": "テスト用送信",
        }
        result = appmod._run_gbp_external_action(
            {"id": "svc-1", "status": "ready", "gbp_profile": "fukuoka"},
            mode="send",
            staff_id="staff-1",
            now="2026-10-19T14:00:00+09:00",
        )
        name_error = False
    except NameError:
        name_error = True
        result = None
    finally:
        appmod.gbp_local_post.perform_notes_gbp_send = original_send
        appmod.gbp_read.load_gbp_read_config = original_load
    report(
        not name_error
        and result == {"ok": True, "message": "テスト用送信"}
        and sent.get("token_exchange") is gbp_read.requests_exchange,
        "サービス送信の共通処理はgbp_read未定義で落ちない",
    )

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
