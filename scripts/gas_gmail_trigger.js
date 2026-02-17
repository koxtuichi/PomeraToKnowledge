/**
 * PomeraToKnowledge — Gmail → GitHub Actions トリガー
 * 
 * Gmailに「POMERA」を含む件名のメールが届いたら、
 * GitHub repository_dispatch APIを叩いてワークフローを起動する。
 * 
 * ■ セットアップ手順は SETUP_GAS_TRIGGER.md を参照
 */

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 設定
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const CONFIG = {
    GITHUB_OWNER: 'koxtuichi',
    GITHUB_REPO: 'PomeraToKnowledge',
    EVENT_TYPE: 'pomera-diary',
    GMAIL_QUERY: 'subject:POMERA is:unread newer_than:1h',
    LABEL_NAME: 'PomeraProcessed'
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// メイン関数 — トリガーから1分間隔で呼び出される
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function checkPomeraMail() {
    const threads = GmailApp.search(CONFIG.GMAIL_QUERY);

    if (threads.length === 0) {
        return; // 未読のPOMERAメールなし
    }

    console.log(`📬 ${threads.length} 件のPOMERAメールを検出`);

    // GitHub repository_dispatch を発火
    const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
    if (!token) {
        console.error('❌ GITHUB_TOKEN がスクリプトプロパティに設定されていません');
        return;
    }

    const subject = threads[0].getFirstMessageSubject();
    const success = triggerGitHubActions(token, subject);

    if (success) {
        // 処理済みのメールを既読にする
        threads.forEach(thread => thread.markRead());
        console.log('✅ GitHub Actions をトリガーし、メールを既読にしました');
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// GitHub repository_dispatch API を叩く
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function triggerGitHubActions(token, subject) {
    const url = `https://api.github.com/repos/${CONFIG.GITHUB_OWNER}/${CONFIG.GITHUB_REPO}/dispatches`;

    const options = {
        method: 'post',
        headers: {
            'Authorization': `Bearer ${token}`,
            'Accept': 'application/vnd.github.v3+json',
            'X-GitHub-Api-Version': '2022-11-28'
        },
        contentType: 'application/json',
        payload: JSON.stringify({
            event_type: CONFIG.EVENT_TYPE,
            client_payload: {
                subject: subject,
                triggered_at: new Date().toISOString()
            }
        }),
        muteHttpExceptions: true
    };

    try {
        const response = UrlFetchApp.fetch(url, options);
        const code = response.getResponseCode();

        if (code === 204) {
            console.log('🚀 repository_dispatch 成功');
            return true;
        } else {
            console.error(`❌ GitHub API エラー: ${code} - ${response.getContentText()}`);
            return false;
        }
    } catch (e) {
        console.error(`❌ リクエスト失敗: ${e.message}`);
        return false;
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 手動テスト用
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function testTrigger() {
    const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
    if (!token) {
        console.error('❌ GITHUB_TOKEN が未設定です');
        return;
    }
    const success = triggerGitHubActions(token, '[TEST] POMERAテスト送信');
    console.log(success ? '✅ テスト成功！' : '❌ テスト失敗');
}
