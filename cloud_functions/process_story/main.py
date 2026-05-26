"""
main.py — Cloud Function エントリポイント：フィクション短編生成

HTTPでPOSTされた STORYメールの件名を受け取り、
ナレッジグラフのブログシードからフィクション短編を生成して
はてなブログに下書き投稿する。

処理フロー:
  1. リクエストから件名を取得
  2. Cloud Storageからナレッジグラフを読込
  3. ブログシードからテーマを抽出
  4. Geminiでフィクション短編を生成
  5. 自己レビューと修正
  6. はてなブログに下書き投稿
  7. Cloud Storageに保存
"""
import os
import json
import re
from datetime import datetime

import functions_framework

import gcs_io
import story_writer
import hatena_publisher


@functions_framework.http
def process_story(request):
    """HTTPで呼ばれる小説処理エントリポイント。"""

    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Content-Type, X-Pomera-Internal-Token",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    try:
        auth_error = _auth_error(request)
        if auth_error:
            return auth_error

        data = request.get_json(silent=True)
        if not data:
            return json.dumps({"error": "リクエストボディが空です"}), 400

        subject = data.get("subject", "")
        body = data.get("body", "")

        print(f"📖 小説リクエストを受信: 件名={subject}")

        # ── ナレッジグラフを読込 ──
        graph_data = gcs_io.load_json_from_gcs("knowledge_graph.jsonld")

        # ── コンテキスト抽出 ──
        context = ""
        if graph_data:
            context = story_writer.extract_relevant_context(graph_data)

        # ── 草案テキストの決定 ──
        # bodyがあればそれを使い、なければナレッジグラフのblog_seedsから取得
        draft_text = body if body else ""

        if not draft_text and graph_data:
            # 最新の日記ノードからblog_seedsを探す
            diary_nodes = [n for n in graph_data.get("nodes", [])
                          if n.get("type") == "日記" and n.get("analysis_content")]
            if diary_nodes:
                diary_nodes.sort(key=lambda n: n.get("date", ""), reverse=True)
                latest = diary_nodes[0]
                try:
                    analysis = json.loads(latest["analysis_content"]) if isinstance(latest["analysis_content"], str) else latest["analysis_content"]
                    seeds = analysis.get("blog_seeds", [])
                    if seeds:
                        seed = seeds[0]
                        draft_text = (
                            f"テーマ: {seed.get('title', '')}\n"
                            f"ジャンル: {seed.get('genre', '')}\n"
                            f"トーン: {seed.get('tone', '')}\n"
                            f"伝えたいこと: {seed.get('core_message', '')}\n"
                            f"エピソード: {seed.get('story_seed', '')}\n"
                            f"読後感: {seed.get('reader_feeling', '')}"
                        )
                except Exception as e:
                    print(f"⚠️ blog_seedsの解析に失敗: {e}")

        if not draft_text:
            return json.dumps({"error": "小説の草案が見つかりません"}), 400

        # ── フィクション短編を生成 ──
        print("🔄 Geminiでフィクション短編を生成中...")
        fiction_data = story_writer.generate_fiction(draft_text, context)

        if not fiction_data:
            return json.dumps({"error": "小説の生成に失敗しました"}), 500

        title = fiction_data.get("title", "無題")
        story_body = fiction_data.get("body", "")
        categories = fiction_data.get("categories", ["フィクション", "短編小説"])

        print(f"✅ 小説生成完了: {title}")

        # ── はてなブログに下書き投稿 ──
        hatena_url = None
        try:
            result = hatena_publisher.post_to_hatena(
                title=title,
                content=story_body,
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

        md_content = f"---\ntitle: {title}\ncategories: {json.dumps(categories, ensure_ascii=False)}\ndate: {datetime.now().isoformat()}\n---\n\n{story_body}"
        gcs_io.save_text_to_gcs(f"stories/{date_str}_{safe_title}.md", md_content)

        meta = {
            "title": title,
            "categories": categories,
            "generated_at": datetime.now().isoformat(),
            "source_subject": subject,
            "hatena_url": hatena_url,
        }
        gcs_io.save_json_to_gcs(f"stories/{date_str}_{safe_title}_meta.json", meta)

        # ── GitHubにも保存 ──
        gcs_io.push_file_to_github(
            f"blog_ready/{date_str}_{safe_title}.md",
            md_content,
            f"Auto-sync: Story {title} [skip ci]"
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


def _auth_error(request):
    expected = os.environ.get("POMERA_INTERNAL_TOKEN")
    if expected and request.headers.get("X-Pomera-Internal-Token") != expected:
        return json.dumps({"error": "unauthorized"}), 401
    return None
