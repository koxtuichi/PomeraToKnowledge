#!/bin/bash
# ギルドマスターゲーム テスト実行スクリプト
# 使い方: bash tests/run_guild_tests.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "====================================="
echo "  GUILD MASTER ロジックテスト"
echo "====================================="

node "$SCRIPT_DIR/guild_master_logic.test.js"
EXIT=$?

if [ $EXIT -eq 0 ]; then
  echo ""
  echo "✅ 全テスト合格 — デプロイ可能"
else
  echo ""
  echo "❌ テスト失敗 — コミット前に修正してください"
fi

exit $EXIT
