"use strict";

function opennamu_do_autocomplete(search_input_id, result_div_id) {
    let search_input = document.getElementById(search_input_id);
    let result_div = document.getElementById(result_div_id);
    let abort_controller = null;
    let debounce_timer = null;

    if (search_input && result_div) {
        const clearTrendingMobilePopup = function() {
            result_div.classList.remove('ringo_trending_results');
            result_div.style.top = '';
        };

        const fetchResults = function() {
            if (debounce_timer) clearTimeout(debounce_timer);

            const query = search_input.value;
            if (query === '') {
                if (window.innerWidth <= 1024) { // 사이드바가 가려지는 충분한 너비에서 표시
                    showTrendingOnMobile();
                } else {
                    clearTrendingMobilePopup();
                    result_div.innerHTML = '';
                    result_div.style.display = 'none';
                }
                return;
            }

            clearTrendingMobilePopup();

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
                if(window.ringoRanking) {
                    const search_bounds = search_input.getBoundingClientRect();
                    result_div.classList.add('ringo_trending_results');
                    result_div.style.top = Math.round(search_bounds.bottom + 8) + 'px';
                    window.ringoRanking.bindMobile(result_div, function() {
                        return search_input.value === '' && window.innerWidth <= 1024 && result_div.style.display !== 'none';
                    });
                }
            }
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
