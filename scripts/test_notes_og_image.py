#!/usr/bin/env python3
"""NOTES記事ページの og:image は絶対URL。表示用画像パスは変えない。"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FAILED = 0
PASSED = 0
OG_IMAGE = re.compile(r'<meta property="og:image" content="([^"]+)"')
DEFAULT = "https://karin-sb.jp/static/images/logoname.jpg"
TEMPLATES = (
    "blog_detail.html",
    "blog_detail_feature.html",
    "blog_detail_column.html",
)


def report(ok, name, detail=""):
    global FAILED, PASSED
    if ok:
        PASSED += 1
        print(f"PASS: {name}")
    else:
        FAILED += 1
        print(f"FAIL: {name} {detail}")


def sample_blog(**overrides):
    blog = {
        "id": "og-1",
        "title": "肩の話",
        "slug": "kata-no-hanashi",
        "excerpt": "つながって見る",
        "body": "<p>本文</p>",
        "image": "/static/images/notes/kata.jpg",
        "date_display": "2026/11/13",
        "date": "2026-11-13",
        "category": "",
        "tags_list": [],
        "article_type": "standard",
        "date_published_iso": "2026-11-13",
        "date_modified_iso": "2026-11-13",
    }
    blog.update(overrides)
    return blog


def render(appmod, template, blog):
    return appmod.render_template(
        template,
        blog=blog,
        author_info=None,
        related_blogs=[],
    )


def og_image(html):
    match = OG_IMAGE.search(html)
    return match.group(1) if match else None


def main():
    import app as appmod

    relative = "/static/images/notes/stretch-pole-posture-thumbnail.jpg"
    absolute = "https://cdn.example.com/notes/thumb.jpg"
    already = "https://karin-sb.jp/static/images/notes/kata.jpg"

    with appmod.app.test_request_context("/blog/kata-no-hanashi"):
        for template in TEMPLATES:
            html = render(appmod, template, sample_blog(image=relative))
            value = og_image(html)
            report(
                value == "https://karin-sb.jp" + relative,
                f"{template} の相対パスは絶対URL",
                value or "",
            )
            if template != "blog_detail_column.html":
                report(
                    f'src="{relative}"' in html,
                    f"{template} の表示用画像は相対パスのまま",
                )
            report(
                "https://karin-sb.jphttps://" not in html
                and "https://karin-sb.jp/https://" not in html,
                f"{template} はドメインを二重に付けない",
            )

        html_abs = render(appmod, "blog_detail.html", sample_blog(image=absolute))
        report(og_image(html_abs) == absolute, "既存の絶対URLはそのまま")

        html_site = render(appmod, "blog_detail.html", sample_blog(image=already))
        report(og_image(html_site) == already, "karin-sb.jp付きURLは二重にしない")

        html_empty = render(appmod, "blog_detail.html", sample_blog(image=""))
        report(og_image(html_empty) == DEFAULT, "未設定は既定の絶対URL")

        html_static = render(appmod, "blog_detail.html", sample_blog(image="static/images/notes/kata.jpg"))
        report(
            og_image(html_static) == "https://karin-sb.jp/static/images/notes/kata.jpg",
            "static/ から始まるパスも絶対URL",
            og_image(html_static) or "",
        )

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
