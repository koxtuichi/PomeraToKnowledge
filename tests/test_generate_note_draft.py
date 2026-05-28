import importlib.util
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "cloud_functions"
    / "generate_note_draft"
    / "note_article_writer.py"
)
spec = importlib.util.spec_from_file_location("note_article_writer", MODULE_PATH)
writer = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = writer
spec.loader.exec_module(writer)


def _sample_node(node_id="日記:2026-03-04"):
    return {
        "id": node_id,
        "type": "日記",
        "date": "2026-03-04",
        "label": "2026-03-04の日記",
        "detail": "仕事の休みを取り、確定申告を完了。別プロジェクトの業務が溜まっていることを確認した日。",
        "analysis_content": {
            "gravity_map": [
                {
                    "task": "別プロジェクトの業務滞留解消",
                    "net_assessment": "やるべきことは明確だが、量に圧倒されている。",
                    "constraints": [
                        {"name": "タスクの積み上がりによる心理的圧迫"},
                        {"name": "本業との兼ね合い"},
                    ],
                }
            ],
            "antigravity_actions": [
                {
                    "target_task": "別プロジェクト業務",
                    "action": "関係者への質問事項とテンプレートに必要な3項目をポメラで箇条書きにする。",
                    "effect": "相手が関わる確認を先に外へ出し、自分の作業待ち時間を減らす。",
                }
            ],
            "insights": [{"finding": "質問を先に切り出すと、待ち時間を減らせる。"}],
        },
    }


def _family_node(node_id="日記:2026-03-06"):
    return {
        "id": node_id,
        "type": "日記",
        "date": "2026-03-06",
        "label": "2026-03-06の日記",
        "detail": "家族の予定が重なり、保育と生活の段取りを先に決めたいと感じた日。",
        "analysis_content": {
            "gravity_map": [
                {
                    "task": "家族予定の段取り",
                    "net_assessment": "家族の予定と生活の用事が混ざり、今日決める順番が曖昧。",
                    "constraints": [
                        {"name": "保育予定の確認"},
                        {"name": "生活用事の重なり"},
                    ],
                }
            ],
            "antigravity_actions": [
                {
                    "target_task": "家族予定",
                    "action": "パートナーに確認する予定を3つに絞って、生活の段取りを一文で書く。",
                    "effect": "家族で確認することと自分で進める生活用事を分ける。",
                }
            ],
            "insights": [{"finding": "家族予定は先に確認先を決めると迷いが減る。"}],
        },
    }


def _history_from_diary(diary, generation_id="gen-old"):
    return [
        {
            "generation": {
                "id": generation_id,
                "status": "published",
                "title": "過去記事",
                **diary.theme_profile,
            }
        }
    ]


def test_render_article_passes_quality():
    diary = writer.collect_diaries([_sample_node()])[0]
    article = writer.render_article(diary, "test-run")
    quality = article["quality"]
    assert quality["passed"] is True
    assert quality["fallback"] is False
    assert quality["heading_count"] == 15
    assert quality["source_traceability"] is True
    assert not quality["forbidden_terms"]


def test_select_diary_excludes_generated_and_published_ids():
    diaries = writer.collect_diaries([_sample_node("日記:2026-03-04"), _sample_node("日記:2026-03-05")])
    blocked = {"日記:2026-03-04", "日記:2026-03-05"}
    assert writer.select_diary(diaries, blocked_diary_ids=blocked) is None


def test_select_diary_blocks_overlapping_theme_from_history():
    diary = writer.collect_diaries([_sample_node("日記:2026-03-04")])[0]
    selection = writer.select_diary_with_decision(
        [diary],
        theme_history=_history_from_diary(diary),
    )
    assert selection["diary"] is None
    assert selection["reason"] == "theme_conflict"
    assert selection["theme_conflicts"][0]["matched_generation_id"] == "gen-old"


def test_select_diary_uses_non_overlapping_theme_candidate():
    diaries = writer.collect_diaries(
        [_sample_node("日記:2026-03-04"), _family_node("日記:2026-03-06")]
    )
    by_id = {diary.id: diary for diary in diaries}
    work_diary = by_id["日記:2026-03-04"]
    family_diary = by_id["日記:2026-03-06"]
    selection = writer.select_diary_with_decision(
        diaries,
        theme_history=_history_from_diary(work_diary),
    )
    assert selection["diary"].id == family_diary.id
    assert selection["reason"] == "selected"


def test_legacy_history_rebuilds_theme_from_linked_diary():
    new_diary = writer.collect_diaries([_sample_node("日記:2026-03-05")])[0]
    legacy_history = [
        {
            "generation": {
                "id": "legacy-gen",
                "status": "published",
                "title": "100円｜仕事が溜まった日に、ポメラで次の質問を切り出す",
            },
            "diary": _sample_node("日記:2026-03-04"),
        }
    ]
    selection = writer.select_diary_with_decision(
        [new_diary],
        theme_history=legacy_history,
    )
    assert selection["diary"] is None
    assert selection["reason"] == "theme_conflict"
    assert selection["theme_conflicts"][0]["matched_generation_id"] == "legacy-gen"


def test_quality_rejects_forbidden_terms():
    markdown = "\n".join(
        [
            "# title",
            *[f"## {heading}\n本文" for heading in writer.REQUIRED_HEADINGS],
            "重力",
            "<!-- source: neo4j diary 日記:2026-03-04 / run test -->",
        ]
    )
    quality = writer.quality_check(markdown)
    assert quality["passed"] is False
    assert "重力" in quality["forbidden_terms"]


def test_collect_diaries_sorts_newer_first():
    diaries = writer.collect_diaries(
        [
            _sample_node("日記:2026-03-04"),
            {
                **_sample_node("日記:2026-03-05"),
                "date": "2026-03-05",
            },
        ]
    )
    assert [diary.date for diary in diaries] == ["2026-03-05", "2026-03-04"]
