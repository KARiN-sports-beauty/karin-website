import os, json, re

BASE_DIR = os.path.dirname(__file__)
BLOG_JSON = os.path.join(BASE_DIR, "static", "data", "blogs.json")
BLOG_DIR = os.path.join(BASE_DIR, "templates", "blogs")

with open(BLOG_JSON, "r", encoding="utf-8") as f:
    blogs = json.load(f)

for blog in blogs:
    if not blog.get("body"):
        path = os.path.join(BLOG_DIR, f"blog_{blog['id']}.html")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                html = f.read()
            match = re.search(r'<div class="blog-body">\s*(.*?)\s*</div>', html, re.S)
            if match:
                body = match.group(1)
                body = re.sub(r'<br\s*/?>', '\n', body).strip()
                blog["body"] = body
                print(f"✅ Restored body for blog ID {blog['id']}")
            else:
                print(f"⚠️ No body found in {path}")
        else:
            print(f"⚠️ Missing file: {path}")

with open(BLOG_JSON, "w", encoding="utf-8") as f:
    json.dump(blogs, f, ensure_ascii=False, indent=2)

print("修復完了 ✅")
