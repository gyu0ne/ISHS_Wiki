"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("views/main_css/js/func/autocomplete.js", "utf8");

function harness(width = 375) {
    const listeners = {};
    const timers = new Map();
    const requests = [];
    const classes = new Set();
    let timerId = 0;
    const input = {
        value: "",
        addEventListener(name, callback) { listeners[name] = callback; },
        getBoundingClientRect() { return { bottom: 40 }; },
        contains() { return false; }
    };
    const results = {
        innerHTML: "", style: {}, contains() { return false; },
        classList: {
            add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
            contains(name) { return classes.has(name); }
        }
    };
    const context = {
        AbortController,
        console,
        document: { getElementById: (id) => id === "input" ? input : results, addEventListener() {} },
        window: {
            innerWidth: width, addEventListener() {},
            ringoRanking: { bindMobile(target) { target.innerHTML = "POPULAR"; target.style.display = "block"; } }
        },
        setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
        clearTimeout(id) { timers.delete(id); },
        opennamu_xss_filter: (text) => text.replaceAll("<", "&lt;"),
        fetch(url, options) {
            return new Promise((resolve) => requests.push({ url, signal: options.signal, resolve }));
        }
    };
    vm.runInNewContext(source, context);
    context.opennamu_do_autocomplete("input", "results");
    return {
        input, results, requests, classes,
        focus() { listeners.focus(); },
        type(value) { input.value = value; listeners.input(); },
        dispatch() { for(const [id, callback] of timers) { timers.delete(id); callback(); } },
        async respond(index, items) {
            requests[index].resolve({ ok: true, json: async () => items });
            await new Promise((resolve) => setImmediate(resolve));
        }
    };
}

async function run() {
    // Given a popular list, typing a zero-result query must stop displaying popularity.
    const empty = harness();
    empty.focus();
    assert.equal(empty.results.innerHTML, "POPULAR");
    empty.type("없는문서");
    empty.dispatch();
    await empty.respond(0, []);
    assert.equal(empty.results.innerHTML, "", "zero search results must not retain the popular list");
    assert.equal(empty.results.style.display, "none");

    // Given a pending search, clearing input restores popularity and invalidates the old response.
    const cleared = harness();
    cleared.type("old");
    cleared.dispatch();
    cleared.type("");
    assert.equal(cleared.requests[0].signal.aborted, true, "clearing input cancels pending search");
    await cleared.respond(0, ["old-result"]);
    assert.equal(cleared.results.innerHTML, "POPULAR", "late response must not overwrite empty-input popularity");

    // Given rapid queries, an older completion must not win while the next query is debouncing.
    const changed = harness();
    changed.type("old");
    changed.dispatch();
    changed.type("new");
    await changed.respond(0, ["old-result"]);
    assert.equal(changed.results.innerHTML, "");
    changed.dispatch();
    await changed.respond(1, ["new<result"]);
    assert.match(changed.results.innerHTML, /new&lt;result/);
    assert.equal(changed.results.style.display, "block");
    changed.type("missing");
    changed.dispatch();
    await changed.respond(2, []);
    assert.equal(changed.results.innerHTML, "");
    assert.equal(changed.results.style.display, "none");

    // Desktop also clears an empty search instead of opening mobile popularity.
    const desktop = harness(1280);
    desktop.type("new");
    desktop.dispatch();
    await desktop.respond(0, ["result"]);
    desktop.type("");
    assert.equal(desktop.results.innerHTML, "");
    assert.equal(desktop.results.style.display, "none");
    console.log("autocomplete query and popularity transitions passed");
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
