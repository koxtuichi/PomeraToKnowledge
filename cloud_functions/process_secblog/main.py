"""
main.py — Cloud Function エントリポイント：SECBLOG記事生成

GASからHTTPでPOSTされた SECBLOGメールの本文を受け取り、
対話形式のセキュリティブログ記事を生成してはてなブログに下書き投稿する。

処理フロー:
  1. リクエストからセキュリティメモを取得
  2. Geminiで対話形式の記事を生成（ナレッジグラフ参照なし）
  3. はてなブログ（セキュリティ学習ブログ）に下書き投稿
  4. Cloud Storageに記事を保存
  5. GitHubにも保存
"""
import os
import json
import re
from datetime import datetime

import functions_framework

import gcs_io
import secblog_writer
import hatena_publisher


@functions_framework.http
def process_secblog(request):
    """GASからHTTPで呼ばれるSECBLOG処理エントリポイント。"""

    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    try:
        data = request.get_json(silent=True)
        if not data:
            return json.dumps({"error": "リクエストボディが空です"}), 400

        body = data.get("body", "")
        subject = data.get("subject", "")

        if not body:
            return json.dumps({"error": "メール本文が空です"}), 400

        print(f"🔒 SECBLOGメモを受信: 件名={subject}, 文字数={len(body)}")

        # ── セキュリティ対話記事を生成 ──
        print("🔄 Geminiで対話形式のセキュリティ記事を生成中...")
        article_data = secblog_writer.generate_secblog_article(body)

        if not article_data:
            return json.dumps({"error": "記事の生成に失敗しました"}), 500

        title = article_data.get("title", "無題")
        article_body = article_data.get("body", "")
        categories = article_data.get("categories", ["セキュリティ", "学習記録"])

        print(f"✅ 記事生成完了: {title}")

        # ── はてなブログ（セキュリティ学習ブログ）に下書き投稿 ──
        hatena_url = None
        try:
            result = hatena_publisher.post_to_hatena(
                title=title,
                content=article_body,
                categories=categories,
                draft=True
            )
            if result:
                hatena_url = hatena_publisher.extract_url_from_response(result)
                print(f"✅ はてなブログに下書き投稿: {hatena_url}")
        except Exception as e:
            print(f"⚠️ はてなブログへの投稿に失敗: {e}")

        # ── Cloud Storageに保存 ──
        date_str = datetime.now().strftime("%Y%m%d")
        safe_title = re.sub(r'[\\/*?:"<>|]', '', title)[:50]

        md_content = (
            f"---\ntitle: {title}\ncategories: {json.dumps(categories, ensure_ascii=False)}\n"
            f"date: {datetime.now().isoformat()}\n---\n\n{article_body}"
        )
        gcs_io.save_text_to_gcs(f"blog_ready/secblog/{date_str}_{safe_title}.md", md_content)

        meta = {
            "title": title,
            "categories": categories,
            "generated_at": datetime.now().isoformat(),
            "source_subject": subject,
            "hatena_url": hatena_url,
        }
        gcs_io.save_json_to_gcs(f"blog_ready/secblog/{date_str}_{safe_title}_meta.json", meta)

        # ── GitHubにも保存 ──
        gcs_io.push_file_to_github(
            f"blog_ready/{date_str}_{safe_title}.md",
            md_content,
            f"Auto-sync: SecBlog article {title} [skip ci]"
        )

        result = {
            "status": "ok",
            "title": title,
            "categories": categories,
            "hatena_url": hatena_url,
        }
        print(f"✅ 処理完了: {json.dumps(result, ensure_ascii=False)}")
        return json.dumps(result, ensure_ascii=False), 200

    except Exception as e:
        import traceback
        print(f"❌ エラー: {e}\n{traceback.format_exc()}")
        return json.dumps({"error": str(e)}), 500
