/**
 * PomeraToKnowledge — Gmail → GitHub Actions トリガー
 * 
 * Gmailに「POMERA」を含む件名のメールが届いたら、
 * GitHub repository_dispatch APIを叩いてワークフローを起動する。
 * 
 * ■ 重複防止策（3層防御）
 *   1. LockService: 同時実行を排他制御
 *   2. 既読化を先に実行: 次のポーリングで検知されない
 *   3. メッセージID記録: 処理済みメールをスキップ
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
// 重複防止ユーティリティ
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/**
 * メッセージIDが処理済みかチェックし、未処理なら記録する。
 * ScriptPropertiesに最新20件のIDを保持する。
 * @returns {boolean} true=処理済み（スキップすべき）, false=未処理（処理OK）
 */
function isAlreadyProcessed(messageId, category) {
    const props = PropertiesService.getScriptProperties();
    const key = `PROCESSED_${category}`;
    const raw = props.getProperty(key) || '[]';

    let processedIds;
    try {
        processedIds = JSON.parse(raw);
    } catch (e) {
        processedIds = [];
    }

    if (processedIds.includes(messageId)) {
        console.log(`⏭️ メッセージID ${messageId} は処理済み。スキップします`);
        return true;
    }

    return false;
}

/**
 * メッセージIDを処理済みとして記録する。
 * 最新20件のみ保持し、古いものは自動的に削除される。
 */
function markAsProcessed(messageId, category) {
    const props = PropertiesService.getScriptProperties();
    const key = `PROCESSED_${category}`;
    const raw = props.getProperty(key) || '[]';

    let processedIds;
    try {
        processedIds = JSON.parse(raw);
    } catch (e) {
        processedIds = [];
    }

    processedIds.push(messageId);
    // 最新20件のみ保持
    if (processedIds.length > 20) {
        processedIds = processedIds.slice(-20);
    }

    props.setProperty(key, JSON.stringify(processedIds));
    console.log(`📌 メッセージID ${messageId} を処理済みとして記録`);
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// メイン関数 — トリガーから1分間隔で呼び出される
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function checkPomeraMail() {
    // 防御1: 排他制御
    const lock = LockService.getScriptLock();
    if (!lock.tryLock(3000)) {
        console.log('⏳ 他のPOMERAトリガーが処理中。スキップします');
        return;
    }

    try {
        const threads = GmailApp.search(CONFIG.GMAIL_QUERY);

        if (threads.length === 0) {
            return;
        }

        console.log(`📬 ${threads.length} 件のPOMERAメールを検出`);

        const msg = threads[0].getMessages()[threads[0].getMessageCount() - 1];
        const msgId = msg.getId();

        // 防御3: メッセージID重複チェック
        if (isAlreadyProcessed(msgId, 'POMERA')) {
            threads.forEach(thread => thread.markRead());
            return;
        }

        // 防御2: 先に既読にして次のポーリングで検知されないようにする
        threads.forEach(thread => thread.markRead());

        const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
        if (!token) {
            console.error('❌ GITHUB_TOKEN がスクリプトプロパティに設定されていません');
            threads.forEach(thread => thread.markUnread());
            return;
        }

        const subject = threads[0].getFirstMessageSubject();
        const success = triggerGitHubActions(token, subject);

        if (success) {
            markAsProcessed(msgId, 'POMERA');
            console.log('✅ GitHub Actions をトリガーしました');
        } else {
            threads.forEach(thread => thread.markUnread());
            console.error('⚠️ トリガー失敗のため未読に戻しました');
        }

    } finally {
        lock.releaseLock();
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
    // 防御1: 排他制御
    const lock = LockService.getScriptLock();
    if (!lock.tryLock(3000)) {
        console.log('⏳ 他のBLOGトリガーが処理中。スキップします');
        return;
    }

    try {
        const threads = GmailApp.search(BLOG_CONFIG.GMAIL_QUERY);

        if (threads.length === 0) {
            return;
        }

        console.log(`📝 ${threads.length} 件のBLOGメールを検出`);

        const msg = threads[0].getMessages()[threads[0].getMessageCount() - 1];
        const msgId = msg.getId();
        const subject = threads[0].getFirstMessageSubject();
        const body = msg.getPlainBody();

        // 防御3: メッセージID重複チェック
        if (isAlreadyProcessed(msgId, 'BLOG')) {
            threads.forEach(thread => thread.markRead());
            return;
        }

        // 防御2: 先に既読化
        threads.forEach(thread => thread.markRead());

        const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
        if (!token) {
            console.error('❌ GITHUB_TOKEN がスクリプトプロパティに設定されていません');
            threads.forEach(thread => thread.markUnread());
            return;
        }

        const success = triggerGitHubActionsWithEvent(token, subject, BLOG_CONFIG.EVENT_TYPE, body);

        if (success) {
            markAsProcessed(msgId, 'BLOG');
            console.log('✅ Blog GitHub Actions をトリガーしました');
        } else {
            threads.forEach(thread => thread.markUnread());
            console.error('⚠️ Blogトリガー失敗のため未読に戻しました');
        }

    } finally {
        lock.releaseLock();
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
    // 防御1: 排他制御
    const lock = LockService.getScriptLock();
    if (!lock.tryLock(3000)) {
        console.log('⏳ 他のSTORYトリガーが処理中。スキップします');
        return;
    }

    try {
        const threads = GmailApp.search(STORY_CONFIG.GMAIL_QUERY);

        if (threads.length === 0) {
            return;
        }

        console.log(`📖 ${threads.length} 件のSTORYメールを検出`);

        const msg = threads[0].getMessages()[threads[0].getMessageCount() - 1];
        const msgId = msg.getId();
        const subject = threads[0].getFirstMessageSubject();

        // 防御3: メッセージID重複チェック
        if (isAlreadyProcessed(msgId, 'STORY')) {
            threads.forEach(thread => thread.markRead());
            return;
        }

        // 防御2: 先に既読化
        threads.forEach(thread => thread.markRead());

        const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
        if (!token) {
            console.error('❌ GITHUB_TOKEN がスクリプトプロパティに設定されていません');
            threads.forEach(thread => thread.markUnread());
            return;
        }

        const success = triggerGitHubActionsWithEvent(token, subject, STORY_CONFIG.EVENT_TYPE);

        if (success) {
            markAsProcessed(msgId, 'STORY');
            console.log('✅ Story GitHub Actions をトリガーしました');
        } else {
            threads.forEach(thread => thread.markUnread());
            console.error('⚠️ Storyトリガー失敗のため未読に戻しました');
        }

    } finally {
        lock.releaseLock();
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
    // 防御1: 排他制御
    const lock = LockService.getScriptLock();
    if (!lock.tryLock(3000)) {
        console.log('⏳ 他のFINCTXトリガーが処理中。スキップします');
        return;
    }

    try {
        const threads = GmailApp.search(FINCTX_CONFIG.GMAIL_QUERY);

        if (threads.length === 0) {
            return;
        }

        console.log(`💰 ${threads.length} 件のFINCTXメールを検出`);

        const message = threads[0].getMessages()[threads[0].getMessages().length - 1];
        const msgId = message.getId();
        const subject = message.getSubject();
        const body = message.getPlainBody();

        // 防御3: メッセージID重複チェック
        if (isAlreadyProcessed(msgId, 'FINCTX')) {
            threads.forEach(thread => thread.markRead());
            return;
        }

        // 防御2: 先に既読化
        threads.forEach(thread => thread.markRead());

        const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
        if (!token) {
            console.error('❌ GITHUB_TOKEN がスクリプトプロパティに設定されていません');
            threads.forEach(thread => thread.markUnread());
            return;
        }

        const success = triggerGitHubActionsWithEvent(token, subject, FINCTX_CONFIG.EVENT_TYPE, body);

        if (success) {
            markAsProcessed(msgId, 'FINCTX');
            console.log('✅ FINCTX GitHub Actions をトリガーしました');
        } else {
            threads.forEach(thread => thread.markUnread());
            console.error('⚠️ FINCTXトリガー失敗のため未読に戻しました');
        }

    } finally {
        lock.releaseLock();
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

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 処理済みID管理用ユーティリティ
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** 処理済みIDの一覧を確認する（デバッグ用） */
function showProcessedIds() {
    const props = PropertiesService.getScriptProperties();
    const categories = ['POMERA', 'BLOG', 'STORY', 'FINCTX'];

    categories.forEach(cat => {
        const raw = props.getProperty(`PROCESSED_${cat}`) || '[]';
        console.log(`${cat}: ${raw}`);
    });
}

/** 処理済みIDをリセットする（トラブル時に使用） */
function resetProcessedIds() {
    const props = PropertiesService.getScriptProperties();
    const categories = ['POMERA', 'BLOG', 'STORY', 'FINCTX'];

    categories.forEach(cat => {
        props.deleteProperty(`PROCESSED_${cat}`);
        console.log(`🗑️ ${cat} の処理済みIDをリセットしました`);
    });
}
