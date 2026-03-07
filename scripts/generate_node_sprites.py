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

# ノード type → Elinスタイルキャラクタープロンプト設定
TYPE_PROMPTS = {
    "日記": {
        "class_hint": "traveler scribe chronicler",
        "visual":     "brown leather journal book, quill pen, worn travel cloak, thoughtful expression",
        "palette":    "warm earthy brown, amber, cream",
    },
    "タスク": {
        "class_hint": "warrior soldier mercenary",
        "visual":     "iron armor, sword or tool, determined resolute stance, utility belt",
        "palette":    "steel blue, dark iron, rust orange",
    },
    "知見": {
        "class_hint": "sage scholar mage",
        "visual":     "wide brimmed hat, open ancient tome, spectacles, calm knowing eyes, robes with runes",
        "palette":    "ivory white, soft blue, silver",
    },
    "出来事": {
        "class_hint": "bard scout ranger",
        "visual":     "hooded cloak, lute or map scroll, curious expression, adventurer gear",
        "palette":    "forest green, deep brown, gold accent",
    },
    "人物": {
        "class_hint": "hero champion",
        "visual":     "noble bearing, distinct costume, confident gaze, unique identity",
        "palette":    "golden, royal purple, warm highlights",
    },
}

DEFAULT_TYPE_PROMPT = {
    "class_hint": "traveler adventurer",
    "visual":     "simple traveling clothes, small pack, open friendly expression",
    "palette":    "muted warm browns and greens",
}


def node_to_sprite_id(node_id: str) -> str:
    """ノードIDをファイル名として安全な文字列に変換"""
    safe = re.sub(r'[^\w\-]', '_', node_id)
    # 長すぎる場合はハッシュで短縮
    if len(safe) > 60:
        h = hashlib.md5(node_id.encode()).hexdigest()[:8]
        safe = safe[:52] + "_" + h
    return safe


def build_prompt(node: dict) -> str:
    """ノード情報からElinスタイルのキャラクター画像生成プロンプトを構築"""
    tp = TYPE_PROMPTS.get(node.get("type", ""), DEFAULT_TYPE_PROMPT)
    label  = node.get("label", "")
    detail = node.get("detail", "")

    # detail が長い場合は先頭50文字だけ使う
    detail_snippet = detail[:60] + ("…" if len(detail) > 60 else "")

    prompt = (
        f"Pixel art RPG character sprite, Elin game style, medieval fantasy, "
        f"small chibi proportions 2-3 head height, front facing, "
        f"{tp['visual']}, "
        f"name theme: {label}, personality hint: {detail_snippet}, "
        f"color palette: {tp['palette']}, "
        f"transparent background, detailed equipment, warm atmospheric lighting, "
        f"game sprite style, high quality pixel art"
    )
    return prompt


def generate_image_with_gemini(prompt: str) -> Optional[bytes]:
    """
    Gemini API (gemini-2.0-flash-preview-image-generation) で画像を生成し、
    PNG バイト列を返す。失敗時は None を返す。
    """
    try:
        import google.generativeai as genai
        from google.generativeai import types as genai_types

        genai.configure(api_key=API_KEY)

        model = genai.GenerativeModel("gemini-2.0-flash-preview-image-generation")
        response = model.generate_content(
            prompt,
            generation_config=genai_types.GenerationConfig(
                response_modalities=["IMAGE"],
            ),
        )

        # レスポンスから画像データを取り出す
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

        # ファイルが既に存在する場合も spriteUrl だけ付与してスキップ
        if sprite_path.exists() and not force:
            rel = f"{SPRITE_REPO_PREFIX}/{sprite_filename}"
            node["spriteUrl"] = rel
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
            print(f"   💾 保存: {rel}")
            generated += 1
        else:
            print(f"   ⚠️  {node_id} の画像生成をスキップ")

        # レート制限対策
        time.sleep(3)

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
