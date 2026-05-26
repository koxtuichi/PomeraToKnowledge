#!/usr/bin/env python3
"""Generate one week of Pomera-driven daily recipe note drafts.

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
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH_DATA = ROOT_DIR / "graph_data.js"
DEFAULT_GUIDE = ROOT_DIR / "config" / "pomera_daily_weekday_guide.json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "note_recipe_ready"
DEFAULT_MANIFEST = ROOT_DIR / "note_recipe_manifest.json"


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

ARTICLE_MIN_CHARS = 2000
ARTICLE_MAX_CHARS = 3000

THEME_ARTICLE_COPY = {
    "work": {
        "reader": "仕事で足が止まるとき、問題はやる気の不足ではなく、論点が混ざりすぎていることが多いです。急ぎの連絡、相手の期待、締切、まだ決めていない前提が一つの塊になると、頭の中では全部が同じ重さに見えます。",
        "lens": "この回では、仕事の重さを「今日決めること」と「今日は置いておくこと」に分けます。分けるだけで、いきなり成果を出さなくても前に進める余白ができます。",
        "warning": "完璧な計画を作る回ではありません。まずは、次の会話や作業に持ち込める小さな一文を作る回です。",
    },
    "publishing": {
        "reader": "発信が止まる日は、書く題材がないのではなく、題材を大きく扱いすぎていることがあります。経験をまとめようとするほど、立派な結論が必要に見えて、最初の一行が重くなります。",
        "lens": "この回では、日記の中にある違和感や小さな前進を、読者が使える一つの視点に変えます。完成記事ではなく、まず売れる小さな単位を見つけることが目的です。",
        "warning": "読者に見せる前から名作にしようとしないでください。今日は、続けるための最小単位を取り出せれば十分です。",
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
        "lens": "この回では、日記を作品の完成形ではなく、素材置き場として読み直します。拾うのは一つだけで構いません。",
        "warning": "すぐ完成させようとすると、せっかくの素材がまた重くなります。今日は拾うところで止めて大丈夫です。",
    },
    "unblock": {
        "reader": "詰まりを感じるとき、私たちはつい原因を一つに決めようとします。でも実際には、時間不足、情報不足、気まずさ、疲れが重なっているだけのことも多いです。",
        "lens": "この回では、詰まりを性格や能力の問題にせず、分解できる状態として扱います。ほどく対象を一つに絞ると、行動は急に軽くなります。",
        "warning": "大きな解決を狙う回ではありません。止まっている状態に、小さな出口を作る回です。",
    },
    "self_understanding": {
        "reader": "自分の気持ちを理解するのは、深く考え込むこととは少し違います。むしろ、頭の中で何度も回っている言葉を外に出して、距離を取ることから始まります。",
        "lens": "この回では、感情に正解を出すのではなく、今の自分が何に反応しているのかを見える形にします。",
        "warning": "きれいに整理しなくて大丈夫です。雑な言葉でも、外に出た瞬間に扱いやすくなります。",
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


def load_graph_from_graph_data(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    match = re.search(r"const GRAPH_DATA = (\{.*\});", content, re.DOTALL)
    if not match:
        raise ValueError(f"GRAPH_DATA が見つかりません: {path}")
    return json.loads(match.group(1))


def load_graph_from_neo4j() -> dict[str, Any]:
    import sys

    sys.path.insert(0, str(ROOT_DIR / "scripts"))
    from neo4j_client import Neo4jClient

    with Neo4jClient() as client:
        return client.export_graph()


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


def load_manifest(path: Path) -> dict[str, Any]:
    return load_json(
        path,
        {
            "version": 1,
            "source_priority": ["graph_data", "neo4j"],
            "used_diary_ids": [],
            "generated_weeks": [],
            "article_history": [],
            "last_run_at": None,
        },
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


def theme_label(theme: str, guide: dict[str, Any]) -> str:
    return guide.get("theme_labels", {}).get(theme, theme)


def extract_seed(slot: ArticleSlot) -> dict[str, str]:
    diary = slot.diary
    if not diary:
        return {
            "situation": "忙しさの中で、何から考え始めればいいか分からない状態。",
            "finding": "まず書く入口を小さくすると、行動の一歩を決めやすくなる。",
            "action": "今日の5分だけで決める一歩を1つ書く。",
        }

    analysis = diary.analysis
    gravity_map = analysis.get("gravity_map") or []
    actions = analysis.get("antigravity_actions") or []
    insights = analysis.get("insights") or []
    emotions = analysis.get("emotion_flow") or []

    situation = diary.detail if diary.detail and diary.detail != "今日の日記エントリ" else ""
    if gravity_map:
        first = gravity_map[0]
        situation = first.get("net_assessment") or first.get("task") or situation
    if not situation:
        situation = analysis.get("coach_comment", "")

    finding = ""
    if insights:
        finding = insights[0].get("finding") or insights[0].get("implication") or ""
    if not finding and emotions:
        finding = f"{emotions[0].get('emotion', '感情')}が思考の入口になっている。"
    if not finding:
        finding = "書くことで、重さの正体を外に出せる。"

    action = ""
    if actions:
        action = actions[0].get("action") or actions[0].get("effect") or ""
    if not action:
        action = "いま一番軽くできる一歩を、5分以内に終わる形で書く。"

    return {
        "situation": short_sentence(situation, 110),
        "finding": short_sentence(finding, 110),
        "action": short_sentence(action, 110),
    }


def theme_article_copy(theme: str) -> dict[str, str]:
    return THEME_ARTICLE_COPY.get(
        theme,
        {
            "reader": "忙しい日ほど、問題は一つに見えて、実際には複数の小さな負荷が重なっています。そのまま考え続けると、何から始めればいいか分からなくなります。",
            "lens": "この回では、頭の中で固まっているものを紙の上に出し、今日扱う一つだけに絞ります。",
            "warning": "大きな結論を急ぐ回ではありません。まずは、次に動ける形まで軽くする回です。",
        },
    )


def visible_character_count(markdown: str) -> int:
    visible = re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL)
    visible = re.sub(r"[#*_>`\\[\\]()]", "", visible)
    return len(re.sub(r"\s+", "", visible))


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


def render_article(slot: ArticleSlot, guide: dict[str, Any], week_id: str) -> str:
    seed = extract_seed(slot)
    title = recipe_title(slot, guide)
    theme = theme_label(slot.actual_theme, guide)
    copy = theme_article_copy(slot.actual_theme)

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
{seed["situation"]}

この状況は、特殊な一日の話に見えて、実は多くの人に起きる形をしています。忙しいときほど、私たちは「やるべきこと」と「気になっていること」と「まだ言葉になっていない感情」を同じ場所に置いてしまいます。その結果、問題そのものよりも、問題の輪郭が見えないことに疲れてしまいます。

## 抽出した思考の型
**{title}**

{seed["finding"]}

{copy["reader"]}

ここで使う考え方は、重さを消すことではありません。重さを、扱える大きさに分けることです。気合いで押し切ると、次の日にまた同じ場所で止まります。だから今日は、考える対象を小さくして、行動の入口だけを作ります。

## 今日の読み方
{copy["lens"]}

まず、今日の自分に問いを一つだけ置きます。

「これは本当に今すぐ全部やる必要があるのか。それとも、今日決める一部だけでいいのか」

この問いを置くだけで、頭の中の塊が少し崩れます。大事なのは、立派な答えを出すことではありません。紙の上に出した時点で、もう頭の中だけで抱えていた状態からは一歩進んでいます。

## 15分で書く5ステップ
1. いま一番気になっていることを、名詞で1つだけ書く。文章にしなくて大丈夫です。
2. その名詞の横に、重くしている理由を1つだけ書く。「時間」「人」「情報」「感情」「体力」のどれに近いかで選びます。
3. 次に、本当はどうなってほしいのかを一文で書きます。願望で構いません。
4. 今日できる行動を、5分で終わる大きさまで削ります。連絡なら1通、調査なら1語、片付けなら1か所です。
5. 最後に、明日に残していいものを1つ書きます。残すものを決めると、今日やる一歩が軽くなります。

## 書き込み欄
- 気になっている名詞:
- 重くしている理由:
- 本当はどうなってほしいか:
- 今日5分でやること:
- 明日に残していいこと:

空欄を全部埋める必要はありません。むしろ、最初は一つだけで十分です。特に「重くしている理由」が書ければ、半分は終わっています。理由が分からないまま頑張ろうとすると、行動量だけ増えて疲れます。理由が見えれば、行動は小さくできます。

## 今日のサンプル変換
元の状況をそのまま抱えると、「ちゃんと考えなきゃ」で止まりやすくなります。そこで、次のように変換します。

- 大きいままの考え: {seed["situation"]}
- 扱える形にした考え: {seed["finding"]}
- 今日の最小行動: {seed["action"]}

この変換のポイントは、結論を急がないことです。日記から拾った材料は、まだ生の状態です。だから最初にやるのは、正しい答えを出すことではなく、次の行動に接続できる形へ置き直すことです。

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


def quality_check(markdown: str, slot: ArticleSlot) -> dict[str, Any]:
    privacy_terms = [term for term in SENSITIVE_REPLACEMENTS if term in markdown]
    privacy_terms.extend(re.findall(r"(?<!皆)[一-龥]{1,4}さん", markdown))
    banned_terms = [term for term in QUALITY_BANNED_TERMS if term in markdown]
    actionability = "## 15分で書く5ステップ" in markdown and "## 5分でやる最小行動" in markdown
    char_count = visible_character_count(markdown)
    length_ok = ARTICLE_MIN_CHARS <= char_count <= ARTICLE_MAX_CHARS
    source_traceability = bool(slot.diary)
    return {
        "privacy": not privacy_terms,
        "privacy_terms": privacy_terms,
        "non_prompt_sale": not banned_terms,
        "banned_terms": banned_terms,
        "actionability": actionability,
        "visible_char_count": char_count,
        "length_ok": length_ok,
        "length_range": [ARTICLE_MIN_CHARS, ARTICLE_MAX_CHARS],
        "source_traceability": source_traceability,
        "fallback": slot.diary is None,
        "passed": (not privacy_terms) and (not banned_terms) and actionability and length_ok,
    }


def slug(index: int, day: str, theme: str) -> str:
    return f"{index:02d}_{day}_{theme}.md"


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


def default_week_id() -> str:
    today = dt.date.today()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


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


def run(args: argparse.Namespace) -> int:
    guide = load_guide(args.guide)
    manifest = load_manifest(args.manifest)

    if args.source == "neo4j":
        graph = load_graph_from_neo4j()
    else:
        graph = load_graph_from_graph_data(args.graph_data)

    candidates = collect_diaries(graph)
    used_ids = set(manifest.get("used_diary_ids", []))
    slots = assemble_week(candidates, guide, used_ids, allow_reuse=args.allow_reuse)

    if args.dry_run:
        print_dry_run(slots, guide)
        return 0

    week_id = args.week_id or default_week_id()
    week_dir = args.output_dir / week_id
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
        quality = quality_check(markdown, slot)
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
                "filename": str(path.relative_to(ROOT_DIR)),
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
        "week_id": week_id,
        "output_dir": str(week_dir.relative_to(ROOT_DIR)),
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="POMERA日記から100円note向けデイリーレシピを一週間分生成する"
    )
    parser.add_argument("--source", choices=["graph_data", "neo4j"], default="graph_data")
    parser.add_argument("--graph-data", type=Path, default=DEFAULT_GRAPH_DATA)
    parser.add_argument("--guide", type=Path, default=DEFAULT_GUIDE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--week-id", help="例: 2026-W22。省略時は現在週")
    parser.add_argument("--dry-run", action="store_true", help="候補割当だけ表示して保存しない")
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
