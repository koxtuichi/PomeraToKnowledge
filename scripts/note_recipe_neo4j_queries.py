"""Cypher-backed material extraction for Pomera note recipe drafts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


MATERIAL_NODE_TYPES = {
    "目標",
    "課題",
    "制約",
    "出来事",
    "解決策",
    "結果",
    "知見",
    "感情",
    "タスク",
    "プロジェクト",
    "goal",
    "issue",
    "constraint",
    "event",
    "solution",
    "result",
    "insight",
    "emotion",
    "task",
    "project",
}

DIARY_REL_TYPES = {"言及する", "言言及する"}
CONTEXT_REL_TYPES = {
    "阻害する",
    "原動力になる",
    "促進する",
    "進捗として",
    "解決策として",
    "引き起こす",
    "対象にする",
    "参加する",
}


@dataclass
class NoteRecipeMaterial:
    problem: str = ""
    background: str = ""
    pain_points: list[str] = field(default_factory=list)
    desired_state: str = ""
    current_status: str = ""
    next_step: str = ""
    evidence: list[str] = field(default_factory=list)
    source: str = "neo4j_cypher"


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, str) and value.strip():
        stripped = value.strip()
        if stripped[0] in "[{":
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _props(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {k: _parse_jsonish(v) for k, v in raw.items()}


def _record_dict(record: Any) -> dict[str, Any]:
    if hasattr(record, "data"):
        return record.data()
    return dict(record)


def _best_diary(row: dict[str, Any]) -> dict[str, Any]:
    diaries = [_props(row.get("diary"))]
    diaries.extend(_props(item) for item in row.get("diaries") or [])
    diaries = [diary for diary in diaries if diary.get("id")]
    if not diaries:
        return {}
    return max(
        diaries,
        key=lambda d: (
            bool(_parse_jsonish(d.get("analysis_content"))),
            len(_text(d.get("detail"))),
            bool("-" in str(d.get("id", ""))),
        ),
    )


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return " / ".join(str(v).strip() for v in value.values() if str(v).strip())
    return str(value).strip()


def _node_line(node: dict[str, Any]) -> str:
    return _text(node.get("current_state")) or _text(node.get("detail")) or _text(node.get("label"))


def _first(nodes: list[dict[str, Any]], types: set[str], *keys: str) -> str:
    for node in nodes:
        if node.get("type") not in types:
            continue
        for key in keys:
            value = _text(node.get(key))
            if value:
                return value
        value = _node_line(node)
        if value:
            return value
    return ""


def _append_unique(items: list[str], value: str, limit: int) -> None:
    clean = " ".join(value.split())
    if clean and clean not in items and len(items) < limit:
        items.append(clean)


def _analysis_fallback(diary: dict[str, Any], material: NoteRecipeMaterial) -> None:
    analysis = _parse_jsonish(diary.get("analysis_content")) or {}
    if not isinstance(analysis, dict):
        analysis = {}

    gravity = analysis.get("gravity_map") or []
    actions = analysis.get("antigravity_actions") or []
    insights = analysis.get("insights") or []

    if not material.problem and gravity:
        first = gravity[0]
        material.problem = _text(first.get("task")) or _text(first.get("net_assessment"))
    if not material.background:
        material.background = _text(diary.get("detail")) or _text(analysis.get("coach_comment"))
    if not material.current_status and gravity:
        material.current_status = _text(gravity[0].get("net_assessment"))
    if not material.next_step and actions:
        material.next_step = _text(actions[0].get("action")) or _text(actions[0].get("effect"))
    if not material.desired_state and insights:
        material.desired_state = _text(insights[0].get("implication")) or _text(insights[0].get("finding"))

    for item in gravity:
        for constraint in item.get("constraints") or []:
            _append_unique(material.pain_points, _text(constraint.get("name")), 3)
    for insight in insights:
        _append_unique(material.evidence, _text(insight.get("finding")), 3)


def _normalize_material(row: dict[str, Any]) -> NoteRecipeMaterial:
    diary = _best_diary(row)
    raw_nodes = (row.get("direct") or []) + (row.get("nearby") or [])
    nodes = []
    seen = set()
    for item in raw_nodes:
        node = _props(item.get("node") if isinstance(item, dict) else item)
        node_id = node.get("id")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        nodes.append(node)

    material = NoteRecipeMaterial(
        problem=_first(nodes, {"課題", "制約", "タスク", "issue", "constraint", "task"}, "current_state", "detail", "label"),
        background=_text(diary.get("detail")),
        desired_state=_first(nodes, {"目標", "プロジェクト", "goal", "project"}, "current_state", "detail", "label"),
        current_status=_first(nodes, {"目標", "課題", "タスク", "結果", "goal", "issue", "task", "result"}, "current_state", "status", "detail"),
        next_step=_first(nodes, {"解決策", "タスク", "知見", "solution", "task", "insight"}, "action", "current_state", "detail", "label"),
    )

    for node in nodes:
        node_type = node.get("type")
        line = _node_line(node)
        if node_type in {"制約", "課題", "constraint", "issue"}:
            _append_unique(material.pain_points, line, 3)
        if node_type in {"出来事", "結果", "知見", "event", "result", "insight"}:
            _append_unique(material.evidence, line, 3)
        for history in node.get("update_history") or []:
            _append_unique(material.evidence, _text(history), 3)

    _analysis_fallback(diary, material)

    if not material.problem:
        material.problem = material.current_status or material.background
    if not material.desired_state:
        material.desired_state = "今日の自分が少し動ける状態にする。"
    if not material.next_step:
        material.next_step = "いま一番軽くできる一歩を、5分以内に終わる形で書く。"
    return material


def fetch_note_recipe_materials(client: Any, diary_ids: list[str]) -> dict[str, NoteRecipeMaterial]:
    """Return normalized article materials keyed by diary id."""
    if not diary_ids:
        return {}

    query = """
    UNWIND $diary_ids AS diary_id
    MATCH (d {id: diary_id})
    WITH d, d.date AS diary_date
    OPTIONAL MATCH (s)
    WHERE s = d OR (
      diary_date IS NOT NULL
      AND coalesce(s.type, '') IN ['日記', 'diary']
      AND s.date = diary_date
    )
    WITH d, collect(DISTINCT s) AS diaries
    UNWIND diaries AS sd
    OPTIONAL MATCH (sd)-[r]-(n)
    WITH d, [
      item IN collect(DISTINCT CASE
        WHEN n IS NOT NULL
          AND coalesce(n.type, '') IN $node_types
          AND (type(r) IN $diary_rel_types OR coalesce(r.rel_type, '') IN $diary_rel_types)
        THEN {node: properties(n), rel: properties(r)}
        ELSE null
      END)
      WHERE item IS NOT NULL
    ] AS direct, diaries
    UNWIND diaries AS sd2
    OPTIONAL MATCH (sd2)-[r0]-(mid)-[r2]-(n2)
    WITH d, direct, diaries, [
      item IN collect(DISTINCT CASE
        WHEN n2 IS NOT NULL
          AND coalesce(n2.type, '') IN $node_types
          AND n2.id <> d.id
          AND (type(r0) IN $diary_rel_types OR coalesce(r0.rel_type, '') IN $diary_rel_types)
          AND (type(r2) IN $context_rel_types OR coalesce(r2.rel_type, '') IN $context_rel_types)
        THEN {node: properties(n2), rel: properties(r2)}
        ELSE null
      END)
      WHERE item IS NOT NULL
    ][0..12] AS nearby
    RETURN d.id AS diary_id,
           properties(d) AS diary,
           [diary IN diaries | properties(diary)] AS diaries,
           direct AS direct,
           nearby AS nearby
    """

    with client._driver.session() as session:
        result = session.run(
            query,
            diary_ids=diary_ids,
            node_types=sorted(MATERIAL_NODE_TYPES),
            diary_rel_types=sorted(DIARY_REL_TYPES),
            context_rel_types=sorted(CONTEXT_REL_TYPES),
        )
        rows = [_record_dict(record) for record in result]
        return {row["diary_id"]: _normalize_material(row) for row in rows if row.get("diary_id")}
