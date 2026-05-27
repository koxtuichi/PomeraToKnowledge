import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_pomera_daily_recipes.py"
spec = importlib.util.spec_from_file_location("generate_pomera_daily_recipes", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def sample_graph():
    return {
        "nodes": [
            {
                "id": "日記:2026-05-01",
                "type": "日記",
                "date": "2026-05-01",
                "label": "2026-05-01の日記",
                "detail": "仕事の提案が重く、次の一歩が見えない。",
                "analysis_content": {
                    "gravity_map": [{"task": "仕事の提案", "net_assessment": "仕事の論点が多く停滞している。"}],
                    "antigravity_actions": [{"action": "5分だけ論点を1つに絞る。"}],
                    "insights": [{"finding": "論点を減らすと動き出しやすい。"}],
                },
            },
            {
                "id": "日記:2026-05-02",
                "type": "日記",
                "date": "2026-05-02",
                "label": "2026-05-02の日記",
                "detail": "ブログとnoteの発信を続けたい。",
                "analysis_content": {
                    "blog_ideas": [{"title": "ポメラ駆動"}],
                    "insights": [{"finding": "発信は小さい型にすると継続しやすい。"}],
                },
            },
        ],
        "edges": [],
    }


def run_args(tmp_path, **overrides):
    args = argparse.Namespace(
        source="neo4j",
        guide=ROOT / "config" / "pomera_daily_weekday_guide.json",
        manifest=tmp_path / "note_recipe_manifest.json",
        output_dir=tmp_path / "note_recipe_ready",
        week_id="2026-W22",
        dry_run=True,
        allow_reuse=False,
        no_update_manifest=True,
        overwrite=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_default_manifest_marks_neo4j_as_only_source(tmp_path):
    manifest = module.load_manifest(tmp_path / "missing_manifest.json")
    assert manifest["source_priority"] == ["neo4j"]
    assert manifest["source_policy"] == {
        "primary": "neo4j",
        "fallback_to_jsonld": False,
        "fallback_to_graph_data": False,
    }


def test_existing_manifest_source_policy_is_normalized(tmp_path):
    manifest_path = tmp_path / "note_recipe_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "source_priority": ["graph_data", "neo4j"],
                "used_diary_ids": ["日記:2026-05-01"],
                "generated_weeks": [],
                "article_history": [],
                "last_run_at": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = module.load_manifest(manifest_path)
    assert manifest["source_priority"] == ["neo4j"]
    assert manifest["source_policy"] == {
        "primary": "neo4j",
        "fallback_to_jsonld": False,
        "fallback_to_graph_data": False,
    }
    assert manifest["used_diary_ids"] == ["日記:2026-05-01"]


def test_parser_rejects_graph_data_source():
    with pytest.raises(SystemExit):
        module.build_parser().parse_args(["--source", "graph_data"])


def test_run_reads_from_neo4j_by_default(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(module, "load_graph_from_neo4j", sample_graph)
    exit_code = module.run(run_args(tmp_path))
    output = capsys.readouterr()
    assert exit_code == 0
    assert "日記:2026-05-02" in output.out
    assert output.err == ""


def test_cli_stops_without_fallback_when_neo4j_env_is_missing(tmp_path):
    env = os.environ.copy()
    for key in ("NEO4J_URI", "NEO4J_USER", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        env.pop(key, None)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == module.NEO4J_STOP_EXIT_CODE
    assert '"reason": "neo4j_unavailable"' in result.stderr
    assert '"fallback_attempted": false' in result.stderr
    assert result.stdout == ""


def test_run_stops_without_fallback_when_neo4j_is_unavailable(monkeypatch, tmp_path, capsys):
    def fail_to_connect():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(module, "load_graph_from_neo4j", fail_to_connect)
    exit_code = module.run(run_args(tmp_path))
    output = capsys.readouterr()
    assert exit_code == module.NEO4J_STOP_EXIT_CODE
    assert '"status": "stopped"' in output.err
    assert '"reason": "neo4j_unavailable"' in output.err
    assert '"fallback_attempted": false' in output.err
    assert "JSON-LD" in output.err
    assert output.out == ""


def test_run_stops_when_neo4j_has_no_diary_nodes(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(module, "load_graph_from_neo4j", lambda: {"nodes": [], "edges": []})
    exit_code = module.run(run_args(tmp_path))
    output = capsys.readouterr()
    assert exit_code == module.NEO4J_NO_DIARY_EXIT_CODE
    assert '"reason": "neo4j_no_diaries"' in output.err
    assert '"fallback_attempted": false' in output.err
    assert output.out == ""


def test_collect_diaries_prefers_analysis_node():
    graph = sample_graph()
    graph["nodes"].append(
        {
            "id": "日記:20260501",
            "type": "日記",
            "date": "2026-05-01",
            "detail": "分析なしの重複日記",
        }
    )
    diaries = module.collect_diaries(graph)
    may_first = [d for d in diaries if d.date == "2026-05-01"][0]
    assert may_first.id == "日記:2026-05-01"
    assert may_first.analysis


def test_assemble_week_uses_unconsumed_diaries_first():
    guide = module.load_guide(ROOT / "config" / "pomera_daily_weekday_guide.json")
    diaries = module.collect_diaries(sample_graph())
    slots = module.assemble_week(diaries, guide, {"日記:2026-05-01"})
    used = [slot.diary.id for slot in slots if slot.diary]
    assert "日記:2026-05-01" not in used
    assert "日記:2026-05-02" in used


def test_choose_best_for_slot_respects_theme_order():
    diaries = [module.score_diary(diary) for diary in module.collect_diaries(sample_graph())]
    selected = module.choose_best_for_slot(diaries, ["publishing", "work"])
    assert selected.id == "日記:2026-05-02"


def test_sanitize_text_removes_sensitive_terms():
    text = module.sanitize_text("2026年5月1日に沙也香とKnowbeの話をして80.2kgで、傑さんとSlackの後に鍼治療へ行った")
    assert "沙也香" not in text
    assert "Knowbe" not in text
    assert "80.2kg" not in text
    assert "傑さん" not in text
    assert "Slack" not in text
    assert "治療" not in text
    assert "パートナー" in text


def test_render_article_is_not_prompt_sale():
    guide = module.load_guide(ROOT / "config" / "pomera_daily_weekday_guide.json")
    diary = module.score_diary(module.collect_diaries(sample_graph())[0])
    slot = module.ArticleSlot(
        index=1,
        day="monday",
        day_label="月",
        preferred_themes=["work"],
        actual_theme="work",
        fallback_theme="next_step",
        diary=diary,
    )
    markdown = module.render_article(slot, guide, "2026-W22")
    quality = module.quality_check(markdown, slot)
    assert "プロンプト" not in markdown
    assert "source_diary_id" not in markdown
    assert "source_date" not in markdown
    assert module.ARTICLE_MIN_CHARS <= module.visible_character_count(markdown) <= module.ARTICLE_MAX_CHARS
    assert quality["passed"]
    assert quality["length_ok"]
    assert "## 15分で書く5ステップ" in markdown
    assert "## 書き込み欄" in markdown
    assert "## つまずいたときの調整" in markdown
