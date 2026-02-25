import os
import json
import argparse
from datetime import datetime
import requests
from typing import Dict, Any, List, Optional

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
   - emotion_category: 「喜び」「達成感」「不安」「怒り」「その他」の5分類から必ず選択
   - trigger: その感情が生まれた具体的なきっかけ（1文で記述）
5. **人物**: 日記に登場する人。
6. **出来事**: 起きた具体的なイベント。
   - status: "予定" / "完了" / "中止"
7. **目標**: 長期的に目指すもの。
   - status: "進行中" / "達成" / "断念"
8. **プロジェクト**: 継続的な取り組み。
9. **概念**: 抽象的な概念や状態。
10. **場所**: 場所。
11. **日記**: 日記エントリそのもの。
12. **購入希望**: 「もっているのがぐれがきている」「買いたい」「欲しい」「植え替えたい」「改辺したい」など、買いたいものややりたい事に関する記述。
    - cost: 金額の目安（言及されている場合のみ、整数円）
    - priority: 「高」（生活上必要不可欠）「中」（近い将来に欲しい）「低」（いつか欲しい）の3分類
    - status: 「検討中」 / 「購入済」 / 「キャンセル」

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
| 欲しがる | 人物/日記 → 購入希望 | 購入希望との関連 |

# 抽出ルール
1. **制約の抽出を重視**: 日記からタスクだけでなく、そのタスクを阻害している「重力」を積極的に見つけてください。
   - 時間がない → 制約「時間不足」→ 阻害する → タスク
   - 疲れている → 制約「疲労」→ 阻害する → タスク
   - やり方がわからない → 制約「技術的課題」→ 阻害する → タスク
   - やる気が出ない → 制約「感情的ブレーキ」→ 阻害する → タスク

2. **感情の原動力を抽出**: ポジティブな感情やモチベーションもグラフに入れてください。

3. **既存タスクとの照合**: コンテキストに「既存のタスク・目標一覧」が提供されます。日記が既存タスク・目標の進捗に言及している場合、新しいノードを作らず既存IDを再利用してください。
   - **重要**: 日記が既存の目標や目標について触れている場合は、必ず「日記ノード → 目標ノード」の `言及する` エッジを出力してください（例: モンスターデザインについて書いた → `日記:XXXX -[言及する]-> 目標:RealisticDesign`）。直接のノード更新がなくても言及エッジは必須です。

4. **タグの付与**: ユーザーが `Task::xxx` や `予定::xxx` のようなタグを使う場合はそのまま解析してください。

5. **全て日本語**: label と detail は必ず日本語で書いてください。

# コンテキスト判定

各ノードに `context` フィールドを付与してください。
日記は1つのファイルに複数の文脈が混在するため、ノードの内容ごとに適切な文脈を判断してください。

- "knowbe"  : Knowbeでの仕事（フロントエンド、チームリーダーとしての活動）に関係するノード
- "saiteki" : Saitekiでの副業（AI研究）に関係するノード
- "private" : プライベート（家族、健康、趣味、個人的な目標など）に関係するノード
- "shared"  : どの文脈にも当てはまらないもの、または複数にまたがるもの

判断のヒント:
- 「チーム」「フロントエンド」「リーダー」「メンバー」などはKnowbeが多い
- 「AI」「研究」「副業」「スタートアップ」などはSaitekiが多い
- 「妻」「子供」「ポメラ」「健康」「体重」「ブログ」などはprivateが多い
- 「エンジニア」「プログラミング」など両社に共通するものはsharedにする

# ノード構造
{
  "id": "種別:一意な名前",
  "label": "表示名（日本語）",
  "type": "タスク/制約/知見/感情/人物/出来事/目標/プロジェクト/概念/場所/日記",
  "detail": "説明（日本語）",
  "status": "該当する場合のみ",
  "sentiment": "感情ノードの場合 -1.0〜1.0（原点値として保持）",
  "emotion_category": "感情ノードの場合: 喜び/達成感/不安/怒り/その他",
  "trigger": "感情ノードの場合: その感情が生まれたきっかけ（1文）",
  "date": "該当する場合 YYYY-MM-DD",
  "category": "役割カテゴリ（エンジニア、父親、夫 など）",
  "context": "knowbe/saiteki/private/shared",
  "tags": ["タグ配列"],
  "constraint_type": "制約ノードの場合: 時間不足/疲労/技術的課題/感情的ブレーキ/物理的障害/リソース不足/その他",
  "cost": "購入希望ノードの場合のみ: 金額の目安（整数円）、不明なら null",
  "priority": "購入希望ノードの場合のみ: 高/中/低"
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
    "family_todos": ["家族関連のやるべきこと"],
    "shopping_list": [
      {
        "item": "商品名（例: おむつ、牛乳、シールはがし液）",
        "category": "食料品/日用品/育児用品/医薬品/その他",
        "urgency": "急ぎ/今週中/いつか",
        "note": "補足メモ（任意、例: Mサイズ、Amazonで注文）"
      }
    ]
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
  ],
  "blog_ideas": [
    {
      "title": "読者が思わずクリックしたくなる、具体的で引きのあるブログ記事タイトル",
      "theme": "このブログ記事が扱う中心テーマ（例: ポメラ活用術・AI日記・育児と仕事の両立など）",
      "hook": "記事の冒頭で読者を引き込む一文（日記中のリアルな体験から抽出）",
      "readiness": "高/中/低（日記のエピソードの濃さ・具体性から判断）"
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
- 「family_digest.shopping_list」には日記やグラフから「買う必要があるもの」を抽出してください。
  - 「〇〇を買う」「〇〇が切れた/なくなった」「〇〇を注文する」「〇〇が必要」などの記述から品目を抽出します。
  - urgency は文脈から判断してください。「急いで」「今日中に」は「急ぎ」、それ以外は「今週中」か「いつか」とします。
  - すでに「買った」「届いた」「注文済み」など完了している品目は shopping_list に含めないでください。
  - 家族全員に共通する日用品・食料品も含めてください。日記に言及がなければ空配列で構いません。
- 「family_digest」には ROLEtoKNOWLEDGE の役割定義に記載されている家族メンバーに関する情報を抽出してください。日記に家族の話題がなければ空で構いません。
- 「blog_seeds」にはユーザーの日記から1話完結のフィクション短編小説の着想を提案してください。星新一のショートショートのような、匿名的で寓話的な物語です。ユーザーの体験をそのまま書くのではなく、テーマや感情を抽出して架空の物語にする前提です。readiness が「高」なものは、感情やエピソードが十分に濃く、すぐに執筆できるものです。
- 「blog_ideas」にはこの日記の内容からブログ記事として書けそうなアイディアをLLMが能動的に提案してください。
  - 「ブログアイディア::」という記法がなくても、日記の体験・気づき・感情・出来事から積極的に2〜3件提案してください。
  - 「手書きで書く手間が減った」「子育てと副業を両立する工夫」「AIに頼んで意外とよかったこと」など、読者が共感できる具体的なテーマを選んでください。
  - readiness が「高」なものは、今すぐ書けるほど情報が揃っているものです。
  - 「ブログアイディア::テーマ」という記法が日記にある場合は、それも必ず含めてください。

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
# セクション別LLM呼び出し基盤
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_graph_context(master_graph: Dict[str, Any], category_filter: Optional[str] = None) -> str:
    """ナレッジグラフのノードをLLM向けのテキストコンテキストに変換する。

    Args:
        master_graph: knowledge_graph.jsonld 全体
        category_filter: 'knowbe' / 'saiteki' / '家族' / '個人' などでフィルタ。Noneなら全件。
    """
    nodes = master_graph.get("nodes", [])
    if category_filter:
        nodes = [n for n in nodes if n.get("category") == category_filter or category_filter in (n.get("tags") or [])]

    lines = ["### ナレッジグラフ: 現在の状態"]

    # タスクノード（status付き）
    tasks = [n for n in nodes if n.get("type") == "タスク"]
    if tasks:
        lines.append("\n**タスク一覧（statusは必ず参照してください）:**")
        for t in tasks:
            status = t.get("status", "進行中")
            detail = t.get("detail", "")
            lines.append(f"- [{status}] {t.get('label', '')}: {detail[:100]}")

    # 目標ノード
    goals = [n for n in nodes if n.get("type") == "目標"]
    if goals:
        lines.append("\n**目標一覧:**")
        for g in goals:
            status = f"[{g['status']}] " if g.get("status") else ""
            lines.append(f"- {status}{g.get('label', '')}: {g.get('detail', '')[:100]}")

    # 欲しいもの / 買い物
    wants = [n for n in nodes if n.get("type") in ["欲しいもの", "買い物", "購入希望"]]
    if wants:
        lines.append("\n**欲しいもの / 買い物（status付き）:**")
        for w in wants:
            status = w.get("status", "未購入")
            lines.append(f"- [{status}] {w.get('label', '')}: {w.get('detail', '')[:80]}")

    # 制約ノード（category_filter指定時は特に重要）
    constraints = [n for n in nodes if n.get("type") == "制約"]
    if constraints:
        lines.append("\n**制約（重力）:**")
        for c in constraints:
            lines.append(f"- {c.get('label', '')}: {c.get('detail', '')[:100]}")

    return "\n".join(lines)


_DEFAULT_SECTION_MODEL = "gemini-2.0-flash-lite"

def call_section_llm(section_name: str, prompt: str, expect_json: bool = True) -> Any:
    """セクション別の独立したLLM呼び出し。JSON配列またはオブジェクトを返す。

    Args:
        section_name: ログ表示用のセクション名
        prompt: 完全なプロンプト文字列
        expect_json: Trueならapplication/jsonで呼び出す
    Returns:
        パースされたPythonオブジェクト（リストまたは辞書）。失敗時は空リスト。
    """
    print(f"   🤖 [{section_name}] LLM呼び出し中...")
    try:
        mime = "application/json" if expect_json else "text/plain"
        raw = call_gemini_api(prompt, model=_DEFAULT_SECTION_MODEL, response_mime_type=mime)
        if not expect_json:
            return raw.strip()
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'```\s*$', '', cleaned).strip()
        parsed = json.loads(cleaned)
        print(f"   ✅ [{section_name}] 取得完了")
        return parsed
    except Exception as e:
        print(f"   ⚠️ [{section_name}] LLM呼び出し失敗: {e}")
        return [] if expect_json else ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 分析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def analyze_updated_state(master_graph: Dict[str, Any], current_diary_node: Dict[str, Any], diary_text: str = "") -> str:
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

    # 9. 前回の分析結果からスケジュールとアクション、買い物リストを引き継ぐ
    prev_schedule = []
    prev_actions = []
    prev_shopping_list = []
    for d_node in all_diary_nodes:
        if d_node.get("analysis_content"):
            try:
                raw_ac = d_node["analysis_content"]
                # Markdownコードブロック除去
                cleaned_ac = raw_ac.strip()
                if cleaned_ac.startswith("```"):
                    cleaned_ac = re.sub(r'^```(?:json)?\s*', '', cleaned_ac)
                    cleaned_ac = re.sub(r'```\s*$', '', cleaned_ac).strip()
                prev_analysis = json.loads(cleaned_ac)

                if prev_analysis.get("upcoming_schedule") and not prev_schedule:
                    prev_schedule = prev_analysis["upcoming_schedule"]
                if prev_analysis.get("antigravity_actions") and not prev_actions:
                    prev_actions = prev_analysis["antigravity_actions"]
                if prev_analysis.get("family_digest", {}).get("shopping_list") and not prev_shopping_list:
                    prev_shopping_list = prev_analysis["family_digest"]["shopping_list"]
                if prev_schedule and prev_actions and prev_shopping_list:
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

    if prev_shopping_list:
        context_summary += "\n**前回出力した買い物リスト（今日の日記で『買った』『届いた』『注文済み』などの完了表現があるものは必ず除外してください。周期的な消耗品でも、今日の日記で購入したと明示されている場合は絶対に含めないでください）:**\n"
        context_summary += json.dumps(prev_shopping_list, ensure_ascii=False, indent=2) + "\n"

    # 日記の流れ
    recent_diary_context = "\n### 最近の日記の流れ（完了判定に使用してください）\n"
    recent_diary_context += "※ 日記の本文に「買った」「注文した」「完了した」「やった」「済んだ」などの表現があるアクションは、前回のアクションリストから必ず除外してください。\n"
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

            # 日記本文（detail）を含める — 完了判定のため最重要
            diary_body = d_node.get("detail", "").strip()
            if diary_body:
                # 長すぎる場合は先頭800文字に制限してトークンを節約
                if len(diary_body) > 800:
                    diary_body = diary_body[:800] + "…（省略）"
                recent_diary_context += f"\n#### {d_date} の日記\n**言及ノード:** {mentions_str}\n**本文:**\n{diary_body}\n"
            else:
                recent_diary_context += f"- **{d_date}**: {mentions_str}\n"


    # 役割定義
    role_def = get_role_definition()

    prompt = f"""
    {ANALYSIS_SYSTEM_PROMPT}

    {role_def}

    {context_summary}

    {recent_diary_context}

    ### 今日の日記（生テキスト）
    以下が今日の日記の全文です。「ブログアイディア::」「ブログゴール::」などのタグは必ずここから抽出してください。
    ---
    {diary_text}
    ---

    ### 今日の新しいエントリ（グラフノード情報）
    {json.dumps(current_diary_node, ensure_ascii=False, indent=2)}

    ### 指示
    上記の「最近の日記の流れ」と「制約（重力）一覧」を元に、タスクの重力バランスを分析し、
    重力を軽減する具体的な提案を行ってください。
    単にタスクを列挙するだけでなく、「なぜそのタスクが進まないのか」「どうすれば重力を軽くできるか」を深く分析してください。
    """
    print("🔄 Antigravity分析を実行中...")
    raw = call_gemini_api(prompt, model=_DEFAULT_SECTION_MODEL, response_mime_type="application/json")
    # Markdownコードブロックが混入した場合に備えてクリーニング
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'```\s*$', '', cleaned).strip()

    # ── antigravity_actions を独立したLLM呼び出しで上書き ──────────────────
    # ナレッジグラフのstatus付きノードをコンテキストに渡してLLMに完了判定させる
    graph_ctx = build_graph_context(master_graph)

    # メインプロンプトが返した前回のアクションを参考として提供
    prev_actions_for_section = []
    try:
        base_parsed = json.loads(cleaned)
        prev_actions_for_section = base_parsed.get("antigravity_actions", [])
    except Exception:
        pass
    # さらに以前のアクション（前回ループから継承したもの）も参考にする
    if prev_actions and not prev_actions_for_section:
        prev_actions_for_section = prev_actions

    # 前回アクションをJSON文字列化（参考として渡す）
    prev_actions_str = json.dumps(prev_actions_for_section, ensure_ascii=False, indent=2) if prev_actions_for_section else "なし"

    actions_prompt = f"""あなたは「反重力コーチ」です。ユーザーの今日の日記と、ナレッジグラフの現在の状態（各ノードのstatusが付いています）を読んでください。

{graph_ctx}

### 今日の日記
{diary_text[:1500]}

### 前回の重力軽減アクション（参考）
{prev_actions_str}

以下のルールに従って「重力軽減アクション」を3〜5件提案してください。

ルール:
1. ナレッジグラフで status が「完了」「購入済み」「注文済み」「done」「completed」のノードに関するアクションは【絶対に提案しないこと】
2. 前回のアクション一覧の中で、日記または最新のノードから「実行済み」「完了」と読み取れるものは除外すること
3. 今日の日記に書かれた悩みや停滞感、重力を解消する新しいアクションを提案すること
4. effort は「5分」「30分」「1時間」のいずれかにすること

JSON配列のみを出力してください（それ以外のテキスト禁止）:
[{{"action": "具体的なアクション", "target_task": "対象タスク名", "effect": "このアクションで軽減される重力の説明", "effort": "5分"}}]
"""
    new_actions = call_section_llm("antigravity_actions", actions_prompt)
    if isinstance(new_actions, list) and new_actions:
        # メイン結果のJSONにantigravity_actionsを上書き
        try:
            base_obj = json.loads(cleaned)
            base_obj["antigravity_actions"] = new_actions
            cleaned = json.dumps(base_obj, ensure_ascii=False)
            print(f"   ✅ antigravity_actions を {len(new_actions)} 件にセクション別LLMで更新しました")
        except Exception as e:
            print(f"   ⚠️ antigravity_actions 上書きに失敗（元の結果を維持）: {e}")
    else:
        print("   ⚠️ セクション別LLMからantigravity_actionsが取得できなかったため元の結果を維持します")

    # ── family_digest サブセクション別LLM呼び出し ────────────────────────
    family_graph_ctx = build_graph_context(master_graph, category_filter="家族")
    diary_short = diary_text[:1200]

    family_highlights_prompt = f"""あなたは家族の記録係です。今日の日記から家族メンバーの出来事・成長・感情を抽出してください。

{family_graph_ctx}

### 今日の日記
{diary_short}

日記に家族の話題がなければ空配列を返してください。
JSON配列のみ出力（他のテキスト禁止）:
[{{"member": "メンバー名（妻・長女など）", "event": "出来事", "emotion": "関連感情"}}]
"""
    family_todos_prompt = f"""今日の日記と家族のナレッジグラフから「家族全員でやるべきこと」を抽出してください。

{family_graph_ctx}

### 今日の日記
{diary_short}

日記に家族のToDo情報がなければ空配列を返してください。
JSON配列のみ出力:
["家族ToDoのテキスト"]
"""
    shopping_prompt = f"""今日の日記と家族のナレッジグラフから「買い物リスト」を抽出してください。

{family_graph_ctx}

### 今日の日記
{diary_short}

ルール:
- 「買った」「届いた」「注文済み」など完了しているものは含めないこと
- statusが「購入済み」「注文済み」「完了」のノードに関する品目は含めないこと
- 消耗品（おむつ・牛乳など）も含めてよい

JSON配列のみ出力:
[{{"item": "商品名", "category": "食料品/日用品/育児用品", "urgency": "急ぎ/今週中/いつか", "note": "補足"}}]
"""
    new_highlights = call_section_llm("family_highlights", family_highlights_prompt)
    new_family_todos = call_section_llm("family_todos", family_todos_prompt)
    new_shopping = call_section_llm("shopping_list", shopping_prompt)

    # ── knowbe サブセクション別LLM呼び出し ──────────────────────────────
    knowbe_graph_ctx = build_graph_context(master_graph, category_filter="knowbe")
    knowbe_constraints_prompt = f"""あなたはKnowbe業務の分析者です。今日の日記からKnowbeの業務に関する「重力（制約・障害）」を3件以内で抽出してください。

{knowbe_graph_ctx}

### 今日の日記
{diary_short}

Knowbeに関する記述がなければ空配列を返してください。
JSON配列のみ出力:
[{{"label": "制約名", "detail": "詳細", "constraint_type": "組織/感情/環境/時間"}}]
"""
    knowbe_tasks_prompt = f"""今日の日記とKnowbeのナレッジグラフから、Knowbe業務の「進行中・未完了タスク」を抽出してください。

{knowbe_graph_ctx}

### 今日の日記
{diary_short}

Knowbeに関するタスク情報がなければ空配列を返してください。
JSON配列のみ出力:
[{{"label": "タスク名", "detail": "詳細", "status": "進行中"}}]
"""
    knowbe_insights_prompt = f"""今日の日記とKnowbeのナレッジグラフから、Knowbe業務に関する「知見・学び」を抽出してください。

{knowbe_graph_ctx}

### 今日の日記
{diary_short}

Knowbeに関する知見がなければ空配列を返してください。
JSON配列のみ出力:
[{{"finding": "気づき", "implication": "それが意味すること"}}]
"""
    new_knowbe_constraints = call_section_llm("knowbe_constraints", knowbe_constraints_prompt)
    new_knowbe_tasks = call_section_llm("knowbe_tasks", knowbe_tasks_prompt)
    new_knowbe_insights = call_section_llm("knowbe_insights", knowbe_insights_prompt)

    # ── saiteki サブセクション別LLM呼び出し ─────────────────────────────
    saiteki_graph_ctx = build_graph_context(master_graph, category_filter="saiteki")
    saiteki_constraints_prompt = f"""あなたはSaiteki業務の分析者です。今日の日記からSaitekiの業務に関する「重力（制約・障害）」を3件以内で抽出してください。

{saiteki_graph_ctx}

### 今日の日記
{diary_short}

Saitekiに関する記述がなければ空配列を返してください。
JSON配列のみ出力:
[{{"label": "制約名", "detail": "詳細", "constraint_type": "組織/感情/環境/時間"}}]
"""
    saiteki_tasks_prompt = f"""今日の日記とSaitekiのナレッジグラフから、Saiteki業務の「進行中・未完了タスク」を抽出してください。

{saiteki_graph_ctx}

### 今日の日記
{diary_short}

Saitekiに関するタスク情報がなければ空配列を返してください。
JSON配列のみ出力:
[{{"label": "タスク名", "detail": "詳細", "status": "進行中"}}]
"""
    saiteki_insights_prompt = f"""今日の日記とSaitekiのナレッジグラフから、Saiteki業務に関する「知見・学び」を抽出してください。

{saiteki_graph_ctx}

### 今日の日記
{diary_short}

Saitekiに関する知見がなければ空配列を返してください。
JSON配列のみ出力:
[{{"finding": "気づき", "implication": "それが意味すること"}}]
"""
    new_saiteki_constraints = call_section_llm("saiteki_constraints", saiteki_constraints_prompt)
    new_saiteki_tasks = call_section_llm("saiteki_tasks", saiteki_tasks_prompt)
    new_saiteki_insights = call_section_llm("saiteki_insights", saiteki_insights_prompt)

    # ── 全セクションをJSONに統合 ─────────────────────────────────────────
    try:
        base_obj = json.loads(cleaned)

        # family_digest を上書き
        base_obj["family_digest"] = {
            "highlights": new_highlights if isinstance(new_highlights, list) else [],
            "family_todos": new_family_todos if isinstance(new_family_todos, list) else [],
            "shopping_list": new_shopping if isinstance(new_shopping, list) else [],
        }

        # knowbe セクションを追加
        base_obj["knowbe"] = {
            "constraints": new_knowbe_constraints if isinstance(new_knowbe_constraints, list) else [],
            "tasks": new_knowbe_tasks if isinstance(new_knowbe_tasks, list) else [],
            "insights": new_knowbe_insights if isinstance(new_knowbe_insights, list) else [],
        }

        # saiteki セクションを追加
        base_obj["saiteki"] = {
            "constraints": new_saiteki_constraints if isinstance(new_saiteki_constraints, list) else [],
            "tasks": new_saiteki_tasks if isinstance(new_saiteki_tasks, list) else [],
            "insights": new_saiteki_insights if isinstance(new_saiteki_insights, list) else [],
        }

        cleaned = json.dumps(base_obj, ensure_ascii=False)
        print("   ✅ family/knowbe/saiteki のセクション別LLM結果を統合しました")
    except Exception as e:
        print(f"   ⚠️ セクション統合に失敗（元の結果を維持）: {e}")

    return cleaned





# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HTML可視化の更新
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _validate_graph_data(graph_data: Dict[str, Any]) -> None:
    """GRAPH_DATA の整合性を検証する。失敗した場合は RuntimeError を送出。"""
    if not isinstance(graph_data, dict):
        raise RuntimeError("GRAPH_DATA がオブジェクトではありません")
    if "nodes" not in graph_data or not isinstance(graph_data["nodes"], list):
        raise RuntimeError("GRAPH_DATA.nodes が見つからないか、リストではありません")
    if "edges" not in graph_data or not isinstance(graph_data["edges"], list):
        raise RuntimeError("GRAPH_DATA.edges が見つからないか、リストではありません")
    # JSON としてシリアライズ・デシリアライズできるか確認
    try:
        roundtripped = json.loads(json.dumps(graph_data, ensure_ascii=False))
        assert len(roundtripped["nodes"]) == len(graph_data["nodes"])
    except Exception as e:
        raise RuntimeError(f"GRAPH_DATA の JSON シリアライズ検証に失敗: {e}")


def update_html_visualization(html_path: str, graph_data: Dict[str, Any]):
    """graph_data.js の GRAPH_DATA を更新する。

    index.html 本体ではなく、同じディレクトリの graph_data.js を書き換えることで
    index.html が破損するリスクを根本的に排除する。
    """
    import os
    js_path = os.path.join(os.path.dirname(os.path.abspath(html_path)), "graph_data.js")
    try:
        # ─── 書き込み前に整合性を検証 ─────────────────────────────────
        _validate_graph_data(graph_data)

        # graph_data.js の内容を生成
        new_content = (
            "// GRAPH_DATA_START\n"
            f"const GRAPH_DATA = {json.dumps(graph_data, ensure_ascii=False, indent=2)};\n"
            "// GRAPH_DATA_END\n"
        )

        with open(js_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        # ─── 書き込み後に再読み込みして検証 ───────────────────────────
        with open(js_path, "r", encoding="utf-8") as f:
            written = f.read()
        # const GRAPH_DATA = ... ; の JSON 部分を抽出して検証
        import re
        m = re.search(r"const GRAPH_DATA = (\{.*\});", written, re.DOTALL)
        if not m:
            raise RuntimeError("書き込み後の graph_data.js から GRAPH_DATA を抽出できません")
        json.loads(m.group(1))  # パースできるか確認

        node_count = len(graph_data["nodes"])
        edge_count = len(graph_data["edges"])
        print(f"✅ graph_data.js を更新しました: {node_count} nodes, {edge_count} edges")

    except RuntimeError as e:
        print(f"❌ GRAPH_DATA 検証エラー: {e}")
        raise
    except Exception as e:
        print(f"❌ graph_data.js 更新エラー: {e}")


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
            analysis_text = analyze_updated_state(updated_master, current_diary_node, diary_text)

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
