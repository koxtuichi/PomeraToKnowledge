"""Render 100-yen note draft articles from Neo4j diary nodes."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from typing import Any


ARTICLE_MIN_CHARS = 4000
ARTICLE_MAX_CHARS = 5000
THEME_OVERLAP_THRESHOLD = 0.58
THEME_PROFILE_VERSION = "2026-05-28-v1"
REQUIRED_HEADINGS = [
    "これは何か",
    "元になった記録",
    "問題はなにか",
    "背景",
    "なにに困っているのか",
    "目指す状態",
    "どのように対処すればいいのか",
    "判断の分け方",
    "日記から拾えた根拠",
    "書き込み欄",
    "よくある失敗",
    "なぜポメラでやるのか",
    "書き終わりの合図",
    "明日に送るメモ",
    "今日の最小行動",
]
FORBIDDEN_TERMS = [
    "重力",
    "引力",
    "同じ重さ",
    "重さの正体",
    "敵",
    "全部埋める必要",
    "かもしれません",
    "大丈夫",
    "プロンプト集",
    "ChatGPTに渡す",
    "診断します",
]
SENSITIVE_REPLACEMENTS = {
    "沙也香": "パートナー",
    "沙也加": "パートナー",
    "さやか": "パートナー",
    "蒼馬": "子ども",
    "Knowbe": "仕事",
    "Saiteki": "別プロジェクト",
    "Slack": "チャット",
}
THEME_KEYWORD_GROUPS = {
    "work_unblock": [
        "仕事",
        "業務",
        "会議",
        "MTG",
        "質問",
        "確認",
        "連携",
        "依頼",
        "返答",
        "テンプレート",
        "本業",
        "作業",
    ],
    "publish_seed": [
        "発信",
        "note",
        "ブログ",
        "記事",
        "投稿",
        "読者",
        "文章",
        "下書き",
        "書く",
    ],
    "family_schedule": [
        "家族",
        "予定",
        "生活",
        "パートナー",
        "子ども",
        "保育",
        "家事",
        "休日",
    ],
    "purchase_decision": [
        "車",
        "購入",
        "買う",
        "欲しい",
        "中古",
        "手続き",
        "納車",
        "お金",
        "金額",
    ],
    "automation_pipeline": [
        "自動化",
        "パイプライン",
        "Neo4j",
        "AI",
        "データ",
        "実装",
        "GCP",
        "Cloud",
    ],
    "learning_reflection": [
        "学習",
        "読書",
        "価値",
        "内省",
        "気づき",
        "振り返り",
        "習慣",
    ],
    "recovery_rhythm": [
        "疲れ",
        "休み",
        "体調",
        "睡眠",
        "余裕",
        "回復",
        "調子",
    ],
}
@dataclass
class Diary:
    id: str
    date: str
    label: str
    detail: str
    analysis: dict[str, Any]
    score: float = 0.0
    seed: dict[str, Any] = field(default_factory=dict)
    theme_profile: dict[str, Any] = field(default_factory=dict)
    theme_decision: dict[str, Any] = field(default_factory=dict)


def _parse_analysis(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_date(value: Any, node_id: str) -> str:
    text = str(value or "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    match = re.search(r"(\d{4})-?(\d{2})-?(\d{2})", node_id)
    return "-".join(match.groups()) if match else ""


def sanitize(text: Any, max_len: int | None = None) -> str:
    result = re.sub(r"\s+", " ", str(text or "")).strip()
    for src, dst in SENSITIVE_REPLACEMENTS.items():
        result = result.replace(src, dst)
    result = re.sub(r"\d{4}年\d{1,2}月\d{1,2}日", "ある日", result)
    result = re.sub(r"\d{4}-\d{2}-\d{2}", "ある日", result)
    result = re.sub(r"\d{1,3}(?:,\d{3})*円", "具体的な金額", result)
    result = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "メールアドレス", result)
    if max_len and len(result) > max_len:
        return result[: max_len - 1].rstrip() + "..."
    return result


def collect_diaries(nodes: list[dict[str, Any]]) -> list[Diary]:
    diaries: list[Diary] = []
    for node in nodes:
        node_id = str(node.get("id", ""))
        date = _normalize_date(node.get("date"), node_id)
        if not node_id or not date:
            continue
        diary = Diary(
            id=node_id,
            date=date,
            label=str(node.get("label") or f"{date}の日記"),
            detail=str(node.get("detail") or ""),
            analysis=_parse_analysis(node.get("analysis_content")),
        )
        diaries.append(score_diary(diary))
    return sorted(diaries, key=lambda d: d.date, reverse=True)


def _blob(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_blob(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_blob(v) for v in value)
    return str(value)


def score_diary(diary: Diary) -> Diary:
    text = " ".join([diary.label, diary.detail, _blob(diary.analysis)])
    score = 0.0
    score += min(3.0, len(diary.detail) / 80.0)
    score += len(diary.analysis.get("insights", []) or []) * 1.2
    score += len(diary.analysis.get("antigravity_actions", []) or []) * 1.4
    score += len(diary.analysis.get("gravity_map", []) or []) * 1.1
    score += text.count("仕事") + text.count("発信") + text.count("家族")
    if not diary.analysis:
        score -= 4.0
    diary.score = round(score, 3)
    diary.seed = build_seed(diary)
    diary.score += seed_score(diary.seed)
    diary.theme_profile = build_theme_profile(diary.seed)
    return diary


def _first_dict(items: Any) -> dict[str, Any]:
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                return item
    return {}


def build_seed(diary: Diary) -> dict[str, Any]:
    analysis = diary.analysis
    action = _first_dict(analysis.get("antigravity_actions"))
    map_item = _first_dict(analysis.get("gravity_map"))
    insight = _first_dict(analysis.get("insights"))
    problem = (
        map_item.get("net_assessment")
        or map_item.get("task")
        or action.get("target_task")
        or diary.detail
        or analysis.get("coach_comment")
    )
    next_step = action.get("action") or action.get("effect") or "今日の判断を一文にして、次に渡す相手か作業を決める。"
    desired = action.get("effect") or insight.get("finding") or "今日扱う一つが決まり、次の行動に移れる状態にする。"
    pain_points = []
    for constraint in map_item.get("constraints") or []:
        if isinstance(constraint, dict) and constraint.get("name"):
            pain_points.append(sanitize(constraint["name"], 90))
    if not pain_points:
        pain_points = ["作業と確認が混ざっている", "次に聞く相手が曖昧になっている", "完了条件が見えにくい"]
    evidence = []
    if diary.detail and diary.detail != "今日の日記エントリ":
        evidence.append(f"日記には、{sanitize(diary.detail, 130)} という流れが残っている。")
    if action.get("action"):
        evidence.append(f"次の行動として、{sanitize(action['action'], 130)} が抽出されている。")
    if map_item.get("task") or map_item.get("net_assessment"):
        evidence.append(f"手が止まっている場所として、{sanitize(map_item.get('task') or map_item.get('net_assessment'), 130)} が抽出されている。")
    return {
        "problem": sanitize(problem, 180),
        "background": sanitize(diary.detail or analysis.get("coach_comment"), 280),
        "pain_points": pain_points[:4],
        "desired_state": sanitize(desired, 180),
        "next_step": sanitize(next_step, 180),
        "evidence": evidence[:4],
    }


def seed_score(seed: dict[str, Any]) -> float:
    keys = ["problem", "background", "desired_state", "next_step"]
    score = sum(1.2 for key in keys if seed.get(key))
    score += len(seed.get("pain_points") or []) * 0.6
    score += len(seed.get("evidence") or []) * 0.6
    return score


def _normalize_theme_text(text: Any) -> str:
    cleaned = sanitize(text)
    cleaned = re.sub(r"[\s、。・,./:：;；!?！？()（）「」『』【】\[\]{}<>＜＞#]+", "", cleaned)
    return cleaned.lower()


def _char_ngrams(text: str, size: int = 3) -> set[str]:
    normalized = _normalize_theme_text(text)
    if len(normalized) < size:
        return {normalized} if normalized else set()
    return {normalized[index : index + size] for index in range(len(normalized) - size + 1)}


def _extract_theme_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    for terms in THEME_KEYWORD_GROUPS.values():
        for term in terms:
            if term.lower() in text.lower() and term not in keywords:
                keywords.append(term)
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text):
        if token not in keywords:
            keywords.append(token)
    return keywords[:12]


def _infer_theme_cluster(text: str, keywords: list[str]) -> str:
    scores: dict[str, int] = {}
    lower_text = text.lower()
    for cluster, terms in THEME_KEYWORD_GROUPS.items():
        score = 0
        for term in terms:
            if term in keywords or term.lower() in lower_text:
                score += 1
        if score:
            scores[cluster] = score
    if not scores:
        return "daily_decision"
    return max(scores.items(), key=lambda item: (item[1], item[0]))[0]


def build_theme_profile(seed: dict[str, Any], title: str = "") -> dict[str, Any]:
    pain_points = seed.get("pain_points") or []
    basis_parts = [
        title,
        seed.get("problem", ""),
        seed.get("background", ""),
        " ".join(str(item) for item in pain_points),
        seed.get("desired_state", ""),
        seed.get("next_step", ""),
    ]
    basis_text = sanitize(" ".join(part for part in basis_parts if part), 420)
    keywords = _extract_theme_keywords(basis_text)
    cluster = _infer_theme_cluster(basis_text, keywords)
    summary_source = seed.get("problem") or seed.get("next_step") or title or basis_text
    return {
        "theme_cluster": cluster,
        "theme_keywords": keywords,
        "theme_basis_text": basis_text,
        "theme_summary": sanitize(summary_source, 120),
        "theme_profile_version": THEME_PROFILE_VERSION,
        "theme_profile_source": "diary_seed",
    }


def normalize_theme_profile(value: dict[str, Any] | None) -> dict[str, Any]:
    profile = value or {}
    keywords = profile.get("theme_keywords") or []
    if isinstance(keywords, str):
        keywords = [item.strip() for item in keywords.split(",") if item.strip()]
    keywords = [sanitize(item, 40) for item in keywords if str(item).strip()]
    basis_text = sanitize(profile.get("theme_basis_text") or profile.get("basis_text") or "", 420)
    theme_summary = sanitize(profile.get("theme_summary") or profile.get("summary") or basis_text, 120)
    cluster = sanitize(profile.get("theme_cluster") or profile.get("cluster") or "", 80)
    if not cluster:
        cluster = _infer_theme_cluster(basis_text, keywords)
    if not keywords and basis_text:
        keywords = _extract_theme_keywords(basis_text)
    return {
        "theme_cluster": cluster or "daily_decision",
        "theme_keywords": keywords[:12],
        "theme_basis_text": basis_text,
        "theme_summary": theme_summary,
        "theme_profile_version": sanitize(
            profile.get("theme_profile_version") or THEME_PROFILE_VERSION, 40
        ),
        "theme_profile_source": sanitize(
            profile.get("theme_profile_source") or "normalized", 40
        ),
    }


def history_theme_profile(record: dict[str, Any]) -> dict[str, Any] | None:
    generation = record.get("generation") if isinstance(record.get("generation"), dict) else record
    generation = generation or {}
    profile = normalize_theme_profile(
        {
            "theme_cluster": generation.get("theme_cluster"),
            "theme_keywords": generation.get("theme_keywords"),
            "theme_basis_text": generation.get("theme_basis_text"),
            "theme_summary": generation.get("theme_summary"),
        }
    )
    if profile["theme_basis_text"] or profile["theme_keywords"]:
        return {
            **profile,
            "generation_id": generation.get("generation_id") or generation.get("id"),
            "title": generation.get("title"),
            "note_url": generation.get("note_url"),
            "status": generation.get("status"),
            "prompt_version": generation.get("prompt_version"),
        }

    diary_node = record.get("diary")
    if isinstance(diary_node, dict):
        diaries = collect_diaries([diary_node])
        if diaries:
            rebuilt = normalize_theme_profile(diaries[0].theme_profile)
            return {
                **rebuilt,
                "generation_id": generation.get("generation_id") or generation.get("id"),
                "title": generation.get("title"),
                "note_url": generation.get("note_url"),
                "status": generation.get("status"),
                "prompt_version": generation.get("prompt_version"),
            }
    title = generation.get("title")
    if title:
        rebuilt = normalize_theme_profile(
            {
                "theme_basis_text": sanitize(title, 240),
                "theme_summary": sanitize(title, 120),
            }
        )
        return {
            **rebuilt,
            "generation_id": generation.get("generation_id") or generation.get("id"),
            "title": title,
            "note_url": generation.get("note_url"),
            "status": generation.get("status"),
            "prompt_version": generation.get("prompt_version"),
        }
    return None


def normalize_theme_history(records: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for record in records or []:
        profile = history_theme_profile(record)
        if profile:
            history.append(profile)
    return history


def score_theme_overlap(
    candidate: dict[str, Any],
    history: dict[str, Any],
) -> dict[str, Any]:
    candidate_profile = normalize_theme_profile(candidate)
    history_profile = normalize_theme_profile(history)
    candidate_keywords = set(candidate_profile["theme_keywords"])
    history_keywords = set(history_profile["theme_keywords"])
    union = candidate_keywords | history_keywords
    keyword_score = len(candidate_keywords & history_keywords) / len(union) if union else 0.0
    same_cluster = (
        candidate_profile["theme_cluster"] == history_profile["theme_cluster"]
        and candidate_profile["theme_cluster"] != "daily_decision"
    )
    candidate_grams = _char_ngrams(candidate_profile["theme_basis_text"])
    history_grams = _char_ngrams(history_profile["theme_basis_text"])
    gram_union = candidate_grams | history_grams
    phrase_score = len(candidate_grams & history_grams) / len(gram_union) if gram_union else 0.0
    score = min(1.0, (0.28 if same_cluster else 0.0) + keyword_score * 0.52 + phrase_score * 0.28)
    matched_keywords = sorted(candidate_keywords & history_keywords)
    return {
        "score": round(score, 3),
        "same_cluster": same_cluster,
        "keyword_score": round(keyword_score, 3),
        "phrase_score": round(phrase_score, 3),
        "matched_keywords": matched_keywords,
        "matched_generation_id": history.get("generation_id"),
        "matched_title": history.get("title"),
        "matched_note_url": history.get("note_url"),
        "matched_status": history.get("status"),
        "matched_theme_summary": history_profile["theme_summary"],
    }


def evaluate_theme_overlap(
    profile: dict[str, Any],
    theme_history: list[dict[str, Any]] | None,
    threshold: float = THEME_OVERLAP_THRESHOLD,
) -> dict[str, Any]:
    comparisons = [
        score_theme_overlap(profile, history)
        for history in normalize_theme_history(theme_history)
    ]
    strongest = max(comparisons, key=lambda item: item["score"], default=None)
    max_similarity = strongest["score"] if strongest else 0.0
    return {
        "blocked": max_similarity >= threshold,
        "max_similarity": max_similarity,
        "threshold": threshold,
        "strongest_match": strongest,
        "history_count": len(comparisons),
    }


def _theme_conflict_summary(diary: Diary) -> dict[str, Any]:
    decision = diary.theme_decision or {}
    match = decision.get("strongest_match") or {}
    return {
        "diary_id": diary.id,
        "date": diary.date,
        "theme_profile": diary.theme_profile,
        "max_similarity": decision.get("max_similarity", 0.0),
        "matched_generation_id": match.get("matched_generation_id"),
        "matched_title": match.get("matched_title"),
        "matched_note_url": match.get("matched_note_url"),
        "matched_theme_summary": match.get("matched_theme_summary"),
        "matched_keywords": match.get("matched_keywords", []),
    }


def select_diary_with_decision(
    diaries: list[Diary],
    blocked_diary_ids: set[str] | None = None,
    diary_id: str | None = None,
    allow_reuse: bool = False,
    theme_history: list[dict[str, Any]] | None = None,
    allow_theme_overlap: bool = False,
    theme_overlap_threshold: float = THEME_OVERLAP_THRESHOLD,
) -> dict[str, Any]:
    used = blocked_diary_ids or set()
    history = normalize_theme_history(theme_history)
    if diary_id:
        matches = [diary for diary in diaries if diary.id == diary_id]
        if not matches:
            return {"diary": None, "reason": "diary_not_found", "theme_conflicts": []}
        if not allow_reuse and diary_id in used:
            return {"diary": None, "reason": "diary_already_used", "theme_conflicts": []}
        pool = matches
    else:
        pool = [diary for diary in diaries if allow_reuse or diary.id not in used]
        pool = [diary for diary in pool if diary.analysis]

    selectable: list[tuple[float, Diary]] = []
    theme_conflicts: list[dict[str, Any]] = []
    for diary in pool:
        if not diary.theme_profile:
            diary.theme_profile = build_theme_profile(diary.seed)
        diary.theme_decision = evaluate_theme_overlap(
            diary.theme_profile,
            history,
            threshold=theme_overlap_threshold,
        )
        if diary.theme_decision["blocked"] and not allow_theme_overlap:
            theme_conflicts.append(_theme_conflict_summary(diary))
            continue
        adjusted_score = diary.score - min(2.5, diary.theme_decision["max_similarity"] * 2.0)
        selectable.append((adjusted_score, diary))

    selected = max(selectable, key=lambda item: (item[0], item[1].score, item[1].date), default=None)
    if selected:
        return {
            "diary": selected[1],
            "reason": "selected",
            "theme_conflicts": theme_conflicts,
            "theme_history_count": len(history),
        }
    reason = "theme_conflict" if theme_conflicts else "no_candidate"
    return {
        "diary": None,
        "reason": reason,
        "theme_conflicts": theme_conflicts,
        "theme_history_count": len(history),
    }


def select_diary(
    diaries: list[Diary],
    blocked_diary_ids: set[str] | None = None,
    diary_id: str | None = None,
    allow_reuse: bool = False,
    theme_history: list[dict[str, Any]] | None = None,
    allow_theme_overlap: bool = False,
    theme_overlap_threshold: float = THEME_OVERLAP_THRESHOLD,
) -> Diary | None:
    selection = select_diary_with_decision(
        diaries,
        blocked_diary_ids=blocked_diary_ids,
        diary_id=diary_id,
        allow_reuse=allow_reuse,
        theme_history=theme_history,
        allow_theme_overlap=allow_theme_overlap,
        theme_overlap_threshold=theme_overlap_threshold,
    )
    return selection["diary"]


def title_for(seed: dict[str, Any]) -> str:
    text = " ".join(str(seed.get(key, "")) for key in ("problem", "background", "next_step"))
    if any(word in text for word in ("仕事", "業務", "会議", "MTG", "質問", "連携")):
        return "100円｜仕事が溜まった日に、ポメラで次の質問を切り出す"
    if any(word in text for word in ("発信", "note", "ブログ", "記事")):
        return "100円｜日記から、今日書ける発信の一文を取り出す"
    if any(word in text for word in ("家族", "予定", "生活")):
        return "100円｜予定が重なる日に、自分の一歩を見失わない"
    return "100円｜忙しい日でも、ポメラで次の一歩を決める"


def render_article(diary: Diary, run_id: str) -> dict[str, Any]:
    seed = diary.seed
    title = title_for(seed)
    if not diary.theme_profile:
        diary.theme_profile = build_theme_profile(seed, title=title)
    pains = "\n".join(f"- {item}" for item in seed["pain_points"])
    evidence = "\n".join(f"- {item}" for item in seed["evidence"])
    body = f"""# {title}

<!-- free_part_start -->
忙しい日に手が止まる原因は、作業量だけではありません。

本当に動きを止めるのは、自分だけで進める作業と、誰かの返答が必要な作業が同じ場所に置かれることです。ひとりで片付けられるもの、相手に聞かないと進まないもの、今日でなくてもよいもの。この区別が消えると、手元のタスクは全部「今すぐ何とかするもの」に見えます。

この回では、ポメラを使って、抱えているものを根性で片付けるのではなく、先に外へ出すべき質問や確認を切り出します。目的は、全体を美しく整理することではありません。次の行動に移るための一文を作ることです。
<!-- free_part_end -->

<!-- paid_part_start -->
## これは何か

これは、忙しい日に「次に誰へ何を聞くか」を決めるための、10分のポメラ駆動です。

やることを全部洗い出す方法ではありません。タスク管理表を作る方法でもありません。今日の狙いはもっと狭くします。自分で抱え続けると遅くなるものを見つけて、質問や確認に変える。ここだけを扱います。

## 元になった記録

元になった日記は、{sanitize(diary.date)} の記録です。内容としては、{sanitize(seed["background"], 260)} という流れが残っていました。

ここで重要なのは、出来事の多さではありません。生活や仕事の確認が重なる中で、次に扱うべきものが見えにくくなっていることです。気持ちの上では一段落していても、仕事や生活側では別の未処理が残ります。

## 問題はなにか

問題は、{seed["problem"]} という形で現れています。

これは、やる気の不足ではありません。頭の中で、自分で動かすこと、相手に聞くこと、明日以降でよいことが混ざっている状態です。このまま始めると、目についたものから触ることになります。すると、返答待ちが必要なものほど後ろに残ります。

ここで厄介なのは、どれも一見すると正しい用事に見えることです。作業するのも正しい。確認するのも正しい。明日の準備をするのも正しい。正しいもの同士が並ぶと、判断は簡単になりません。むしろ、どれから触っても間違いではないため、決める負担だけが増えます。

だから、最初の問いを変えます。「何が一番大事か」ではなく、「今日外へ出さないと止まるものは何か」と聞きます。この問いにすると、答えは現実の順番に近づきます。

## 背景

忙しい日ほど、私たちは自分の作業量だけを見ます。どれだけ残っているか。どれだけ終わっていないか。今日どこまで進めるか。

しかし実際の仕事や生活は、自分の手元だけで完結しません。相手の確認、合意、素材、判断が必要な場面があります。そこを後回しにすると、自分は作業しているつもりでも、全体の進行は止まります。

この状態では、頑張り方を間違えやすくなります。自分でできる作業に長く入り込むほど、相手への確認は後ろへ下がります。最後に確認が残ると、その日の中では返答が返ってきません。すると翌日、昨日の続きではなく、昨日出せなかった確認から再開することになります。

ポメラで先に書く意味は、この再開の遅れを減らすことです。書くことで、相手へ渡すものと自分で進めるものを分けます。分けるだけで、今日の順番は変わります。

## なにに困っているのか

今回見えている困りごとは、主に次の通りです。

{pains}

ここで困るのは、考える力がないからではありません。考える対象が大きすぎるからです。大きい言葉のままだと、何をすれば始まったことになるのかが見えません。

## 目指す状態

目指すのは、{seed["desired_state"]} という状態です。

すべてを解決する必要はありません。今日の予定を壊さず、次の会話や作業に入れるところまで行ければ区切れます。この回で目指すのは、頭の中の混雑を完全になくすことではありません。今日扱うものと、明日に送るものを分けることです。

目指す状態は、気持ちが完全に軽くなることではありません。次の行動が見えていることです。送る質問が決まっている。返答待ちの間に進める作業がある。明日に送るものが一行で置かれている。この3つがそろえば、まだ未完了が残っていても前に進めます。

## どのように対処すればいいのか

ポメラを開いたら、次の順番で書きます。

1. いま頭に残っていることを、名詞で全部出す。
2. その中から、相手の返答が必要なものを選ぶ。
3. 選んだものを、相手が答えやすい質問文に変える。
4. 今日送る質問を3つ以下に絞る。
5. 返答を待つ間に進める作業を一つだけ書く。

今回なら、今日の最小行動は「{seed["next_step"]}」です。ここまで小さくすると、考える対象が行動に変わります。

ここで一度、書く順番を守ります。先に質問を書かず、まず名詞で出します。名詞にすると、感情や焦りが少し離れます。「業務が多い」ではなく「確認先」「テンプレート」「返答待ち」「今日送る文面」のように置きます。次に、それぞれの横へ小さく印を付けます。自分で動くものには「自分」、相手の返答が必要なものには「相手」、今日は置くものには「明日」と書きます。

この印があるだけで、作業の順番が変わります。自分で動けるものから始めるのではなく、相手に渡すものを先に送る。返答を待つ間に、自分で進むものへ移る。これが、忙しい日の待ち時間を減らす基本形です。

## 判断の分け方

最初に重要度で並べると失敗しやすいです。重要なものほど大きく見え、大きく見えるほど着手しづらくなります。

先に見るのは、返答待ちが発生するかどうかです。自分だけで進むもの。相手の返答が必要なもの。完了条件が曖昧なもの。この3つに分けます。相手の返答が必要なものは先に外へ出します。完了条件が曖昧なものは質問に変えます。

## 日記から拾えた根拠

今回の根拠は、次のような記録です。

{evidence}

根拠は、立派な結論でなくて構いません。日記に残っている小さな違和感や、途中までの考えで使えます。途中の言葉こそ、次の行動に変えやすい材料になります。

## 書き込み欄

- 頭に残っていること:
- 自分だけで進むもの:
- 相手の返答が必要なもの:
- 完了条件が曖昧なもの:
- 今日送る質問3つ:

この欄は、迷いを見せるためのものではありません。判断を外に出すための作業台です。特に見るべきなのは、「相手の返答が必要なもの」です。

書くときは、文章にしすぎない方が使えます。最初から整った文にすると、きれいに書くことへ意識が向きます。ここで必要なのは完成文ではありません。判断材料です。「テンプレ項目」「確認先」「優先案件」「返答待ち」のような短い言葉で置きます。

その後で、送るものだけ文章にします。全部を文章化しないことで、時間を使いすぎずに済みます。

## よくある失敗

よくある失敗は、溜まったものをそのまま順番に片付けようとすることです。上から順番に処理すると、手元でできるものから進みます。短時間で終わるものを消すと気分はよくなります。しかし、相手の返答が必要なものが後ろに残ると、結局その日の終わりに止まります。

もう一つの失敗は、質問を曖昧なまま送ることです。「どうしましょうか」では、相手も判断しにくいです。AとBならどちらを優先するか。この3項目で進めてよいか。判断に必要な情報は誰が持っているか。この形にします。

## なぜポメラでやるのか

この作業は、チャット画面の中ではやりにくいです。チャットを開くと、すぐ送れる反面、考えが浅いまま相手に渡してしまいます。通知も見えます。過去の会話も見えます。別の依頼も目に入ります。

ポメラは、その手前に置く道具です。送る前に質問を削る。相手に渡す前に論点を絞る。まだ送らない状態で、言葉だけを整える。忙しい日に必要なのは勢いではありません。相手が答えられる形まで整えた一文です。

## 書き終わりの合図

終わりの合図は、今日送る質問が3つ以下になったときです。3つを超えるなら、まだ混ざっています。質問を減らします。

1つ目は、今日返答がないと止まるもの。2つ目は、完了条件を決めるもの。3つ目は、相手が持っている情報を受け取るもの。この3つに収まったら、ポメラを閉じます。そして、チャットやメールに移します。

このとき、質問の数を増やさないことが重要です。質問が多いと、相手に渡す前に自分がまた迷います。3つ以下にするのは、相手のためだけではありません。自分が次の行動に移るためでもあります。

## 明日に送るメモ

最後に、明日でよいものを一行だけ残します。ここで残すのは、今日送らない質問ではありません。今日の返答を待ったあとに考えることです。

たとえば、返答が来たら初版を30分で作る。優先対象が決まったら関係者へ共有する。情報の持ち主が分かったら次の確認先を一人に絞る。このように、翌日に開いたときの入口を書きます。

## 今日の最小行動

今日やることは一つです。

{seed["next_step"]}

この一文が書けたら、次にやることは明確です。質問を送る。返答を待つあいだに、自分だけで進む作業へ移る。

ポメラ駆動は、仕事を増やすための習慣ではありません。判断を言葉にして、次の行動へ渡すための習慣です。

終わったあとに見るのは、完成度ではありません。次に渡す相手が決まっているか。送る文面があるか。返答を待つ間に進める作業が一つあるか。この3つが見えていれば、今日の役割は果たしています。

日記は、その材料をすでに持っています。何に引っかかったのか。何を後回しにしたのか。どこで判断が止まったのか。ポメラで読み直す価値は、そこにあります。過去の記録をきれいに保存するためではなく、今日の行動へ変えるために読みます。

最後に、送る文面を一度だけ声に出すつもりで読みます。相手が答えられる形になっているか。判断してほしい点が一つに絞られているか。返答が来たあと、自分が何をするか分かるか。ここまで確認したら、その日のポメラは閉じます。

閉じたら、実際に送ります。書いたまま残すと、また頭の中へ戻ります。ポメラで作った一文は、外へ出して初めて流れを作ります。
<!-- paid_part_end -->

<!-- source: neo4j diary {diary.id} / run {run_id} -->
"""
    quality = quality_check(body)
    return {
        "title": title,
        "markdown": body,
        "quality": quality,
        "source_diary_id": diary.id,
        "source_date": diary.date,
        "theme_profile": diary.theme_profile,
        "theme_decision": diary.theme_decision
        or {
            "blocked": False,
            "max_similarity": 0.0,
            "threshold": THEME_OVERLAP_THRESHOLD,
            "strongest_match": None,
            "history_count": 0,
        },
    }


def visible_text(markdown: str) -> str:
    text = re.sub(r"<!--.*?-->", "", markdown, flags=re.S)
    text = re.sub(r"^# .+$", "", text, flags=re.M)
    return text


def quality_check(markdown: str) -> dict[str, Any]:
    visible = visible_text(markdown)
    compact = re.sub(r"\s+", "", visible)
    headings = re.findall(r"^##\s+(.+)$", markdown, flags=re.M)
    forbidden = [term for term in FORBIDDEN_TERMS if term in markdown]
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in headings]
    source_traceability = "source: neo4j diary" in markdown
    length_ok = ARTICLE_MIN_CHARS <= len(compact) <= ARTICLE_MAX_CHARS
    return {
        "visible_char_count": len(compact),
        "length_range": [ARTICLE_MIN_CHARS, ARTICLE_MAX_CHARS],
        "length_ok": length_ok,
        "heading_count": len(headings),
        "missing_headings": missing,
        "section_ok": not missing,
        "forbidden_terms": forbidden,
        "concrete_language": not forbidden,
        "source_traceability": source_traceability,
        "fallback": False,
        "passed": length_ok and not missing and not forbidden and source_traceability,
    }


def default_run_id(now: dt.datetime | None = None) -> str:
    current = now or dt.datetime.now(dt.timezone.utc)
    return current.strftime("%Y%m%dT%H%M%SZ")
