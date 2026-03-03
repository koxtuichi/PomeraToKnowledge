"""
main.py — Cloud Function エントリポイント：ナレッジグラフ対話チャット

GitHub Pagesからのチャットリクエストを受け取り、
GCSからナレッジグラフを読み込んでGemini APIで回答を生成する。
"""
import os
import json

import functions_framework
from google.cloud import storage
import google.generativeai as genai

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "pomera-knowledge-data")
genai.configure(api_key=GOOGLE_API_KEY)

# GCSからナレッジグラフをキャッシュ（同一インスタンス内で再利用）
_cached_graph = None


def _load_graph_from_gcs() -> dict:
    """GCSからナレッジグラフを読み込む。"""
    global _cached_graph
    if _cached_graph is not None:
        return _cached_graph

    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        # master_graph.jsonを優先、なければknowledge_graph.jsonld
        for path in ["master_graph.json", "knowledge_graph.jsonld"]:
            blob = bucket.blob(path)
            if blob.exists():
                content = blob.download_as_text(encoding="utf-8")
                _cached_graph = json.loads(content)
                print(f"✅ GCSからグラフを読み込み: {path}")
                return _cached_graph
    except Exception as e:
        print(f"⚠️ GCS読み込みエラー: {e}")

    return {}


@functions_framework.http
def chat_knowledge(request):
    """GitHub PagesのチャットUIからHTTPで呼ばれるエントリポイント。"""

    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }

    if request.method == "OPTIONS":
        return ("", 204, headers)

    try:
        data = request.get_json(silent=True)
        if not data:
            return (json.dumps({"error": "リクエストが空です"}), 400, headers)

        question = data.get("question", "").strip()
        history = data.get("history", [])

        if not question:
            return (json.dumps({"error": "質問が空です"}), 400, headers)

        # GCSからグラフを読み込み
        graph_data = _load_graph_from_gcs()

        # コンテキストを構築（サイズ制限あり）
        context = _build_context(graph_data)

        # Geminiで回答生成
        answer = _generate_answer(question, context, history)

        return (
            json.dumps({"answer": answer}, ensure_ascii=False),
            200,
            headers
        )

    except Exception as e:
        import traceback
        print(f"❌ エラー: {e}\n{traceback.format_exc()}")
        return (json.dumps({"error": str(e)}), 500, headers)


def _build_context(graph_data: dict) -> str:
    """ナレッジグラフをチャット用コンテキスト文字列に変換する。最大15,000文字。"""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    if not nodes:
        return "ナレッジグラフのデータがありません。"

    lines = [f"## ナレッジグラフ概要\n- ノード数: {len(nodes)}\n- エッジ数: {len(edges)}\n"]

    # 日記ノード（最新8件の分析内容）
    diary_nodes = sorted(
        [n for n in nodes if n.get("type") in ("日記", "diary")],
        key=lambda n: n.get("date", ""),
        reverse=True
    )[:8]

    if diary_nodes:
        lines.append("## 最近の日記分析")
        for n in diary_nodes:
            date = n.get("date", "不明")
            analysis = (n.get("analysis_content", "") or n.get("detail", ""))[:400]
            if analysis:
                lines.append(f"\n### {date}\n{analysis}")

    # Gravityノード（重力上位10件）
    gravity_nodes = sorted(
        [n for n in nodes if n.get("gravity", 0) > 0],
        key=lambda n: n.get("gravity", 0),
        reverse=True
    )[:10]
    if gravity_nodes:
        lines.append("\n## 重力の高いノード")
        for n in gravity_nodes:
            lines.append(f"- {n.get('id', '')} (G={n.get('gravity', 0)}): {n.get('detail', '')[:60]}")

    # 重要ノード上位15件
    important_nodes = sorted(nodes, key=lambda n: n.get("weight", 0), reverse=True)[:15]
    lines.append("\n## 重要度上位ノード")
    for n in important_nodes:
        lines.append(f"- [{n.get('type', '')}] {n.get('id', '')}: {n.get('detail', '')[:60]}")

    # タイプ別統計
    type_counts = {}
    for n in nodes:
        t = n.get("type", "不明")
        type_counts[t] = type_counts.get(t, 0) + 1
    lines.append("\n## タイプ別統計")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1])[:8]:
        lines.append(f"- {t}: {count}件")

    context = "\n".join(lines)

    # 15,000文字に収める
    if len(context) > 15000:
        context = context[:15000] + "\n...(省略)"

    return context


def _generate_answer(question: str, context: str, history: list) -> str:
    """Gemini APIで回答を生成する。"""
    model = genai.GenerativeModel("gemini-2.0-flash")

    system_prompt = f"""あなたはユーザーの個人ナレッジグラフのAIアシスタントです。
ユーザーの日記や思考の記録をもとに、親身になって回答してください。

{context}

回答ルール:
- データに基づいて具体的に答える
- データにない場合は正直に伝える
- 200〜400文字で簡潔に
- 語りかけは柔らかいトーンで"""

    chat_history = []
    for h in history[-6:]:
        if h.get("role") == "user":
            chat_history.append({"role": "user", "parts": [h["content"]]})
        elif h.get("role") == "assistant":
            chat_history.append({"role": "model", "parts": [h["content"]]})

    chat = model.start_chat(history=chat_history)
    response = chat.send_message(f"{system_prompt}\n\nユーザーの質問: {question}")
    return response.text.strip()

