import os
import json
import argparse
import re
from datetime import datetime, timedelta
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
13. **月次クレカ請求**: 日記でクレジットカードの月次請求額を記録した記述。「セゾンゴールド::171412」「2月のクレカ請求」のような記述から抽出する。
    - id形式: 「月次クレカ請求:カード名:YYYY-MM」（例: 「月次クレカ請求:セゾンゴールド:2026-02」）
    - card_name: カード名（文字列）
    - month: 対象月（YYYY-MM形式）
    - amount: 請求額（整数・円）
    - 請求額が0円のカードも含めること
14. **月次収入**: 日記で収入を記録した記述。「knowbeから〇〇万円の振込」「今月の収入は〇〇円」のような記述から抽出する。
    - id形式: 「月次収入:収入源名:YYYY-MM」（例: 「月次収入:knowbe:2026-02」）
    - source: 収入源名（文字列）
    - month: 対象月（YYYY-MM形式）
    - amount: 収入額（整数・円）
    - note: 補足（税抜き/税込み等）


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

6. **購入希望ノードのstatus更新（重要）**: 日記に「〇〇を買った」「〇〇を購入した」「〇〇が届いた」「〇〇を注文した」という記述があった場合、既存の購入希望ノードの中でその商品に相当するものを探し、同じIDでstatus=「購入済」として出力してください。
   - 例: 既存ノード「購入希望:おむつ」があり、日記に「おむつを購入した」と書かれていたら → id=\"購入希望:おむつ\", status=\"購入済\" を出力する
   - 例: 既存ノード「購入希望:蒼馬のオムツ」があり、日記に「蒼馬のオムツを買った」と書かれていたら → id=\"購入希望:蒼馬のオムツ\", status=\"購入済\" を出力する
   - 消耗品（おむつ・粉ミルク・猫の餌など）が再び「足りなくなった」「また必要」と書かれていたらstatus=\"検討中\"に戻してください

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
  "value_shift_topics": [
    {
      "category": "価値カテゴリ名（例: 創作・表現）",
      "direction": "up/down/steady",
      "delta_label": "以前より前に出ている/以前より少し落ち着いている/観察中",
      "evidence_summary": "直近の日記と比較期間から見える、断定しない根拠要約",
      "recent_examples": [
        {
          "date": "YYYY-MM-DD",
          "summary": "生の日記本文ではなく、短く丸めた要約"
        }
      ],
      "impact": "行動や感情への影響の可能性（診断ではなく仮説として書く）",
      "question": "次に考えるための穏やかな問い",
      "confidence": "高/中/低",
      "comparison_window": {
        "recent_days": 14,
        "baseline_days": 60
      }
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
- 「value_shift_topics」は「価値観が変わった」と断定せず、「最近の日記では以前よりこのテーマが前に出ているようです」のような観察表現にしてください。心理診断や人格断定、生の日記本文の長い引用、家族名・金額・健康状態など機微情報の露出は避けてください。
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


def call_gemini_api(prompt: str, model: str = "gemini-3.1-flash-lite-preview", response_mime_type: str = "text/plain", max_retries: int = 3) -> str:
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
    json_text = call_gemini_api(prompt, model="gemini-3.1-flash-lite-preview", response_mime_type="application/json")
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
        json_text = call_gemini_api(prompt, model="gemini-3.1-flash-lite-preview", response_mime_type="application/json")
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


def build_diary_history(master_graph: Dict[str, Any], max_days: int = 30) -> str:
    """日記ノードを日付昇順で並べてテキスト化する。shopping_list判定など時系列確認用。

    ノードの type=='日記' またはラベルが '日記:YYYY-MM-DD' 形式のものを収集する。
    最大 max_days 件に絞る（新しいものほど重要なため降順でmax_days件、その後昇順表示）。
    """
    import re as _re
    nodes = master_graph.get("nodes", [])
    diary_entries = []
    for n in nodes:
        label = n.get("label", "")
        # 'type' が日記 または ラベルが日記:YYYY-MM-DD 形式
        if n.get("type") == "日記" or _re.match(r"日記:\d{4}-\d{2}-\d{2}", label):
            date_str = n.get("date") or _re.search(r"(\d{4}-\d{2}-\d{2})", label)
            if hasattr(date_str, "group"):
                date_str = date_str.group(1)
            if date_str:
                content = n.get("analysis_content") or n.get("content") or n.get("detail") or ""
                diary_entries.append((date_str, content[:600]))
    # 日付昇順でソートして最新 max_days 件を昇順表示
    diary_entries.sort(key=lambda x: x[0])
    diary_entries = diary_entries[-max_days:]

    if not diary_entries:
        return "（過去の日記ノードが見つかりませんでした）"

    lines = ["### 過去の日記（時系列順・最新30件）"]
    for date_str, content in diary_entries:
        lines.append(f"\n**{date_str}の日記:**")
        lines.append(content[:500] if content else "（内容なし）")
    return "\n".join(lines)


VALUE_SHIFT_DEFS = [
    {
        "label": "家族・つながり",
        "keywords": ["家族", "妻", "父親", "一緒", "相談", "共有", "チーム", "メンバー", "感謝"],
        "impact": "つながりの記述が増えると、協力や感謝が行動の支えになりやすい一方、自分の時間との配分も気になりやすくなります。",
        "question": "このテーマが前に出ると、今週どの場面が少し動きやすくなりますか？",
    },
    {
        "label": "創作・表現",
        "keywords": ["ブログ", "ポメラ", "YouTube", "発信", "執筆", "小説", "描く", "描いた", "動画", "書籍", "記事", "表現", "原稿"],
        "impact": "形にして外へ出すテーマが前に出ると、達成感が増えやすい一方、未完了の種も増えやすくなります。",
        "question": "今週の小さな一手にするとしたら、どの表現を少しだけ形にしますか？",
    },
    {
        "label": "探究・成長",
        "keywords": ["読書", "学び", "学ぶ", "学習", "AI", "研究", "知見", "NotebookLM", "試す", "試した", "試行", "改善", "技術", "分析", "実験"],
        "impact": "学びや改善の手がかりが増えると、迷いを構造化しやすくなりますが、調べる量が増えて着手が重くなることもあります。",
        "question": "この学びを、今日の行動に一つだけつなげるなら何がよさそうですか？",
    },
    {
        "label": "自由・選択",
        "keywords": ["自由", "選択", "収益", "独立", "転職", "社員化", "ストックオプション", "主体", "裁量", "自分で選", "自分のため"],
        "impact": "自分で選ぶ感覚が前に出ると、納得感のある行動を選びやすくなります。",
        "question": "いま選び直せる余地があるとしたら、どこに小さく作れそうですか？",
    },
    {
        "label": "安心・整える",
        "keywords": ["安心", "不安", "貯金", "支出", "確定申告", "体重", "健康", "整理", "条件", "手取り", "お金", "掃除"],
        "impact": "整えるテーマが前に出ると、曖昧な不安を扱いやすくなります。",
        "question": "見える形にすると少し軽くなりそうなものは何ですか？",
    },
]


def _parse_value_shift_date(node: Dict[str, Any]) -> Optional[datetime]:
    raw = str(node.get("date") or node.get("last_seen") or node.get("id") or node.get("label") or "")
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw[:10] if pattern == "%Y-%m-%d" else raw[:8], pattern)
        except ValueError:
            pass
    match = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", raw)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _walk_value_shift_text(value: Any, depth: int = 0) -> List[str]:
    if value is None or depth > 4:
        return []
    if isinstance(value, (str, int, float)):
        return [str(value)]
    if isinstance(value, list):
        parts: List[str] = []
        for item in value[:12]:
            parts.extend(_walk_value_shift_text(item, depth + 1))
        return parts
    if isinstance(value, dict):
        parts = []
        for item in list(value.values())[:16]:
            parts.extend(_walk_value_shift_text(item, depth + 1))
        return parts
    return []


def _parse_analysis_content(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'```\s*$', '', cleaned).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        return parsed
    except Exception:
        return None


def _value_shift_entry_text(node: Dict[str, Any]) -> str:
    parts = [
        node.get("label", ""),
        node.get("detail", ""),
        node.get("current_state", ""),
        " ".join(node.get("tags") or []),
    ]
    for history in node.get("update_history") or []:
        if isinstance(history, dict):
            parts.extend([history.get("content", ""), history.get("state", "")])

    analysis = _parse_analysis_content(node.get("analysis_content"))
    if isinstance(analysis, dict):
        for key in ("insights", "emotion_flow", "gravity_map", "antigravity_actions", "blog_ideas"):
            parts.extend(_walk_value_shift_text(analysis.get(key)))

    return "。".join(str(part) for part in parts if part)[:6000]


def _count_value_shift_keywords(text: str, keywords: List[str]) -> int:
    source = str(text or "").lower()
    score = 0
    for keyword in keywords:
        target = str(keyword).lower()
        if target:
            if re.fullmatch(r"[a-z0-9][a-z0-9_+-]*", target):
                score += len(re.findall(rf"(?<![a-z0-9]){re.escape(target)}(?![a-z0-9])", source))
            else:
                score += source.count(target)
    return score


def build_value_shift_topics(master_graph: Dict[str, Any], max_topics: int = 3) -> List[Dict[str, Any]]:
    """日記履歴から、以前より前に出ている/落ち着いている価値テーマを保守的に抽出する。"""
    entries = []
    for node in master_graph.get("nodes", []):
        if node.get("type") not in ("日記", "diary"):
            continue
        date_value = _parse_value_shift_date(node)
        if not date_value:
            continue
        text = _value_shift_entry_text(node)
        if not text.strip():
            continue
        entries.append({"date": date_value, "date_str": date_value.strftime("%Y-%m-%d"), "text": text})

    entries.sort(key=lambda item: item["date"])
    if len(entries) < 6:
        return []

    reference_date = entries[-1]["date"]
    recent_days = 14
    baseline_days = 60
    recent_start = reference_date - timedelta(days=recent_days - 1)
    baseline_start = recent_start - timedelta(days=baseline_days)

    recent_entries = [item for item in entries if item["date"] >= recent_start]
    baseline_entries = [item for item in entries if baseline_start <= item["date"] < recent_start]
    recent_label = f"直近{recent_days}日"
    baseline_label = f"比較{baseline_days}日"

    if len(recent_entries) < 2 or len(baseline_entries) < 3:
        recent_entries = entries[-5:]
        baseline_entries = entries[-25:-5]
        if len(recent_entries) < 2 or len(baseline_entries) < 3:
            return []
        recent_label = f"直近{len(recent_entries)}件"
        baseline_label = f"比較{len(baseline_entries)}件"

    topics = []
    for definition in VALUE_SHIFT_DEFS:
        keywords = definition["keywords"]
        recent_scores = [
            _count_value_shift_keywords(item["text"], keywords)
            for item in recent_entries
        ]
        baseline_scores = [
            _count_value_shift_keywords(item["text"], keywords)
            for item in baseline_entries
        ]
        recent_score = sum(recent_scores)
        baseline_score = sum(baseline_scores)
        recent_rate = recent_score / max(1, len(recent_entries))
        baseline_rate = baseline_score / max(1, len(baseline_entries))
        delta = recent_rate - baseline_rate
        magnitude = abs(delta)

        if delta >= 0.45 and recent_score >= 2:
            direction = "up"
            delta_label = "以前より前に出ている"
            evidence = f"{recent_label}では「{definition['label']}」に関する手がかりが、比較期間より目立っています。ひとつの傾向として読むのがよさそうです。"
            active_score = recent_score
        elif delta <= -0.45 and baseline_score >= 2:
            direction = "down"
            delta_label = "以前より少し落ち着いている"
            evidence = f"{recent_label}では「{definition['label']}」に関する手がかりが、比較期間より少なめです。関心が消えたというより、いまは他テーマが前に出ている可能性があります。"
            active_score = baseline_score
        else:
            continue

        if magnitude >= 1.2 and active_score >= 4:
            confidence = "高"
        elif magnitude >= 0.7 and active_score >= 3:
            confidence = "中"
        else:
            continue

        recent_examples = []
        seen_example_dates = set()
        for entry, score in zip(recent_entries, recent_scores):
            if score > 0 and entry["date_str"] not in seen_example_dates:
                seen_example_dates.add(entry["date_str"])
                recent_examples.append({
                    "date": entry["date_str"],
                    "summary": f"この日の記述で「{definition['label']}」に関する手がかりがありました。",
                })
            if len(recent_examples) >= 2:
                break

        if not recent_examples and direction == "down" and recent_entries:
            recent_examples.append({
                "date": f"{recent_entries[0]['date_str']}〜{recent_entries[-1]['date_str']}",
                "summary": f"直近期間では「{definition['label']}」に関する具体的な手がかりは控えめでした。",
            })

        topics.append({
            "category": definition["label"],
            "direction": direction,
            "delta_label": delta_label,
            "evidence_summary": evidence,
            "recent_examples": recent_examples,
            "impact": definition["impact"],
            "question": definition["question"],
            "confidence": confidence,
            "comparison_window": {
                "recent_days": recent_days,
                "baseline_days": baseline_days,
                "recent_label": recent_label,
                "baseline_label": baseline_label,
                "recent_entries": len(recent_entries),
                "baseline_entries": len(baseline_entries),
            },
            "metrics": {
                "recent_score": round(recent_rate, 2),
                "baseline_score": round(baseline_rate, 2),
                "delta": round(delta, 2),
            },
        })

    topics.sort(key=lambda item: abs(item.get("metrics", {}).get("delta", 0)), reverse=True)
    return topics[:max_topics]


_DEFAULT_SECTION_MODEL = "gemini-3.1-flash-lite-preview"

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
    if not raw:
        print("   ⚠️ Gemini APIからの応答がNullです。Antigravity分析をスキップします。")
        return "{}"
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
    # 時系列日記を取得（shopping_list の時系列確認用）
    diary_history_ctx = build_diary_history(master_graph, max_days=30)

    shopping_prompt = f"""以下の「過去の日記（時系列順）」を読み、現在も買う必要があるものを判断して買い物リストを作成してください。

**重要なルール: 時系列で最新の記述を優先する**
例：
- 2/1「おむつが必要」→ 2/2「おむつを購入」→ 2/14「おむつが足りなくなった」→ リストに含める
- 2/1「おむつが必要」→ 2/2「おむつを購入」→ 最新の購入後に必要という記述なし → リストから除外
- 「買った」「届いた」「注文した」「購入した」という記述が最後にある品目は除外
- 消耗品は定期的に補充が必要なので、必要と書かれた日付が最近であればリストに含める

{diary_history_ctx}

{family_graph_ctx}

### 今日の日記
{diary_short}

JSON配列のみ出力:
[{{"item": "商品名", "category": "食料品/日用品/育児用品", "urgency": "急ぎ/今週中/いつか", "note": "最後に必要と書かれた日付"}}]
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

        # LLMの推測ではなく、日記ノードの時系列比較からホーム表示用の観察トピックを作る。
        base_obj["value_shift_topics"] = build_value_shift_topics(master_graph)

        cleaned = json.dumps(base_obj, ensure_ascii=False)
        print("   ✅ family/knowbe/saiteki/value_shift_topics の結果を統合しました")
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

    # 4. マスターグラフへのマージ (Neo4jが正とのため、JSON書き込みは廃止)
    print("🔄 グラフをマージ中...")
    updated_master = None
    try:
        with open(args.output_graph, "r", encoding="utf-8") as f:
            daily_graph_for_merge = json.load(f)

        updated_master = graph_merger.merge_graphs(master_graph, daily_graph_for_merge)
        # knowledge_graph.jsonld への書き込みは廃止。Neo4j が正のデータソース。
        print(f"✅ グラフのマージが完了しました (Neo4jは同期済み)")

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

            # 分析結果を Neo4j の日記ノードに書き込む
            try:
                import neo4j_client as _nc
                _client = _nc.Neo4jClient()
                _client.upsert_node_batch_simple([{
                    "id": diary_node_id,
                    "analysis_content": analysis_text,
                }])
                _client.close()
                print(f"✅ グラフの {diary_node_id} に分析結果を統合しました")
            except Exception as neo4j_err:
                print(f"⚠️  Neo4j への分析結果書き込みに失敗: {neo4j_err}")

        else:
            print("⚠️ 日記ノードが見つかりません。分析をスキップします。")

    except Exception as e:
        print(f"❌ 分析中にエラー: {e}")

    # 6. Neo4j → graph_data.js エクスポート
    try:
        import importlib.util, sys as _sys
        _exp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "export_neo4j_to_graphdata.py")
        _spec = importlib.util.spec_from_file_location("export_neo4j_to_graphdata", _exp_path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)

        _js_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../graph_data.js")
        _js_path = os.path.normpath(_js_path)

        import neo4j_client as _nc
        _client = _nc.Neo4jClient()
        _graph = _client.export_graph()
        _client.close()
        _mod.write_graph_data_js(_graph, _js_path)
    except Exception as e:
        print(f"❌ graph_data.js エクスポート中にエラー: {e}")


if __name__ == "__main__":
    main()
