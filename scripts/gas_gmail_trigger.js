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
// BLOG メール検知 — トリガーから1分間隔で呼び出される
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const BLOG_CONFIG = {
    EVENT_TYPE: 'pomera-blog',
    GMAIL_QUERY: 'subject:BLOG is:unread newer_than:1h -subject:POMERA'
};

function checkBlogMail() {
    const threads = GmailApp.search(BLOG_CONFIG.GMAIL_QUERY);

    if (threads.length === 0) {
        return; // 未読のBLOGメールなし
    }

    console.log(`📝 ${threads.length} 件のBLOGメールを検出`);

    const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
    if (!token) {
        console.error('❌ GITHUB_TOKEN がスクリプトプロパティに設定されていません');
        return;
    }

    const msg = threads[0].getMessages()[threads[0].getMessageCount() - 1];
    const subject = threads[0].getFirstMessageSubject();
    // メール本文をpayloadに含める（FINCTXと同じ方式）
    const body = msg.getPlainBody();
    const success = triggerGitHubActionsWithEvent(token, subject, BLOG_CONFIG.EVENT_TYPE, body);

    if (success) {
        threads.forEach(thread => thread.markRead());
        console.log('✅ Blog GitHub Actions をトリガーし、メールを既読にしました');
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// GitHub repository_dispatch API（イベントタイプ指定版）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function triggerGitHubActionsWithEvent(token, subject, eventType, body = null) {
    const url = `https://api.github.com/repos/${CONFIG.GITHUB_OWNER}/${CONFIG.GITHUB_REPO}/dispatches`;

    const clientPayload = {
        subject: subject,
        triggered_at: new Date().toISOString()
    };
    // bodyがある場合はpayloadに含める（BLOG/FINCTXで使用）
    if (body) clientPayload.body = body;

    const options = {
        method: 'post',
        headers: {
            'Authorization': `Bearer ${token}`,
            'Accept': 'application/vnd.github.v3+json',
            'X-GitHub-Api-Version': '2022-11-28'
        },
        contentType: 'application/json',
        payload: JSON.stringify({
            event_type: eventType,
            client_payload: clientPayload
        }),
        muteHttpExceptions: true
    };

    try {
        const response = UrlFetchApp.fetch(url, options);
        const code = response.getResponseCode();

        if (code === 204) {
            console.log(`🚀 repository_dispatch 成功 (event: ${eventType})`);
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

function testBlogTrigger() {
    const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
    if (!token) {
        console.error('❌ GITHUB_TOKEN が未設定です');
        return;
    }
    const success = triggerGitHubActionsWithEvent(token, '[TEST] BLOGテスト送信', BLOG_CONFIG.EVENT_TYPE);
    console.log(success ? '✅ ブログテスト成功！' : '❌ ブログテスト失敗');
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// STORY メール検知 — トリガーから1分間隔で呼び出される
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const STORY_CONFIG = {
    EVENT_TYPE: 'pomera-story',
    GMAIL_QUERY: 'subject:STORY is:unread newer_than:1h -subject:POMERA -subject:BLOG'
};

function checkStoryMail() {
    const threads = GmailApp.search(STORY_CONFIG.GMAIL_QUERY);

    if (threads.length === 0) {
        return; // 未読のSTORYメールなし
    }

    console.log(`📖 ${threads.length} 件のSTORYメールを検出`);

    const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
    if (!token) {
        console.error('❌ GITHUB_TOKEN がスクリプトプロパティに設定されていません');
        return;
    }

    const subject = threads[0].getFirstMessageSubject();
    const success = triggerGitHubActionsWithEvent(token, subject, STORY_CONFIG.EVENT_TYPE);

    if (success) {
        threads.forEach(thread => thread.markRead());
        console.log('✅ Story GitHub Actions をトリガーし、メールを既読にしました');
    }
}

function testStoryTrigger() {
    const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
    if (!token) {
        console.error('❌ GITHUB_TOKEN が未設定です');
        return;
    }
    const success = triggerGitHubActionsWithEvent(token, '[TEST] STORYテスト送信', STORY_CONFIG.EVENT_TYPE);
    console.log(success ? '✅ 小説テスト成功！' : '❌ 小説テスト失敗');
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 家計コンテキスト (FINCTX) メール検知
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const FINCTX_CONFIG = {
    EVENT_TYPE: 'pomera-finctx',
    GMAIL_QUERY: 'subject:FINCTX is:unread newer_than:24h'
};

function checkFinCtxMail() {
    const threads = GmailApp.search(FINCTX_CONFIG.GMAIL_QUERY);

    if (threads.length === 0) {
        return; // 未読のFINCTXメールなし
    }

    console.log(`💰 ${threads.length} 件のFINCTXメールを検出`);

    const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
    if (!token) {
        console.error('❌ GITHUB_TOKEN がスクリプトプロパティに設定されていません');
        return;
    }

    // メール本文を取得してペイロードに含める
    const message = threads[0].getMessages()[threads[0].getMessages().length - 1];
    const subject = message.getSubject();
    const body = message.getPlainBody();

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
            event_type: FINCTX_CONFIG.EVENT_TYPE,
            client_payload: {
                subject: subject,
                body: body,
                triggered_at: new Date().toISOString()
            }
        }),
        muteHttpExceptions: true
    };

    try {
        const response = UrlFetchApp.fetch(url, options);
        const code = response.getResponseCode();

        if (code === 204) {
            threads.forEach(thread => thread.markRead());
            console.log('✅ FINCTX GitHub Actions をトリガーし、メールを既読にしました');
        } else {
            console.error(`❌ GitHub API エラー: ${code} - ${response.getContentText()}`);
        }
    } catch (e) {
        console.error(`❌ リクエスト失敗: ${e.message}`);
    }
}

function testFinCtxTrigger() {
    const sampleBody = `[FINCTX]テスト\n\n## 収入\n給与・Knowbe: 650000\n副業・Saiteki: 80000\n`;
    const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
    if (!token) {
        console.error('❌ GITHUB_TOKEN が未設定です');
        return;
    }

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
            event_type: FINCTX_CONFIG.EVENT_TYPE,
            client_payload: {
                subject: '[FINCTX]テスト',
                body: sampleBody,
                triggered_at: new Date().toISOString()
            }
        }),
        muteHttpExceptions: true
    };

    try {
        const response = UrlFetchApp.fetch(url, options);
        console.log(response.getResponseCode() === 204 ? '✅ FINCTXテスト成功！' : '❌ FINCTXテスト失敗');
    } catch (e) {
        console.error(`❌ リクエスト失敗: ${e.message}`);
    }
}
