"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const renderSource = readFileSync(
    join(__dirname, "../views/main_css/js/func/render.js"),
    "utf8"
);

function renderFallback(tex, katex) {
    let innerHTMLWrites = 0;
    const element = {
        dataset: { tex },
        style: {},
        textContent: "",
        set innerHTML(value) {
            innerHTMLWrites += 1;
        }
    };
    const document = {
        addEventListener() {},
        querySelectorAll: () => [element]
    };
    const window = {};
    if (katex !== undefined) {
        window.katex = katex;
    }

    const context = vm.createContext({ console, document, window });
    vm.runInContext(renderSource, context, { filename: "render.js" });
    context.opennamu_render_math();

    return { element, innerHTMLWrites };
}

test("uses literal textContent when KaTeX is missing or throws", () => {
    for (const katex of [undefined, { render: () => { throw new Error("bad TeX"); } }]) {
        const tex = '</script><img src=x onerror=alert(1)>';
        const { element, innerHTMLWrites } = renderFallback(tex, katex);

        assert.equal(element.textContent, tex);
        assert.equal(innerHTMLWrites, 0);
    }
});
