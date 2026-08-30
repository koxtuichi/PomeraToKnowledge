import argparse
import importlib.util
import json
import os
import subprocess
import sys
from types import SimpleNamespace
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


def sample_weekly_graph():
    return {
        "nodes": [
            {
                "id": f"日記:2026-05-{day:02d}",
                "type": "日記",
                "date": f"2026-05-{day:02d}",
                "label": f"2026-05-{day:02d}の日記",
                "detail": f"仕事の確認事項が増えたので、次に確認することを整理した日 {day}",
                "analysis_content": {
                    "gravity_map": [
                        {
                            "task": "仕事の確認事項整理",
                            "constraints": [{"name": "確認事項が多い"}],
                            "net_assessment": "仕事の確認事項が多く、次の一歩を選びにくい。",
                        }
                    ],
                    "antigravity_actions": [
                        {"action": "今日確認する項目を3つだけメモする。"}
                    ],
                    "insights": [
                        {"finding": "確認事項を絞ると、次の会話に入りやすい。"}
                    ],
                },
            }
            for day in range(1, 8)
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
        mode="single",
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
    monkeypatch.setattr(module, "load_materials_from_neo4j", lambda diary_ids: {})
    exit_code = module.run(run_args(tmp_path))
    output = capsys.readouterr()
    assert exit_code == 0
    assert '"mode": "single"' in output.out
    assert "selected_diary_id" in output.out
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


def test_run_stops_without_fallback_when_neo4j_material_query_fails(
    monkeypatch, tmp_path, capsys
):
    def fail_to_query_materials(diary_ids):
        raise RuntimeError("query failed")

    monkeypatch.setattr(module, "load_graph_from_neo4j", sample_graph)
    monkeypatch.setattr(module, "load_materials_from_neo4j", fail_to_query_materials)
    exit_code = module.run(run_args(tmp_path, dry_run=False))
    output = capsys.readouterr()

    assert exit_code == module.NEO4J_STOP_EXIT_CODE
    assert '"reason": "neo4j_material_query_failed"' in output.err
    assert '"fallback_attempted": false' in output.err
    assert "JSON-LD" in output.err
    assert output.out == ""
    assert not (tmp_path / "note_recipe_ready").exists()


def test_run_single_generates_one_longform_article(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(module, "load_graph_from_neo4j", sample_graph)
    monkeypatch.setattr(module, "load_materials_from_neo4j", lambda diary_ids: {})
    exit_code = module.run(run_args(tmp_path, dry_run=False, overwrite=True))
    output = capsys.readouterr()

    assert exit_code == 0
    assert '"mode": "single"' in output.out
    assert '"article_count": 1' in output.out
    run_dir = tmp_path / "note_recipe_ready" / "2026-W22"
    markdowns = list(run_dir.glob("*.md"))
    assert len(markdowns) == 1
    markdown = markdowns[0].read_text(encoding="utf-8")
    assert module.ARTICLE_MIN_CHARS <= module.visible_character_count(markdown) <= module.ARTICLE_MAX_CHARS
    assert "## 問題はなにか" in markdown
    assert "## 背景" in markdown
    assert "## どのように対処すればいいのか" in markdown
    assert "同じ重さ" not in markdown
    quality = json.loads((run_dir / "quality_report.json").read_text(encoding="utf-8"))
    assert quality["passed"]
    article_quality = quality["items"][0]["quality"]
    assert article_quality["concrete_signal_ok"]
    assert article_quality["seed_concrete_checks"]["passed"]
    assert len(article_quality["concrete_signals"]) >= 3


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


def test_run_weekly_mode_keeps_legacy_seven_draft_flow(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(module, "load_graph_from_neo4j", sample_graph)
    exit_code = module.run(run_args(tmp_path, mode="weekly"))
    output = capsys.readouterr()

    assert exit_code == 0
    assert '"slot": 1' in output.out
    assert "selected_diary_id" not in output.out


def test_run_weekly_mode_can_generate_legacy_seven_articles(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(module, "load_graph_from_neo4j", sample_weekly_graph)
    monkeypatch.setattr(module, "load_materials_from_neo4j", lambda diary_ids: {})
    exit_code = module.run(run_args(tmp_path, mode="weekly", dry_run=False, overwrite=True))
    output = capsys.readouterr()

    assert exit_code == 0
    assert '"mode": "weekly"' in output.out
    assert '"article_count": 7' in output.out
    run_dir = tmp_path / "note_recipe_ready" / "2026-W22"
    markdowns = list(run_dir.glob("*.md"))
    assert len(markdowns) == 7
    quality = json.loads((run_dir / "quality_report.json").read_text(encoding="utf-8"))
    assert quality["passed"]
    assert len(quality["items"]) == 7


def test_sanitize_text_removes_sensitive_terms():
    text = module.sanitize_text("2026年5月1日に沙也香とKnowbeの話をして80.2kgで、傑さんとSlackの後に鍼治療へ行った")
    assert "沙也香" not in text
    assert "Knowbe" not in text
    assert "80.2kg" not in text
    assert "傑さん" not in text
    assert "Slack" not in text
    assert "治療" not in text
    assert "パートナー" in text


def test_sanitize_text_softens_old_gravity_terms():
    text = module.sanitize_text("技術的トラブルが重力となるが、制作物の引力は強い。")
    assert "重力" not in text
    assert "引力" not in text
    assert "行動を止めている理由" in text
    assert "何度も戻って見たくなる手応え" in text


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
    quality = module.quality_check(markdown, slot, mode="weekly")
    assert "プロンプト" not in markdown
    assert "source_diary_id" not in markdown
    assert "source_date" not in markdown
    assert module.LEGACY_ARTICLE_MIN_CHARS <= module.visible_character_count(markdown) <= module.LEGACY_ARTICLE_MAX_CHARS
    assert quality["passed"]
    assert quality["length_ok"]
    assert "## 15分で書く5ステップ" in markdown
    assert "## 書き込み欄" in markdown
    assert "## つまずいたときの調整" in markdown
    assert "## 問題はなにか" in markdown
    assert "## なにに困っているのか" in markdown
    assert "## 目指す状態" in markdown


def test_primary_quality_rejects_generic_seed_even_with_template_signals():
    diary = module.score_diary(module.collect_diaries(sample_graph())[0])
    seed = {
        "problem": "進行中",
        "background": "今日の日記エントリ",
        "pain_points": [],
        "desired_state": "達成",
        "current_status": "進行中",
        "next_step": "進行中",
        "evidence": [],
        "situation": "進行中",
        "finding": "達成",
        "action": "進行中",
    }
    candidate = module.ArticleCandidate(
        diary=diary,
        material=None,
        seed=seed,
        score=0.0,
        reasons=[],
    )

    markdown = module.render_primary_article(candidate, "test-run")
    quality = module.quality_check(markdown, mode="primary", seed=seed)

    assert quality["concrete_signal_ok"]
    assert not quality["seed_concrete_checks"]["passed"]
    assert not quality["concrete_language"]
    assert not quality["passed"]


def test_render_article_uses_cypher_material():
    guide = module.load_guide(ROOT / "config" / "pomera_daily_weekday_guide.json")
    diary = module.score_diary(module.collect_diaries(sample_graph())[0])
    material = SimpleNamespace(
        problem="提案の論点が多すぎて次の判断が止まっている。",
        background="仕事の提案を進めたいが、確認事項が混ざっている。",
        pain_points=["情報が足りない", "誰に確認するかが曖昧"],
        desired_state="今日決める一文だけを取り出せている。",
        current_status="提案は進行中だが、最初の確認で止まっている。",
        next_step="関係者に確認する一文を5分で書く。",
        evidence=["日記では提案が重いと書かれている。"],
    )
    slot = module.ArticleSlot(
        index=1,
        day="monday",
        day_label="月",
        preferred_themes=["work"],
        actual_theme="work",
        fallback_theme="next_step",
        diary=diary,
        material=material,
    )

    markdown = module.render_article(slot, guide, "2026-W22")

    assert "提案の論点が多すぎて次の判断が止まっている" in markdown
    assert "関係者に確認する一文を5分で書く" in markdown
    assert "情報が足りない" in markdown
    assert module.quality_check(markdown, slot, mode="weekly")["passed"]


def test_extract_seed_ignores_off_theme_cypher_material():
    diary = module.score_diary(module.collect_diaries(sample_graph())[0])
    slot = module.ArticleSlot(
        index=1,
        day="monday",
        day_label="月",
        preferred_themes=["work"],
        actual_theme="work",
        fallback_theme="next_step",
        diary=diary,
        material=SimpleNamespace(
            problem="体重の数値を下げたい。",
            background="食事と健康の話。",
            pain_points=["カロリー過多"],
            desired_state="健康を整える。",
            current_status="体重管理中。",
            next_step="食事を見直す。",
            evidence=["進捗管理を楽しんだ。"],
        ),
    )

    seed = module.extract_seed(slot)

    assert seed["problem"] != "体重の数値を下げたい。"
    assert seed["action"] == "いま一番軽くできる一歩を、5分以内に終わる形で書く。"


def test_extract_seed_prefers_theme_relevant_analysis_items():
    diary = module.DiaryCandidate(
        id="日記:2026-03-01",
        date="2026-03-01",
        label="日記",
        detail="家族予定、YouTube動画トラブル、仕事MTGについて記録。",
        analysis={
            "gravity_map": [
                {
                    "task": "YouTube動画の継続運用",
                    "constraints": [{"name": "BANリスクの予期不安"}],
                    "net_assessment": "動画トラブルが気になっている。",
                }
            ],
            "antigravity_actions": [
                {
                    "action": "知人とのMTGに向け、話すべき3項目をポメラでメモする",
                    "target_task": "Knowbe MTG前の思考整理",
                    "effect": "会議前に論点を絞り、時間のひっかかりを減らす。",
                },
                {
                    "action": "YouTube Studioを見ない",
                    "target_task": "YouTube動画アップロードトラブル",
                    "effect": "再生回数への不安を遮断する。",
                },
            ],
            "insights": [
                {
                    "finding": "不完全な動画への高い反応がある。",
                    "implication": "動画には手応えがある。",
                },
                {
                    "finding": "Knowbeでの受動的な不満を、Saitekiでの能動的な成果で相殺し始めている。",
                    "implication": "進捗を可視化するスタイルを仕事にも転用できる。",
                },
            ],
        },
        themes={},
        score=0.0,
    )
    slot = module.ArticleSlot(
        index=1,
        day="monday",
        day_label="月",
        preferred_themes=["work"],
        actual_theme="work",
        fallback_theme="next_step",
        diary=diary,
    )

    seed = module.extract_seed(slot)

    assert "MTG前の思考整理" in seed["problem"]
    assert "動画" not in seed["problem"]
    assert "知人とのMTG" in seed["action"]
    assert "打ち合わせで話す3項目" in seed["finding"]
    assert seed["pain_points"] == ["会議前に話す論点と時間配分を絞りきれていない。"]
    assert all("BAN" not in point for point in seed["pain_points"])
