#!/usr/bin/env python3
"""外部投稿の表示・保存・未接続。Google API も本番投稿もしない。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import external_posts
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
        {"status": "posted", "id": "x"}, tokyo, 12, "本文", "", "", "staff-1", "2026-10-05T10:00:00+09:00"
    )
    report(locked is None and lock_reason, "投稿済行は上書きしない", str(lock_reason))

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
    report("is-disabled" in draft_html and "/posts/gbp_tokyo" not in draft_html, "下書きの外部投稿はリンクではない")
    report('href="/admin/blogs/12/posts/gbp_tokyo"' in live_html, "公開記事からGBP東京へ進める")
    report('href="/admin/blogs/12/posts/gbp_fukuoka"' in live_html, "公開記事からGBP福岡へ進める")
    report("✓ GBP東京済" in live_html and "Instagram 保存済" in live_html and "Facebook 失敗" in live_html, "カードに状態の文字")
    report("トレーニング・リコンディショニング" in service_html and "area=tokyo" in service_html and "area=fukuoka" in service_html, "サービス画面は1画面で地域を切り替える")
    report("<form" not in service_html, "サービス画面に送信フォームは無い")
    report(
        "この内容を保存" in preview_html
        and 'action="/admin/blogs/12/posts/gbp_tokyo"' in preview_html
        and "外部サービスへの送信は" in preview_html,
        "確認画面は管理画面への保存まで",
    )
    report(appmod.gbp_period_key(2026, 10, "H1") == "2026-10-H1", "半月キーは従来どおり")

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
