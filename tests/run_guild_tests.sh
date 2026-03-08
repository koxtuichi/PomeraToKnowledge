#!/bin/bash
# ギルドマスターゲーム テスト実行スクリプト
# 使い方: bash tests/run_guild_tests.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "====================================="
echo "  GUILD MASTER テストスイート"
echo "====================================="
echo ""

FAIL=0

echo "【1/2】ロジックテスト (guild_master_logic.test.js)"
node "$SCRIPT_DIR/guild_master_logic.test.js"
[ $? -ne 0 ] && FAIL=1

echo ""
echo "【2/2】フローテスト (guild_master_flow.test.js)"
node "$SCRIPT_DIR/guild_master_flow.test.js"
[ $? -ne 0 ] && FAIL=1

echo ""
if [ $FAIL -eq 0 ]; then
  echo "✅ 全テスト合格 — デプロイ可能"
else
  echo "❌ テスト失敗 — コミット前に修正してください"
fi

exit $FAIL

