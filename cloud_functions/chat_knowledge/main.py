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
MODEL = "gemini-2.5-flash"

# Vertex AI クライアント（IAM認証、APIキー不要）
client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

# インスタンス内キャッシュ（Cloud Functionの同一インスタンスで再利用）
_cache_name: str | None = None
_cache_expires_at: datetime.datetime | None = None
_graph_last_updated: datetime.datetime | None = None  # GCSのグラフ更新時刻


def _get_or_create_cache(graph_text: str, graph_updated_at: datetime.datetime | None = None) -> str:
    """コンテキストキャッシュを取得または作成する。グラフが更新されていれば再作成。"""
    global _cache_name, _cache_expires_at, _graph_last_updated

    now = datetime.datetime.now(datetime.timezone.utc)

    # グラフが更新されていたらキャッシュを無効化
    if graph_updated_at and _graph_last_updated and graph_updated_at > _graph_last_updated:
        print(f"🔄 グラフが更新されました（{graph_updated_at}）。キャッシュを再作成します")
        _cache_name = None

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
- 語りかけは「〜ですね」「〜でしょうか」など柔らかいトーンで
- ノードのID（MonsterDrawingやHighQuality_MonsterDrawingなどの英語名称）はそのまま読み上げず、detailフィールドの日本語の説明で言及する"""

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
    _cache_expires_at = now + datetime.timedelta(hours=1, minutes=50)
    _graph_last_updated = graph_updated_at or now
    print(f"✅ キャッシュ作成完了: {_cache_name}")
    return _cache_name


def _load_graph_from_gcs() -> tuple[str, datetime.datetime | None]:
    """GCSからナレッジグラフを読み込んでテキストに変換する。更新時刻も返す。"""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET)

        for path in ["master_graph.json", "knowledge_graph.jsonld"]:
            blob = bucket.blob(path)
            if blob.exists():
                blob.reload()  # メタデータ最新化
                updated_at = blob.updated  # datetime
                content = blob.download_as_text(encoding="utf-8")
                graph = json.loads(content)
                print(f"✅ GCSから読み込み: {path} ({len(content)//1024}KB) updated={updated_at}")
                return _graph_to_text(graph), updated_at

    except Exception as e:
        print(f"⚠️ GCS読み込みエラー: {e}")

    return "ナレッジグラフのデータが見つかりませんでした。", None


def _graph_to_text(graph: dict) -> str:
    """ナレッジグラフをGeminiが読みやすいテキスト形式に変換する。"""
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    lines = [
        f"## ナレッジグラフ概要",
        f"ノード数: {len(nodes)} / エッジ数: {len(edges)}",
        ""
    ]

    # --- 日付別ノード一覧（直近14日） ---
    # 日付を持つノードを日付ごとにまとめ、新しい順に表示
    dated_nodes: dict[str, list] = {}
    for n in nodes:
        d = n.get("date", "")
        if d and len(d) == 10:  # YYYY-MM-DD形式のみ
            dated_nodes.setdefault(d, []).append(n)

    recent_dates = sorted(dated_nodes.keys(), reverse=True)[:14]
    if recent_dates:
        lines.append("## 日付別の記録（新しい順）")
        for date in recent_dates:
            lines.append(f"\n### {date}")
            for n in dated_nodes[date]:
                t = n.get("type", "")
                detail = n.get("detail", "") or n.get("id", "")
                status = n.get("status", "")
                status_str = f" [{status}]" if status else ""
                lines.append(f"- [{t}]{status_str} {detail}")

    # --- Gravityノード（未解決の重要課題） ---
    gravity_nodes = sorted(
        [n for n in nodes if n.get("gravity", 0) > 0],
        key=lambda n: n.get("gravity", 0), reverse=True
    )
    if gravity_nodes:
        lines.append("\n## 重力ノード（未解決の制約・課題）")
        for n in gravity_nodes[:20]:
            g = n.get("gravity", 0)
            detail = n.get("detail", "") or n.get("id", "")
            date = n.get("date", "")
            date_str = f" ({date})" if date else ""
            lines.append(f"- [{n.get('type','')}]{date_str} {detail} (G={g})")

    # --- 重要ノード（重み上位、ただし日付があるものは日付を付記） ---
    important = sorted(nodes, key=lambda n: n.get("weight", 0), reverse=True)[:30]
    lines.append("\n## 重要ノード（重み上位）")
    for n in important:
        t = n.get("type", "")
        detail = n.get("detail", "") or n.get("id", "")
        w = n.get("weight", 0)
        date = n.get("date", "")
        date_str = f" ({date})" if date else ""
        lines.append(f"- [{t}]{date_str} {detail} (W={w})")

    # --- エッジ（関係性） ---
    if edges:
        lines.append("\n## 主要な関係性")
        for e in edges[:50]:
            src = e.get("source", "")
            tgt = e.get("target", "")
            rel = e.get("relation", e.get("type", ""))
            lines.append(f"- {src} → {rel} → {tgt}")

    # --- タイプ別統計 ---
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
        graph_text, graph_updated_at = _load_graph_from_gcs()
        cache_name = _get_or_create_cache(graph_text, graph_updated_at)

        # 今日の日付を取得してコンテキストに追加
        today = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))  # JST
        ).strftime("%Y年%m月%d日")

        # 会話履歴を構築（最大6往復）
        chat_contents = []

        # 先頭に「今日の日付」を注入（キャッシュは静的なため毎回追加が必要）
        chat_contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=f"【現在の日付】今日は {today} です。グラフのノードに記録日（date）が含まれる場合はその日付を参照し、古いタスクと最新のものを区別して回答してください。")]
            )
        )
        chat_contents.append(
            types.Content(role="model", parts=[types.Part(text="はい、了解しました。今日は" + today + "ですね。最新のデータを優先して回答します。")])
        )

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
                max_output_tokens=4096,
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
