"""
main.py — Cloud Function エントリポイント：ナレッジグラフ対話チャット

GitHub Pagesからのチャットリクエストを受け取り、
ナレッジグラフをコンテキストにGemini APIで回答を生成する。
"""
import os
import json

import functions_framework
import google.generativeai as genai

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
genai.configure(api_key=GOOGLE_API_KEY)


@functions_framework.http
def chat_knowledge(request):
    """GitHub PagesのチャットUIからHTTPで呼ばれるエントリポイント。"""

    # CORS対応（GitHub Pagesからのリクエストを許可）
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
        graph_data = data.get("graph_data", {})
        history = data.get("history", [])  # 会話履歴

        if not question:
            return (json.dumps({"error": "質問が空です"}), 400, headers)

        # ナレッジグラフのコンテキストを構築
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
    """ナレッジグラフをチャット用のコンテキスト文字列に変換する。"""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    if not nodes:
        return "ナレッジグラフのデータがありません。"

    lines = [f"## ナレッジグラフ概要\n- ノード数: {len(nodes)}\n- エッジ数: {len(edges)}\n"]

    # 日記ノード（最新10件）
    diary_nodes = sorted(
        [n for n in nodes if n.get("type") in ("日記", "diary")],
        key=lambda n: n.get("date", ""),
        reverse=True
    )[:10]

    if diary_nodes:
        lines.append("## 最近の日記エントリ")
        for n in diary_nodes:
            date = n.get("date", "不明")
            analysis = n.get("analysis_content", "")
            lines.append(f"\n### {date}")
            if analysis:
                # 長すぎる分析は短縮
                lines.append(analysis[:600] + ("..." if len(analysis) > 600 else ""))

    # Gravity（制約）ノード
    gravity_nodes = [n for n in nodes if n.get("gravity", 0) > 0]
    gravity_nodes.sort(key=lambda n: n.get("gravity", 0), reverse=True)
    if gravity_nodes:
        lines.append("\n## 重力の高いノード（未解決の制約）")
        for n in gravity_nodes[:10]:
            lines.append(f"- {n.get('id', '')} (gravity={n.get('gravity', 0)}) — {n.get('detail', '')[:80]}")

    # 重要ノード（重み上位）
    important_nodes = sorted(nodes, key=lambda n: n.get("weight", 0), reverse=True)[:20]
    lines.append("\n## 重要度の高いノード")
    for n in important_nodes:
        lines.append(f"- [{n.get('type', '')}] {n.get('id', '')}: {n.get('detail', '')[:80]}")

    # タイプ別の統計
    type_counts = {}
    for n in nodes:
        t = n.get("type", "不明")
        type_counts[t] = type_counts.get(t, 0) + 1

    lines.append("\n## ノードタイプ別統計")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1])[:10]:
        lines.append(f"- {t}: {count}件")

    return "\n".join(lines)


def _generate_answer(question: str, context: str, history: list) -> str:
    """Gemini APIで回答を生成する。"""
    model = genai.GenerativeModel("gemini-2.0-flash")

    # システムプロンプト
    system_prompt = f"""あなたはユーザーの個人ナレッジグラフのAIアシスタントです。
ユーザーの日記や思考の記録をもとに、親身になって回答してください。

以下はユーザーのナレッジグラフのデータです：

{context}

回答ルール:
- ユーザーの思考や記録に基づいて具体的に答える
- データにない場合は「記録には見当たりません」と正直に伝える
- 200〜400文字程度で簡潔に答える
- 必要に応じてリスト形式を使う
- ユーザーへの語りかけは「〜ですね」「〜でしょうか」など柔らかいトーンで
"""

    # 会話履歴を構築
    chat_history = []
    for h in history[-6:]:  # 直近6往復まで
        if h.get("role") == "user":
            chat_history.append({"role": "user", "parts": [h["content"]]})
        elif h.get("role") == "assistant":
            chat_history.append({"role": "model", "parts": [h["content"]]})

    # チャットセッション開始
    chat = model.start_chat(history=chat_history)
    response = chat.send_message(f"{system_prompt}\n\nユーザーの質問: {question}")

    return response.text.strip()
