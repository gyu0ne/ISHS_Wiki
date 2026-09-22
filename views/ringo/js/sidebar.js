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
    let stopped = false;
    let request = null;
    let retryable = false;
    let retries = 0;
    const max_retries = 2; // ponytail: short recovery window; add ticket refresh only for longer outages.
    let timer = null;

    const send_view = function() {
        if(sent || stopped || request || document.hidden) {
            return;
        }
        if(retryable) {
            retries += 1;
        }
        request = fetch('/api/ranking/view', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            body: JSON.stringify({ ticket: ticket })
        }).then(function(res) {
            if(!res.ok) {
                const error = new Error('Ranking view request failed');
                error.status = res.status;
                throw error;
            }
            sent = true;
            retryable = false;
        }).catch(function(error) {
            retryable = !error.status || error.status === 429 || error.status >= 500;
            if(!retryable) {
                stopped = true;
            }
            console.warn('Ranking view request failed:', error);
        }).finally(function() {
            request = null;
            if(retryable && !sent) {
                schedule_retry();
            }
        });
    };

    const schedule_retry = function() {
        if(sent || stopped || request || document.hidden) {
            return;
        }
        if(retries >= max_retries) {
            stopped = true;
            return;
        }
        timer = window.setTimeout(send_view, 1000);
    };

    const schedule_view = function() {
        if(sent || stopped || request || foreground_started_at === null) {
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
        if(foreground_ms >= 5000) {
            if(retryable) {
                schedule_retry();
            } else {
                send_view();
            }
            return;
        }
        schedule_view();
    });
    schedule_view();
}

window.ringoRanking = {
    bindMobile: ringo_bind_mobile_trending,
    refresh: ringo_refresh_trending,
    render: ringo_render_trending
};

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


});
