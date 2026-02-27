"use strict";

function opennamu_edit_move_all() {
    let lang_data = new FormData();
    lang_data.append('data', 'move document_name why');

    fetch('/api/lang', {
        method: 'POST',
        body: lang_data,
    }).then(function(res) {
        return res.json();
    }).then(function(lang) {
        lang = lang["data"];
        // lang[0] = move, lang[1] = document_name, lang[2] = why

        const container = document.getElementById('opennamu_edit_move_all');
        container.innerHTML = `
            <style>
                #opennamu_move_all_wrap { max-width: 700px; }
                #opennamu_move_all_wrap .move_section { margin-bottom: 8px; }
                #opennamu_move_all_wrap label { display: block; font-weight: bold; margin-bottom: 4px; }
                #opennamu_move_all_textarea {
                    width: 100%; min-height: 130px; box-sizing: border-box;
                    font-family: monospace; font-size: 13px;
                }
                #opennamu_move_all_from, #opennamu_move_all_to,
                #opennamu_move_all_send { width: 100%; box-sizing: border-box; }
                #opennamu_move_all_result { margin-top: 12px; }
                .move_result_item { padding: 3px 0; font-size: 13px; }
                .move_result_ok   { color: #2a9d2a; }
                .move_result_err  { color: #c0392b; }
                .move_result_skip { color: #888; }
                #opennamu_move_preview { margin-top: 8px; font-size: 13px; color: #555; }
            </style>
            <div id="opennamu_move_all_wrap">
                <div class="move_section">
                    <label>이동할 문서 목록 (한 줄에 하나씩)</label>
                    <textarea id="opennamu_move_all_textarea" placeholder="입력"></textarea>
                </div>
                <hr class="main_hr">
                <div class="move_section">
                    <label>치환할 문자열 (From)</label>
                    <input id="opennamu_move_all_from" type="text" placeholder="입력">
                </div>
                <div class="move_section">
                    <label>바꿀 문자열 (To, 비워두면 제거)</label>
                    <input id="opennamu_move_all_to" type="text" placeholder="비워두면 제거">
                </div>
                <hr class="main_hr">
                <div id="opennamu_move_preview"></div>
                <hr class="main_hr">
                <div class="move_section">
                    <label>${lang[2]}</label>
                    <input id="opennamu_move_all_send" type="text" placeholder="${lang[2]}">
                </div>
                <hr class="main_hr">
                <button id="opennamu_move_all_btn" onclick="opennamu_do_move_all()">${lang[0]}</button>
                <div id="opennamu_move_all_result"></div>
            </div>
        `;

        // 미리보기 실시간 갱신
        function updatePreview() {
            const titles = document.getElementById('opennamu_move_all_textarea').value
                .split('\n').map(s => s.trim()).filter(s => s);
            const from = document.getElementById('opennamu_move_all_from').value;
            const to   = document.getElementById('opennamu_move_all_to').value;
            const preview = document.getElementById('opennamu_move_preview');

            if (!titles.length || !from) {
                preview.innerHTML = '';
                return;
            }

            let html = '<b>미리보기</b><br>';
            titles.forEach(function(t) {
                const moved = t.replace(from, to);
                if (moved === t) {
                    html += `<span style="color:#888">${escHtml(t)} → (변화 없음)</span><br>`;
                } else {
                    html += `<span>${escHtml(t)} → <b>${escHtml(moved)}</b></span><br>`;
                }
            });
            preview.innerHTML = html;
        }

        document.getElementById('opennamu_move_all_textarea').addEventListener('input', updatePreview);
        document.getElementById('opennamu_move_all_from').addEventListener('input', updatePreview);
        document.getElementById('opennamu_move_all_to').addEventListener('input', updatePreview);
    });
}

function escHtml(str) {
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function opennamu_do_move_all() {
    const textarea = document.getElementById('opennamu_move_all_textarea');
    const fromVal  = document.getElementById('opennamu_move_all_from').value;
    const toVal    = document.getElementById('opennamu_move_all_to').value;
    const send     = document.getElementById('opennamu_move_all_send').value;
    const btn      = document.getElementById('opennamu_move_all_btn');
    const resultDiv= document.getElementById('opennamu_move_all_result');

    const titles = textarea.value.split('\n').map(s => s.trim()).filter(s => s);

    if (!titles.length) {
        alert('이동할 문서 이름을 입력하세요.');
        return;
    }
    if (!fromVal) {
        alert('치환할 문자열(From)을 입력하세요.');
        return;
    }

    btn.disabled = true;
    btn.textContent = '이동 중...';
    resultDiv.innerHTML = '';

    fetch('/api/move_multiple', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            titles: titles,
            from: fromVal,
            to: toVal,
            send: send
        })
    }).then(function(res) {
        return res.json();
    }).then(function(data) {
        btn.disabled = false;
        btn.textContent = '이동';

        if (data.result !== 'ok') {
            resultDiv.innerHTML = '<span class="move_result_err">오류: ' + escHtml(data.msg || '알 수 없는 오류') + '</span>';
            return;
        }

        let html = '<b>결과</b><br>';
        let ok = 0, swap = 0, err = 0, skip = 0;
        data.data.forEach(function(item) {
            if (item.result === 'ok') {
                ok++;
                html += `<div class="move_result_item move_result_ok">✅ ${escHtml(item.title)} → ${escHtml(item.target)}</div>`;
            } else if (item.result === 'swap') {
                swap++;
                html += `<div class="move_result_item move_result_ok">🔄 ${escHtml(item.title)} ⇋ ${escHtml(item.target)} (바꿔치기)</div>`;
            } else if (item.result === 'skip') {
                skip++;
                html += `<div class="move_result_item move_result_skip">⏭ ${escHtml(item.title)} (변화 없음)</div>`;
            } else {
                err++;
                const msgs = {
                    'no_auth': '권한 없음',
                    'not_found': '원본 문서 없음',
                    'no_change': '변화 없음'
                };
                const msg = msgs[item.msg] || escHtml(item.msg || '오류');
                html += `<div class="move_result_item move_result_err">❌ ${escHtml(item.title)} — ${msg}</div>`;
            }
        });
        html += `<br><b>완료: ${ok}개 이동 / ${swap}개 바꿔치기 / ${skip}개 건너뜀 / ${err}개 오류</b>`;
        resultDiv.innerHTML = html;

        // 성공한 게 있으면 textarea 비우기
        if (ok > 0) {
            document.getElementById('opennamu_move_all_textarea').value = '';
            document.getElementById('opennamu_move_preview').innerHTML = '';
        }
    }).catch(function(e) {
        btn.disabled = false;
        btn.textContent = '이동';
        resultDiv.innerHTML = '<span class="move_result_err">네트워크 오류: ' + escHtml(String(e)) + '</span>';
    });
}