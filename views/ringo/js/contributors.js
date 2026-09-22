"use strict";

(function() {
    const card = document.getElementById('sidebar_contributors');
    const target = document.getElementById('contributors_sidebar_wrap');
    if(!card || !target) {
        return;
    }

    let request = null;
    let forbidden = false;

    function showMessage(text) {
        const message = document.createElement('p');
        message.className = 'ringo_trending_message';
        message.textContent = text;
        target.replaceChildren(message);
    }

    function internalUrl(value) {
        try {
            const url = new URL(value, window.location.origin);
            if(value && url.origin === window.location.origin &&
                (url.protocol === 'https:' || url.protocol === 'http:') &&
                !url.username && !url.password && !url.pathname.startsWith('//')) {
                return url.pathname + url.search + url.hash;
            }
        } catch(error) {
            return '';
        }
        return '';
    }

    function render(data) {
        if(!data || data.response !== 'ok' || !Array.isArray(data.items) ||
            (data.page !== undefined && data.page !== 1)) {
            throw new Error('Invalid contributor response');
        }
        if(data.items.length === 0) {
            showMessage(data.stale && data.generated_at === 0 ?
                '순위를 집계하고 있습니다.' : '표시할 기여자 순위가 없습니다.');
            return;
        }
        const list = document.createElement('ul');
        list.className = 'ringo_contributor_list';
        data.items.slice(0, 5).forEach(function(item, index) {
            if(!item || typeof item.name !== 'string' || typeof item.url !== 'string' ||
                typeof item.score !== 'number' || !Number.isFinite(item.score)) {
                throw new Error('Invalid contributor');
            }
            const row = document.createElement('li');
            row.className = 'ringo_ranked';
            row.dataset.rank = String(index + 1);
            const rank = document.createElement('span');
            rank.className = 'ringo_rank_badge';
            rank.textContent = String(index + 1);
            const url = internalUrl(item.url);
            const name = document.createElement(url ? 'a' : 'span');
            name.className = 'ringo_contributor_name';
            name.textContent = item.name;
            if(url) {
                name.href = url;
            }
            const score = document.createElement('span');
            score.className = 'ringo_contributor_score';
            score.textContent = item.score.toLocaleString('ko-KR', { maximumFractionDigits: 2 });
            row.appendChild(rank);
            row.appendChild(name);
            row.appendChild(score);
            list.appendChild(row);
        });
        target.replaceChildren(list);
    }

    function refresh() {
        if(document.hidden || forbidden || request) {
            return request;
        }
        request = fetch('/api/rankings/contributors', {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' }
        }).then(function(response) {
            if(response.status === 401 || response.status === 403) {
                forbidden = true;
                card.hidden = true;
                target.replaceChildren();
                return null;
            }
            if(!response.ok) {
                throw new Error('Contributor request failed');
            }
            return response.json();
        }).then(function(data) {
            if(!forbidden) {
                render(data);
            }
        }).catch(function() {
            showMessage('기여자 순위를 불러올 수 없습니다.');
        }).finally(function() {
            request = null;
        });
        return request;
    }

    refresh();
    window.setInterval(refresh, 300000);
    document.addEventListener('visibilitychange', function() {
        if(!document.hidden) {
            refresh();
        }
    });
})();
