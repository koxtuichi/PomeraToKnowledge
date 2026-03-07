#!/usr/bin/env python3
"""
日記ノード → キャラクター画像生成スクリプト
===============================================
モンスターファーム方式：日記のナレッジグラフノードを読み込み、
ノードの type / label / detail から Gemini でキャラ画像を生成し
daily_graph.json に spriteUrl を付与する。

使い方:
  python scripts/generate_node_sprites.py
  python scripts/generate_node_sprites.py --force  # 全ノードを再生成
"""

import json
import os
import re
import sys
import argparse
import hashlib
import time
import base64
from pathlib import Path
from typing import Optional

# ===== 設定 =====
SCRIPT_DIR   = Path(__file__).parent
ROOT_DIR     = SCRIPT_DIR.parent
GRAPH_PATH   = ROOT_DIR / "daily_graph.json"
SPRITE_DIR   = ROOT_DIR / "sprites" / "characters" / "nodes"
SPRITE_REPO_PREFIX = "sprites/characters/nodes"  # GitHub Pages / rawコンテンツ用の相対パス

API_KEY = os.environ.get("GOOGLE_API_KEY", "")

# ===== レア度定義 =====
# ノードtypeからレア度を決定
RARITY_BY_TYPE = {
    "人物": "UR",  # 必殺技シーン
    "知見": "SR",  # 技発動シーン
    "出来事": "SR",  # ドラマチックシーン
    "タスク": "R",   # 戦闘構えポーズ
    "日記": "N",    # 立ち絵
}

# レア度 → ポーズ/背景プロンプト
RARITY_POSE = {
    "N": (
        "neutral standing pose, front facing, calm relaxed stance, "
        "simple parchment/washi paper background with subtle texture"
    ),
    "R": (
        "battle-ready stance, hand gripping weapon, slight crouch, "
        "determined fierce expression, dynamic pose ready to strike, "
        "stone dungeon or forest background with moody lighting"
    ),
    "SR": (
        "mid-action dynamic pose, actively casting spell or attacking, "
        "motion lines, glowing magical aura or weapon trail effect, "
        "dramatic speed lines background, intense expression, "
        "skill activation scene like a trading card"
    ),
    "UR": (
        "ultimate special skill cinematic pose, enormous dramatic aura and energy explosion, "
        "full-art vertical trading card illustration, "
        "character at center of massive power release, light rays and particle effects, "
        "epic legendary scene, Yu-Gi-Oh card art style ultra dramatic composition, "
        "glowing eyes, ultimate technique moment"
    ),
}

RARITY_LABEL = {"N": "N", "R": "R", "SR": "SR", "UR": "UR"}

# ノード type → キャラクタービジュアル設定
TYPE_PROMPTS = {
    "日記": {
        "class_hint": "traveler scribe chronicler",
        "visual":     "brown leather journal book, quill pen, worn travel cloak, thoughtful expression",
        "palette":    "warm earthy brown, amber, cream",
    },
    "タスク": {
        "class_hint": "warrior soldier mercenary",
        "visual":     "iron armor, sword and shield, battle-scarred equipment",
        "palette":    "steel blue, dark iron, rust orange",
    },
    "知見": {
        "class_hint": "sage scholar archmage",
        "visual":     "wide brimmed hat, ancient tome, spectacles, robes with glowing runes",
        "palette":    "ivory white, soft blue, silver, glowing cyan accents",
    },
    "出来事": {
        "class_hint": "bard scout ranger",
        "visual":     "hooded cloak, lute or map scroll, adventurer gear, quick agile build",
        "palette":    "forest green, deep brown, gold accent",
    },
    "人物": {
        "class_hint": "legendary hero champion",
        "visual":     "ornate noble armor, divine weapon, flowing cape, intense charismatic presence",
        "palette":    "golden, royal purple, radiant warm highlights",
    },
}

DEFAULT_TYPE_PROMPT = {
    "class_hint": "traveler adventurer",
    "visual":     "simple traveling clothes, small pack, open friendly expression",
    "palette":    "muted warm browns and greens",
}


def get_rarity(node: dict) -> str:
    """ノードのtypeからレア度を返す"""
    return RARITY_BY_TYPE.get(node.get("type", ""), "N")



def node_to_sprite_id(node_id: str) -> str:
    """ノードIDをファイル名として安全な文字列に変換"""
    safe = re.sub(r'[^\w\-]', '_', node_id)
    # 長すぎる場合はハッシュで短縮
    if len(safe) > 60:
        h = hashlib.md5(node_id.encode()).hexdigest()[:8]
        safe = safe[:52] + "_" + h
    return safe


def build_prompt(node: dict) -> str:
    """ノード情報からレア度連動のキャラクターアートプロンプトを構築"""
    tp = TYPE_PROMPTS.get(node.get("type", ""), DEFAULT_TYPE_PROMPT)
    rarity = get_rarity(node)
    pose_bg = RARITY_POSE[rarity]
    detail = node.get("detail", "")
    detail_snippet = detail[:60] + ("…" if len(detail) > 60 else "")

    prompt = (
        f"Pixel art RPG character card art, Elin game style, medieval fantasy, "
        f"vertical portrait format 3:4 aspect ratio, "
        f"{tp['class_hint']} character, "
        f"{tp['visual']}, "
        f"personality hint: {detail_snippet}, "
        f"color palette: {tp['palette']}, "
        f"{pose_bg}, "
        f"high quality detailed pixel art, rich color depth, expressive character design, "
        f"NO text, NO letters, NO writing, NO labels, NO numbers, NO UI elements"
    )
    return prompt

def build_story_prompt(node: dict) -> str:
    """ノード情報からキャラクターの背景ストーリープロンプトを構築"""
    tp = TYPE_PROMPTS.get(node.get("type", ""), DEFAULT_TYPE_PROMPT)
    label  = node.get("label", "")
    detail = node.get("detail", "")
    node_type = node.get("type", "旅人")

    prompt = (
        f"あなたは中世ファンタジーRPGのゲームシナリオライターです。\n"
        f"以下の情報をもとに、このキャラクターの短い背景ストーリーを日本語で2〜3文生成してください。\n"
        f"文体は詩的で幻想的に。プレイヤーがこのキャラに出会ったときの感覚が伝わるように書いてください。\n\n"
        f"ノードタイプ: {node_type}\n"
        f"ラベル: {label}\n"
        f"内容: {detail}\n\n"
        f"このキャラは {tp['class_hint']} の系統で、色合いは {tp['palette']} のイメージ。\n"
        f"ゲーム内の旅人紹介文として、50〜80文字程度で出力してください。"
    )
    return prompt


def generate_story_with_gemini(prompt: str) -> Optional[str]:
    """
    Gemini 2.5 Flash でキャラクターの背景ストーリーを生成し文字列を返す。
    失敗時は None を返す。
    """
    try:
        from google import genai

        client = genai.Client(api_key=API_KEY)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = response.text.strip()
        return text
    except Exception as e:
        print(f"  ❌ ストーリー生成エラー: {e}")
        return None



def generate_image_with_gemini(prompt: str) -> Optional[bytes]:
    """
    Gemini API (gemini-2.5-flash-image) で画像を生成し、
    PNG バイト列を返す。失敗時は None を返す。
    """
    try:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=API_KEY)

        response = client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                return part.inline_data.data  # bytes

        print(f"  ⚠️  画像データが空でした")
        return None

    except Exception as e:
        print(f"  ❌ Gemini API エラー: {e}")
        return None


def process_nodes(force: bool = False) -> int:
    """ノードを処理して画像を生成する。生成したノード数を返す"""
    if not GRAPH_PATH.exists():
        print(f"❌ {GRAPH_PATH} が見つかりません")
        return 0

    with open(GRAPH_PATH, encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph.get("nodes", [])
    if not nodes:
        print("ノードがありません。スキップします。")
        return 0

    SPRITE_DIR.mkdir(parents=True, exist_ok=True)

    generated = 0
    for node in nodes:
        node_id = node.get("id", "")
        if not node_id:
            continue

        # すでに spriteUrl があればスキップ（--force で強制再生成）
        if node.get("spriteUrl") and not force:
            print(f"  ⏭  スキップ（生成済み）: {node_id}")
            continue

        sprite_filename = node_to_sprite_id(node_id) + ".png"
        sprite_path = SPRITE_DIR / sprite_filename

        # ファイルが既に存在する場合も spriteUrl / rarity だけ付与してスキップ
        if sprite_path.exists() and not force:
            rel = f"{SPRITE_REPO_PREFIX}/{sprite_filename}"
            node["spriteUrl"] = rel
            node["rarity"] = get_rarity(node)
            print(f"  ✅ 既存ファイルを使用: {rel}")
            continue

        print(f"🎨 生成中: {node_id}  [{node.get('type', '?')}] {node.get('label', '')}")
        prompt = build_prompt(node)
        print(f"   プロンプト: {prompt[:80]}…")

        img_bytes = generate_image_with_gemini(prompt)
        if img_bytes:
            sprite_path.write_bytes(img_bytes)
            rel = f"{SPRITE_REPO_PREFIX}/{sprite_filename}"
            node["spriteUrl"] = rel
            node["rarity"] = get_rarity(node)
            print(f"   💾 保存: {rel} [{get_rarity(node)}]")
            generated += 1
        else:
            print(f"   ⚠️  {node_id} の画像生成をスキップ")

        # ストーリー生成（未取得もしくは強制再生成の場合）
        if not node.get("story") or force:
            print(f"📖 ストーリー生成中: {node_id}")
            story_prompt = build_story_prompt(node)
            story = generate_story_with_gemini(story_prompt)
            if story:
                node["story"] = story
                print(f"   📝 ストーリー: {story[:60]}…")

        # レート制限対策
        time.sleep(2)

    # daily_graph.json を更新して保存
    with open(GRAPH_PATH, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完了：{generated} 件の画像を生成しました")
    return generated


def main():
    parser = argparse.ArgumentParser(description="日記ノード → キャラ画像生成")
    parser.add_argument("--force", action="store_true", help="spriteUrlが付いていても再生成する")
    parser.add_argument("--dry-run", action="store_true", help="プロンプトだけ表示して生成しない")
    args = parser.parse_args()

    if not API_KEY:
        print("❌ GOOGLE_API_KEY が設定されていません")
        sys.exit(1)

    if args.dry_run:
        print("=== DRY RUN: プロンプト確認モード ===")
        with open(GRAPH_PATH, encoding="utf-8") as f:
            graph = json.load(f)
        for node in graph.get("nodes", []):
            if not node.get("id"):
                continue
            print(f"\nノード: {node['id']}")
            print(f"  type  : {node.get('type')}")
            print(f"  label : {node.get('label')}")
            print(f"  prompt: {build_prompt(node)}")
        return

    process_nodes(force=args.force)


if __name__ == "__main__":
    main()
