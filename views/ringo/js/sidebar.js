"use strict";

const RINGO_RECENT_SIDEBAR_REFRESH_MS = 60000;
const RINGO_TRENDING_REFRESH_MS = 30000;

const ringo_trending_state = {
    items: null,
    status: 'loading',
    request: null,
    mobile_views: []
};

function ringo_trending_url(url) {
    try {
        const parsed_url = new URL(url, window.location.origin);
        if(parsed_url.origin === window.location.origin) {
            return parsed_url.pathname + parsed_url.search + parsed_url.hash;
        }
    } catch(error) {
        console.warn('Invalid trending URL:', error);
    }

    return '#';
}

function ringo_render_trending(target) {
    if(!target) {
        return;
    }

    target.replaceChildren();

    if(ringo_trending_state.status === 'error') {
        const message = document.createElement('p');
        message.className = 'ringo_trending_message';
        message.textContent = '실시간 인기 문서를 불러올 수 없습니다.';
        target.appendChild(message);
        return;
    }

    if(ringo_trending_state.items === null) {
        const message = document.createElement('p');
        message.className = 'ringo_trending_message';
        message.textContent = '불러오는 중입니다.';
        target.appendChild(message);
        return;
    }

    if(ringo_trending_state.items.length === 0) {
        const message = document.createElement('p');
        message.className = 'ringo_trending_message';
        message.textContent = '표시할 실시간 인기 문서가 없습니다.';
        target.appendChild(message);
        return;
    }

    const list = document.createElement('ul');
    list.className = 'opennamu_trending_sidebar ringo_trending_list';
    for(let index = 0; index < ringo_trending_state.items.length; index++) {
        const item = ringo_trending_state.items[index];
        const list_item = document.createElement('li');
        const link = document.createElement('a');
        const rank = document.createElement('span');
        const title = document.createElement('span');

        link.href = ringo_trending_url(item.url);
        rank.className = 'ringo_trending_rank';
        rank.textContent = String(index + 1) + '.';
        title.className = 'ringo_trending_title';
        title.textContent = item.title;
        link.appendChild(rank);
        link.appendChild(title);
        list_item.appendChild(link);
        list.appendChild(list_item);
    }
    target.appendChild(list);
}

function ringo_render_all_trending() {
    ringo_render_trending(document.querySelector('#sidebar_trending .opennamu_trending_sidebar'));
    for(let index = 0; index < ringo_trending_state.mobile_views.length; index++) {
        const mobile_view = ringo_trending_state.mobile_views[index];
        if(mobile_view.is_active()) {
            ringo_render_trending(mobile_view.target);
        }
    }
}

function ringo_refresh_trending() {
    if(document.hidden || ringo_trending_state.request) {
        return ringo_trending_state.request;
    }

    ringo_trending_state.request = fetch('/api/trending', {
        credentials: 'same-origin',
        headers: { 'Accept': 'application/json' }
    }).then(function(res) {
        if(!res.ok) {
            throw new Error('Trending request failed');
        }
        return res.json();
    }).then(function(data) {
        if(!data || data.response !== 'ok' || !Array.isArray(data.items)) {
            throw new Error('Trending response is invalid');
        }

        ringo_trending_state.items = data.items.filter(function(item) {
            return item && typeof item.title === 'string' && typeof item.url === 'string';
        });
        ringo_trending_state.status = 'ready';
        ringo_render_all_trending();
    }).catch(function(error) {
        ringo_trending_state.items = [];
        ringo_trending_state.status = 'error';
        ringo_render_all_trending();
        console.warn('Trending fetch failed:', error);
    }).finally(function() {
        ringo_trending_state.request = null;
    });

    return ringo_trending_state.request;
}

function ringo_bind_mobile_trending(target, is_active) {
    const known_view = ringo_trending_state.mobile_views.some(function(view) {
        return view.target === target;
    });
    if(!known_view) {
        ringo_trending_state.mobile_views.push({ target: target, is_active: is_active });
    }
    ringo_render_trending(target);
    target.style.display = 'block';
    ringo_refresh_trending();
}

function ringo_start_ranking_view() {
    const ticket_element = document.getElementById('ranking_ticket');
    const ticket = ticket_element && ticket_element.dataset.rankingTicket;
    if(!ticket) {
        return;
    }

    let foreground_started_at = document.hidden ? null : performance.now();
    let foreground_ms = 0;
    let sent = false;
    let timer = null;

    const send_view = function() {
        if(sent) {
            return;
        }
        sent = true;
        fetch('/api/ranking/view', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            body: JSON.stringify({ ticket: ticket })
        }).catch(function(error) {
            console.warn('Ranking view request failed:', error);
        });
    };

    const schedule_view = function() {
        if(sent || foreground_started_at === null) {
            return;
        }
        const remaining_ms = Math.max(0, 5000 - foreground_ms - (performance.now() - foreground_started_at));
        timer = window.setTimeout(function() {
            foreground_ms = 5000;
            send_view();
        }, remaining_ms);
    };

    document.addEventListener('visibilitychange', function() {
        if(document.hidden) {
            if(foreground_started_at !== null) {
                foreground_ms += performance.now() - foreground_started_at;
                foreground_started_at = null;
            }
            window.clearTimeout(timer);
            return;
        }

        foreground_started_at = performance.now();
        schedule_view();
    });
    schedule_view();
}

window.ringoRanking = {
    bindMobile: ringo_bind_mobile_trending,
    refresh: ringo_refresh_trending,
    render: ringo_render_trending
};

// func
function ringo_do_xss_encode(data) {
    data = data.replace(/'/g, '&#x27;');
    data = data.replace(/"/g, '&quot;');
    data = data.replace(/</g, '&lt;');
    data = data.replace(/</g, '&gt;');

    return data;
}

function ringo_do_url_encode(data) {
    return encodeURIComponent(data);
}

function ringo_refresh_recent_sidebar() {
    const recent_sidebar = document.getElementById('recent_sidebar_wrap');
    if(!recent_sidebar) {
        return;
    }

    fetch('/api/sidebar/recent').then(function(res) {
        return res.json();
    }).then(function(data) {
        if(data && data.response === 'ok' && typeof data.data === 'string') {
            recent_sidebar.innerHTML = data.data;
        }
    }).catch(function(error) {
    });
}


// event
function ringo_do_side_button_1() {
    if(temp_save[0] === '') {
        fetch("/api/recent_change/10").then(function(res) {
            return res.json();
        }).then(function(text) {
            let data = '';
            for(let for_a = 0; for_a < text.length; for_a++) {
                if(text[for_a][6] === '') {
                    data += '<a href="/w/' + ringo_do_url_encode(text[for_a][1]) + '">' + ringo_do_xss_encode(text[for_a][1]) + '</a><br>';
                    data += text[for_a][2] + ' | ' + ringo_do_xss_encode(text[for_a][3]) + '<br>';
                }
            }

            document.getElementById('side_content').innerHTML = data;
            temp_save[0] = data;
        }).catch(function(error) {
            document.getElementById('side_content').innerHTML = 'Error';
        });
    } else {
        document.getElementById('side_content').innerHTML = temp_save[0];
    }
}

function ringo_do_side_button_2() {
    if(temp_save[1] === '') {
        fetch("/api/recent_discuss/10").then(function(res) {
            return res.json();
        }).then(function(text) {
            let data = '';
            for(let for_a = 0; for_a < text.length; for_a++) {
                data += '<a href="/thread/' + ringo_do_url_encode(text[for_a][3]) + '">' + ringo_do_xss_encode(text[for_a][1]) + '</a><br>';
                data += text[for_a][2] + ' | ' + text[for_a][5] +'<br>';
            }

            document.getElementById('side_content').innerHTML = data;
            temp_save[1] = data;
        }).catch(function(error) {
            document.getElementById('side_content').innerHTML = 'Error';
        });
    } else {
        document.getElementById('side_content').innerHTML = temp_save[1];
    }
}

function ringo_do_side_button_3() {
    if(temp_save[2] === '') {
        fetch("/api/v2/bbs/main").then(function(res) {
            return res.json();
        }).then(function(data) {
            let end_data = '';

            let text = data['data'];
            for(let for_a = 0; for_a < text.length; for_a++) {
                end_data += '<a href="/bbs/w/' + text[for_a].set_id + '/' + text[for_a].set_code + '">' + ringo_do_xss_encode(text[for_a].title) + '</a><br>';
                end_data += text[for_a].date + ' | ' + text[for_a].user_id +'<br>';
            }

            document.getElementById('side_content').innerHTML = end_data;
            temp_save[2] = end_data;
        });
    } else {
        document.getElementById('side_content').innerHTML = temp_save[2];
    }
}

// init
let temp_save = ['', '', ''];

window.addEventListener('DOMContentLoaded', function() {
    ringo_refresh_recent_sidebar();
    window.setInterval(ringo_refresh_recent_sidebar, RINGO_RECENT_SIDEBAR_REFRESH_MS);

    ringo_render_all_trending();
    ringo_refresh_trending();
    window.setInterval(ringo_refresh_trending, RINGO_TRENDING_REFRESH_MS);
    document.addEventListener('visibilitychange', function() {
        if(!document.hidden) {
            ringo_refresh_trending();
        }
    });
    ringo_start_ranking_view();

    if(document.getElementById("side_button_1")) {
        document.getElementById("side_button_1").addEventListener("click", ringo_do_side_button_1);
        document.getElementById("side_button_2").addEventListener("click", ringo_do_side_button_2);
        document.getElementById("side_button_3").addEventListener("click", ringo_do_side_button_3);

        ringo_do_side_button_1();
    }
});
