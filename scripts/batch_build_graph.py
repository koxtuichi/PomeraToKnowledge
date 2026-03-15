#!/usr/bin/env python3
"""
batch_build_graph.py
--------------------
diary/ フォルダ内の全日記ファイルを日付順に処理して
マスターグラフを構築し Neo4j へ一括投入するバッチスクリプト。

重複日付ファイル (例: 同じ日の [POMERA] と [POMERA][POMERA]) は
ファイルサイズが大きい方を採用する。

使い方:
  python3 scripts/batch_build_graph.py
  python3 scripts/batch_build_graph.py --dry-run   # 処理対象の確認のみ
"""

import os
import sys
import re
import json
import subprocess
import argparse
from datetime import datetime
from collections import defaultdict

# スクリプトディレクトリをパスに追加
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(SCRIPT_DIR, "..")
DIARY_DIR = os.path.join(BASE_DIR, "diary")
MASTER_GRAPH = os.path.join(BASE_DIR, "knowledge_graph.jsonld")
DAILY_GRAPH = os.path.join(BASE_DIR, "daily_graph.json")
LOG_DIR = os.path.join(BASE_DIR, "batch_logs")


def extract_date(filename: str):
    """ファイル名から YYYY-MM-DD を抽出する。"""
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", filename)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    m2 = re.search(r"^(\d{8})", os.path.basename(filename))
    if m2:
        s = m2.group(1)
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def collect_diary_files(diary_dir: str) -> list:
    """日記ファイルを日付ごとに選別して (date, path) のリストを返す。
    
    同じ日付で複数ファイルがある場合はサイズが大きい方を採用する。
    """
    by_date = defaultdict(list)

    for fname in os.listdir(diary_dir):
        if not fname.endswith(".txt"):
            continue
        fpath = os.path.join(diary_dir, fname)
        date_str = extract_date(fname)
        if date_str:
            size = os.path.getsize(fpath)
            by_date[date_str].append((size, fpath))

    result = []
    for date_str in sorted(by_date.keys()):
        candidates = sorted(by_date[date_str], key=lambda x: x[0], reverse=True)
        chosen_path = candidates[0][1]
        skipped = [os.path.basename(c[1]) for c in candidates[1:]]
        result.append((date_str, chosen_path, skipped))

    return result


def load_env(base_dir: str) -> dict:
    """プロジェクトルートの .env を読み込んで環境変数dictを返す。"""
    env = os.environ.copy()
    env_path = os.path.join(base_dir, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def run_one_diary(diary_path: str, dry_run: bool = False) -> bool:
    """llm_graph_builder.py を1件の日記で実行する。成功なら True を返す。"""
    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "llm_graph_builder.py"),
        diary_path,   # 位置引数
        "--master_graph", MASTER_GRAPH,
        "--output_graph", DAILY_GRAPH,
        "--output_report", os.path.join(BASE_DIR, "analysis_report.md"),
    ]

    if dry_run:
        print(f"    [DRY-RUN] {' '.join(cmd)}")
        return True

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
        env=load_env(BASE_DIR),
    )

    if result.returncode != 0:
        print(f"    ❌ 失敗 (returncode={result.returncode})")
        print(result.stderr[-500:] if result.stderr else "")
        return False
    else:
        # 最後の2行だけ表示（Neo4j同期確認）
        lines = result.stdout.strip().splitlines()
        summary = "\n".join(lines[-4:]) if len(lines) > 4 else result.stdout
        print(summary)
        return True


def main():
    parser = argparse.ArgumentParser(description="全日記を一括でグラフ化してNeo4jへ投入")
    parser.add_argument("--dry-run", action="store_true", help="処理対象の確認のみ。LLM・Neo4j書き込みなし")
    parser.add_argument("--from-date", help="この日付以降のみ処理 (YYYY-MM-DD)")
    parser.add_argument("--to-date", help="この日付以前のみ処理 (YYYY-MM-DD)")
    args = parser.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)

    entries = collect_diary_files(DIARY_DIR)

    if args.from_date:
        entries = [(d, p, s) for d, p, s in entries if d >= args.from_date]
    if args.to_date:
        entries = [(d, p, s) for d, p, s in entries if d <= args.to_date]

    print(f"📋 処理対象: {len(entries)}件の日記ファイル")
    print()

    success = 0
    failed = []

    for i, (date_str, diary_path, skipped) in enumerate(entries, 1):
        fname = os.path.basename(diary_path)
        print(f"[{i:02d}/{len(entries)}] {date_str}  →  {fname}")
        if skipped:
            print(f"    ⏭  スキップ (重複小): {skipped}")

        ok = run_one_diary(diary_path, dry_run=args.dry_run)
        if ok:
            success += 1
        else:
            failed.append(date_str)
        print()

    print("=" * 60)
    print(f"✅ 成功: {success}件 / {len(entries)}件")
    if failed:
        print(f"❌ 失敗: {', '.join(failed)}")

    if not args.dry_run:
        # 最終的なNeo4jのカウントを確認
        print()
        sys.path.insert(0, SCRIPT_DIR)
        try:
            from neo4j_client import Neo4jClient
            client = Neo4jClient()
            print(f"📊 Neo4j 最終カウント:")
            print(f"   ノード数: {client.count_nodes()}")
            print(f"   エッジ数: {client.count_edges()}")
            client.close()
        except Exception as e:
            print(f"⚠️  カウント確認失敗: {e}")


if __name__ == "__main__":
    main()
