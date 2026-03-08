#!/usr/bin/env python3
"""
ワールドスプライト生成スクリプト
================================
Elinテイストの中世ファンタジー環境画像と職業別キャラクター画像を生成する。

使い方:
  python scripts/generate_world_sprites.py
  python scripts/generate_world_sprites.py --force  # 全ファイルを再生成
  python scripts/generate_world_sprites.py --type env    # 環境画像のみ
  python scripts/generate_world_sprites.py --type chars  # キャラ画像のみ
"""

import os
import sys
import argparse
import time
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent
SPRITES_DIR = ROOT_DIR / "sprites"
CHARS_DIR = SPRITES_DIR / "characters"
STYLE_REFS_DIR = SCRIPT_DIR / "style_refs"

API_KEY = os.environ.get("GOOGLE_API_KEY", "")

# ===== 環境画像定義 =====
ENV_SPRITES = {
    "grass": {
        "path": SPRITES_DIR / "grass.png",
        "prompt": (
            "Top-down 2D tile texture, single grass tile, verdant green grass with natural variation, "
            "pixel art style, isometric-compatible, seamlessly tileable, "
            "Elin game style lush fantasy grass, soft natural colors, slight texture detail, "
            "512x512 pixels, clean edges, no characters, no objects, only grass ground texture"
        ),
    },
    "grass2": {
        "path": SPRITES_DIR / "grass2.png",
        "prompt": (
            "Top-down 2D tile texture, single grass tile variant, slightly darker green with small wildflowers, "
            "pixel art style, isometric-compatible, seamlessly tileable, "
            "Elin game style lush fantasy grass with tiny colorful flower details, "
            "512x512 pixels, clean edges, no characters, no objects, only decorated grass ground texture"
        ),
    },
    "grass3": {
        "path": SPRITES_DIR / "grass3.png",
        "prompt": (
            "Top-down 2D tile texture, single dry grass tile, golden-brown grass with light patches, "
            "pixel art style, isometric-compatible, seamlessly tileable, "
            "Elin game style semi-arid fantasy grass, warm earthy tones, "
            "512x512 pixels, clean edges, no characters, no objects, only dry grass ground texture"
        ),
    },
    "house": {
        "path": SPRITES_DIR / "house.png",
        "prompt": (
            "Isometric pixel art, small cozy medieval cottage, stone walls with wooden beams, "
            "red clay tile roof with slight smoke from chimney, warm glowing windows, "
            "Elin game style fantasy architecture, charming and detailed, warm afternoon lighting, "
            "transparent background, single building object no ground tile, "
            "512x512 pixels, clean pixel art style"
        ),
    },
    "tower": {
        "path": SPRITES_DIR / "tower.png",
        "prompt": (
            "Isometric pixel art, tall medieval stone watchtower, imposing dark stone construction, "
            "crenelated battlements at top, small arrow-slit windows, ivy growing on lower walls, "
            "Elin game style fantasy architecture, slightly aged and weathered, "
            "transparent background, single tower object no ground, "
            "512x512 pixels, clean pixel art style"
        ),
    },
    "tree": {
        "path": SPRITES_DIR / "tree.png",
        "prompt": (
            "Isometric pixel art, round lush fantasy tree, full dense green canopy, "
            "thick brown trunk, Elin game style nature object, bright cheerful colors, "
            "soft shadows under canopy, transparent background, single tree object no ground, "
            "512x512 pixels, clean pixel art style"
        ),
    },
    "well": {
        "path": SPRITES_DIR / "well.png",
        "prompt": (
            "Isometric pixel art, traditional stone well with wooden bucket rope and crossbar, "
            "detailed stone masonry, mossy aged stones, small wooden roof cover, "
            "Elin game style decorative object, charming village prop, "
            "transparent background, single well object no ground, "
            "512x512 pixels, clean pixel art style"
        ),
    },
    "char": {
        "path": SPRITES_DIR / "char.png",
        "prompt": (
            "Pixel art sprite sheet, 6 frames of wizard character walking animation, "
            "chibi style, blue robes, pointed hat, magic staff, "
            "3 frames top row left to right walk cycle, 3 frames bottom row walk cycle, "
            "white background, evenly spaced frames, 192x128 pixels total sheet, "
            "each frame approximately 64x64 pixels"
        ),
    },
    "fire": {
        "path": SPRITES_DIR / "fire.png",
        "prompt": (
            "Pixel art sprite sheet, 6 frames of campfire flame animation, "
            "bright orange and yellow flames, warm glow, "
            "3 frames top row 3 frames bottom row, "
            "white background, evenly spaced frames, 192x128 pixels total sheet, "
            "each frame approximately 64x64 pixels"
        ),
    },
}

# ===== 職業別キャラクター画像定義 =====
CLASS_SPRITES = {
    "warrior": {
        "path": CHARS_DIR / "warrior.png",
        "prompt": (
            "Japanese moe anime portrait illustration, "
            "large close-up bust-up portrait: face occupying upper 65 percent of frame, "
            "huge beautiful moe eyes with detailed sparkly irises and long lashes, "
            "tiny delicate nose, small cute mouth, soft rosy cheeks, smooth fair skin, "
            "flat cel-shading with minimal shadows, muted desaturated soft color palette, "
            "CONSISTENT uniform art style, crisp clean line art, "
            "medieval fantasy female warrior, light plate armor with pauldrons, "
            "determined brave expression, red or orange accent color, "
            "PURE WHITE background, NO magical effects NO particles, "
            "high quality Japanese doujin anime illustration style, vertical portrait format"
        ),
    },
    "hero": {
        "path": CHARS_DIR / "hero.png",
        "prompt": (
            "Japanese moe anime portrait illustration, "
            "large close-up bust-up portrait: face occupying upper 65 percent of frame, "
            "huge beautiful moe eyes with detailed sparkly irises and long lashes, "
            "tiny delicate nose, small cute mouth, soft rosy cheeks, smooth fair skin, "
            "flat cel-shading with minimal shadows, muted desaturated soft color palette, "
            "CONSISTENT uniform art style, crisp clean line art, "
            "medieval fantasy hero character, ornate golden armor, noble cloak, "
            "confident radiant expression, gold and white color theme, "
            "PURE WHITE background, NO magical effects NO particles, "
            "high quality Japanese doujin anime illustration style, vertical portrait format"
        ),
    },
    "mage": {
        "path": CHARS_DIR / "mage.png",
        "prompt": (
            "Japanese moe anime portrait illustration, "
            "large close-up bust-up portrait: face occupying upper 65 percent of frame, "
            "huge beautiful moe eyes with detailed sparkly irises and long lashes, "
            "tiny delicate nose, small cute mouth, soft rosy cheeks, smooth fair skin, "
            "flat cel-shading with minimal shadows, muted desaturated soft color palette, "
            "CONSISTENT uniform art style, crisp clean line art, "
            "medieval fantasy mage, elegant academic robes, pointed hat hint, "
            "thoughtful intelligent expression, soft lavender and blue color theme, "
            "PURE WHITE background, NO magical effects NO particles, "
            "high quality Japanese doujin anime illustration style, vertical portrait format"
        ),
    },
    "alchemist": {
        "path": CHARS_DIR / "alchemist.png",
        "prompt": (
            "Japanese moe anime portrait illustration, "
            "large close-up bust-up portrait: face occupying upper 65 percent of frame, "
            "huge beautiful moe eyes with detailed sparkly irises and long lashes, "
            "tiny delicate nose, small cute mouth, soft rosy cheeks, smooth fair skin, "
            "flat cel-shading with minimal shadows, muted desaturated soft color palette, "
            "CONSISTENT uniform art style, crisp clean line art, "
            "medieval fantasy alchemist, apron over scholarly robes, potion vial accessory, "
            "curious bright-eyed expression, green and gold color theme, "
            "PURE WHITE background, NO magical effects NO particles, "
            "high quality Japanese doujin anime illustration style, vertical portrait format"
        ),
    },
    "sage": {
        "path": CHARS_DIR / "sage.png",
        "prompt": (
            "Japanese moe anime portrait illustration, "
            "large close-up bust-up portrait: face occupying upper 65 percent of frame, "
            "huge beautiful moe eyes with detailed sparkly irises and long lashes, "
            "tiny delicate nose, small cute mouth, soft rosy cheeks, smooth fair skin, "
            "flat cel-shading with minimal shadows, muted desaturated soft color palette, "
            "CONSISTENT uniform art style, crisp clean line art, "
            "medieval fantasy sage, flowing white silver robes, ancient runic accessories, "
            "calm wise serene expression, silver white and pale blue color theme, "
            "PURE WHITE background, NO magical effects NO particles, "
            "high quality Japanese doujin anime illustration style, vertical portrait format"
        ),
    },
    "scout": {
        "path": CHARS_DIR / "scout.png",
        "prompt": (
            "Japanese moe anime portrait illustration, "
            "large close-up bust-up portrait: face occupying upper 65 percent of frame, "
            "huge beautiful moe eyes with detailed sparkly irises and long lashes, "
            "tiny delicate nose, small cute mouth, soft rosy cheeks, smooth fair skin, "
            "flat cel-shading with minimal shadows, muted desaturated soft color palette, "
            "CONSISTENT uniform art style, crisp clean line art, "
            "medieval fantasy scout ranger, light leather armor, hooded cloak, "
            "alert energetic expression, forest green and brown color theme, "
            "PURE WHITE background, NO magical effects NO particles, "
            "high quality Japanese doujin anime illustration style, vertical portrait format"
        ),
    },
    "default_char": {
        "path": CHARS_DIR / "default_char.png",
        "prompt": (
            "Japanese moe anime portrait illustration, "
            "large close-up bust-up portrait: face occupying upper 65 percent of frame, "
            "huge beautiful moe eyes with detailed sparkly irises and long lashes, "
            "tiny delicate nose, small cute mouth, soft rosy cheeks, smooth fair skin, "
            "flat cel-shading with minimal shadows, muted desaturated soft color palette, "
            "CONSISTENT uniform art style, crisp clean line art, "
            "medieval fantasy traveler, simple warm traveling cloak, friendly open expression, "
            "warm neutral tones, beige brown and amber color theme, "
            "PURE WHITE background, NO magical effects NO particles, "
            "high quality Japanese doujin anime illustration style, vertical portrait format"
        ),
    },
}


def load_style_refs() -> list:
    """style_refs/内のPNG画像をロードして返す"""
    refs = []
    if not STYLE_REFS_DIR.exists():
        return refs
    for p in sorted(STYLE_REFS_DIR.glob("*.png"))[:3]:
        data = p.read_bytes()
        refs.append({"mime": "image/png", "data": data})
        print(f"  🖼  スタイル参考読み込み: {p.name}")
    return refs


def generate_image(prompt: str, use_style_refs: bool = True) -> Optional[bytes]:
    """Gemini API で画像を生成して PNG バイト列を返す"""
    try:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=API_KEY)
        contents = []

        if use_style_refs:
            style_refs = load_style_refs()
            if style_refs:
                for ref in style_refs:
                    contents.append(
                        genai_types.Part.from_bytes(
                            data=ref["data"],
                            mime_type=ref["mime"],
                        )
                    )
                style_instruction = (
                    "Use the above images as STYLE REFERENCE ONLY. "
                    "Match the anime portrait character style from these reference images. "
                    "Do NOT copy the exact characters — create a NEW original character based on the description below:\n\n"
                )
                contents.append(genai_types.Part.from_text(text=style_instruction + prompt))
            else:
                contents.append(genai_types.Part.from_text(text=prompt))
        else:
            contents.append(genai_types.Part.from_text(text=prompt))

        response = client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=contents,
            config=genai_types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                return part.inline_data.data

        print("  ⚠️  画像データが空でした")
        return None

    except Exception as e:
        print(f"  ❌ Gemini API エラー: {e}")
        return None


def generate_sprites(targets: dict, label: str, use_style_refs: bool = False, force: bool = False):
    """指定されたスプライト辞書を処理して画像を生成する"""
    print(f"\n{'='*50}")
    print(f"  {label} 生成開始")
    print(f"{'='*50}")

    for name, cfg in targets.items():
        path: Path = cfg["path"]
        prompt: str = cfg["prompt"]

        if path.exists() and not force:
            print(f"  ⏭  スキップ（既存）: {path.name}")
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"🎨 生成中: {name}")
        print(f"   プロンプト: {prompt[:80]}…")

        img_bytes = generate_image(prompt, use_style_refs=use_style_refs)
        if img_bytes:
            path.write_bytes(img_bytes)
            print(f"   💾 保存: {path.relative_to(ROOT_DIR)}")
        else:
            print(f"   ⚠️  {name} の画像生成をスキップ")

        time.sleep(2)

    print(f"\n✅ {label} 完了")


def main():
    parser = argparse.ArgumentParser(description="ワールドスプライト生成")
    parser.add_argument("--force", action="store_true", help="既存ファイルも再生成する")
    parser.add_argument("--type", choices=["env", "chars", "all"], default="all",
                        help="生成タイプ: env(環境), chars(キャラ), all(両方)")
    args = parser.parse_args()

    if not API_KEY:
        print("❌ GOOGLE_API_KEY が設定されていません")
        sys.exit(1)

    if args.type in ("env", "all"):
        # 環境画像はスタイル参考なしで生成（アイソメトリック/タイル）
        generate_sprites(ENV_SPRITES, "環境画像", use_style_refs=False, force=args.force)

    if args.type in ("chars", "all"):
        # キャラクター画像はスタイル参考あり
        generate_sprites(CLASS_SPRITES, "職業別キャラクター画像", use_style_refs=True, force=args.force)


if __name__ == "__main__":
    main()
