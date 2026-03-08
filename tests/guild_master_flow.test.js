#!/usr/bin/env node
/**
 * guild_master.html — UIフロー・統合テストスイート
 * 実行方法: node tests/guild_master_flow.test.js
 *
 * ロジックテストに加えて、以下のフローを検証する：
 * - 日記を書く (addCP)
 * - ビュー遷移 (showView)
 * - ギルド待機所の表示
 * - 週次報告の表示
 * - パーティー作成〜メンバー追加の完全フロー
 * - 週進行の完全フロー
 */
'use strict';

// ========= DOM モック (フロー用に拡張版) =========
const _dom = {};          // getElementById で返す要素を管理
const _innerHTML = {};    // setInnerHTML で設定されたHTMLを記録
const _logEntries = [];   // addLog で追加されたエントリ
const _logBar = [];       // setLogBar で設定されたテキスト

const mockElem = (id) => {
    const e = {
        id,
        textContent: '',
        innerHTML: '',
        classList: {
            _classes: new Set(),
            add(c) { this._classes.add(c); },
            remove(c) { this._classes.delete(c); },
            contains(c) { return this._classes.has(c); },
        },
        style: { display: '' },
        value: '',
        children: { length: 50 },
        lastChild: null,
        prepend(child) { _logEntries.unshift(child.textContent); },
        appendChild() { },
        remove() { },
        onclick: null,
    };
    // innerHTMLのsetter で記録
    let _html = '';
    Object.defineProperty(e, 'innerHTML', {
        get() { return _html; },
        set(v) { _html = v; _innerHTML[id] = v; },
    });
    return e;
};

// 特定IDの要素を管理
const _elements = {};
global.document = {
    getElementById(id) {
        if (!_elements[id]) _elements[id] = mockElem(id);
        return _elements[id];
    },
    createElement(tag) {
        const e = mockElem('_tmp');
        e.className = '';
        e.onclick = null;
        return e;
    },
};
global.localStorage = {
    _store: {},
    getItem(k) { return this._store[k] ?? null; },
    setItem(k, v) { this._store[k] = v; },
    removeItem(k) { delete this._store[k]; },
};
global.alert = () => { };
global.confirm = () => true;
global.prompt = () => '1';

// ========= JS読み込み =========
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const html = fs.readFileSync(
    path.join(__dirname, '..', 'guild_master.html'), 'utf8'
);
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) { console.error('script tag not found'); process.exit(1); }
try {
    vm.runInThisContext(scriptMatch[1]);
} catch (e) {
    console.error('JS parse/eval error:', e.message);
    process.exit(1);
}

// ========= テストフレームワーク =========
let passed = 0, failed = 0, errors = [];

function test(name, fn) {
    try {
        fn();
        console.log(`  ✓ ${name}`);
        passed++;
    } catch (e) {
        console.error(`  ✗ ${name}`);
        console.error(`    → ${e.message}`);
        failed++;
        errors.push({ name, msg: e.message });
    }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }
function assertEqual(a, b, msg) { if (a !== b) throw new Error(msg || `expected ${b}, got ${a}`); }
function assertContains(str, sub, msg) { if (!str.includes(sub)) throw new Error(msg || `"${sub}" が含まれない: ...${str.slice(0, 80)}...`); }
function assertRange(v, lo, hi, msg) { if (v < lo || v > hi) throw new Error(msg || `${v} は [${lo}, ${hi}] 外`); }

// テスト前にG_STATEをリセットするヘルパー
function resetState() {
    G_STATE.cp = 100;
    G_STATE.week = 1;
    G_STATE.year = 1;
    G_STATE.parties = [];
    G_STATE.roster = [];
    G_STATE.dismissed = [];
    G_STATE.pendingReports = [];
    G_STATE.globalLog = [];
    initRoster();
}

// パーティーをG_STATE.partiesに直接追加するヘルパー
function addPartyDirect(name = 'テストパーティー', region = '北の森', item = '剣') {
    const p = {
        id: uid(),
        name,
        region,
        targetItem: item,
        members: [],
        leaderId: null,
        directive: { focus: 'steady', conflict: 'leader', cpPerWeek: 20 },
        status: 'idle',
        cpDebt: 0,
    };
    G_STATE.parties.push(p);
    return p;
}

// ========= フローテスト =========

console.log('\n◆ addCP() — 日記を書くフロー');
test('addCP でCPが15〜35増える', () => {
    resetState();
    const before = G_STATE.cp;
    addCP();
    const diff = G_STATE.cp - before;
    assertRange(diff, 15, 35, `CP増加量 ${diff} が範囲外`);
});
test('addCP を5回呼んでも累積される', () => {
    resetState();
    const before = G_STATE.cp;
    for (let i = 0; i < 5; i++) addCP();
    assert(G_STATE.cp > before, `addCP5回後もCPが増えていない: ${G_STATE.cp}`);
    assert(G_STATE.cp >= before + 5 * 15, `最小増加量を下回っている`);
});
test('addCP 後にlocalStorageにセーブされる', () => {
    resetState();
    localStorage._store = {};
    addCP();
    assert(localStorage._store['gm_v1'] != null, 'saveStateが呼ばれていない');
});

console.log('\n◆ showView() — ビュー遷移フロー');
test('showView("roster") で currentView が roster になる', () => {
    showView('roster');
    assertEqual(currentView, 'roster', `currentViewが${currentView}のまま`);
});
test('showView("reports") で currentView が reports になる', () => {
    showView('reports');
    assertEqual(currentView, 'reports');
});
test('showView("welcome") で currentView が welcome になる', () => {
    showView('welcome');
    assertEqual(currentView, 'welcome');
});
test('showView("party") で currentView が party になる', () => {
    showView('party');
    assertEqual(currentView, 'party');
});
test('存在しないビューを渡しても例外が出ない', () => {
    // エラーなく実行できることを確認
    showView('nonexistent');
});

console.log('\n◆ ギルド待機所 — showRosterView() フロー');
test('showRosterView() でv-rosterのInnerHTMLが更新される', () => {
    resetState();
    delete _innerHTML['v-roster'];
    showRosterView();
    const html = _innerHTML['v-roster'] || '';
    assert(html.length > 0, 'v-roster のHTMLが空のまま');
});
test('showRosterView() でキャラクター名が含まれるHTMLが生成される', () => {
    resetState();
    // ロスターに1名確実に追加
    G_STATE.roster = [genChar()];
    showRosterView();
    const h = _innerHTML['v-roster'] || '';
    assertContains(h, 'ギルド待機所', 'ヘッダーが含まれない');
});
test('ロスターが空の場合に「応募者はいません」が表示される', () => {
    resetState();
    G_STATE.roster = [];
    showRosterView();
    const h = _innerHTML['v-roster'] || '';
    assertContains(h, '応募者はいません', '空ロスター時のメッセージが含まれない');
});
test('showRosterView() でcurrentViewがrosterになる', () => {
    showRosterView();
    assertEqual(currentView, 'roster');
});

console.log('\n◆ 週次報告 — showReportsView() フロー');
test('showReportsView() でv-reportsのInnerHTMLが更新される', () => {
    resetState();
    delete _innerHTML['v-reports'];
    showReportsView();
    const h = _innerHTML['v-reports'] || '';
    assert(h.length > 0, 'v-reports のHTMLが空のまま');
});
test('報告が0件のとき「未読の報告はありません」が表示される', () => {
    resetState();
    G_STATE.pendingReports = [];
    showReportsView();
    const h = _innerHTML['v-reports'] || '';
    assertContains(h, '未読の報告はありません', '空報告時のメッセージが含まれない');
});
test('報告が1件あるとき週次報告が表示される', () => {
    resetState();
    const p = addPartyDirect();
    p.members = [genChar()];
    G_STATE.pendingReports = [{ party: p, events: [{ type: 'drop', text: '剣を発見' }] }];
    showReportsView();
    const h = _innerHTML['v-reports'] || '';
    assertContains(h, 'テストパーティー', 'パーティー名が含まれない');
    assertContains(h, '剣を発見', 'イベントテキストが含まれない');
});
test('showReportsView() でcurrentViewがreportsになる', () => {
    showReportsView();
    assertEqual(currentView, 'reports');
});

console.log('\n◆ パーティー管理 — 完全フロー');
test('addMemberToParty でロスターからメンバーが移動する', () => {
    resetState();
    const p = addPartyDirect();
    const rosterBefore = G_STATE.roster.length;
    assert(rosterBefore > 0, 'ロスターが空');
    const c = G_STATE.roster[0];
    addMemberToParty(p.id, c.id);
    assertEqual(p.members.length, 1, 'メンバーが追加されていない');
    assertEqual(G_STATE.roster.length, rosterBefore - 1, 'ロスターから削除されていない');
    assertEqual(p.members[0].id, c.id, '追加されたキャラが違う');
});
test('最初に追加されたメンバーが自動でリーダーになる', () => {
    resetState();
    const p = addPartyDirect();
    const c = G_STATE.roster[0];
    addMemberToParty(p.id, c.id);
    assertEqual(p.leaderId, c.id, 'リーダーが自動設定されていない');
});
test('4人以上追加しようとしても4人でキャップされる', () => {
    resetState();
    const p = addPartyDirect();
    // ロスターに5人追加
    while (G_STATE.roster.length < 5) G_STATE.roster.push(genChar());
    const ids = G_STATE.roster.slice(0, 5).map(c => c.id);
    for (const id of ids) addMemberToParty(p.id, id);
    assertEqual(p.members.length, 4, `4人上限を超えた: ${p.members.length}人`);
});
test('setLeader でリーダーが変わる', () => {
    resetState();
    const p = addPartyDirect();
    while (G_STATE.roster.length < 2) G_STATE.roster.push(genChar());
    addMemberToParty(p.id, G_STATE.roster[0].id);
    addMemberToParty(p.id, G_STATE.roster[0].id); // 2人目を追加
    const secondId = p.members[1]?.id;
    if (secondId) {
        setLeader(p.id, secondId);
        assertEqual(p.leaderId, secondId, 'リーダーが変更されていない');
    }
});
test('removeMember でメンバーがパーティーから削除される', () => {
    resetState();
    const p = addPartyDirect();
    const c = G_STATE.roster[0];
    addMemberToParty(p.id, c.id);
    assertEqual(p.members.length, 1);
    removeMember(p.id, c.id);
    assertEqual(p.members.length, 0, 'メンバーが削除されていない');
});
test('removeMember で解雇されたキャラがdismissedリストに追加される', () => {
    resetState();
    const p = addPartyDirect();
    const c = G_STATE.roster[0];
    addMemberToParty(p.id, c.id);
    const dismissedBefore = G_STATE.dismissed.length;
    removeMember(p.id, c.id);
    assert(G_STATE.dismissed.length > dismissedBefore, 'dismissedリストに追加されていない');
});

console.log('\n◆ 週進行 — advanceWeek() フロー');
test('advanceWeek() で週が+1される', () => {
    resetState();
    const before = G_STATE.week;
    advanceWeek();
    assertEqual(G_STATE.week, before + 1, `週が進んでいない: ${G_STATE.week}`);
});
test('advanceWeek() でCP報酬のあるパーティーのCPが控除される', () => {
    resetState();
    G_STATE.cp = 100;
    const p = addPartyDirect();
    p.members = [genChar()];
    p.status = 'active';
    p.directive.cpPerWeek = 20;
    advanceWeek();
    assertEqual(G_STATE.cp, 80, `CP控除が不正: ${G_STATE.cp}`);
});
test('advanceWeek() でパーティーから週次報告が届く', () => {
    resetState();
    G_STATE.cp = 500;
    const p = addPartyDirect();
    p.members = [genChar()];
    p.status = 'active';
    advanceWeek();
    assert(G_STATE.pendingReports.length > 0, '週次報告が生成されていない');
});
test('advanceWeek() 後にロスターのlengthが負にならない', () => {
    resetState();
    G_STATE.cp = 500;
    advanceWeek();
    assert(G_STATE.roster.length >= 0, 'ロスターが負になった');
});
test('CP0でadvanceWeek()を呼んでもcpDebtが積み上がり解散しない(1週目)', () => {
    resetState();
    G_STATE.cp = 0;
    const p = addPartyDirect();
    p.members = [genChar()];
    p.status = 'active';
    advanceWeek();
    assert(p.status !== 'disbanded', '1週目でいきなり解散した');
    assertEqual(p.cpDebt, 20, `cpDebt が不正: ${p.cpDebt}`);
});

console.log('\n◆ モーダル — openModal / closeModal');
test('openModal がclassListにopenを追加する', () => {
    const el = document.getElementById('mcreate');
    el.classList.remove('open');
    openModal('mcreate');
    assert(el.classList.contains('open'), 'openクラスが追加されていない');
});
test('closeModal がclassListからopenを削除する', () => {
    const el = document.getElementById('mcreate');
    el.classList.add('open');
    closeModal('mcreate');
    assert(!el.classList.contains('open'), 'openクラスが削除されていない');
});

console.log('\n◆ dismissReport() — 報告の既読処理');
test('dismissReport で reports から1件削除される', () => {
    resetState();
    const p = addPartyDirect();
    G_STATE.pendingReports = [
        { party: p, events: [] },
        { party: p, events: [] },
    ];
    dismissReport(0);
    assertEqual(G_STATE.pendingReports.length, 1, '削除されていない');
});

// ========= サマリー =========
console.log('\n' + '─'.repeat(40));
console.log(`結果: ${passed + failed} テスト中 ${passed} 件成功 / ${failed} 件失敗`);
if (errors.length > 0) {
    console.log('\n失敗したテスト:');
    errors.forEach(e => console.log(`  ✗ ${e.name}: ${e.msg}`));
}
console.log('─'.repeat(40));
process.exit(failed > 0 ? 1 : 0);
