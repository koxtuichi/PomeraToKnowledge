"""
study_analyzer.py
-----------------
勉強記録を Neo4j から取得し、study_report.json を生成するスクリプト。

データフロー:
  Neo4j (type=勉強記録 / type=問題（学習）) → 集計・問題生成 → study_report.json

出力形式:
{
  "generated_at": "ISO8601",
  "subjects": [科目別集計（習熟度・学習回数・未解決疑問）],
  "quiz": [Gemini APIが生成した問題・ヒント],
  "study_blog_ideas": [勉強内容を活かしたブログアイデア],
  "weekly_summary": "今週の学習サマリー"
}
"""

import os
import json
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List

import requests

# ── 設定 ──
API_KEY = os.getenv("GOOGLE_API_KEY")
OUTPUT_FILE = "study_report.json"
_DEFAULT_MODEL = "gemini-2.0-flash"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Neo4j からデータ取得
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_study_nodes_from_neo4j() -> List[Dict[str, Any]]:
    """Neo4jClient.export_graph() を使い、type=勉強記録 のノードを返す。"""
    try:
        # scripts/ ディレクトリが sys.path に入っていない場合に備える
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)

        import neo4j_client as _nc
        client = _nc.Neo4jClient()
        graph = client.export_graph()
        client.close()

        study_nodes = [n for n in graph.get("nodes", []) if n.get("type") == "勉強記録"]
        question_nodes = [n for n in graph.get("nodes", []) if n.get("type") == "問題（学習）"]
        print(f"✅ Neo4j から 勉強記録 {len(study_nodes)} 件, 問題 {len(question_nodes)} 件 取得")
        return study_nodes, question_nodes

    except Exception as e:
        print(f"⚠️ Neo4j 取得失敗: {e}")
        # ローカルフォールバック: study_drafts/ ディレクトリのテキストファイルから簡易生成
        return _fallback_from_files(), []


def _fallback_from_files() -> List[Dict[str, Any]]:
    """Neo4j が使えない場合、study_drafts/ から簡易ノードを生成する。"""
    study_nodes = []
    drafts_dir = "study_drafts"
    if not os.path.exists(drafts_dir):
        return study_nodes

    for fname in sorted(os.listdir(drafts_dir)):
        if not fname.endswith(".txt"):
            continue
        fpath = os.path.join(drafts_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                body = f.read().strip()
            # ファイル名から科目を推測（例: 20260319_STUDY_TypeScript.txt → TypeScript）
            parts = fname.replace(".txt", "").split("_STUDY_")
            subject = parts[-1] if len(parts) > 1 else "不明"
            node = {
                "id": f"勉強記録:{subject}:{fname[:8]}",
                "type": "勉強記録",
                "label": f"{subject} の勉強記録",
                "subject": subject,
                "detail": body[:500],
                "date": f"{fname[:4]}-{fname[4:6]}-{fname[6:8]}",
                "mastery": 0.5,
                "key_concepts": [],
                "questions": [],
                "learning_type": "その他",
            }
            study_nodes.append(node)
        except Exception:
            pass

    print(f"📂 フォールバック: study_drafts/ から {len(study_nodes)} 件生成")
    return study_nodes


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Gemini API ユーティリティ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def call_gemini_api(prompt: str, model: str = _DEFAULT_MODEL, max_retries: int = 3) -> str:
    if not API_KEY:
        raise ValueError("GOOGLE_API_KEY が未設定です。")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    params = {"key": API_KEY}
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }

    import time
    for attempt in range(max_retries + 1):
        response = requests.post(url, headers=headers, json=data, params=params)
        if response.status_code == 200:
            break
        elif response.status_code == 429 and attempt < max_retries:
            wait = 30 * (2 ** attempt)
            print(f"⏳ レートリミット。{wait}秒後リトライ ({attempt+1}/{max_retries})...")
            time.sleep(wait)
        else:
            raise Exception(f"API Error: {response.status_code} - {response.text}")

    result = response.json()
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return "{}"


def call_gemini_json(prompt: str) -> Any:
    """Gemini を呼び出してJSONをパースして返す。失敗時は空オブジェクト。"""
    try:
        raw = call_gemini_api(prompt)
        import re
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'```\s*$', '', cleaned).strip()
        return json.loads(cleaned)
    except Exception as e:
        print(f"⚠️ Gemini JSON 解析失敗: {e}")
        return {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 集計
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def aggregate_subjects(study_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """科目別に習熟度・学習回数・未解決疑問数を集計する。"""
    subjects: Dict[str, Dict[str, Any]] = {}

    for node in study_nodes:
        subj = node.get("subject") or node.get("label", "不明")
        if subj not in subjects:
            subjects[subj] = {
                "subject": subj,
                "count": 0,
                "mastery_sum": 0.0,
                "unsolved_questions": [],
                "key_concepts": [],
                "last_studied": "",
            }
        s = subjects[subj]
        s["count"] += 1
        s["mastery_sum"] += float(node.get("mastery") or 0.5)

        # 未解決疑問
        qs = node.get("questions") or []
        if isinstance(qs, str):
            try:
                qs = json.loads(qs)
            except Exception:
                qs = [qs]
        s["unsolved_questions"].extend(qs)

        # 概念
        kc = node.get("key_concepts") or []
        if isinstance(kc, str):
            try:
                kc = json.loads(kc)
            except Exception:
                kc = [kc]
        s["key_concepts"].extend(kc)

        # 最終学習日
        date = node.get("date", "")
        if date > s["last_studied"]:
            s["last_studied"] = date

    result = []
    for subj, s in subjects.items():
        avg_mastery = round(s["mastery_sum"] / s["count"], 2) if s["count"] > 0 else 0.0
        result.append({
            "subject": subj,
            "count": s["count"],
            "mastery": avg_mastery,
            "unsolved_question_count": len(s["unsolved_questions"]),
            "unsolved_questions": list(set(s["unsolved_questions"]))[:5],
            "key_concepts": list(set(s["key_concepts"]))[:10],
            "last_studied": s["last_studied"],
        })

    result.sort(key=lambda x: x["last_studied"], reverse=True)
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 問題生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_quiz(study_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Gemini API を使って学習内容から問題を生成する。"""
    if not study_nodes:
        return []
    if not API_KEY:
        print("⚠️ GOOGLE_API_KEY 未設定。クイズ生成をスキップします。")
        return []

    # 勉強内容を要約してプロンプトに渡す
    study_summaries = []
    for node in study_nodes[:10]:  # 最大10件
        subj = node.get("subject", node.get("label", "不明"))
        concepts = node.get("key_concepts") or []
        if isinstance(concepts, str):
            try:
                concepts = json.loads(concepts)
            except Exception:
                concepts = [concepts]
        detail = node.get("detail", "")[:300]
        study_summaries.append(f"- 科目: {subj}\n  概念: {', '.join(concepts[:5]) if concepts else '記載なし'}\n  内容: {detail}")

    summaries_str = "\n".join(study_summaries)

    prompt = f"""あなたは教育の専門家です。以下の勉強記録を参考に、理解度を確認するための問題を3〜5件生成してください。

### 勉強記録
{summaries_str}

### 出力形式
JSON配列で出力してください。各要素は以下の形式:
[
  {{
    "subject": "科目名",
    "question": "問題文（日本語）",
    "hint": "解答のヒント（1文）",
    "answer": "模範解答（1〜3文）",
    "difficulty": "易/中/難"
  }}
]

JSON配列のみ出力してください。それ以外のテキストは不要です。"""

    print("🤖 クイズを生成中...")
    result = call_gemini_json(prompt)
    if isinstance(result, list):
        print(f"✅ クイズ {len(result)} 件を生成しました")
        return result
    return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ブログアイデア生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_study_blog_ideas(study_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """勉強内容を活かしたブログ記事アイデアを生成する。"""
    if not study_nodes:
        return []
    if not API_KEY:
        print("⚠️ GOOGLE_API_KEY 未設定。ブログアイデア生成をスキップします。")
        return []

    study_summaries = []
    for node in study_nodes[:8]:
        subj = node.get("subject", node.get("label", "不明"))
        detail = node.get("detail", "")[:200]
        study_summaries.append(f"- 科目: {subj} / 内容: {detail}")

    summaries_str = "\n".join(study_summaries)

    prompt = f"""あなたはテックブロガーです。以下の勉強記録を元に、読者が興味を持つブログ記事のアイデアを2〜3件提案してください。

### 勉強記録
{summaries_str}

### 出力形式
JSON配列で出力してください:
[
  {{
    "title": "クリックしたくなるタイトル",
    "theme": "記事のテーマ",
    "hook": "冒頭の引きになる一文",
    "readiness": "高/中/低"
  }}
]

JSON配列のみ出力してください。"""

    print("🤖 勉強ブログアイデアを生成中...")
    result = call_gemini_json(prompt)
    if isinstance(result, list):
        print(f"✅ ブログアイデア {len(result)} 件を生成しました")
        return result
    return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 週次サマリー生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_weekly_summary(study_nodes: List[Dict[str, Any]], subjects: List[Dict[str, Any]]) -> str:
    """今週の学習内容のサマリーを生成する。"""
    if not study_nodes:
        return "今週の勉強記録はありません。"
    if not API_KEY:
        # APIキーなし時は簡易サマリーを返す
        subject_names = list(set(n.get("subject", "不明") for n in study_nodes))
        return f"今週は {', '.join(subject_names)} を学習しました（計 {len(study_nodes)} セッション）。"

    # 今週のノードに絞る
    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    recent_nodes = [n for n in study_nodes if (n.get("date") or "") >= week_start]
    if not recent_nodes:
        recent_nodes = study_nodes[:5]

    subj_summary = "\n".join([
        f"- {s['subject']}: 習熟度 {s['mastery']}, {s['count']} 回学習, 未解決疑問 {s['unsolved_question_count']} 件"
        for s in subjects[:5]
    ])

    prompt = f"""以下の今週の学習状況を元に、学習者を励ます簡潔なサマリーを150文字以内で書いてください。

### 科目別まとめ
{subj_summary}

### 学習セッション数
{len(recent_nodes)} セッション

JSON形式で返してください:
{{"summary": "サマリー文章"}}"""

    result = call_gemini_json(prompt)
    if isinstance(result, dict) and result.get("summary"):
        return result["summary"]
    return f"今週は {len(recent_nodes)} セッションの学習を記録しました。"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ブログ記事一覧収集
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _collect_recent_reviews(reviews_dir: str = "study_reviews", limit: int = 20) -> List[Dict[str, Any]]:
    """study_reviews/ にあるレビューJSONを日付降順で収集して返す。"""
    reviews = []
    if not os.path.exists(reviews_dir):
        return reviews

    for fname in sorted(os.listdir(reviews_dir), reverse=True):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(reviews_dir, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            reviews.append(data)
        except Exception:
            pass
        if len(reviews) >= limit:
            break

    return reviews


def _collect_recent_study_articles(blog_ready_dir: str = "blog_ready", limit: int = 10) -> List[Dict[str, Any]]:
    """blog_ready/ にある type=study_article のメタデータを収集して返す。"""
    articles = []
    if not os.path.exists(blog_ready_dir):
        return articles

    for fname in sorted(os.listdir(blog_ready_dir), reverse=True):
        if not fname.endswith(".json"):
            continue
        meta_path = os.path.join(blog_ready_dir, fname)
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("type") == "study_article":
                articles.append({
                    "title": meta.get("title", "無題"),
                    "subject": meta.get("subject", ""),
                    "generated_at": meta.get("generated_at", ""),
                    "estimated_read_time": meta.get("estimated_read_time", ""),
                    "categories": meta.get("categories", []),
                    "description": meta.get("description", ""),
                })
        except Exception:
            pass

        if len(articles) >= limit:
            break

    return articles


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    print("📚 study_analyzer.py を開始します...")

    # 1. Neo4j から勉強ノードを取得
    study_nodes, question_nodes = fetch_study_nodes_from_neo4j()

    if not study_nodes:
        print("⚠️ 勉強記録ノードが見つかりませんでした。study_report.json を空で生成します。")
        report = {
            "generated_at": datetime.now().isoformat(),
            "subjects": [],
            "quiz": [],
            "study_blog_ideas": [],
            "weekly_summary": "勉強記録がまだありません。[STUDY]で始まる件名でメールを送ってみてください。",
        }
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"✅ {OUTPUT_FILE} を生成しました（空）")
        return

    # 2. 科目別集計
    print("📊 科目別集計中...")
    subjects = aggregate_subjects(study_nodes)

    # 3. 問題生成
    quiz = generate_quiz(study_nodes)

    # 4. ブログアイデア生成
    blog_ideas = generate_study_blog_ideas(study_nodes)

    # 5. 週次サマリー
    weekly_summary = generate_weekly_summary(study_nodes, subjects)

    # 6. 生成済みブログ記事一覧（blog_ready/ の study_article type）
    recent_study_articles = _collect_recent_study_articles()

    # 7. 最近のレビュー一覧（study_reviews/）
    recent_reviews = _collect_recent_reviews()

    # 8. レポート生成
    report = {
        "generated_at": datetime.now().isoformat(),
        "subjects": subjects,
        "quiz": quiz,
        "study_blog_ideas": blog_ideas,
        "weekly_summary": weekly_summary,
        "recent_study_articles": recent_study_articles,
        "recent_reviews": recent_reviews,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"✅ {OUTPUT_FILE} を生成しました")
    print(f"   科目数: {len(subjects)}")
    print(f"   クイズ: {len(quiz)} 件")
    print(f"   ブログアイデア: {len(blog_ideas)} 件")
    print(f"   週次サマリー: {weekly_summary[:50]}...")


if __name__ == "__main__":
    main()
