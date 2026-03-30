"use strict";

function opennamu_do_autocomplete(search_input_id, result_div_id) {
    let search_input = document.getElementById(search_input_id);
    let result_div = document.getElementById(result_div_id);
    let abort_controller = null;
    let debounce_timer = null;

    if (search_input && result_div) {
        const fetchResults = function() {
            if (debounce_timer) clearTimeout(debounce_timer);

            const query = search_input.value;
            if (query === '') {
                if (window.innerWidth <= 1024) { // 사이드바가 가려지는 충분한 너비에서 표시
                    showTrendingOnMobile();
                } else {
                    result_div.innerHTML = '';
                    result_div.style.display = 'none';
                }
                return;
            }

            debounce_timer = setTimeout(function() {
                if (abort_controller) abort_controller.abort();
                abort_controller = new AbortController();

                fetch('/api/search_title/' + encodeURIComponent(query), { signal: abort_controller.signal })
                    .then(function(res) {
                        if (!res.ok) throw new Error('Network response was not ok');
                        return res.json();
                    })
                    .then(function(data) {
                        // 결과가 있는 경우에만 갱신하여 깜빡임 방지
                        // 사용자의 요청대로 결과가 0개여도 기존 리스트를 유지함 (조합 중 상태 고려)
                        if (data.length > 0) {
                            let html = '<ul>';
                            for (let i = 0; i < data.length; i++) {
                                html += '<li><a href="/w/' + encodeURIComponent(data[i]) + '">' + opennamu_xss_filter(data[i]) + '</a></li>';
                            }
                            html += '</ul>';
                            result_div.innerHTML = html;
                            result_div.style.display = 'block';
                        }
                    })
                    .catch(function(error) {
                        if (error.name === 'AbortError') return;
                        console.error('Autocomplete fetch error:', error);
                    });
            }, 50);
        };

        const showTrendingOnMobile = function() {
            if (search_input.value === '' && window.innerWidth <= 1024) {
                const trending_sidebar = document.querySelector('.opennamu_trending_sidebar');
                
                if (trending_sidebar) {
                    processTrendingHTML(trending_sidebar.innerHTML);
                } else {
                    // 사이드바를 못 찾은 경우 API로 직접 호출 (모바일 등)
                    fetch('/api/trending')
                        .then(res => res.json())
                        .then(data => {
                            if (data.response === 'ok') {
                                processTrendingHTML(data.data);
                            } else {
                                throw new Error(data.data);
                            }
                        })
                        .catch(err => {
                            result_div.innerHTML = '<div style="padding: 10px; color: var(--muted); font-size: 0.9em;">추천 검색어를 불러올 수 없습니다.</div>';
                            result_div.style.display = 'block';
                        });
                }
            }
        };

        const processTrendingHTML = function(html_source) {
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = html_source;
            const items = tempDiv.querySelectorAll('li');
            
            if (items.length > 0) {
                let html = '<ul style="list-style: none; padding: 0; margin: 0;">';
                items.forEach((item, index) => {
                    const link = item.querySelector('a');
                    if (link) {
                        const title = link.textContent.trim();
                        // 1, 2, 3... 순위 숫자가 제목에 포함되어 있을 수 있음
                        const cleanTitle = title.replace(/^[0-9]+\s+/, ''); 
                        const href = link.getAttribute('href');
                        html += `<li><a href="${href}" style="display: flex; align-items: center; padding: 12px 18px; text-decoration: none; color: var(--text); font-size: 14px;">
                            <span style="width: 20px; font-weight: 800; color: #7fad39; margin-right: 8px;">${index + 1}</span>
                            <span style="font-weight: 500; white-space: nowrap;">${opennamu_xss_filter(cleanTitle)}</span>
                        </a></li>`;
                    }
                });
                html += '</ul>';
                result_div.innerHTML = html;
            } else {
                result_div.innerHTML = html_source; // '최근 데이터가 없습니다' div 등
            }
            result_div.style.display = 'block';
        };

        // 한글 입력을 위해 input 이벤트 하나만 사용 (isComposing 제거)
        search_input.addEventListener('input', fetchResults);
        search_input.addEventListener('focus', showTrendingOnMobile);
        search_input.addEventListener('click', showTrendingOnMobile);

        document.addEventListener('click', function(event) {
            if (!search_input.contains(event.target) && !result_div.contains(event.target)) {
                result_div.innerHTML = '';
                result_div.style.display = 'none';
            }
        });
    }
}

window.addEventListener('DOMContentLoaded', function() {
    if(document.getElementById('search_input_not_mobile')) {
        opennamu_do_autocomplete('search_input_not_mobile', 'autocomplete_results_not_mobile');
    }
    if(document.getElementById('search_input_mobile')) {
        opennamu_do_autocomplete('search_input_mobile', 'autocomplete_results_mobile');
    }
});