"use strict";

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('views/ringo/js/contributors.js', 'utf8');
const template = fs.readFileSync('views/ringo/index.html', 'utf8');

function element(tagName) {
    return {
        tagName, children: [], dataset: {}, hidden: false, _text: '',
        appendChild(child) { this.children.push(child); },
        replaceChildren(...children) { this.children = children; this._text = ''; },
        set textContent(value) { this._text = String(value); this.children = []; },
        get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    };
}

function harness(hidden = false) {
    const card = element('section');
    const target = element('div');
    const calls = [];
    const listeners = {};
    const intervals = [];
    const document = {
        hidden,
        createElement: element,
        getElementById: id => id === 'sidebar_contributors' ? card : target,
        addEventListener: (event, callback) => { listeners[event] = callback; }
    };
    vm.runInNewContext(source, {
        document, URL,
        window: {
            location: { origin: 'https://ishswiki.xyz' },
            setInterval: (callback, delay) => { intervals.push({ callback, delay }); }
        },
        fetch: (url, options) => new Promise((resolve, reject) => {
            calls.push({ url, options, resolve, reject });
        })
    });
    return {
        card, target, calls, document,
        refresh: () => intervals[0].callback(),
        resume: () => listeners.visibilitychange(),
        delay: intervals[0].delay,
        async respond(data, status = 200) {
            calls.at(-1).resolve({ ok: status === 200, status, json: () => Promise.resolve(data) });
            await new Promise(resolve => setImmediate(resolve));
        }
    };
}

async function verifyContributorCard() {
    assert.ok(template.indexOf('id="sidebar_recent_changes"') < template.indexOf('id="sidebar_trending"'));
    assert.ok(template.indexOf('id="sidebar_trending"') < template.indexOf('id="sidebar_contributors"'));
    assert.match(template, /<a href="\/rankings">전체 보기<\/a>/);
    assert.match(template, /defer src="\/views\/ringo\/js\/contributors\.js/);
    assert.doesNotMatch(template, /\.ringo_ranked:nth-child/, 'medals must use global rank, never page row position');

    const card = harness();
    assert.strictEqual(card.delay, 300000, 'contributors refresh every five minutes');
    assert.strictEqual(card.calls[0].url, '/api/rankings/contributors');
    assert.strictEqual(card.calls[0].options.credentials, 'same-origin');
    card.refresh();
    card.resume();
    assert.strictEqual(card.calls.length, 1, 'initial request cannot overlap timer or foreground refresh');
    await card.respond({ response: 'ok', page: 1, items: [
        { name: '<img src=x onerror=alert(1)>', url: '/w/member', score: 1234.5 },
        { name: '외부 링크', url: 'https://evil.test/member', score: 4 },
        { name: '스크립트', url: 'javascript:alert(1)', score: 3 },
        { name: '이름만', url: '', score: 2 },
        { name: '다섯째', url: 'https://ishswiki.xyz/w/five', score: 1 },
        { name: '여섯째', url: '/w/six', score: 0 }
    ] });
    const rows = card.target.children[0].children;
    assert.strictEqual(rows.length, 5, 'only the first five contributors appear');
    assert.deepStrictEqual(rows.map(row => row.dataset.rank), ['1', '2', '3', '4', '5']);
    assert.strictEqual(rows[0].children[1].textContent, '<img src=x onerror=alert(1)>', 'nickname markup remains literal text');
    assert.strictEqual(rows[0].children[1].children.length, 0);
    assert.strictEqual(rows[0].children[1].href, '/w/member');
    assert.strictEqual(rows[0].children[2].textContent, '1,234.5');
    for(const index of [1, 2, 3]) {
        assert.strictEqual(rows[index].children[1].tagName, 'span', 'unsafe or absent URLs stay readable without a link');
    }
    assert.strictEqual(rows[4].children[1].href, '/w/five');

    card.document.hidden = true;
    card.refresh();
    card.resume();
    assert.strictEqual(card.calls.length, 1, 'hidden documents do not refresh');
    card.document.hidden = false;
    card.resume();
    assert.strictEqual(card.calls.length, 2, 'foreground resume refreshes immediately');
    await card.respond({ response: 'ok', items: [], stale: true, generated_at: 0 });
    assert.match(card.target.textContent, /집계하고 있습니다/);
    card.refresh();
    await card.respond({ response: 'ok', items: [], stale: false, generated_at: 100 });
    assert.match(card.target.textContent, /표시할 기여자 순위가 없습니다/);

    card.refresh();
    await card.respond({}, 503);
    assert.match(card.target.textContent, /불러올 수 없습니다/);
    card.refresh();
    card.calls.at(-1).reject(new Error('offline'));
    await new Promise(resolve => setImmediate(resolve));
    assert.match(card.target.textContent, /불러올 수 없습니다/);

    for(const url of ['blob:https://ishswiki.xyz/id', 'https://ishswiki.xyz//evil.test/path']) {
        card.refresh();
        await card.respond({ response: 'ok', items: [{ name: '안전한 이름', url, score: 1 }] });
        assert.strictEqual(card.target.children[0].children[0].children[1].tagName, 'span');
    }
    for(const data of [null, { response: 'ok', items: [{ name: 'broken', url: '/w/a', score: '1' }] },
        { response: 'ok', page: 2, items: [] }]) {
        card.refresh();
        await card.respond(data);
        assert.match(card.target.textContent, /불러올 수 없습니다/, 'invalid snapshots cannot produce misleading ranks');
    }
    for(const status of [401, 403]) {
        const denied = harness();
        await denied.respond({}, status);
        assert.strictEqual(denied.card.hidden, true, 'unauthorized contributor card is hidden');
        assert.strictEqual(denied.target.children.length, 0);
        denied.refresh();
        denied.resume();
        assert.strictEqual(denied.calls.length, 1, 'forbidden card stops fetching');
    }
    const background = harness(true);
    assert.strictEqual(background.calls.length, 0, 'a hidden tab does not start a request');
    background.document.hidden = false;
    background.resume();
    await background.respond({ response: 'ok', items: [] });
    assert.strictEqual(background.calls.length, 1);
}

verifyContributorCard().then(() => {
    console.log('contributor sidebar UI checks passed');
}).catch(error => {
    console.error(error);
    process.exitCode = 1;
});
