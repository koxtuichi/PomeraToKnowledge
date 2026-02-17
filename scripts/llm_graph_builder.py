import os
import json
import argparse
from datetime import datetime
import requests
from typing import Dict, Any, List

try:
    import graph_merger
except ImportError:
    print("⚠️  graph_merger module not found. Persistence features will be limited.")

# ── 設定 ──
API_KEY = os.getenv("GOOGLE_API_KEY")
ROLE_DEF_FILE = "role_definition.txt"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# プロンプト定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EXTRACTION_SYSTEM_PROMPT = """
# 役割
あなたは、ユーザーの「分身」を構築するためのナレッジエンジニアです。
日記から、タスク管理を高度化するための「知識グラフの差分」を抽出してください。

# 抽出対象（ノードの種類）

1. **タスク**: 具体的、または抽象的な「やるべきこと」。
   - status: "未着手" / "進行中" / "完了" / "保留"
2. **制約（重力）**: タスクの実行を妨げる要因。
   - 種類: "時間不足" / "疲労" / "技術的課題" / "感情的ブレーキ" / "物理的障害" / "リソース不足" / "その他"
3. **知見**: 試行錯誤から得られた教訓や、将来の資産に繋がりそうな気づき。
4. **感情**: その時の感情。タスクの原動力、または阻害要因になる。
   - sentiment: -1.0 から 1.0 の数値
5. **人物**: 日記に登場する人。
6. **出来事**: 起きた具体的なイベント。
   - status: "予定" / "完了" / "中止"
7. **目標**: 長期的に目指すもの。
   - status: "進行中" / "達成" / "断念"
8. **プロジェクト**: 継続的な取り組み。
9. **概念**: 抽象的な概念や状態。
10. **場所**: 場所。
11. **日記**: 日記エントリそのもの。

# 関係性（エッジの種類）

| 関係名 | 方向 | 意味 |
|--------|------|------|
| 阻害する | 制約 → タスク | この制約がタスクの実行を妨げている |
| 原動力になる | 感情/知見 → タスク | この感情や知見がタスクを推進する力になる |
| 一部である | 知見 → プロジェクト | この知見がプロジェクトの一部を構成する |
| 言及する | 日記 → 各ノード | 日記内で触れたもの |
| 引き起こす | 出来事 → 感情/知見 | 因果関係 |
| 参加する | 人物 → 出来事 | 人物が出来事に参加 |
| 場所で | 出来事 → 場所 | 出来事が起きた場所 |
| 対象にする | タスク → 人物/概念 | タスクの対象 |
| 計画する | プロジェクト → タスク | プロジェクトに属するタスク |
| 解決する | 知見/タスク → 制約 | 制約を解消する手段 |
| 関連する | 任意 → 任意 | その他の関係 |

# 抽出ルール
1. **制約の抽出を重視**: 日記からタスクだけでなく、そのタスクを阻害している「重力」を積極的に見つけてください。
   - 時間がない → 制約「時間不足」→ 阻害する → タスク
   - 疲れている → 制約「疲労」→ 阻害する → タスク
   - やり方がわからない → 制約「技術的課題」→ 阻害する → タスク
   - やる気が出ない → 制約「感情的ブレーキ」→ 阻害する → タスク

2. **感情の原動力を抽出**: ポジティブな感情やモチベーションもグラフに入れてください。

3. **既存タスクとの照合**: コンテキストに「既存のタスク・目標一覧」が提供されます。日記が既存タスクの進捗に言及している場合、新しいノードを作らず既存IDを再利用してください。

4. **タグの付与**: ユーザーが `Task::xxx` や `予定::xxx` のようなタグを使う場合はそのまま解析してください。

5. **全て日本語**: label と detail は必ず日本語で書いてください。

# ノード構造
{
  "id": "種別:一意な名前",
  "label": "表示名（日本語）",
  "type": "タスク/制約/知見/感情/人物/出来事/目標/プロジェクト/概念/場所/日記",
  "detail": "説明（日本語）",
  "status": "該当する場合のみ",
  "sentiment": "感情ノードの場合 -1.0〜1.0",
  "date": "該当する場合 YYYY-MM-DD",
  "category": "役割カテゴリ（エンジニア、父親、夫 など）",
  "tags": ["タグ配列"],
  "constraint_type": "制約ノードの場合: 時間不足/疲労/技術的課題/感情的ブレーキ/物理的障害/リソース不足/その他"
}

# エッジ構造
{
  "source": "ソースノードID",
  "target": "ターゲットノードID",
  "type": "関係名（日本語: 阻害する/原動力になる/一部である 等）",
  "label": "関係の短い説明（日本語）"
}

# 出力形式
以下のJSON形式で出力してください。
{
  "nodes": [...],
  "edges": [...]
}
"""

ANALYSIS_SYSTEM_PROMPT = """
あなたは、ユーザーの「分身」として振る舞う Antigravity アドバイザーです。
ユーザーのナレッジグラフから「タスクにかかっている重力（制約）」と「エネルギー（原動力）」を分析し、
重力を軽減する具体的な提案を行ってください。

# 分析のアプローチ

1. **重力マップの作成**: 各タスクにどんな制約（重力）がかかっているかを整理する
2. **エネルギーの発見**: どんな感情や知見がタスクの原動力になるかを見つける
3. **重力軽減の提案**: 制約を解消・軽減する具体的なアクションを提案する
   - 「やるかやらないか」二択ではなく、「どうすれば重力を軽くできるか」を考える
   - 例: 「副業の重力が強すぎるから、掃除の優先度を下げて、代わりに5分で終わるこの作業をしよう」
   - 例: 「粘着剤を剥がす方法をGeminiで検索して解決する」
   - 例: 「副業が一段落するまで掃除は土曜のみに設定変更しよう」

# 出力フォーマット
出力は必ず以下のJSON形式に従ってください。

{
  "coach_comment": "ユーザーの心に寄り添い、重力と向き合う短いメッセージ（3-5文）",
  "gravity_map": [
    {
      "task": "タスク名",
      "task_id": "タスクのID",
      "constraints": [
        {
          "name": "制約名",
          "type": "時間不足/疲労/技術的課題/感情的ブレーキ/物理的障害/リソース不足",
          "severity": "高/中/低"
        }
      ],
      "energy_sources": [
        {
          "name": "原動力の名前",
          "type": "感情/知見/目標"
        }
      ],
      "net_assessment": "このタスクの重力バランスの総合評価（1文）"
    }
  ],
  "antigravity_actions": [
    {
      "action": "具体的な重力軽減アクション",
      "target_task": "対象タスク",
      "effect": "このアクションで軽減される重力の説明",
      "effort": "5分/30分/1時間/半日"
    }
  ],
  "insights": [
    {
      "finding": "日記やグラフから見つけた気づき",
      "implication": "その気づきが意味すること"
    }
  ],
  "emotion_flow": [
    {
      "emotion": "感情名",
      "sentiment": -1.0,
      "context": "その感情が生じた文脈"
    }
  ],
  "upcoming_schedule": [
    {
      "title": "予定名",
      "date": "YYYY-MM-DD",
      "time": "HH:MM（不明なら null）",
      "category": "本業/副業/家族/個人"
    }
  ],
  "family_digest": {
    "highlights": [
      {
        "member": "家族メンバー名（ROLEtoKNOWLEDGEの役割定義を参照）",
        "event": "出来事や成長の記録",
        "emotion": "関連する感情"
      }
    ],
    "family_todos": ["家族関連のやるべきこと"]
  },
  "blog_seeds": [
    {
      "title": "短編小説の仮タイトル",
      "genre": "日常/仕事/子育て/テクノロジー/人間関係",
      "tone": "ほっこり/シリアス/コミカル/哲学的",
      "story_seed": "物語の種になるエピソードや気づき",
      "core_message": "読者に伝えたいメッセージ",
      "reader_feeling": "読後に残したい感情",
      "readiness": "高/中/低"
    }
  ]
}

# 重要な注意事項
- 「antigravity_actions」では、日記の本文で「買った」「注文した」「完了した」「やった」「済んだ」「実行した」など完了を示す記述があるアクションは提案しないでください。完了済みのアクションを除外し、代わりに新しい重力軽減アクションを提案してください。
  - 前回出力したアクションリストがコンテキストに含まれている場合、日記で完了が確認できたものは除外し、まだ実行されていないものは引き続き提案してください。
- 「upcoming_schedule」には日記やグラフで言及されている「確定している未来の予定」だけを含めてください。過去の予定は含めないでください。
  - 日記中に「予定::2026/02/20 18:00-19:00」のように `予定::` メタデータで日時が記載されている場合は、そこから date と time を正確に抽出してください。
  - time は「18:00-19:00」「18:00」のような形式で記載します。時間が不明な場合のみ null にしてください。
  - 日記本文中に「〇時から」「〇〇時」などの時間記述がある場合も、それを time に含めてください。
- 「family_digest」には ROLEtoKNOWLEDGE の役割定義に記載されている家族メンバーに関する情報を抽出してください。日記に家族の話題がなければ空で構いません。
- 「blog_seeds」にはユーザーの日記から1話完結のフィクション短編小説の着想を提案してください。星新一のショートショートのような、匿名的で寓話的な物語です。ユーザーの体験をそのまま書くのではなく、テーマや感情を抽出して架空の物語にする前提です。readiness が「高」なものは、感情やエピソードが十分に濃く、すぐに執筆できるものです。

言語: 日本語。
JSON以外のテキストは一切含めないでください。
"""

RESOLUTION_SYSTEM_PROMPT = """
You are a Data Consistency Expert.
Your task is to identify semantic duplicates between a list of "New Nodes" and "Existing Nodes" in a Knowledge Graph.

### Rules
1. **Strict Semantic Matching**: Only match nodes that refer to the EXACT SAME concept, entity, or event, despite minor wording differences.
   - Example 1: "GitHub Actionsの制約" (New) == "GitHub Actionsの制限" (Existing) -> MATCH
   - Example 2: "ポメラDM250" (New) == "ポメラ" (Existing) -> NO MATCH (Specific vs General) -> UNLESS context implies identity.
   - Example 3: "妻" (New) == "さやか" (Existing) -> MATCH (if context establishes this).
   - Example 4: "Monster Design" (New) == "Monster Design Practice" (Existing) -> MATCH

2. **Output Format**: JSON object mapping { "new_node_id": "existing_node_id" }.
   - Only include pairs where a match is found.
   - If no matches, return generic empty JSON `{}`.
   - The key is the ID of the NEW node, the value is the ID of the EXISTING node.

3. Consider node 'type' as a strong hint. Distinct types (e.g., Place vs Person) usually don't match.
"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ユーティリティ関数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_role_definition() -> str:
    """ユーザー定義の役割定義ファイルを読み込む。"""
    if os.path.exists(ROLE_DEF_FILE):
        try:
            with open(ROLE_DEF_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                return f"\n### ユーザー定義の役割\n{content}\n"
        except Exception as e:
            print(f"⚠️ 役割定義の読み込みに失敗: {e}")
    return ""


def call_gemini_api(prompt: str, model: str = "gemini-3-flash-preview", response_mime_type: str = "text/plain", max_retries: int = 3) -> str:
    if not API_KEY:
        raise ValueError("GOOGLE_API_KEY is not set.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    params = {"key": API_KEY}
    headers = {"Content-Type": "application/json"}

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": response_mime_type}
    }

    for attempt in range(max_retries + 1):
        response = requests.post(url, headers=headers, json=data, params=params)

        if response.status_code == 200:
            break
        elif response.status_code == 429 and attempt < max_retries:
            wait_time = 30 * (2 ** attempt)  # 30秒, 60秒, 120秒
            print(f"⏳ レートリミット到達。{wait_time}秒後にリトライします... ({attempt + 1}/{max_retries})")
            import time
            time.sleep(wait_time)
        else:
            raise Exception(f"API Error: {response.status_code} - {response.text}")

    result = response.json()
    try:
        if "candidates" in result and result["candidates"]:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            print(f"DEBUG: Empty candidates in response: {result}")
            return "{}"
    except (KeyError, IndexError):
        raise Exception(f"Unexpected API response format: {result}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# グラフ抽出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_graph(text: str, context_str: str = "") -> Dict[str, Any]:
    role_def = get_role_definition()
    full_context = f"{context_str}\n{role_def}"

    prompt = f"""
    {EXTRACTION_SYSTEM_PROMPT}

    {full_context}

    ### ユーザーの日記
    {text}
    """
    print("🔄 グラフを抽出中...")
    json_text = call_gemini_api(prompt, model="gemini-3-flash-preview", response_mime_type="application/json")
    return json.loads(json_text)


def get_master_context(master_graph: Dict[str, Any]) -> str:
    """マスターグラフから文脈情報を抽出する。"""
    nodes = master_graph.get("nodes", [])

    active_goals = [n for n in nodes if n.get("type") == "目標" and n.get("status") in ["進行中", "Active"]]
    active_tasks = [n for n in nodes if n.get("type") == "タスク" and n.get("status") not in ["完了", "Completed"]]
    constraints = [n for n in nodes if n.get("type") == "制約"]
    scheduled_events = [n for n in nodes if n.get("type") == "出来事" and n.get("status") in ["予定", "Scheduled"]]

    context_str = "### マスターグラフの文脈\n"

    if active_goals:
        context_str += "**進行中の目標:**\n"
        for g in active_goals:
            context_str += f"- {g.get('label')}: {g.get('detail')}\n"

    if active_tasks:
        context_str += "\n**既存のタスク:**\n"
        for t in active_tasks:
            context_str += f"- [ID: {t.get('id')}] {t.get('label')}: {t.get('detail', '')}\n"

    if constraints:
        context_str += "\n**既知の制約（重力）:**\n"
        for c in constraints:
            context_str += f"- {c.get('label')}: {c.get('detail', '')}\n"

    if scheduled_events:
        context_str += "\n**予定されているイベント:**\n"
        for e in scheduled_events:
            date = e.get("date", "日付不明")
            context_str += f"- [{date}] {e.get('label')}: {e.get('detail')}\n"

    if not active_goals and not active_tasks and not constraints and not scheduled_events:
        context_str += "履歴にタスク・目標・制約はまだありません。\n"

    return context_str


def resolve_semantic_duplicates(daily_graph: Dict[str, Any], master_graph: Dict[str, Any]) -> Dict[str, Any]:
    """LLMを使ってセマンティック重複を検出・マージする。"""
    print("🔍 マスターグラフとの重複をチェック中...")

    daily_nodes = daily_graph.get("nodes", [])
    master_nodes = master_graph.get("nodes", [])

    if not master_nodes or not daily_nodes:
        return daily_graph

    mergeable_types = {'タスク', '制約', '知見', '感情', '目標', 'プロジェクト', '概念', '人物', '場所', '出来事'}

    new_candidates = [n for n in daily_nodes if n.get('type') in mergeable_types]
    if not new_candidates:
        return daily_graph

    master_candidates = [n for n in master_nodes if n.get('type') in mergeable_types]
    if not master_candidates:
        return daily_graph

    new_list_str = "\n".join([f"- {n['id']} ({n.get('type')}): {n.get('label')}" for n in new_candidates])
    master_list_str = "\n".join([f"- {n['id']} ({n.get('type')}): {n.get('label')}" for n in master_candidates])

    prompt = f"""
    {RESOLUTION_SYSTEM_PROMPT}

    ### New Nodes (Daily)
    {new_list_str}

    ### Existing Nodes (Master)
    {master_list_str}

    Return JSON mapping.
    """

    try:
        json_text = call_gemini_api(prompt, model="gemini-3-flash-preview", response_mime_type="application/json")
        mapping = json.loads(json_text)

        if not mapping:
            print("✅ 重複なし。")
            return daily_graph

        print(f"🔄 {len(mapping)}件のセマンティック重複を発見。マージ中...")
        for new_id, existing_id in mapping.items():
            print(f"   - {new_id} -> {existing_id}")

            for n in daily_graph.get("nodes", []):
                if n['id'] == new_id:
                    n['id'] = existing_id

            for e in daily_graph.get("edges", []):
                if e['source'] == new_id: e['source'] = existing_id
                if e['target'] == new_id: e['target'] = existing_id

        return daily_graph

    except Exception as e:
        print(f"⚠️ 重複解決に失敗: {e}。解決なしで続行します。")
        return daily_graph


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 分析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def analyze_updated_state(master_graph: Dict[str, Any], current_diary_node: Dict[str, Any]) -> str:
    """更新後のグラフ全体を分析し、Antigravityアドバイスを生成する。"""

    # 1. 進行中の目標
    active_goals = [n for n in master_graph.get("nodes", []) if n.get("type") == "目標" and n.get("status") in ["進行中", "Active"]]

    # 2. 知見
    recent_insights = sorted(
        [n for n in master_graph.get("nodes", []) if n.get("type") == "知見"],
        key=lambda x: x.get("last_seen", ""), reverse=True
    )[:10]

    # 3. 予定
    scheduled_events = [n for n in master_graph.get("nodes", []) if n.get("type") == "出来事" and n.get("status") in ["予定", "Scheduled"]]

    # 4. 未完了タスク
    pending_tasks = [n for n in master_graph.get("nodes", []) if n.get("type") == "タスク" and n.get("status") not in ["完了", "Completed"]]

    # 5. 制約（重力）
    constraints = [n for n in master_graph.get("nodes", []) if n.get("type") == "制約"]

    # 6. 感情
    emotions = [n for n in master_graph.get("nodes", []) if n.get("type") == "感情"]

    # 7. 最近の日記
    all_diary_nodes = sorted(
        [n for n in master_graph.get("nodes", []) if n.get("type") == "日記"],
        key=lambda x: x.get("date", ""), reverse=True
    )[:5]

    # 8. タスクと制約の接続情報
    edges = master_graph.get("edges", [])
    blocking_edges = [e for e in edges if e.get("type") == "阻害する"]
    motivating_edges = [e for e in edges if e.get("type") == "原動力になる"]

    # 9. 前回の分析結果からスケジュールとアクションを引き継ぐ
    prev_schedule = []
    prev_actions = []
    for d_node in all_diary_nodes:
        if d_node.get("analysis_content"):
            try:
                prev_analysis = json.loads(d_node["analysis_content"])
                if prev_analysis.get("upcoming_schedule") and not prev_schedule:
                    prev_schedule = prev_analysis["upcoming_schedule"]
                if prev_analysis.get("antigravity_actions") and not prev_actions:
                    prev_actions = prev_analysis["antigravity_actions"]
                if prev_schedule and prev_actions:
                    break
            except (json.JSONDecodeError, TypeError):
                pass

    # コンテキスト構築
    context_summary = "### 現在の状況\n"

    if active_goals:
        context_summary += "**進行中の目標:**\n" + "\n".join([f"- {n.get('label')}: {n.get('detail')}" for n in active_goals]) + "\n"

    if pending_tasks:
        context_summary += "\n**未完了タスク:**\n"
        for t in pending_tasks:
            # このタスクに対する制約を収集
            task_constraints = []
            for be in blocking_edges:
                if be.get("target") == t.get("id"):
                    constraint_node = next((n for n in constraints if n["id"] == be.get("source")), None)
                    if constraint_node:
                        task_constraints.append(constraint_node.get("label"))
            constraint_str = f" [重力: {', '.join(task_constraints)}]" if task_constraints else ""
            context_summary += f"- {t.get('label')}{constraint_str}\n"

    if constraints:
        context_summary += "\n**制約（重力）一覧:**\n" + "\n".join([f"- {n.get('label')} ({n.get('constraint_type', '不明')}): {n.get('detail')}" for n in constraints]) + "\n"

    if emotions:
        context_summary += "\n**感情:**\n" + "\n".join([f"- {n.get('label')} (sentiment: {n.get('sentiment', 0)})" for n in emotions]) + "\n"

    if recent_insights:
        context_summary += "\n**最近の知見:**\n" + "\n".join([f"- {n.get('label')}" for n in recent_insights]) + "\n"

    if scheduled_events:
        context_summary += "\n**今後の予定:**\n" + "\n".join([f"- {n.get('date')} {n.get('label')}: {n.get('detail', '')}" for n in scheduled_events]) + "\n"

    if prev_schedule:
        context_summary += "\n**前回出力したスケジュール（時間情報を引き継いでください）:**\n"
        context_summary += json.dumps(prev_schedule, ensure_ascii=False, indent=2) + "\n"

    if prev_actions:
        context_summary += "\n**前回出力した重力軽減アクション（日記で完了が確認できたものは除外し、新しいアクションに入れ替えてください）:**\n"
        context_summary += json.dumps(prev_actions, ensure_ascii=False, indent=2) + "\n"

    # 日記の流れ
    recent_diary_context = "\n### 最近の日記の流れ\n"
    if not all_diary_nodes:
        recent_diary_context += "最近の日記エントリはありません。\n"
    else:
        for d_node in all_diary_nodes:
            d_date = d_node.get("date", "不明")
            d_id = d_node.get("id")

            mentioned_nodes = []
            for edge in edges:
                if edge.get("source") == d_id and edge.get("type") == "言及する":
                    target_id = edge.get("target")
                    target_node = next((n for n in master_graph.get("nodes", []) if n["id"] == target_id), None)
                    if target_node:
                        mentioned_nodes.append(f"{target_node.get('label')} ({target_node.get('type')})")

            mentions_str = ", ".join(mentioned_nodes) if mentioned_nodes else "特定の言及なし"
            recent_diary_context += f"- **{d_date}**: {mentions_str}\n"

    # 役割定義
    role_def = get_role_definition()

    prompt = f"""
    {ANALYSIS_SYSTEM_PROMPT}

    {role_def}

    {context_summary}

    {recent_diary_context}

    ### 今日の新しいエントリ
    {json.dumps(current_diary_node, ensure_ascii=False, indent=2)}

    ### 指示
    上記の「最近の日記の流れ」と「制約（重力）一覧」を元に、タスクの重力バランスを分析し、
    重力を軽減する具体的な提案を行ってください。
    単にタスクを列挙するだけでなく、「なぜそのタスクが進まないのか」「どうすれば重力を軽くできるか」を深く分析してください。
    """
    print("🔄 Antigravity分析を実行中...")
    return call_gemini_api(prompt, model="gemini-3-flash-preview")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HTML可視化の更新
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def update_html_visualization(html_path: str, graph_data: Dict[str, Any]):
    """index.htmlのGRAPH_DATAを更新する。"""
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        start_marker = "// GRAPH_DATA_START"
        end_marker = "// GRAPH_DATA_END"

        start_idx = html_content.find(start_marker)
        end_idx = html_content.find(end_marker)

        if start_idx != -1 and end_idx != -1:
            new_block = f"{start_marker}\n    const GRAPH_DATA = {json.dumps(graph_data, ensure_ascii=False, indent=2)};\n    "
            new_html = html_content[:start_idx] + new_block + html_content[end_idx:]

            with open(html_path, "w", encoding="utf-8") as f:
                f.write(new_html)
            print(f"✅ 可視化画面を更新しました: {html_path}")
        else:
            print(f"⚠️ マーカーが見つかりません: {html_path}")

    except Exception as e:
        print(f"❌ HTML更新エラー: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メインフロー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description="Pomera Diary → Antigravity Knowledge Graph")
    parser.add_argument("input_file", help="日記テキストファイルのパス")
    parser.add_argument("--output_graph", default="daily_graph.json", help="日次グラフJSONの出力先")
    parser.add_argument("--master_graph", default="knowledge_graph.jsonld", help="マスターグラフのパス")
    parser.add_argument("--output_report", default="daily_report.md", help="分析レポートの出力先")

    args = parser.parse_args()

    # 1. 日記の読み込み
    try:
        import unicodedata
        args.input_file = unicodedata.normalize('NFC', args.input_file)
        with open(args.input_file, "r", encoding="utf-8") as f:
            diary_text = f.read()
    except FileNotFoundError:
        print(f"❌ ファイルが見つかりません: {args.input_file}")
        return

    # 2. マスターグラフの読み込み
    print(f"📂 マスターグラフを読み込み中: {args.master_graph}")
    try:
        master_graph = graph_merger.load_graph(args.master_graph)
    except Exception as e:
        print(f"⚠️ マスターグラフの読み込みに失敗、新規作成: {e}")
        master_graph = {
            "nodes": [],
            "edges": [],
            "metadata": {
                "schema_version": "2.0-antigravity",
                "description": "タスクの重力モデルに基づく知識グラフ"
            }
        }
    master_context_str = get_master_context(master_graph)

    # 3. 日次グラフの抽出
    try:
        daily_graph = extract_graph(diary_text, master_context_str)

        # 日付の抽出
        import re
        match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', args.input_file)
        if match:
            y, m, d = match.groups()
            current_date_str = f"{y}-{int(m):02d}-{int(d):02d}"
            print(f"📅 ファイル名から日付を抽出: {current_date_str}")
        else:
            current_date_str = datetime.now().strftime("%Y-%m-%d")
            print(f"⚠️ ファイル名から日付を抽出できず、今日の日付を使用: {current_date_str}")

        daily_graph["metadata"] = {
            "generated_at": datetime.now().isoformat(),
            "source_file": args.input_file,
            "node_count": len(daily_graph.get("nodes", [])),
            "edge_count": len(daily_graph.get("edges", []))
        }

        # 日記ノードの追加
        diary_node_id = f"日記:{current_date_str}"
        if not any(node.get("id") == diary_node_id for node in daily_graph.get("nodes", [])):
            daily_graph.get("nodes", []).append({
                "id": diary_node_id,
                "label": f"{current_date_str}の日記",
                "type": "日記",
                "date": current_date_str,
                "detail": "今日の日記エントリ",
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "weight": 1
            })

        # ユーザーノードの追加
        user_node_id = "人物:自分"
        if not any(node.get("id") == user_node_id for node in daily_graph.get("nodes", [])):
            daily_graph.get("nodes", []).append({
                "id": user_node_id,
                "label": "自分",
                "type": "人物",
                "detail": "日記の作成者",
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "weight": 1
            })

        # 接続の確保: 自分 → 日記
        daily_graph.get("edges", []).append({
            "source": user_node_id,
            "target": diary_node_id,
            "type": "関連する",
            "label": "書いた",
            "weight": 1
        })

        # 接続の確保: 日記 → 各ノード（孤立を防ぐ）
        for node in daily_graph.get("nodes", []):
            nid = node.get("id")
            if nid == user_node_id or nid == diary_node_id:
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

        # セマンティック重複の解決
        daily_graph = resolve_semantic_duplicates(daily_graph, master_graph)

        # 日次グラフの保存
        with open(args.output_graph, "w", encoding="utf-8") as f:
            json.dump(daily_graph, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"❌ 抽出中にエラー: {e}")
        return

    # 4. マスターグラフへのマージ
    print("🔄 マスターグラフへマージ中...")
    updated_master = None
    try:
        with open(args.output_graph, "r", encoding="utf-8") as f:
            daily_graph_for_merge = json.load(f)

        updated_master = graph_merger.merge_graphs(master_graph, daily_graph_for_merge)

        with open(args.master_graph, "w", encoding="utf-8") as f:
            json.dump(updated_master, f, ensure_ascii=False, indent=2)
        print(f"✅ マスターグラフを更新しました: {args.master_graph}")

    except Exception as e:
        print(f"❌ マージ中にエラー: {e}")
        updated_master = master_graph

    # 5. Antigravity分析
    try:
        current_diary_node = next((n for n in updated_master.get("nodes", []) if n["id"] == diary_node_id), None)

        if current_diary_node:
            analysis_text = analyze_updated_state(updated_master, current_diary_node)

            with open(args.output_report, "w", encoding="utf-8") as f:
                f.write(f"# Antigravity分析レポート ({datetime.now().date()})\n\n")
                f.write(f"**分析対象:** {current_date_str} の日記\n\n")
                f.write(analysis_text)
            print(f"✅ 分析レポートを保存しました: {args.output_report}")

            current_diary_node["analysis_content"] = analysis_text

            with open(args.master_graph, "w", encoding="utf-8") as f:
                json.dump(updated_master, f, ensure_ascii=False, indent=2)
            print(f"✅ グラフの {diary_node_id} に分析結果を統合しました")

        else:
            print("⚠️ 日記ノードが見つかりません。分析をスキップします。")

    except Exception as e:
        print(f"❌ 分析中にエラー: {e}")

    # 6. HTML可視化の更新
    try:
        html_path = "index.html"
        if os.path.exists(html_path):
            update_html_visualization(html_path, updated_master)
        else:
            print(f"⚠️ {html_path} が見つかりません。可視化の更新をスキップします。")
    except Exception as e:
        print(f"❌ 可視化更新中にエラー: {e}")


if __name__ == "__main__":
    main()
