#!/usr/bin/env python3
"""Generate Pomera-driven note drafts from Neo4j diary material.

This pipeline turns diary analysis into small, reusable writing recipes.
It deliberately avoids selling prompts: each article is a human-facing
thinking pattern with concrete steps.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GUIDE = ROOT_DIR / "config" / "pomera_daily_weekday_guide.json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "note_recipe_ready"
DEFAULT_MANIFEST = ROOT_DIR / "note_recipe_manifest.json"
NEO4J_STOP_EXIT_CODE = 10
NEO4J_NO_DIARY_EXIT_CODE = 11
SOURCE_PRIORITY = ["neo4j"]


THEME_KEYWORDS = {
    "work": [
        "仕事",
        "業務",
        "タスク",
        "会議",
        "MTG",
        "提案",
        "進捗",
        "Knowbe",
        "Saiteki",
        "プロジェクト",
        "稼働",
    ],
    "publishing": [
        "note",
        "ブログ",
        "発信",
        "記事",
        "読者",
        "収益化",
        "副業",
        "販売",
        "はてな",
    ],
    "relationships": [
        "妻",
        "夫婦",
        "家族",
        "子ども",
        "育児",
        "パートナー",
        "関係",
        "会話",
        "信頼",
        "沙也",
        "さやか",
        "蒼馬",
    ],
    "health_money": [
        "体重",
        "健康",
        "ダイエット",
        "食事",
        "ラーメン",
        "睡眠",
        "お金",
        "家計",
        "収入",
        "税金",
        "貯金",
        "支出",
        "給与",
    ],
    "life": [
        "生活",
        "習慣",
        "朝",
        "夜",
        "掃除",
        "時間",
        "予定",
        "買い物",
        "日常",
    ],
    "creation": [
        "創作",
        "絵",
        "描",
        "YouTube",
        "動画",
        "モンスター",
        "アイディア",
        "ネタ",
        "ポメラ",
        "書く",
    ],
    "unblock": [
        "不安",
        "迷い",
        "停滞",
        "重い",
        "困",
        "詰ま",
        "悩",
        "ブレーキ",
        "できない",
        "はかどらない",
    ],
    "self_understanding": [
        "気づき",
        "価値観",
        "感情",
        "自信",
        "内省",
        "理解",
        "振り返",
        "自己",
        "思考",
    ],
    "review": ["週", "今月", "前進", "達成", "進ん", "完了", "変化", "振り返"],
}

MATERIAL_THEME_KEYWORDS = {
    **THEME_KEYWORDS,
    "work": [
        "仕事",
        "業務",
        "会議",
        "MTG",
        "提案",
        "Knowbe",
        "Saiteki",
        "プロジェクト",
        "稼働",
    ],
}

SENSITIVE_REPLACEMENTS = {
    "沙也香": "パートナー",
    "沙也加": "パートナー",
    "さやか": "パートナー",
    "蒼馬": "子ども",
    "鍼治療": "体のケア",
    "治療": "ケア",
    "Knowbe": "仕事",
    "Saiteki": "別プロジェクト",
    "Slack": "チャット",
    "江頭": "関係者",
    "鈴木": "関係者",
    "小松田": "関係者",
    "直道": "知人",
}

QUALITY_BANNED_TERMS = [
    "プロンプト集",
    "以下の文章をAIに入力",
    "ChatGPTに渡す",
    "診断します",
    "治療",
    "うつです",
    "発達障害",
]

READER_WEAKENING_TERMS = [
    "全部埋める必要",
    "空欄を全部埋める必要",
    "最初は一つだけでも十分",
    "最初は一つだけで十分",
    "できる範囲で",
    "無理に",
    "大丈夫",
    "構いません",
    "気が向いたら",
    "余裕があれば",
    "完璧でなくていい",
]

ARTICLE_MIN_CHARS = 4000
ARTICLE_MAX_CHARS = 5000
LEGACY_ARTICLE_MIN_CHARS = 2000
LEGACY_ARTICLE_MAX_CHARS = 3000
CANDIDATE_PREFETCH_LIMIT = 12

ABSTRACT_LANGUAGE_REPLACEMENTS = {
    "重力": "行動を止めている理由",
    "引力": "何度も戻って見たくなる手応え",
    "同じ重さ": "急ぎのことと後でよいことの区別がつかない状態",
    "重さの正体": "手が止まっている理由",
    "頭の中で重く": "何から始めるかを選べない状態で",
    "重くなっているもの": "まだ行動に分けられていない材料",
}
ABSTRACT_LANGUAGE_TERMS = list(ABSTRACT_LANGUAGE_REPLACEMENTS)
CONCRETE_LANGUAGE_REQUIRED_SIGNALS = [
    "今日すぐ相手に伝えること",
    "今日中に確認だけすればいいこと",
    "数日かけて考えたほうがいいこと",
    "気になっているけれど、今触っても進まないこと",
    "今日の予定や会話に影響するもの",
    "明日でよいもの",
]
CONCRETE_ACTION_KEYWORDS = [
    "書く",
    "メモ",
    "確認",
    "決める",
    "整理",
    "送る",
    "見る",
    "分ける",
    "選ぶ",
    "作る",
    "切り出す",
    "箇条書き",
]
GENERIC_SEED_TERMS = [
    "進行中",
    "達成",
    "未着手",
    "購入済み",
    "今日の日記エントリ",
]

PRIMARY_REQUIRED_SECTIONS = [
    "## これは何か",
    "## 元になった記録",
    "## 問題はなにか",
    "## 背景",
    "## なにに困っているのか",
    "## 目指す状態",
    "## どのように対処すればいいのか",
    "## 書き込み欄",
    "## 今日の最小行動",
]

LEGACY_REQUIRED_SECTIONS = [
    "## 15分で書く5ステップ",
    "## 5分でやる最小行動",
]

THEME_ARTICLE_COPY = {
    "work": {
        "reader": "仕事で足が止まるとき、問題はやる気の不足ではなく、論点が混ざりすぎていることが多いです。急ぎの連絡、相手の期待、締切、まだ決めていない前提が一つの塊になると、頭の中では全部が同じ重さに見えます。",
        "lens": "この回では、仕事の重さを「今日決めること」と「今日は置いておくこと」に分けます。分けるだけで、いきなり成果を出さなくても前に進める余白ができます。",
        "warning": "完璧な計画を作る回ではありません。まずは、次の会話や作業に持ち込める小さな一文を作る回です。",
    },
    "publishing": {
        "reader": "発信が止まる日は、書く題材がないのではなく、題材を大きく扱いすぎていることがあります。経験をまとめようとするほど、立派な結論が必要に見えて、最初の一行が重くなります。",
        "lens": "この回では、日記の中にある違和感や小さな前進を、読者が使える一つの視点に変えます。完成記事ではなく、まず売れる小さな単位を見つけることが目的です。",
        "warning": "読者に見せる前から名作にしようとしないでください。今日は、続けるための最小単位を取り出します。",
    },
    "relationships": {
        "reader": "人間関係の引っかかりは、相手の言葉そのものよりも、自分の中に残った解釈で重くなることがあります。何が起きたか、何を期待したか、何を言えなかったかが混ざると、次の会話が少し怖くなります。",
        "lens": "この回では、相手を評価する前に、自分の中で止まっている言葉を見つけます。責めるためではなく、次に少し柔らかく話すための準備です。",
        "warning": "相手を変えるための回ではありません。自分が持ち帰ってしまった重さを、扱える大きさに戻す回です。",
    },
    "health_money": {
        "reader": "健康やお金の不安は、数字だけを見ると冷たく、感情だけを見ると大きくなりすぎます。だからこそ、事実と気持ちを分けて同じ紙に置くことが効きます。",
        "lens": "この回では、気になる数字や支出を責める材料ではなく、生活を調整するためのサインとして扱います。",
        "warning": "厳密な診断や家計設計ではありません。今日の自分が安心して動くための確認に絞ります。",
    },
    "life": {
        "reader": "生活が散らかっている感覚は、部屋や予定だけの問題ではありません。小さな未完了が積み重なると、自分の時間を自分で持てていない感じが強くなります。",
        "lens": "この回では、生活全体を立て直すのではなく、今日の自分に戻れる一点を探します。整える場所は小さいほど効果が見えやすくなります。",
        "warning": "理想の暮らしを作る回ではありません。今日の負荷を少し下げるための現実的な回です。",
    },
    "creation": {
        "reader": "創作やネタ出しは、気分が乗る日だけのものにすると続きません。日記の中には、まだ名前のない素材が残っています。出来事、言い回し、違和感、少し笑えたこと。そのままでは作品にならなくても、入口にはなります。",
        "lens": "この回では、日記を作品の完成形ではなく、素材置き場として読み直します。今日拾う素材を一つに決めます。",
        "warning": "すぐ完成させようとすると、せっかくの素材がまた大きくなります。今日は拾うところで区切ります。",
    },
    "unblock": {
        "reader": "詰まりを感じるとき、私たちはつい原因を一つに決めようとします。でも実際には、時間不足、情報不足、気まずさ、疲れが重なっているだけのことも多いです。",
        "lens": "この回では、詰まりを性格や能力の問題にせず、分解できる状態として扱います。ほどく対象を一つに絞ると、行動は急に軽くなります。",
        "warning": "大きな解決を狙う回ではありません。止まっている状態に、小さな出口を作る回です。",
    },
    "self_understanding": {
        "reader": "自分の気持ちを理解するのは、深く考え込むこととは少し違います。むしろ、頭の中で何度も回っている言葉を外に出して、距離を取ることから始まります。",
        "lens": "この回では、感情に正解を出すのではなく、今の自分が何に反応しているのかを見える形にします。",
        "warning": "最初は雑な言葉で外に出します。外に出た瞬間から、扱える材料に変わります。",
    },
    "review": {
        "reader": "振り返りが苦手な人ほど、できなかったことの確認会になりがちです。でも日記には、目立たない前進も残っています。会話した、調べた、少し迷いが減った。その粒を拾わないと、自分がずっと止まっているように感じます。",
        "lens": "この回では、一週間を採点するのではなく、見落としていた変化を拾います。前進を見つけると、次の一歩が責務ではなく続きになります。",
        "warning": "反省会にしすぎないでください。今日は、次週へ持っていく小さな証拠を見つける回です。",
    },
}


@dataclass
class DiaryCandidate:
    id: str
    date: str
    label: str
    detail: str
    analysis: dict[str, Any]
    themes: dict[str, float] = field(default_factory=dict)
    score: float = 0.0


@dataclass
class ArticleSlot:
    index: int
    day: str
    day_label: str
    preferred_themes: list[str]
    actual_theme: str
    fallback_theme: str
    diary: DiaryCandidate | None
    material: Any | None = None


@dataclass
class ArticleCandidate:
    diary: DiaryCandidate
    material: Any | None
    seed: dict[str, Any]
    score: float
    reasons: list[str] = field(default_factory=list)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        tmp_name = f.name
    os.replace(tmp_name, path)


def load_graph_from_neo4j() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT_DIR / "scripts"))
    from neo4j_client import Neo4jClient

    with Neo4jClient() as client:
        return client.export_graph()


def load_materials_from_neo4j(diary_ids: list[str]) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT_DIR / "scripts"))
    from neo4j_client import Neo4jClient
    from note_recipe_neo4j_queries import fetch_note_recipe_materials

    with Neo4jClient() as client:
        return fetch_note_recipe_materials(client, diary_ids)


def stop_report(reason: str, message: str, error: Exception | None = None) -> dict[str, Any]:
    report = {
        "status": "stopped",
        "reason": reason,
        "message": message,
        "source": "neo4j",
        "fallback_attempted": False,
        "fallback_policy": "JSON-LD と graph_data.js への代替生成は行わない",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if error is not None:
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
    return report


def print_stop_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)


def parse_analysis(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def normalize_date(value: str | None, node_id: str) -> str | None:
    if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    if value and re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", node_id)
    if match:
        return "-".join(match.groups())
    match = re.search(r"(\d{8})", node_id)
    if match:
        s = match.group(1)
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def collect_diaries(graph: dict[str, Any]) -> list[DiaryCandidate]:
    by_date: dict[str, list[DiaryCandidate]] = {}
    for node in graph.get("nodes", []):
        node_id = str(node.get("id", ""))
        node_type = node.get("type")
        if node_type not in ("日記", "diary") and not node_id.startswith("日記:"):
            continue
        date = normalize_date(node.get("date"), node_id)
        if not date:
            continue
        analysis = parse_analysis(node.get("analysis_content"))
        candidate = DiaryCandidate(
            id=node_id,
            date=date,
            label=str(node.get("label") or f"{date}の日記"),
            detail=str(node.get("detail") or ""),
            analysis=analysis,
        )
        by_date.setdefault(date, []).append(candidate)

    result = []
    for date, candidates in by_date.items():
        candidates.sort(
            key=lambda d: (
                bool(d.analysis),
                bool(re.fullmatch(r"日記:\d{4}-\d{2}-\d{2}", d.id)),
                len(d.detail),
            ),
            reverse=True,
        )
        result.append(candidates[0])
    return sorted(result, key=lambda d: d.date)


def flatten_analysis_text(diary: DiaryCandidate) -> str:
    chunks = [diary.label, diary.detail]
    analysis = diary.analysis
    for key in (
        "coach_comment",
        "gravity_map",
        "antigravity_actions",
        "insights",
        "emotion_flow",
        "blog_ideas",
        "blog_seeds",
        "knowbe",
        "saiteki",
    ):
        value = analysis.get(key)
        if value:
            chunks.append(json.dumps(value, ensure_ascii=False))
    return "\n".join(chunks)


def score_diary(diary: DiaryCandidate) -> DiaryCandidate:
    text = flatten_analysis_text(diary)
    themes: dict[str, float] = {}
    for theme, keywords in THEME_KEYWORDS.items():
        hit = 0
        for keyword in keywords:
            hit += text.count(keyword)
        if hit:
            themes[theme] = min(1.0, hit / 6.0)

    analysis = diary.analysis
    richness = 0.0
    richness += len(analysis.get("insights", []) or []) * 1.4
    richness += len(analysis.get("antigravity_actions", []) or []) * 1.2
    richness += len(analysis.get("gravity_map", []) or []) * 1.2
    richness += len(analysis.get("blog_ideas", []) or []) * 0.8
    richness += len(analysis.get("emotion_flow", []) or []) * 0.6
    if analysis.get("coach_comment"):
        richness += 1.0
    if diary.detail and diary.detail != "今日の日記エントリ":
        richness += min(2.0, len(diary.detail) / 80.0)
    if not analysis:
        richness *= 0.35

    diary.themes = themes or {"self_understanding": 0.2}
    diary.score = round(richness + sum(diary.themes.values()), 3)
    return diary


def neo4j_source_policy() -> dict[str, bool | str]:
    return {
        "primary": "neo4j",
        "fallback_to_jsonld": False,
        "fallback_to_graph_data": False,
    }


def normalize_manifest_source_policy(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest["source_priority"] = list(SOURCE_PRIORITY)
    manifest["source_policy"] = neo4j_source_policy()
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    return normalize_manifest_source_policy(
        load_json(
            path,
            {
                "version": 1,
                "source_priority": list(SOURCE_PRIORITY),
                "source_policy": neo4j_source_policy(),
                "used_diary_ids": [],
                "generated_weeks": [],
                "article_history": [],
                "last_run_at": None,
            },
        )
    )


def load_guide(path: Path) -> dict[str, Any]:
    guide = load_json(path, {})
    if not guide.get("weekdays"):
        raise ValueError(f"曜日ガイドが不正です: {path}")
    return guide


def choose_best_for_slot(
    candidates: list[DiaryCandidate], preferred: list[str]
) -> DiaryCandidate | None:
    if not candidates:
        return None
    for theme in preferred:
        themed = [diary for diary in candidates if diary.themes.get(theme, 0.0) > 0]
        if themed:
            return max(themed, key=lambda d: (d.themes.get(theme, 0.0), d.score, d.date))
    return max(candidates, key=lambda d: (d.score, d.date))


def slot_theme(diary: DiaryCandidate | None, preferred: list[str], fallback_theme: str) -> str:
    if not diary:
        return fallback_theme
    for theme in preferred:
        if diary.themes.get(theme, 0.0) > 0:
            return theme
    return max(diary.themes.items(), key=lambda item: item[1])[0]


def assemble_week(
    candidates: list[DiaryCandidate],
    guide: dict[str, Any],
    used_diary_ids: set[str],
    allow_reuse: bool = False,
) -> list[ArticleSlot]:
    pool = [
        score_diary(d)
        for d in candidates
        if allow_reuse or d.id not in used_diary_ids
    ]
    pool.sort(key=lambda d: (d.score, d.date), reverse=True)

    slots: list[ArticleSlot] = []
    remaining = list(pool)
    for index, weekday in enumerate(guide["weekdays"], start=1):
        preferred = weekday.get("preferred_themes", [])
        fallback_theme = weekday.get("fallback_theme", "next_step")
        diary = choose_best_for_slot(remaining, preferred)
        if diary:
            remaining = [d for d in remaining if d.id != diary.id]
        actual_theme = slot_theme(diary, preferred, fallback_theme)
        slots.append(
            ArticleSlot(
                index=index,
                day=weekday["day"],
                day_label=weekday["label"],
                preferred_themes=preferred,
                actual_theme=actual_theme,
                fallback_theme=fallback_theme,
                diary=diary,
            )
        )
    return slots


def sanitize_text(text: str) -> str:
    result = text
    for src, dst in ABSTRACT_LANGUAGE_REPLACEMENTS.items():
        result = result.replace(src, dst)
    result = result.replace("Knowbe MTG", "仕事のMTG")
    for src, dst in SENSITIVE_REPLACEMENTS.items():
        result = result.replace(src, dst)
    result = result.replace("関係者さん", "関係者")
    result = result.replace("知人さん", "知人")
    result = re.sub(r"(?<!皆)[一-龥]{1,4}さん", "関係者", result)
    result = re.sub(r"\d{4}年\d{1,2}月\d{1,2}日", "ある日", result)
    result = re.sub(r"\d{4}-\d{2}-\d{2}", "ある日", result)
    result = re.sub(r"\d{1,3}(?:,\d{3})*円", "具体的な金額", result)
    result = re.sub(r"\d+(?:\.\d+)?kg", "体重の数値", result)
    result = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "メールアドレス", result)
    return result.strip()


def short_sentence(text: str, max_len: int = 72) -> str:
    text = sanitize_text(re.sub(r"\s+", " ", text))
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "..."


def section_text(text: str, max_len: int = 420) -> str:
    text = sanitize_text(re.sub(r"\s+", " ", text))
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "..."


def theme_label(theme: str, guide: dict[str, Any]) -> str:
    return guide.get("theme_labels", {}).get(theme, theme)


def text_blob(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(text_blob(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(text_blob(item) for item in value)
    return str(value)


def theme_keyword_score(value: Any, theme: str) -> int:
    if theme in {"self_understanding", "review"}:
        return 1
    text = text_blob(value)
    return sum(1 for keyword in MATERIAL_THEME_KEYWORDS.get(theme, []) if keyword in text)


def theme_item(items: list[Any], theme: str) -> tuple[dict[str, Any], int]:
    candidates = [item for item in items if isinstance(item, dict)]
    if not candidates:
        return {}, 0
    scored = [(theme_keyword_score(item, theme), index, item) for index, item in enumerate(candidates)]
    score, _, item = max(scored, key=lambda row: (row[0], -row[1]))
    return (item, score) if score > 0 else (candidates[0], 0)


def pain_from_action(action: dict[str, Any]) -> str:
    target = text_blob(action.get("target_task"))
    effect = text_blob(action.get("effect"))
    if "MTG" in target or "会議" in effect:
        return "会議前に話す論点と時間配分を絞りきれていない。"
    if target:
        return f"{target}の入口がまだ決まっていない。"
    return effect


def desired_from_action(action: dict[str, Any]) -> str:
    target = text_blob(action.get("target_task"))
    effect = text_blob(action.get("effect"))
    if "MTG" in target or "会議" in effect:
        return "打ち合わせで話す3項目が見えていて、終わったら次の予定に戻れる。"
    if effect:
        return effect
    return ""


def material_matches_theme(material: Any, theme: str) -> bool:
    if material is None:
        return False
    if theme in {"self_understanding", "review"}:
        return True
    values = [
        getattr(material, "problem", ""),
        getattr(material, "background", ""),
        getattr(material, "desired_state", ""),
        getattr(material, "current_status", ""),
        getattr(material, "next_step", ""),
        " ".join(getattr(material, "pain_points", []) or []),
        " ".join(getattr(material, "evidence", []) or []),
    ]
    return theme_keyword_score(values, theme) > 0


def material_to_seed(material: Any) -> dict[str, Any]:
    return {
        "problem": section_text(getattr(material, "problem", ""), 220),
        "background": section_text(getattr(material, "background", ""), 360),
        "pain_points": [
            section_text(item, 120)
            for item in (getattr(material, "pain_points", []) or [])[:4]
        ],
        "desired_state": section_text(getattr(material, "desired_state", ""), 220),
        "current_status": section_text(getattr(material, "current_status", ""), 220),
        "next_step": section_text(getattr(material, "next_step", ""), 220),
        "evidence": [
            section_text(item, 160)
            for item in (getattr(material, "evidence", []) or [])[:4]
        ],
        "situation": section_text(
            getattr(material, "current_status", "") or getattr(material, "background", ""),
            220,
        ),
        "finding": section_text(
            getattr(material, "desired_state", "") or getattr(material, "problem", ""),
            220,
        ),
        "action": section_text(getattr(material, "next_step", ""), 220),
    }


def diary_to_seed(diary: DiaryCandidate | None, theme: str) -> dict[str, Any]:
    if not diary:
        return {
            "problem": "何から考え始めればいいか分からない。",
            "background": "忙しさの中で、急ぎの用事、あとで考えること、ただ気になっていることの仕分けが外れている。",
            "pain_points": ["時間が足りない", "情報が混ざっている", "次の一歩が見えない"],
            "desired_state": "今日の自分が少し動ける状態にする。",
            "current_status": "考える材料が頭の中に残っている。",
            "next_step": "今日の5分だけで決める一歩を1つ書く。",
            "evidence": [],
            "situation": "何から考え始めればいいか分からない状態。",
            "finding": "まず書く入口を小さくすると、行動の一歩を決めやすくなる。",
            "action": "今日の5分だけで決める一歩を1つ書く。",
        }

    analysis = diary.analysis
    gravity_map = analysis.get("gravity_map") or []
    actions = analysis.get("antigravity_actions") or []
    insights = analysis.get("insights") or []
    emotions = analysis.get("emotion_flow") or []
    selected_gravity, gravity_score = theme_item(gravity_map, theme)
    selected_action, action_score = theme_item(actions, theme)
    selected_insight, insight_score = theme_item(insights, theme)

    situation = diary.detail if diary.detail and diary.detail != "今日の日記エントリ" else ""
    if gravity_score:
        situation = selected_gravity.get("net_assessment") or selected_gravity.get("task") or situation
    elif action_score:
        situation = selected_action.get("target_task") or selected_action.get("effect") or situation
    if not situation:
        situation = analysis.get("coach_comment", "")

    finding = ""
    if action_score:
        finding = desired_from_action(selected_action)
    if not finding and selected_insight and (insight_score or theme in {"self_understanding", "review"}):
        finding = selected_insight.get("finding") or selected_insight.get("implication") or ""
    if not finding and emotions:
        finding = f"{emotions[0].get('emotion', '感情')}が思考の入口になっている。"
    if not finding:
        finding = "急ぎの用事、あとで考えること、ただ気になっていることを分けると、次の一歩を決めやすくなる。"

    action = ""
    if selected_action and (action_score or theme in {"self_understanding", "review"}):
        action = selected_action.get("action") or selected_action.get("effect") or ""
    if not action:
        action = "いま一番軽くできる一歩を、5分以内に終わる形で書く。"

    pain_points = []
    if gravity_score:
        pain_points = [
            section_text(item.get("name", ""), 120)
            for item in (selected_gravity.get("constraints") or [])
            if item.get("name")
        ][:4]
    if not pain_points and action_score:
        pain = pain_from_action(selected_action)
        if pain:
            pain_points = [section_text(pain, 120)]

    evidence = []
    if diary.detail and diary.detail != "今日の日記エントリ":
        evidence.append(f"日記には、{section_text(diary.detail, 120)} という出来事の並びが残っている。")
    if action_score and selected_action and selected_action.get("action"):
        evidence.append(f"次の行動として、{section_text(selected_action['action'], 120)} が抽出されている。")
    if gravity_score and selected_gravity and (selected_gravity.get("task") or selected_gravity.get("net_assessment")):
        evidence.append(
            "手が止まっている場所として、"
            f"{section_text(selected_gravity.get('task') or selected_gravity.get('net_assessment'), 120)} "
            "が抽出されている。"
        )
    if not evidence and finding:
        evidence.append(section_text(finding, 160))

    return {
        "problem": section_text(situation, 220),
        "background": section_text(diary.detail or analysis.get("coach_comment", ""), 360),
        "pain_points": pain_points,
        "desired_state": section_text(finding, 220),
        "current_status": section_text(situation, 220),
        "next_step": section_text(action, 220),
        "evidence": evidence[:4],
        "situation": section_text(situation, 220),
        "finding": section_text(finding, 220),
        "action": section_text(action, 220),
    }


def extract_seed(slot: ArticleSlot) -> dict[str, Any]:
    material = slot.material
    if material_matches_theme(material, slot.actual_theme):
        return material_to_seed(material)
    return diary_to_seed(slot.diary, slot.actual_theme)


def theme_article_copy(theme: str) -> dict[str, str]:
    return THEME_ARTICLE_COPY.get(
        theme,
        {
            "reader": "忙しい日ほど、問題は一つに見えて、実際には複数の小さな負荷が重なっています。そのまま考え続けると、何から始めればいいか分からなくなります。",
            "lens": "この回では、頭の中で固まっているものを紙の上に出し、今日扱う一つだけに絞ります。",
            "warning": "大きな結論を急ぐ回ではありません。まずは、次に動ける形まで軽くする回です。",
        },
    )


def count_filled(values: list[Any]) -> int:
    return sum(1 for value in values if text_blob(value).strip())


def seed_readiness_score(seed: dict[str, Any]) -> float:
    score = 0.0
    score += count_filled(
        [
            seed.get("problem"),
            seed.get("background"),
            seed.get("desired_state"),
            seed.get("next_step"),
        ]
    ) * 1.2
    score += len(seed.get("pain_points") or []) * 0.8
    score += len(seed.get("evidence") or []) * 0.5
    if seed.get("next_step"):
        score += 1.0
    problem = text_blob(seed.get("problem"))
    next_step = text_blob(seed.get("next_step"))
    desired = text_blob(seed.get("desired_state"))
    current = text_blob(seed.get("current_status"))
    if problem and next_step and problem == next_step:
        score -= 8.0
    if desired and current and desired == current:
        score -= 1.5
    if any(value in GENERIC_SEED_TERMS for value in (problem, next_step, desired, current)):
        score -= 2.0
    if "今年は「革命の年」" in problem or "今年は「革命の年」" in next_step:
        score -= 2.0
    if next_step and not any(keyword in next_step for keyword in CONCRETE_ACTION_KEYWORDS):
        score -= 3.0
    return score


def best_seed_for_diary(diary: DiaryCandidate, material: Any | None, theme: str) -> dict[str, Any]:
    diary_seed = diary_to_seed(diary, theme)
    if material is None:
        return diary_seed
    material_seed = material_to_seed(material)
    if seed_readiness_score(material_seed) >= seed_readiness_score(diary_seed) + 1.5:
        return material_seed
    return diary_seed


def candidate_title(candidate: ArticleCandidate) -> str:
    problem = candidate.seed.get("problem") or candidate.seed.get("situation") or "忙しい日の思考整理"
    if "MTG" in problem or "会議" in problem:
        return "忙しい日でも、ポメラで次の会話を軽くする"
    if "ブログ" in problem or "発信" in problem or "note" in problem:
        return "日記から、今日書ける発信の一文を取り出す"
    if "家族" in problem or "予定" in problem:
        return "予定が重なる日に、自分の一歩を見失わない"
    return "忙しい日でも、ポメラで次の一歩を決める"


def score_article_candidate(diary: DiaryCandidate, material: Any | None) -> ArticleCandidate:
    theme = max(score_diary(diary).themes.items(), key=lambda item: item[1])[0]
    seed = best_seed_for_diary(diary, material, theme)
    pain_points = seed.get("pain_points") or []
    evidence = seed.get("evidence") or []
    reasons = []
    score = diary.score

    filled = count_filled(
        [
            seed.get("problem"),
            seed.get("background"),
            seed.get("desired_state"),
            seed.get("next_step"),
        ]
    )
    score += filled * 1.4
    if seed.get("problem"):
        reasons.append("問題が具体的")
    if seed.get("background"):
        reasons.append("背景が追える")
    if pain_points:
        score += len(pain_points) * 0.9
        reasons.append("困りごとが複数ある")
    if evidence:
        score += len(evidence) * 0.7
        reasons.append("根拠がある")
    if seed.get("next_step"):
        score += 1.4
        reasons.append("次の一歩がある")

    vague = ["進行中", "達成", "未着手", "今日の日記エントリ"]
    if any(seed.get(key, "") in vague for key in ("problem", "current_status", "situation")):
        score -= 2.0
    if not pain_points:
        score -= 1.0

    return ArticleCandidate(
        diary=diary,
        material=material,
        seed=seed,
        score=round(score, 3),
        reasons=reasons[:4],
    )


def choose_article_candidate(
    diaries: list[DiaryCandidate],
    material_map: dict[str, Any],
    used_diary_ids: set[str],
    allow_reuse: bool = False,
) -> ArticleCandidate | None:
    candidates = [
        score_article_candidate(diary, material_map.get(diary.id))
        for diary in diaries
        if allow_reuse or diary.id not in used_diary_ids
    ]
    if not candidates and not allow_reuse:
        candidates = [
            score_article_candidate(diary, material_map.get(diary.id))
            for diary in diaries
        ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.score, item.diary.date))


def visible_character_count(markdown: str) -> int:
    visible = re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL)
    visible = re.sub(r"[#*_>`\\[\\]()]", "", visible)
    return len(re.sub(r"\s+", "", visible))


def seed_concrete_checks(seed: dict[str, Any] | None) -> dict[str, Any]:
    if seed is None:
        return {"passed": False, "reason": "missing_seed"}

    fields = {
        "problem": text_blob(seed.get("problem")),
        "background": text_blob(seed.get("background")),
        "desired_state": text_blob(seed.get("desired_state")),
        "next_step": text_blob(seed.get("next_step")),
    }
    missing_fields = [key for key, value in fields.items() if not value.strip()]
    generic_fields = [
        key
        for key, value in fields.items()
        if value.strip() in GENERIC_SEED_TERMS
    ]
    next_step = fields["next_step"]
    action_ok = any(keyword in next_step for keyword in CONCRETE_ACTION_KEYWORDS)
    action_size_ok = len(next_step) >= 12
    evidence_items = [
        text_blob(item)
        for item in (seed.get("evidence") or [])
        if text_blob(item).strip()
    ]
    evidence_ok = len(evidence_items) >= 2
    distinct_ok = bool(fields["problem"]) and fields["problem"] not in {
        fields["desired_state"],
        fields["next_step"],
    }
    passed = (
        not missing_fields
        and not generic_fields
        and action_ok
        and action_size_ok
        and evidence_ok
        and distinct_ok
    )
    return {
        "passed": passed,
        "missing_fields": missing_fields,
        "generic_fields": generic_fields,
        "next_step_action_ok": action_ok,
        "next_step_size_ok": action_size_ok,
        "evidence_count": len(evidence_items),
        "evidence_ok": evidence_ok,
        "distinct_problem_ok": distinct_ok,
    }


def display_path(path: Path) -> str:
    absolute = path.resolve()
    try:
        return str(absolute.relative_to(ROOT_DIR))
    except ValueError:
        return str(absolute)


def recipe_title(slot: ArticleSlot, guide: dict[str, Any]) -> str:
    theme = theme_label(slot.actual_theme, guide)
    title_map = {
        "work": "仕事の重さを、今日の一歩に変える",
        "publishing": "発信が止まる日を、小さく再起動する",
        "relationships": "人間関係の引っかかりを、言葉にする",
        "health_money": "健康やお金の不安を、見える形にする",
        "life": "生活の散らかりを、ひとつだけ整える",
        "creation": "日記から創作と発信の種を拾う",
        "unblock": "今週の詰まりを、ひとつだけほどく",
        "self_understanding": "自分の中の重さに、名前をつける",
        "review": "前進を見落とさない週次レビュー",
    }
    return title_map.get(slot.actual_theme, f"{theme}ための10分")


def bullets(items: list[str], fallback: list[str]) -> str:
    values = [item for item in items if item] or fallback
    return "\n".join(f"- {item}" for item in values)


def render_primary_article(candidate: ArticleCandidate, run_id: str) -> str:
    seed = candidate.seed
    title = candidate_title(candidate)
    problem = seed.get("problem") or "何から考え始めればいいか分からない。"
    background = seed.get("background") or seed.get("situation") or "複数の予定や気がかりが同じ時間帯に重なっている。"
    current_status = seed.get("current_status") or seed.get("situation") or problem
    desired_state = seed.get("desired_state") or "今日の自分が、次の一歩を迷わず選べる状態。"
    next_step = seed.get("next_step") or seed.get("action") or "今日扱うことを一つだけ書く。"
    pain_lines = bullets(
        seed.get("pain_points") or [],
        [
            "急ぎの用事と、あとで考えればいいことの区別がついていない。",
            "次の会話や作業で何を確認するかが、頭の中だけに残っている。",
            "考える時間を伸ばせず、途中で別の予定に移る必要がある。",
        ],
    )
    evidence_lines = bullets(
        seed.get("evidence") or [],
        ["日記には、迷い、予定、次の行動につながる言葉が同じ日の記録として残っている。"],
    )

    return f"""# 100円｜{title}

<!-- free_part_start -->
考える時間がない日の問題は、時間そのものではありません。

本当に削られているのは、自分で判断する場所です。急ぎの連絡、あとで考える予定、ただ気になっている通知、家族や仕事の用事。これらが同じ場所に置かれると、実際には5分で動かせることまで、人生全体の問題のように見えてしまいます。

私はここにポメラ駆動の価値があると考えています。ポメラは文章を書く道具である前に、判断を取り戻すための小さな部屋です。この回では、日記に残った混雑を読み直し、今日の一文と行動に変えるところまで持っていきます。
<!-- free_part_end -->

<!-- paid_part_start -->
## これは何か
これは、忙しい日に自分の判断を取り戻すための、10分のポメラ駆動です。

目的は、きれいな計画を作ることではありません。頭の中で膨らんだ問題を、今日の自分が扱う一文まで切ることです。ここを曖昧にすると、日記はただの記録で終わります。書いたのに動けない。考えたのに戻れない。その状態を変えるために、ポメラを開きます。

日記には出来事だけでなく、迷い方が残ります。どこで止まったのか。何を言えなかったのか。何を後回しにしたのか。そこを拾うと、日記は過去ログではなく、今日の判断材料になります。

## 元になった記録
{background}

この記録から見える現在地は、{current_status} という状態です。

ここで見るべきなのは、出来事の要約ではありません。記録の奥にある「まだ行動に接続されていない判断」です。日記の価値は、過去を保存することだけにありません。今日の自分が戻れる場所を作ることにあります。

## 問題はなにか
問題は、{problem} という形で現れています。

これは、やる気の不足ではありません。判断の置き場所が失われている状態です。

今日すぐ相手に伝えること。

今日中に確認だけすればいいこと。

数日かけて考えたほうがいいこと。

気になっているけれど、今触っても進まないこと。

この4つが混ざると、優先順位は消えます。全部が「今すぐ考えるべきこと」に見える。けれど、同時には考えられない。だから手が止まります。私はこの止まり方を、単なる忙しさとして片付けたくありません。ここに、日記を読み直す理由があります。

## 背景
背景には、複数の予定や関心が同じ時間帯に重なっていることがあります。

仕事の確認、家族や生活の予定、発信や創作のアイディア、気になる数字や通知。それぞれは別の種類の話です。けれど、書き出さないまま抱えていると、種類の違いが見えなくなります。

スマホを開くと、材料は増えます。検索、通知、過去の投稿、別のタブ。材料が増えるほど、判断は薄まります。ポメラでやることは逆です。情報を増やさない。すでに頭の中にある材料だけを外に出し、種類ごとに分ける。これが、集中できる道具を使う意味です。

## なにに困っているのか
今回見えている困りごとは、主に次の通りです。

{pain_lines}

ここで困るのは、考える力がないからではありません。考える対象が大きすぎるからです。

「仕事を進める」「発信を続ける」「生活を整える」のような言葉は、大きすぎます。大きい言葉のままだと、何をすれば始まったことになるのかが見えません。

だから、ポメラでは一段小さくします。小さくするのは逃げではありません。行動へ接続するための編集です。

仕事なら、「次の会話で何を確認するか」。

発信なら、「今日のメモから一文だけ見出しにするなら何か」。

生活なら、「今日確認する数字や予定はどれか」。

小さくすると、行動につながります。

## 目指す状態
目指すのは、{desired_state} という状態です。

今日の予定を壊さず、次の会話や作業に入れるところまで進めます。ここで欲しいのは万能な解決策ではなく、今日の自分が使える判断です。

この回で目指すのは、頭の中の混雑を消し去ることではありません。今日扱うものと、明日に送るものを分けることです。

明日に送ることは、先延ばしではありません。

今日は扱わないと決めることです。

## どのように対処すればいいのか
ポメラを開いたら、次の順番で書きます。

1. いま頭に残っていることを、名詞で全部出す。
2. その中から、今日の予定や会話に影響するものを一つ選ぶ。
3. それを「次に使う一文」に変える。
4. 5分以内でできる行動に削る。
5. 明日でよいものを一行だけ書いて閉じる。

最初から文章にしません。名詞で出します。名詞にすると、頭の中で膨らんでいたものが机の上に置かれます。置かれたものは、選べます。

今回なら、次のように変換します。

- 大きいままの考え: {problem}
- 扱える形にした考え: {desired_state}
- 今日の最小行動: {next_step}

この変換で作るのは結論ではありません。行動の入口です。入口ができると、次に戻る場所ができます。戻る場所があるだけで、忙しい日の再起動は変わります。

## 判断の分け方
書き出したあとに見るのは、重要度だけではありません。

重要そうに見えることでも、今日さわる必要がないものはあります。逆に、小さく見えることでも、今日の予定や会話に影響するものは先に扱ったほうがいい場合があります。

ここでは、次の3つに分けます。

1つ目は、今日の予定に直接影響するものです。会議で話すこと、出発時間までに決めること、相手に返す一文などです。これは今日扱います。

2つ目は、大事だけれど今日でなくてよいものです。仕組みづくり、発信の設計、買い物や支払いの見直しなどです。これは明日に送ります。

3つ目は、気になっているだけのものです。通知の数字、動画の反応、あとで見ればいい情報などです。これは、いま見ないと決めます。

この3つに分けるだけで、書いたメモの読み方が変わります。全部を解決するためのリストではなく、今日扱うものを選ぶためのリストになります。

## 日記から拾えた根拠
今回の根拠は、次のような記録です。

{evidence_lines}

根拠は、完成した結論である必要はありません。むしろ途中の言葉に価値があります。違和感、止まった場所、少しだけ前に進んだ行動。そこに、次の一文の材料があります。

## 書き込み欄
- 頭に残っていること:
- 今日の予定や会話に影響するもの:
- 次に使う一文:
- 5分以内でやること:
- 明日でよいもの:

今日書くのは一つだけです。選ぶことで、思考を前に進めます。

特に大事なのは、「明日でよいもの」を書くことです。これを書かないと、頭の中ではいつまでも今日の問題として残ります。明日に送るものを決めると、今日扱う一つに集中できます。

## よくある失敗
一番多い失敗は、最初から正しい答えを書こうとすることです。

たとえば、いきなり「今後の発信戦略をどうするか」と書くと、問いが大きすぎます。読者、媒体、投稿頻度、収益化、ネタ管理まで広がります。これでは、10分では終わりません。

その場合は、「今日のメモから一文だけ見出しにするなら何か」に変えます。

仕事でも同じです。「この案件をどう進めるか」では大きすぎます。相手、期限、品質、役割分担、連絡手段まで入ってきます。

その場合は、「次の会話で何を確認するか」に変えます。

生活でも同じです。「家計を見直す」では大きすぎます。過去の支出、今月の請求、今後の貯金、買いたいものまで広がります。

その場合は、「今日確認する数字はどれか」に変えます。

問いを小さくするのは、弱めることではありません。行動に接続する形へ研ぐことです。

## なぜポメラでやるのか
この作業をスマホでやると、考える前に別の入口が開きます。通知を見る。検索する。過去の投稿を見る。関連する動画を見る。必要な情報を探していたはずなのに、気づくと別のことを考えています。

ポメラは、その逆です。

検索できない。通知も来ない。画像も流れてこない。できることは、ほとんど書くことだけです。

だから、外から材料を増やすのではなく、今ある材料を並べ替える道具として使えます。

忙しい日に必要なのは、正解を探すことではありません。

今ある材料の中から、今日使うものを選ぶことです。

## 書き終わりの合図
ポメラ駆動は、いつまでも書き続けるためのものではありません。

終わりの合図は、次の一文が書けたときです。

「次にやることは、これです」

この一文が書けたら、いったん閉じます。まだ考えたいことが残っていても、閉じます。

閉じることにも意味があります。考え続けるほど、また別のテーマが混ざってくるからです。ポメラを閉じることで、「今日扱うのはここまで」と区切りを作れます。

忙しい日の思考整理は、深さよりも区切りが大事です。

## 明日に送るメモ
最後に、明日に送るものを一行だけ残します。

「明日はここから考える」と書いておくと、翌日また同じところから悩み直さなくて済みます。

明日に送るメモは、短く書きます。長い説明より、次に開いた瞬間に動ける入口を残します。

たとえば「カード請求を見る」「発信自動化は土曜に考える」「動画の反応は夜だけ見る」のように、次に開いたときの入口をはっきりさせます。

今日やらないことにも、置き場所を作る。

これができると、今日の一歩が選びやすくなります。

書く目的は、すべてを片付けることではありません。今日の自分が迷わず戻れる場所を一つ作ることです。

その場所があるだけで、次に開いたときの再起動が少し楽になります。

迷ったまま終わるのではなく、戻る場所を決めて終わる。これが、忙しい日のポメラの役割です。

## 今日の最小行動
今日やることは、これだけです。

{next_step}

ここで終わらせます。次の一歩を決めたら、今日の判断は前に進んでいます。

忙しい日の勝ち方は、全部を片付けることではありません。今日の予定を壊さずに、次の一歩を決めることです。

ポメラ駆動は、気合いで人生を変える方法ではありません。

昨日まで頭の中に残っていたものを、今日の一文に変える方法です。

まずは、ポメラを開いてこう書いてください。

「今日、次に使う一文は何か」

答えを一つに決めます。
<!-- paid_part_end -->

<!-- source: neo4j diary / run {run_id} -->
"""


def render_article(slot: ArticleSlot, guide: dict[str, Any], week_id: str) -> str:
    seed = extract_seed(slot)
    title = recipe_title(slot, guide)
    theme = theme_label(slot.actual_theme, guide)
    copy = theme_article_copy(slot.actual_theme)
    pain_lines = "\n".join(
        f"- {item}" for item in (seed.get("pain_points") or ["次の一歩が見えない"])
    )
    evidence_lines = "\n".join(
        f"- {item}" for item in (seed.get("evidence") or [seed["finding"]])
    )

    return f"""# 100円｜今日のポメラ駆動: {title}

<!-- free_part_start -->
忙しい日ほど、考える前に次のタスクが来ます。

今日のテーマは「{theme}」です。目的は、完璧に整理することではありません。POMERA、紙、メモ帳のどれでもいいので、10分だけ書いて、今日の一歩を1つ残すことです。

無料部分では結論だけ置きます。頭の中で重くなっているものは、意志の弱さではなく、まだ分解されていない材料です。有料部分では、日記から拾った状況をもとに、同じように使える書き込み式のレシピにしています。
<!-- free_part_end -->

<!-- paid_part_start -->
## これは何か
これは、集中して書くための小さな思考レシピです。情報を増やすためではなく、頭の中の重さを外に出して、動ける形に変えるために使います。

日記は、その日の記録で終わらせると「書いたけれど、何も変わらなかった」で止まりがちです。けれど、日記には次の行動の材料が残っています。何に迷ったのか。どこで少し軽くなったのか。誰に何を言えなかったのか。そこを拾うと、日記は過去ログではなく、今日の自分を動かす道具になります。

## 元になった状況
{seed["background"] or seed["situation"]}

現在地は、{seed["current_status"] or seed["situation"]}という状態です。忙しいときほど、私たちは「やるべきこと」と「気になっていること」と「まだ言葉になっていない感情」を同じ場所に置いてしまいます。

## 問題はなにか
問題は、{seed["problem"]}という形で現れています。

これを性格や根性の問題にしないことが大事です。日記とグラフを見返すと、止まっている理由は一つではなく、背景、制約、未整理の判断が重なっています。

## なにに困っているのか
今回見えている引っかかりは、主に次の通りです。

{pain_lines}

{copy["reader"]}

ここで使う考え方は、重さを消すことではありません。重さを、扱える大きさに分けることです。気合いで押し切ると、次の日にまた同じ場所で止まります。だから今日は、考える対象を小さくして、行動の入口だけを作ります。

## 目指す状態
目指すのは、{seed["desired_state"] or seed["finding"]} という状態です。

{copy["lens"]}

日記から拾えた根拠は、次のようなものです。

{evidence_lines}

まず、今日の自分に問いを一つだけ置きます。

「これは本当に今すぐ全部やる必要があるのか。それとも、今日決める一部だけでいいのか」

この問いを置くだけで、頭の中の塊が少し崩れます。大事なのは、立派な答えを出すことではありません。紙の上に出した時点で、もう頭の中だけで抱えていた状態からは一歩進んでいます。

## 15分で書く5ステップ
1. いま一番気になっていることを、名詞で1つだけ書く。文章にする前に、対象を机の上に置きます。
2. その名詞の横に、重くしている理由を1つだけ書く。「時間」「人」「情報」「感情」「体力」のどれに近いかで選びます。
3. 次に、本当はどうなってほしいのかを一文で書きます。ここで向かう先を決めます。
4. 今日できる行動を、5分で終わる大きさまで削ります。連絡なら1通、調査なら1語、片付けなら1か所です。
5. 最後に、明日に残していいものを1つ書きます。残すものを決めると、今日やる一歩が軽くなります。

## 書き込み欄
- 気になっている名詞:
- 重くしている理由:
- 本当はどうなってほしいか:
- 今日5分でやること:
- 明日に残していいこと:

今日書く欄を一つに決めます。特に「重くしている理由」が書ければ、行動の入口が見えます。理由が分からないまま頑張ろうとすると、行動量だけ増えて疲れます。理由が見えれば、行動は小さくできます。

## 今日のサンプル変換
元の状況をそのまま抱えると、「ちゃんと考えなきゃ」で止まりやすくなります。そこで、次のように変換します。

- 大きいままの考え: {seed["situation"]}
- 扱える形にした考え: {seed["finding"]}
- 今日の最小行動: {seed["action"]}

この変換のポイントは、結論を急がないことです。日記から拾った材料を、次の行動に接続できる形へ置き直します。

## 使いどころ
- 考えることが多すぎて、最初の一手が見えないとき。
- 日記を書いたのに、行動に変わっていないと感じるとき。
- 忙しさの中で、自分の判断を一度外に出したいとき。

## つまずいたときの調整
書いている途中で手が止まったら、問いが大きすぎます。その場合は「今日だけ」「5分だけ」「一人でできることだけ」のどれかを足してください。

たとえば「今後どうするか」では大きすぎます。「今日、誰に何を一文だけ送るか」なら扱えます。「生活を整える」では大きすぎます。「机の上の一つだけ戻す」なら動けます。小さくするのは逃げではありません。続けるための技術です。

## 向かない場面
- すぐに専門家の判断が必要な問題。
- 誰かに送る文章をそのまま作りたい場面。
- 気持ちが強く揺れていて、まず休息や相談が必要な場面。

{copy["warning"]}

## 5分でやる最小行動
{seed["action"]}

この一歩をやったら、成果の大きさではなく「次に迷う場所が少し減ったか」で見てください。ポメラ駆動の価値は、派手な成果よりも、毎日少しずつ自分の判断材料が残っていくことにあります。

## 明日への持ち越し
今日の最後に、次の一文を書いて終わります。

「明日の自分は、ここから始めればいい」

この一文があると、翌日の再起動が楽になります。日記は毎日ゼロから書くものではなく、昨日の自分が残した足場から続けるものです。

## 今日の合言葉
全部を片付けなくていい。今日の一歩だけ、紙の外に出す。
<!-- paid_part_end -->
"""


def quality_check(
    markdown: str,
    slot: ArticleSlot | None = None,
    mode: str = "primary",
    seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    privacy_terms = [term for term in SENSITIVE_REPLACEMENTS if term in markdown]
    privacy_terms.extend(re.findall(r"(?<!皆)[一-龥]{1,4}さん", markdown))
    banned_terms = [term for term in QUALITY_BANNED_TERMS if term in markdown]
    reader_weakening_terms = [
        term for term in READER_WEAKENING_TERMS if term in markdown
    ]
    abstract_terms = [term for term in ABSTRACT_LANGUAGE_TERMS if term in markdown] if mode == "primary" else []
    concrete_signals = (
        [signal for signal in CONCRETE_LANGUAGE_REQUIRED_SIGNALS if signal in markdown]
        if mode == "primary"
        else []
    )
    concrete_signal_ok = mode == "weekly" or len(concrete_signals) >= 3
    seed_checks = (
        seed_concrete_checks(seed)
        if mode == "primary"
        else {"passed": True}
    )
    required_sections = (
        LEGACY_REQUIRED_SECTIONS if mode == "weekly" else PRIMARY_REQUIRED_SECTIONS
    )
    section_ok = all(section in markdown for section in required_sections)
    char_count = visible_character_count(markdown)
    min_chars = LEGACY_ARTICLE_MIN_CHARS if mode == "weekly" else ARTICLE_MIN_CHARS
    max_chars = LEGACY_ARTICLE_MAX_CHARS if mode == "weekly" else ARTICLE_MAX_CHARS
    length_ok = min_chars <= char_count <= max_chars
    source_traceability = bool(slot.diary) if slot is not None else "source: neo4j diary" in markdown
    return {
        "privacy": not privacy_terms,
        "privacy_terms": privacy_terms,
        "non_prompt_sale": not banned_terms,
        "banned_terms": banned_terms,
        "reader_commitment": not reader_weakening_terms,
        "reader_weakening_terms": reader_weakening_terms,
        "concrete_language": (not abstract_terms) and concrete_signal_ok and seed_checks["passed"],
        "abstract_terms": abstract_terms,
        "concrete_signals": concrete_signals,
        "concrete_signal_ok": concrete_signal_ok,
        "seed_concrete_checks": seed_checks,
        "section_ok": section_ok,
        "visible_char_count": char_count,
        "length_ok": length_ok,
        "length_range": [min_chars, max_chars],
        "source_traceability": source_traceability,
        "fallback": slot.diary is None if slot is not None else False,
        "passed": (
            (not privacy_terms)
            and (not banned_terms)
            and (not reader_weakening_terms)
            and (not abstract_terms)
            and concrete_signal_ok
            and seed_checks["passed"]
            and section_ok
            and length_ok
            and bool(source_traceability)
        ),
    }


def slug(index: int, day: str, theme: str) -> str:
    return f"{index:02d}_{day}_{theme}.md"


def primary_slug(candidate: ArticleCandidate) -> str:
    date = candidate.diary.date.replace("-", "")
    return f"{date}_single_longform.md"


def build_single_manifest(
    candidate: ArticleCandidate,
    article: dict[str, Any],
    run_id: str,
    considered_count: int,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "mode": "single",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "article": article,
        "selection": {
            "selected_diary_id": candidate.diary.id,
            "selected_date": candidate.diary.date,
            "score": candidate.score,
            "reasons": candidate.reasons,
            "considered_diary_count": considered_count,
        },
        "diary_coverage": {
            "source_diary_count": 1,
            "source_diary_ids": [candidate.diary.id],
            "fallback_count": 0,
        },
        "quality_checks": {
            "passed": article["quality"]["passed"],
            "items": [
                {
                    "article_id": article["article_id"],
                    "quality": article["quality"],
                }
            ],
        },
    }


def build_week_manifest(
    slots: list[ArticleSlot], articles: list[dict[str, Any]], week_id: str
) -> dict[str, Any]:
    source_ids = [slot.diary.id for slot in slots if slot.diary]
    theme_counts: dict[str, int] = {}
    for slot in slots:
        theme_counts[slot.actual_theme] = theme_counts.get(slot.actual_theme, 0) + 1
    return {
        "week_id": week_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "articles": articles,
        "theme_summary": theme_counts,
        "diary_coverage": {
            "source_diary_count": len(source_ids),
            "source_diary_ids": source_ids,
            "fallback_count": sum(1 for slot in slots if not slot.diary),
        },
        "quality_checks": {
            "passed": all(article["quality"]["passed"] for article in articles),
            "items": [
                {
                    "article_id": article["article_id"],
                    "quality": article["quality"],
                }
                for article in articles
            ],
        },
    }


def update_manifest(
    manifest: dict[str, Any],
    week_manifest: dict[str, Any],
    article_records: list[dict[str, Any]],
) -> dict[str, Any]:
    normalize_manifest_source_policy(manifest)
    used = set(manifest.get("used_diary_ids", []))
    used.update(week_manifest["diary_coverage"]["source_diary_ids"])
    manifest["used_diary_ids"] = sorted(used)
    week_id = week_manifest["week_id"]
    manifest["generated_weeks"] = [
        week
        for week in manifest.get("generated_weeks", [])
        if week.get("week_id") != week_id
    ]
    manifest["article_history"] = [
        article
        for article in manifest.get("article_history", [])
        if article.get("week_id") != week_id
    ]
    manifest.setdefault("generated_weeks", []).append(
        {
            "week_id": week_id,
            "article_ids": [a["article_id"] for a in article_records],
            "source_diary_ids": week_manifest["diary_coverage"]["source_diary_ids"],
            "fallback_count": week_manifest["diary_coverage"]["fallback_count"],
            "status": "drafted",
        }
    )
    manifest.setdefault("article_history", []).extend(article_records)
    manifest["last_run_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return manifest


def update_manifest_single(
    manifest: dict[str, Any],
    single_manifest: dict[str, Any],
    article_record: dict[str, Any],
) -> dict[str, Any]:
    normalize_manifest_source_policy(manifest)
    used = set(manifest.get("used_diary_ids", []))
    used.update(single_manifest["diary_coverage"]["source_diary_ids"])
    manifest["used_diary_ids"] = sorted(used)
    run_id = single_manifest["run_id"]
    manifest["generated_runs"] = [
        run
        for run in manifest.get("generated_runs", [])
        if run.get("run_id") != run_id
    ]
    manifest["article_history"] = [
        article
        for article in manifest.get("article_history", [])
        if article.get("run_id") != run_id
    ]
    manifest.setdefault("generated_runs", []).append(
        {
            "run_id": run_id,
            "article_id": article_record["article_id"],
            "source_diary_ids": single_manifest["diary_coverage"]["source_diary_ids"],
            "fallback_count": single_manifest["diary_coverage"]["fallback_count"],
            "status": "drafted",
        }
    )
    manifest.setdefault("article_history", []).append(article_record)
    manifest["last_run_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return manifest


def default_week_id() -> str:
    today = dt.date.today()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


def default_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def print_single_dry_run(candidate: ArticleCandidate, considered_count: int) -> None:
    print(
        json.dumps(
            {
                "mode": "single",
                "selected_diary_id": candidate.diary.id,
                "selected_date": candidate.diary.date,
                "score": candidate.score,
                "reasons": candidate.reasons,
                "considered_diary_count": considered_count,
                "title": candidate_title(candidate),
                "problem": candidate.seed.get("problem"),
                "next_step": candidate.seed.get("next_step"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def print_dry_run(slots: list[ArticleSlot], guide: dict[str, Any]) -> None:
    rows = []
    for slot in slots:
        rows.append(
            {
                "slot": slot.index,
                "day": slot.day_label,
                "preferred": [theme_label(t, guide) for t in slot.preferred_themes],
                "actual_theme": theme_label(slot.actual_theme, guide),
                "source_diary_id": slot.diary.id if slot.diary else None,
                "source_date": slot.diary.date if slot.diary else None,
                "score": slot.diary.score if slot.diary else None,
                "title": recipe_title(slot, guide),
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def run_weekly(args: argparse.Namespace, guide: dict[str, Any], manifest: dict[str, Any], candidates: list[DiaryCandidate]) -> int:
    used_ids = set(manifest.get("used_diary_ids", []))
    slots = assemble_week(candidates, guide, used_ids, allow_reuse=args.allow_reuse)

    if args.dry_run:
        print_dry_run(slots, guide)
        return 0

    diary_ids = [slot.diary.id for slot in slots if slot.diary]
    try:
        material_map = load_materials_from_neo4j(diary_ids)
    except Exception as e:
        print_stop_report(
            stop_report(
                "neo4j_material_query_failed",
                "Neo4jの関係性素材を取得できないため、note下書き生成を停止しました。",
                e,
            )
        )
        return NEO4J_STOP_EXIT_CODE
    for slot in slots:
        if slot.diary:
            slot.material = material_map.get(slot.diary.id)

    week_id = args.week_id or default_week_id()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT_DIR / args.output_dir
    week_dir = output_dir / week_id
    if week_dir.exists() and not args.overwrite:
        raise FileExistsError(f"出力先が既に存在します。--overwrite を指定してください: {week_dir}")
    if week_dir.exists() and args.overwrite:
        for path in week_dir.iterdir():
            if path.is_file():
                path.unlink()
    week_dir.mkdir(parents=True, exist_ok=True)

    articles = []
    article_records = []
    for slot in slots:
        article_id = f"pomera_daily_{week_id}_{slot.index:02d}"
        markdown = render_article(slot, guide, week_id)
        quality = quality_check(markdown, slot, mode="weekly")
        filename = slug(slot.index, slot.day, slot.actual_theme)
        path = week_dir / filename
        path.write_text(markdown, encoding="utf-8")
        record = {
            "article_id": article_id,
            "filename": filename,
            "title": recipe_title(slot, guide),
            "day": slot.day,
            "day_label": slot.day_label,
            "actual_theme": slot.actual_theme,
            "source_diary_ids": [slot.diary.id] if slot.diary else [],
            "source_dates": [slot.diary.date] if slot.diary else [],
            "quality": quality,
        }
        articles.append(record)
        article_records.append(
            {
                "article_id": article_id,
                "week_id": week_id,
                "filename": display_path(path),
                "source_diary_ids": record["source_diary_ids"],
                "actual_theme": slot.actual_theme,
                "status": "drafted",
            }
        )

    week_manifest = build_week_manifest(slots, articles, week_id)
    atomic_write_json(week_dir / "week_manifest.json", week_manifest)
    atomic_write_json(
        week_dir / "quality_report.json",
        {
            "week_id": week_id,
            "passed": week_manifest["quality_checks"]["passed"],
            "items": week_manifest["quality_checks"]["items"],
        },
    )

    summary = {
        "source": "neo4j",
        "mode": "weekly",
        "week_id": week_id,
        "output_dir": display_path(week_dir),
        "article_count": len(articles),
        "source_diary_count": week_manifest["diary_coverage"]["source_diary_count"],
        "fallback_count": week_manifest["diary_coverage"]["fallback_count"],
        "quality_passed": week_manifest["quality_checks"]["passed"],
    }

    if not week_manifest["quality_checks"]["passed"]:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2

    if not args.no_update_manifest:
        updated = update_manifest(manifest, week_manifest, article_records)
        atomic_write_json(args.manifest, updated)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def run_single(args: argparse.Namespace, manifest: dict[str, Any], candidates: list[DiaryCandidate]) -> int:
    scored_diaries = [score_diary(diary) for diary in candidates]
    prefetch = sorted(scored_diaries, key=lambda d: (d.score, d.date), reverse=True)[
        : CANDIDATE_PREFETCH_LIMIT
    ]
    diary_ids = [diary.id for diary in prefetch]
    try:
        material_map = load_materials_from_neo4j(diary_ids)
    except Exception as e:
        print_stop_report(
            stop_report(
                "neo4j_material_query_failed",
                "Neo4jの関係性素材を取得できないため、note下書き生成を停止しました。",
                e,
            )
        )
        return NEO4J_STOP_EXIT_CODE

    candidate = choose_article_candidate(
        scored_diaries,
        material_map,
        set(manifest.get("used_diary_ids", [])),
        allow_reuse=args.allow_reuse,
    )
    if candidate is None:
        print_stop_report(
            stop_report(
                "neo4j_no_article_candidate",
                "Neo4jの日記から記事候補を選定できなかったため、note下書き生成を停止しました。",
            )
        )
        return NEO4J_NO_DIARY_EXIT_CODE

    if args.dry_run:
        print_single_dry_run(candidate, len(scored_diaries))
        return 0

    run_id = args.week_id or default_run_id()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT_DIR / args.output_dir
    run_dir = output_dir / run_id
    if run_dir.exists() and not args.overwrite:
        raise FileExistsError(f"出力先が既に存在します。--overwrite を指定してください: {run_dir}")
    if run_dir.exists() and args.overwrite:
        for path in run_dir.iterdir():
            if path.is_file():
                path.unlink()
    run_dir.mkdir(parents=True, exist_ok=True)

    article_id = f"pomera_single_{run_id}"
    markdown = render_primary_article(candidate, run_id)
    quality = quality_check(markdown, mode="primary", seed=candidate.seed)
    filename = primary_slug(candidate)
    path = run_dir / filename
    path.write_text(markdown, encoding="utf-8")
    article = {
        "article_id": article_id,
        "filename": filename,
        "title": candidate_title(candidate),
        "source_diary_ids": [candidate.diary.id],
        "source_dates": [candidate.diary.date],
        "quality": quality,
    }
    article_record = {
        "article_id": article_id,
        "run_id": run_id,
        "filename": display_path(path),
        "source_diary_ids": [candidate.diary.id],
        "status": "drafted",
    }
    single_manifest = build_single_manifest(candidate, article, run_id, len(scored_diaries))
    atomic_write_json(run_dir / "run_manifest.json", single_manifest)
    atomic_write_json(
        run_dir / "quality_report.json",
        {
            "run_id": run_id,
            "passed": single_manifest["quality_checks"]["passed"],
            "items": single_manifest["quality_checks"]["items"],
        },
    )

    summary = {
        "source": "neo4j",
        "mode": "single",
        "run_id": run_id,
        "output_dir": display_path(run_dir),
        "article_count": 1,
        "selected_diary_id": candidate.diary.id,
        "selected_date": candidate.diary.date,
        "candidate_score": candidate.score,
        "fallback_count": 0,
        "quality_passed": single_manifest["quality_checks"]["passed"],
    }

    if not single_manifest["quality_checks"]["passed"]:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2

    if not args.no_update_manifest:
        updated = update_manifest_single(manifest, single_manifest, article_record)
        atomic_write_json(args.manifest, updated)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def run(args: argparse.Namespace) -> int:
    guide = load_guide(args.guide)
    manifest = load_manifest(args.manifest)

    try:
        graph = load_graph_from_neo4j()
    except Exception as e:
        print_stop_report(
            stop_report(
                "neo4j_unavailable",
                "Neo4jに接続できないため、note下書き生成を停止しました。",
                e,
            )
        )
        return NEO4J_STOP_EXIT_CODE

    candidates = collect_diaries(graph)
    if not candidates:
        print_stop_report(
            stop_report(
                "neo4j_no_diaries",
                "Neo4jから日記ノードを取得できなかったため、note下書き生成を停止しました。",
            )
        )
        return NEO4J_NO_DIARY_EXIT_CODE

    if args.mode == "weekly":
        return run_weekly(args, guide, manifest, candidates)
    return run_single(args, manifest, candidates)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Neo4jの日記データから100円note向け長文下書きを生成する"
    )
    parser.add_argument(
        "--source",
        choices=["neo4j"],
        default="neo4j",
        help="入力元。JSON-LD/graph_data fallback は行わないため neo4j のみ指定可能。",
    )
    parser.add_argument(
        "--mode",
        choices=["single", "weekly"],
        default="single",
        help="single は全日記から1本を選定して長文生成。weekly は旧7本生成。",
    )
    parser.add_argument("--guide", type=Path, default=DEFAULT_GUIDE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--week-id", help="singleではrun id、weeklyでは例: 2026-W22。省略時は自動採番")
    parser.add_argument("--dry-run", action="store_true", help="候補選定だけ表示して保存しない")
    parser.add_argument("--allow-reuse", action="store_true", help="manifestの使用済み日記も候補に含める")
    parser.add_argument("--no-update-manifest", action="store_true", help="出力しても全体manifestを更新しない")
    parser.add_argument("--overwrite", action="store_true", help="既存の週次出力ディレクトリを上書きする")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
