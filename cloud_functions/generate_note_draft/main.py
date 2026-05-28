"""Cloud Function entrypoint for Neo4j-only note draft generation."""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

import functions_framework

import gcs_io
from neo4j_diary_client import Neo4jDiaryClient
from note_article_writer import (
    THEME_OVERLAP_THRESHOLD,
    collect_diaries,
    default_run_id,
    render_article,
    select_diary_with_decision,
)


READY_PREFIX = os.environ.get("NOTE_READY_PREFIX", "note_ready")
FAILED_PREFIX = os.environ.get("NOTE_FAILED_PREFIX", "note_failed")
LANE = os.environ.get("NOTE_LANE", "note_daily_recipe")
PROMPT_VERSION = os.environ.get("NOTE_PROMPT_VERSION", "2026-05-28-v1")
THEME_HISTORY_LIMIT = int(os.environ.get("NOTE_THEME_HISTORY_LIMIT", "100"))
FALLBACK_POLICY = "JSON-LD と graph_data.js への代替生成は行わない"


def _headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def _json_response(payload: dict[str, Any], status: int):
    return json.dumps(payload, ensure_ascii=False), status, _headers()


def _stop_report(
    run_id: str,
    reason: str,
    message: str,
    status: int,
    error: Exception | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    report: dict[str, Any] = {
        "status": "stopped",
        "run_id": run_id,
        "reason": reason,
        "message": message,
        "source": "neo4j",
        "fallback_attempted": False,
        "fallback_policy": FALLBACK_POLICY,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if error is not None:
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
    if extra:
        report.update(extra)
    try:
        report["stop_report_path"] = gcs_io.save_json(
            f"{FAILED_PREFIX}/{run_id}/stop_report.json", report
        )
    except Exception as gcs_error:
        report["stop_report_save_error"] = str(gcs_error)
    return report, status


def _mark_published(data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    diary_id = str(data.get("diary_id") or "").strip()
    note_url = str(data.get("note_url") or "").strip()
    if not diary_id:
        return {"error": "diary_id is required"}, 400
    with Neo4jDiaryClient() as client:
        updated = client.mark_published(diary_id, LANE, PROMPT_VERSION, note_url=note_url)
    if not updated:
        return {
            "status": "stopped",
            "reason": "neo4j_generation_not_found",
            "message": "公開済みに更新できるNoteGenerationが見つかりませんでした。",
            "diary_id": diary_id,
            "source": "neo4j",
        }, 404
    return {
        "status": "ok",
        "action": "mark_published",
        "diary_id": diary_id,
        "source": "neo4j",
    }, 200


@functions_framework.http
def generate_note_draft(request):
    if request.method == "OPTIONS":
        return "", 204, _headers()
    if request.method != "POST":
        return _json_response({"error": "POST only"}, 405)

    data = request.get_json(silent=True) or {}
    if data.get("action") == "mark_published":
        payload, status = _mark_published(data)
        return _json_response(payload, status)

    run_id = str(data.get("run_id") or default_run_id()).strip()
    diary_id = str(data.get("diary_id") or "").strip() or None
    allow_reuse = bool(data.get("allow_reuse", False))
    allow_theme_overlap = bool(data.get("allow_theme_overlap", False))

    try:
        with Neo4jDiaryClient() as client:
            nodes = [client.fetch_diary(diary_id)] if diary_id else client.fetch_diaries()
            nodes = [node for node in nodes if node]
            blocked = client.fetch_generation_blocked_ids(LANE, PROMPT_VERSION)
            theme_history = client.fetch_generation_theme_history(
                LANE,
                PROMPT_VERSION,
                limit=THEME_HISTORY_LIMIT,
            )
    except Exception as error:
        payload, status = _stop_report(
            run_id,
            "neo4j_unavailable",
            "Neo4jに接続できないため、note下書き生成を停止しました。",
            503,
            error,
        )
        return _json_response(payload, status)

    diaries = collect_diaries(nodes)
    if not diaries:
        payload, status = _stop_report(
            run_id,
            "neo4j_no_diaries",
            "Neo4jから日記ノードを取得できなかったため停止しました。",
            404,
        )
        return _json_response(payload, status)

    selection = select_diary_with_decision(
        diaries,
        blocked_diary_ids=blocked,
        diary_id=diary_id,
        allow_reuse=allow_reuse,
        theme_history=theme_history,
        allow_theme_overlap=allow_theme_overlap,
        theme_overlap_threshold=THEME_OVERLAP_THRESHOLD,
    )
    diary = selection["diary"]
    if diary is None:
        if selection["reason"] == "theme_conflict":
            payload, status = _stop_report(
                run_id,
                "neo4j_theme_conflict",
                "既に生成・公開済みの記事テーマと近いため停止しました。",
                409,
                extra={
                    "theme_conflicts": selection["theme_conflicts"][:5],
                    "theme_history_count": selection.get("theme_history_count", 0),
                },
            )
            return _json_response(payload, status)
        payload, status = _stop_report(
            run_id,
            "neo4j_no_eligible_diary",
            "未使用かつanalysis_contentを持つ日記候補がないため停止しました。",
            409,
        )
        return _json_response(payload, status)

    try:
        with Neo4jDiaryClient() as client:
            claim = client.claim_generation(diary.id, LANE, PROMPT_VERSION, run_id)
    except Exception as error:
        payload, status = _stop_report(
            run_id,
            "neo4j_claim_failed",
            "Neo4j上のNoteGeneration claimに失敗したため停止しました。",
            503,
            error,
        )
        return _json_response(payload, status)
    if not claim["claimed"]:
        payload, status = _stop_report(
            run_id,
            "neo4j_generation_already_exists",
            "同じ日記のnote生成状態がNeo4jに存在するため停止しました。",
            409,
        )
        payload["existing_generation"] = claim
        return _json_response(payload, status)

    try:
        article = render_article(diary, run_id)
        if not article["quality"]["passed"]:
            gcs_io.save_json(
                f"{FAILED_PREFIX}/{run_id}/quality_report.json", article["quality"]
            )
            with Neo4jDiaryClient() as client:
                client.mark_generation(
                    claim["generation_id"],
                    "failed",
                    {"failure_reason": "quality_failed"},
                )
            payload, status = _stop_report(
                run_id,
                "quality_failed",
                "品質チェックに通らないためnote ready成果物として保存しません。",
                422,
            )
            payload["quality"] = article["quality"]
            return _json_response(payload, status)

        article_id = f"pomera_note_{run_id}"
        prefix = f"{READY_PREFIX}/{run_id}"
        md_path = gcs_io.save_text(f"{prefix}/article.md", article["markdown"])
        meta = {
            "article_id": article_id,
            "run_id": run_id,
            "title": article["title"],
            "source": "neo4j",
            "source_diary_ids": [article["source_diary_id"]],
            "source_dates": [article["source_date"]],
            "markdown_path": md_path,
            "theme_profile": article["theme_profile"],
            "theme_decision": article["theme_decision"],
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        meta_path = gcs_io.save_json(f"{prefix}/article.json", meta)
        quality_path = gcs_io.save_json(
            f"{prefix}/quality_report.json", article["quality"]
        )
        state_manifest = {
            "source": "neo4j",
            "lane": LANE,
            "prompt_version": PROMPT_VERSION,
            "last_generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "article_history": [
                {
                    "article_id": article_id,
                    "run_id": run_id,
                    "title": article["title"],
                    "source_diary_ids": [article["source_diary_id"]],
                    "source_dates": [article["source_date"]],
                    "status": "generated",
                    "markdown_path": md_path,
                    "meta_path": meta_path,
                    "quality_path": quality_path,
                    "theme_profile": article["theme_profile"],
                    "theme_decision": article["theme_decision"],
                }
            ],
        }
        state_path = gcs_io.save_json(f"{prefix}/state_snapshot.json", state_manifest)
        with Neo4jDiaryClient() as client:
            updated = client.mark_generation(
                claim["generation_id"],
                "generated",
                {
                    "article_id": article_id,
                    "title": article["title"],
                    "markdown_path": md_path,
                    "meta_path": meta_path,
                    "quality_path": quality_path,
                    "theme_cluster": article["theme_profile"]["theme_cluster"],
                    "theme_keywords": article["theme_profile"]["theme_keywords"],
                    "theme_basis_text": article["theme_profile"]["theme_basis_text"],
                    "theme_summary": article["theme_profile"]["theme_summary"],
                    "theme_profile_version": article["theme_profile"][
                        "theme_profile_version"
                    ],
                    "theme_profile_source": article["theme_profile"][
                        "theme_profile_source"
                    ],
                    "max_theme_similarity": article["theme_decision"][
                        "max_similarity"
                    ],
                    "theme_similarity_threshold": article["theme_decision"][
                        "threshold"
                    ],
                    "theme_history_count": article["theme_decision"][
                        "history_count"
                    ],
                    "theme_overlap_allowed": allow_theme_overlap,
                },
            )
        if not updated:
            raise RuntimeError("claimed NoteGeneration could not be updated")
    except Exception as error:
        try:
            with Neo4jDiaryClient() as client:
                client.mark_generation(
                    claim["generation_id"],
                    "failed",
                    {"failure_reason": "artifact_or_generation_update_failed"},
                )
        except Exception as mark_error:
            print(f"failed to mark NoteGeneration as failed: {mark_error}")
        payload, status = _stop_report(
            run_id,
            "artifact_or_generation_update_failed",
            "claim後の成果物保存またはNeo4j状態更新に失敗したため停止しました。",
            500,
            error,
        )
        return _json_response(payload, status)

    return _json_response(
        {
            "status": "ok",
            "article_id": article_id,
            "run_id": run_id,
            "title": article["title"],
            "source": "neo4j",
            "source_diary_ids": [article["source_diary_id"]],
            "source_dates": [article["source_date"]],
            "markdown_path": md_path,
            "meta_path": meta_path,
            "quality_path": quality_path,
            "state_path": state_path,
            "theme_profile": article["theme_profile"],
            "theme_decision": article["theme_decision"],
            "quality": article["quality"],
        },
        200,
    )
