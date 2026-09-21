"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const sidebar = fs.readFileSync("views/ringo/js/sidebar.js", "utf8");
const autocomplete = fs.readFileSync("views/main_css/js/func/autocomplete.js", "utf8");
const template = fs.readFileSync("views/ringo/index.html", "utf8");

assert.match(sidebar, /window\.ringoRanking/, "ranking state must be shared with mobile search");
assert.match(sidebar, /RINGO_TRENDING_REFRESH_MS\s*=\s*30000/, "visible tabs refresh trending every 30 seconds");
assert.match(sidebar, /document\.hidden/, "hidden tabs must not refresh trending");
assert.match(sidebar, /textContent\s*=\s*item\.title/, "trending titles must use safe DOM text");
assert.match(sidebar, /fetch\('\/api\/ranking\/view'/, "eligible document views must send the signed ticket");
assert.match(sidebar, /JSON\.stringify\(\{ ticket: ticket \}\)/, "view event sends only the opaque ticket");
assert.match(autocomplete, /window\.ringoRanking/, "mobile empty search must use the shared trending snapshot");
assert.doesNotMatch(autocomplete, /processTrendingHTML|cleanTitle|replace\(\/\^\[0-9\]/, "mobile search must not parse legacy HTML or alter titles");
assert.match(autocomplete, /classList\.add\('ringo_trending_results'\)/, "mobile trending results opt into the viewport popup layout");
assert.match(autocomplete, /getBoundingClientRect\(\)/, "viewport popup is positioned below its search input");
assert.match(sidebar, /title\.className\s*=\s*'ringo_trending_title'/, "rank and title have scoped layout hooks");
assert.match(template, /body\.namu #autocomplete_results_not_mobile\.ringo_trending_results,[\s\S]*body\.namu #autocomplete_results_mobile\.ringo_trending_results\s*\{[\s\S]*position:\s*fixed[\s\S]*left:\s*10px[\s\S]*right:\s*10px/, "mobile popular results override the later ID-based popup width with viewport bounds");

function makeElement(tagName) {
    return {
        tagName,
        children: [],
        className: "",
        href: "",
        style: {},
        _text: "",
        appendChild(child) {
            this.children.push(child);
            return child;
        },
        replaceChildren(...children) {
            this.children = children;
            this._text = "";
        },
        set textContent(value) {
            this.children = [];
            this._text = String(value);
        },
        get textContent() {
            return this._text + this.children.map((child) => child.textContent).join("");
        }
    };
}

async function verifyTrendingStates() {
    const sidebarTarget = makeElement("div");
    const documentListeners = {};
    const responses = [
        { ok: true, json: () => Promise.resolve({ response: "ok", items: [{ title: "2024 <script>", url: "/w/2024" }] }) },
        { ok: true, json: () => Promise.resolve({ response: "ok", items: [{ title: "새 문서", url: "/w/new" }] }) },
        { ok: true, json: () => Promise.resolve({ response: "ok", items: [] }) },
        { ok: false, json: () => Promise.resolve({}) }
    ];
    let fetchCalls = 0;
    const document = {
        hidden: false,
        createElement: makeElement,
        querySelector: () => sidebarTarget,
        getElementById: () => null,
        addEventListener(name, callback) {
            documentListeners[name] = callback;
        }
    };
    const window = {
        location: { origin: "https://ishswiki.xyz" },
        addEventListener() {},
        setInterval() {},
        setTimeout() {},
        clearTimeout() {}
    };
    const context = {
        URL,
        console: { warn() {} },
        document,
        fetch() {
            fetchCalls += 1;
            return Promise.resolve(responses.shift());
        },
        performance: { now: () => 0 },
        window
    };

    vm.runInNewContext(sidebar, context);
    await window.ringoRanking.refresh();
    assert.strictEqual(sidebarTarget.textContent, "1.2024 <script>", "safe DOM preserves a leading-digit title literally");
    assert.strictEqual(sidebarTarget.children[0].children[0].children[0].href, "/w/2024", "structured URL renders as an internal link");

    const mobileTarget = makeElement("div");
    window.ringoRanking.bindMobile(mobileTarget, () => true);
    await window.ringoRanking.refresh();
    assert.strictEqual(sidebarTarget.textContent, "1.새 문서", "sidebar receives the latest shared snapshot");
    assert.strictEqual(mobileTarget.textContent, "1.새 문서", "mobile empty search receives the same latest snapshot");

    await window.ringoRanking.refresh();
    assert.match(sidebarTarget.textContent, /표시할 실시간 인기 문서가 없습니다/, "empty trending response has an ordinary empty state");

    await window.ringoRanking.refresh();
    assert.match(sidebarTarget.textContent, /불러올 수 없습니다/, "non-200 trending response has an ordinary failure state");

    document.hidden = true;
    await window.ringoRanking.refresh();
    assert.strictEqual(fetchCalls, 4, "hidden tabs do not refresh trending");
}

async function verifyTicketDelay() {
    const documentListeners = {};
    const windowListeners = {};
    const timers = [];
    const calls = [];
    let now = 0;
    const document = {
        hidden: true,
        createElement: makeElement,
        querySelector: () => makeElement("div"),
        getElementById(id) {
            return id === "ranking_ticket" ? { dataset: { rankingTicket: "signed-ticket" } } : null;
        },
        addEventListener(name, callback) {
            documentListeners[name] = documentListeners[name] || [];
            documentListeners[name].push(callback);
        }
    };
    const window = {
        location: { origin: "https://ishswiki.xyz" },
        addEventListener(name, callback) {
            windowListeners[name] = callback;
        },
        setInterval() {},
        setTimeout(callback, delay) {
            const timer = { callback, delay, cleared: false };
            timers.push(timer);
            return timer;
        },
        clearTimeout(timer) {
            timer.cleared = true;
        }
    };
    const context = {
        URL,
        console: { warn() {} },
        document,
        fetch(url, options) {
            calls.push({ url, options });
            if(url === "/api/trending") {
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ response: "ok", items: [] }) });
            }
            return Promise.resolve({ ok: true });
        },
        performance: { now: () => now },
        window
    };
    const emitVisibility = () => documentListeners.visibilitychange.forEach((callback) => callback());

    vm.runInNewContext(sidebar, context);
    windowListeners.DOMContentLoaded();
    assert.strictEqual(calls.filter((call) => call.url === "/api/ranking/view").length, 0, "hidden time does not count toward a view");

    document.hidden = false;
    emitVisibility();
    now = 2000;
    document.hidden = true;
    emitVisibility();
    now = 3000;
    document.hidden = false;
    emitVisibility();
    const activeTimer = timers.find((timer) => !timer.cleared && timer.delay === 3000);
    assert.ok(activeTimer, "resume schedules only the remaining foreground time");
    activeTimer.callback();
    activeTimer.callback();

    const viewCalls = calls.filter((call) => call.url === "/api/ranking/view");
    assert.strictEqual(viewCalls.length, 1, "five foreground seconds send one view event");
    assert.strictEqual(viewCalls[0].options.credentials, "same-origin", "view event uses same-origin credentials");
    assert.strictEqual(viewCalls[0].options.body, JSON.stringify({ ticket: "signed-ticket" }), "view event sends only the opaque ticket");
}

async function verifyRefreshDeduplication() {
    const target = makeElement("div");
    let resolveResponse;
    const document = {
        hidden: false,
        createElement: makeElement,
        querySelector: () => target,
        getElementById: () => null,
        addEventListener() {}
    };
    const window = {
        location: { origin: "https://ishswiki.xyz" },
        addEventListener() {},
        setInterval() {},
        setTimeout() {},
        clearTimeout() {}
    };
    const context = {
        URL,
        console: { warn() {} },
        document,
        fetch() {
            return new Promise((resolve) => {
                resolveResponse = resolve;
            });
        },
        performance: { now: () => 0 },
        window
    };

    vm.runInNewContext(sidebar, context);
    const first = window.ringoRanking.refresh();
    const second = window.ringoRanking.refresh();
    assert.strictEqual(first, second, "concurrent visible refreshes share one request");
    resolveResponse({ ok: true, json: () => Promise.resolve({ response: "ok", items: [] }) });
    await first;
}

Promise.all([verifyTrendingStates(), verifyTicketDelay(), verifyRefreshDeduplication()]).then(() => {
    console.log("rankings UI contract checks passed");
}).catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
