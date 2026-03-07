"""
main.py — Cloud Function エントリポイント

GASからHTTPでPOSTされたリクエストを受け取り、日記処理パイプラインを実行する。
既存の llm_graph_builder.py と graph_merger.py をインポートして処理を行う。

処理フロー:
  1. リクエストから日記本文と件名を取得
  2. Cloud Storageからマスターグラフを読込
  3. Geminiでグラフ抽出
  4. セマンティック重複の解決
  5. マスターグラフにマージ
  6. Antigravity分析
  7. Cloud Storageに結果保存
  8. GitHubにgraph_data.jsをpush（Pages更新用）
"""
import os
import json
import re
from datetime import datetime

import functions_framework

import gcs_io
import llm_graph_builder
import graph_merger


@functions_framework.http
def process_diary(request):
    """GASからHTTPで呼ばれるメインエントリポイント。"""

    # CORS対応
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    try:
        data = request.get_json(silent=True)
        if not data:
            return json.dumps({"error": "リクエストボディが空です"}), 400

        diary_text = data.get("body", "")
        subject = data.get("subject", "")

        if not diary_text:
            return json.dumps({"error": "日記本文が空です"}), 400

        print(f"📬 日記を受信: 件名={subject}, 文字数={len(diary_text)}")

        # ── 日付の抽出 ──
        current_date_str = _extract_date(subject)
        print(f"📅 日付: {current_date_str}")

        # ── 日記ファイルをCloud Storageに保存 ──
        diary_filename = f"diary/{_make_diary_filename(subject, current_date_str)}"
        gcs_io.save_text_to_gcs(diary_filename, diary_text)

        # ── マスターグラフ読込 ──
        print("📂 マスターグラフをCloud Storageから読み込み中...")
        master_graph = gcs_io.load_json_from_gcs("knowledge_graph.jsonld")
        if not master_graph:
            master_graph = {
                "nodes": [],
                "edges": [],
                "metadata": {
                    "schema_version": "2.0-antigravity",
                    "description": "タスクの重力モデルに基づく知識グラフ"
                }
            }

        # ── 役割定義の読込 ──
        role_def = gcs_io.load_text_from_gcs("role_definition.txt")
        if role_def:
            llm_graph_builder.ROLE_DEF_CACHE = role_def

        # ── コンテキスト作成 ──
        master_context_str = llm_graph_builder.get_master_context(master_graph)

        # ── Geminiでグラフ抽出 ──
        print("🔄 Geminiでグラフを抽出中...")
        daily_graph = llm_graph_builder.extract_graph(diary_text, master_context_str)

        # ── 日記ノードとメタデータの追加 ──
        daily_graph = _add_diary_metadata(daily_graph, current_date_str, diary_filename)

        # ── セマンティック重複の解決 ──
        daily_graph = llm_graph_builder.resolve_semantic_duplicates(daily_graph, master_graph)

        # ── 日次グラフをCloud Storageに保存 ──
        gcs_io.save_json_to_gcs("daily_graph.json", daily_graph)

        # ── マスターグラフにマージ ──
        print("🔄 マスターグラフへマージ中...")
        updated_master = graph_merger.merge_graphs(master_graph, daily_graph)

        # ── Antigravity分析 ──
        analysis_text = ""
        diary_node_id = f"日記:{current_date_str}"
        current_diary_node = next(
            (n for n in updated_master.get("nodes", []) if n["id"] == diary_node_id),
            None
        )
        if current_diary_node:
            print("🔍 Antigravity分析を実行中...")
            analysis_text = llm_graph_builder.analyze_updated_state(
                updated_master, current_diary_node, diary_text
            )
            current_diary_node["analysis_content"] = analysis_text

        # ── マスターグラフをCloud Storageに保存 ──
        gcs_io.save_json_to_gcs("knowledge_graph.jsonld", updated_master)

        # ── 分析レポートをCloud Storageに保存 ──
        if analysis_text:
            report = (
                f"# Antigravity分析レポート ({datetime.now().date()})\n\n"
                f"**分析対象:** {current_date_str} の日記\n\n"
                f"{analysis_text}"
            )
            gcs_io.save_text_to_gcs("daily_report.md", report)

        # ── GitHubにgraph_data.jsをpush ──
        print("📤 GitHub Pagesを更新中...")
        graph_data_js = gcs_io.generate_graph_data_js(updated_master)
        gcs_io.push_file_to_github(
            "graph_data.js",
            graph_data_js,
            f"Auto-sync: Graph Update {current_date_str} [skip ci]"
        )

        # knowledge_graph.jsonldもGitHubに保存（バージョン管理用）
        gcs_io.push_file_to_github(
            "knowledge_graph.jsonld",
            json.dumps(updated_master, ensure_ascii=False, indent=2),
            f"Auto-sync: JSONLD Update {current_date_str} [skip ci]"
        )

        # 日記ファイルをGitHubにも保存
        gcs_io.push_file_to_github(
            diary_filename,
            diary_text,
            f"Auto-sync: Diary {current_date_str} [skip ci]"
        )

        # 分析レポートをGitHubにも保存
        if analysis_text:
            report_filename = f"reports/{current_date_str.replace('-', '')}_report.md"
            gcs_io.push_file_to_github(
                report_filename,
                report,
                f"Auto-sync: Report {current_date_str} [skip ci]"
            )

        # ── SNS::タグの検出と処理 ──
        sns_posts = _extract_sns_tags(diary_text)
        sns_queue_ids = []
        if sns_posts:
            print(f"📱 SNS::タグを {len(sns_posts)} 件検出")
            for i, sns_text in enumerate(sns_posts):
                try:
                    generated = _generate_sns_post(sns_text)
                    queue_id = f"{current_date_str.replace('-', '')}_{i+1}"
                    queue_item = {
                        "id": queue_id,
                        "original_text": sns_text,
                        "generated_post": generated,
                        "created_at": datetime.now().isoformat(),
                        "approved_at": None,
                        "posted_at": None,
                        "threads_post_id": None,
                    }
                    gcs_io.save_json_to_gcs(f"sns_queue/pending/{queue_id}.json", queue_item)
                    sns_queue_ids.append(queue_id)
                    print(f"  ✅ SNS投稿キューに追加: {queue_id}")
                except Exception as e:
                    print(f"  ⚠️ SNS投稿の生成に失敗: {e}")

        result = {
            "status": "ok",
            "date": current_date_str,
            "nodes_added": len(daily_graph.get("nodes", [])),
            "edges_added": len(daily_graph.get("edges", [])),
            "total_nodes": len(updated_master.get("nodes", [])),
            "total_edges": len(updated_master.get("edges", [])),
        }
        if sns_queue_ids:
            result["sns_pending"] = sns_queue_ids
            result["sns_generated_posts"] = []
            for qid in sns_queue_ids:
                item = gcs_io.load_json_from_gcs(f"sns_queue/pending/{qid}.json")
                if item:
                    result["sns_generated_posts"].append({
                        "id": qid,
                        "original": item["original_text"],
                        "generated": item["generated_post"],
                    })

        print(f"✅ 処理完了: {json.dumps(result, ensure_ascii=False)}")
        return json.dumps(result, ensure_ascii=False), 200

    except Exception as e:
        import traceback
        error_msg = f"❌ 処理中にエラー: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        return json.dumps({"error": str(e)}), 500


def _extract_date(subject: str) -> str:
    """件名から日付を抽出する。"""
    match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', subject)
    if match:
        y, m, d = match.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}"
    match = re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})', subject)
    if match:
        y, m, d = match.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}"
    return datetime.now().strftime("%Y-%m-%d")


def _make_diary_filename(subject: str, date_str: str) -> str:
    """日記のファイル名を生成する。"""
    safe_subject = re.sub(r'[\\/*?:"<>|]', '', subject)[:50]
    date_prefix = date_str.replace("-", "")
    return f"{date_prefix}_[POMERA]{safe_subject}.txt"


def _add_diary_metadata(daily_graph: dict, current_date_str: str, source_file: str) -> dict:
    """日記ノードとメタデータをdaily_graphに追加する。"""
    now_iso = datetime.now().isoformat()

    daily_graph["metadata"] = {
        "generated_at": now_iso,
        "source_file": source_file,
        "node_count": len(daily_graph.get("nodes", [])),
        "edge_count": len(daily_graph.get("edges", []))
    }

    diary_node_id = f"日記:{current_date_str}"
    user_node_id = "人物:自分"

    # 日記ノードの追加
    if not any(n.get("id") == diary_node_id for n in daily_graph.get("nodes", [])):
        daily_graph.get("nodes", []).append({
            "id": diary_node_id,
            "label": f"{current_date_str}の日記",
            "type": "日記",
            "date": current_date_str,
            "detail": "今日の日記エントリ",
            "first_seen": now_iso,
            "last_seen": now_iso,
            "weight": 1
        })

    # ユーザーノードの追加
    if not any(n.get("id") == user_node_id for n in daily_graph.get("nodes", [])):
        daily_graph.get("nodes", []).append({
            "id": user_node_id,
            "label": "自分",
            "type": "人物",
            "detail": "日記の作成者",
            "first_seen": now_iso,
            "last_seen": now_iso,
            "weight": 1
        })

    # 自分 → 日記 エッジ
    daily_graph.get("edges", []).append({
        "source": user_node_id,
        "target": diary_node_id,
        "type": "関連する",
        "label": "書いた",
        "weight": 1
    })

    # 日記 → 各ノード エッジ（孤立防止）
    for node in daily_graph.get("nodes", []):
        nid = node.get("id")
        if nid in (user_node_id, diary_node_id):
            continue
        edge_exists = any(
            (e.get("source") == diary_node_id and e.get("target") == nid) or
            (e.get("source") == nid and e.get("target") == diary_node_id)
            for e in daily_graph.get("edges", [])
        )
        if not edge_exists:
            daily_graph.get("edges", []).append({
                "source": diary_node_id,
                "target": nid,
                "type": "言及する",
                "label": "言及",
                "weight": 1
            })

    return daily_graph


def _extract_sns_tags(diary_text: str) -> list:
    """日記本文からSNS::タグの内容を全て抽出する。"""
    results = []
    lines = diary_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("SNS::"):
            # SNS::以降のテキストを取得（複数行対応）
            content = line[5:].strip()
            i += 1
            # 次のタグや空行2連続まで後続行も含める
            empty_count = 0
            while i < len(lines):
                next_line = lines[i].strip()
                if next_line.startswith("SNS::") or next_line.startswith("BLOG::") or next_line.startswith("予定::"):
                    break
                if next_line == "":
                    empty_count += 1
                    if empty_count >= 2:
                        break
                else:
                    empty_count = 0
                content += "\n" + next_line
                i += 1
            content = content.strip()
            if content:
                results.append(content)
        else:
            i += 1
    return results


def _generate_sns_post(original_text: str) -> str:
    """Gemini APIでSNS用の投稿文を生成する。

    500文字以内でリーチしやすく校正する。
    """
    prompt = f"""以下のテキストをThreadsに投稿するための文章に校正してください。

元のテキスト:
---
{original_text}
---

ルール:
- 500文字以内に収める（絶対に超えないこと）
- 元の内容の本質と著者の声を保つ
- SNSでのリーチを最大化するよう工夫する
- 最初の1行で読者の興味を引くフックを入れる
- 適切なハッシュタグを2〜3個追加する
- 絵文字は控えめに使う（0〜2個）
- 投稿文のみを返す（説明や引用符は不要）

投稿文:"""

    try:
        result = llm_graph_builder.call_gemini_api(prompt)
        # 500文字制限の強制
        if len(result) > 500:
            result = result[:497] + "..."
        return result.strip()
    except Exception as e:
        print(f"⚠️ SNS投稿の生成に失敗: {e}")
        # フォールバック: 元テキストをそのまま使う
        if len(original_text) > 500:
            return original_text[:497] + "..."
        return original_text
