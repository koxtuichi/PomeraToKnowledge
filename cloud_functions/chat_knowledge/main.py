"""
main.py — Cloud Function：ナレッジグラフ対話チャット（Vertex AI版）

Vertex AI + 明示的コンテキストキャッシュを使用。
- APIキー不要（IAM認証）
- ナレッジグラフ全体をコンテキストキャッシュとして保持（2時間TTL）
- 429エラーなし（Vertex AIは従量課金でレート制限が緩い）
"""
import os
import json
import datetime
import functions_framework

from google.cloud import storage
from google import genai
from google.genai import types

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "pomeradriven")
LOCATION = "us-central1"  # コンテキストキャッシュ対応リージョン
GCS_BUCKET = os.environ.get("GCS_BUCKET", "pomera-knowledge-data")
MODEL = "gemini-2.0-flash-001"

# Vertex AI クライアント（IAM認証、APIキー不要）
client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

# インスタンス内キャッシュ（Cloud Functionの同一インスタンスで再利用）
_cache_name: str | None = None
_cache_expires_at: datetime.datetime | None = None


def _get_or_create_cache(graph_text: str) -> str:
    """コンテキストキャッシュを取得または作成する。"""
    global _cache_name, _cache_expires_at

    now = datetime.datetime.now(datetime.timezone.utc)

    # 有効なキャッシュがあれば再利用
    if _cache_name and _cache_expires_at and now < _cache_expires_at:
        print(f"✅ キャッシュ再利用: {_cache_name}")
        return _cache_name

    # 新しいキャッシュを作成（TTL 2時間）
    print("🔄 新しいコンテキストキャッシュを作成中...")
    system_instruction = """あなたはユーザーの個人ナレッジグラフのAIアシスタントです。
ユーザーの日記・思考・行動の記録をもとに、親身になって回答してください。

以下のナレッジグラフはユーザーが日々ポメラで記録した思考・日記・タスク・人間関係などを
グラフ構造で表したものです。このデータを最大限活用して質問に答えてください。

回答ルール:
- ナレッジグラフのデータに基づいて具体的に答える
- データにない場合は正直に「記録には見当たりません」と伝える
- 200〜400文字で簡潔に答える
- 必要に応じてリスト形式を使う
- 語りかけは「〜ですね」「〜でしょうか」など柔らかいトーンで"""

    cache = client.caches.create(
        model=MODEL,
        config=types.CreateCachedContentConfig(
            system_instruction=system_instruction,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"ナレッジグラフデータ:\n{graph_text}")]
                )
            ],
            ttl="7200s",  # 2時間
            display_name="knowledge-graph-cache",
        )
    )

    _cache_name = cache.name
    _cache_expires_at = now + datetime.timedelta(hours=1, minutes=50)  # 余裕を持って1時間50分
    print(f"✅ キャッシュ作成完了: {_cache_name}")
    return _cache_name


def _load_graph_from_gcs() -> str:
    """GCSからナレッジグラフを読み込んでテキストに変換する。"""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET)

        for path in ["master_graph.json", "knowledge_graph.jsonld"]:
            blob = bucket.blob(path)
            if blob.exists():
                content = blob.download_as_text(encoding="utf-8")
                graph = json.loads(content)
                print(f"✅ GCSから読み込み: {path} ({len(content)//1024}KB)")
                return _graph_to_text(graph)

    except Exception as e:
        print(f"⚠️ GCS読み込みエラー: {e}")

    return "ナレッジグラフのデータが見つかりませんでした。"


def _graph_to_text(graph: dict) -> str:
    """ナレッジグラフをGeminiが読みやすいテキスト形式に変換する。"""
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    lines = [
        f"## ナレッジグラフ概要",
        f"ノード数: {len(nodes)} / エッジ数: {len(edges)}",
        ""
    ]

    # Gravityノード（重力が高い＝未解決の重要課題）
    gravity_nodes = sorted(
        [n for n in nodes if n.get("gravity", 0) > 0],
        key=lambda n: n.get("gravity", 0), reverse=True
    )
    if gravity_nodes:
        lines.append("\n## 重力ノード（未解決の制約・課題）")
        for n in gravity_nodes[:20]:
            g = n.get("gravity", 0)
            detail = n.get("detail", "")
            lines.append(f"- [{n.get('type','')}] {n.get('id','')} (G={g}): {detail}")

    # 重要ノード（重み上位）
    important = sorted(nodes, key=lambda n: n.get("weight", 0), reverse=True)[:30]
    lines.append("\n## 重要ノード（重み上位）")
    for n in important:
        t = n.get("type", "")
        nid = n.get("id", "")
        detail = n.get("detail", "")
        w = n.get("weight", 0)
        lines.append(f"- [{t}] {nid} (W={w}): {detail}")

    # エッジ（関係性）
    if edges:
        lines.append("\n## 主要な関係性")
        for e in edges[:50]:
            src = e.get("source", "")
            tgt = e.get("target", "")
            rel = e.get("relation", e.get("type", ""))
            lines.append(f"- {src} → {rel} → {tgt}")

    # タイプ別統計
    type_counts: dict[str, int] = {}
    for n in nodes:
        t = n.get("type", "不明")
        type_counts[t] = type_counts.get(t, 0) + 1
    lines.append("\n## タイプ別統計")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {t}: {count}件")

    return "\n".join(lines)


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

        # GCSからグラフを読み込み、キャッシュを取得/作成
        graph_text = _load_graph_from_gcs()
        cache_name = _get_or_create_cache(graph_text)

        # 会話履歴を構築（最大6往復）
        chat_contents = []
        for h in history[-12:]:  # 6往復 = 12メッセージ
            role = "user" if h.get("role") == "user" else "model"
            chat_contents.append(
                types.Content(role=role, parts=[types.Part(text=h["content"])])
            )
        # 現在の質問を追加
        chat_contents.append(
            types.Content(role="user", parts=[types.Part(text=question)])
        )

        # Vertex AI でキャッシュを使って回答生成
        response = client.models.generate_content(
            model=MODEL,
            contents=chat_contents,
            config=types.GenerateContentConfig(
                cached_content=cache_name,
                temperature=0.7,
                max_output_tokens=800,
            )
        )

        answer = response.text.strip()
        return (
            json.dumps({"answer": answer}, ensure_ascii=False),
            200,
            headers
        )

    except Exception as e:
        import traceback
        print(f"❌ エラー: {e}\n{traceback.format_exc()}")
        return (json.dumps({"error": str(e)}), 500, headers)
