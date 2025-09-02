"use strict";

function opennamu_do_autocomplete(search_input_id, result_div_id) {
    let search_input = document.getElementById(search_input_id);
    let result_div = document.getElementById(result_div_id);

    search_input.addEventListener('keyup', function() {
        if (search_input.value === '') {
            result_div.innerHTML = '';
            return;
        }

        fetch('/api/search_title/' + opennamu_do_url_encode(search_input.value))
            .then(function(res) {
                if (!res.ok) {
                    throw new Error('Network response was not ok');
                }
                return res.json();
            })
            .then(function(data) {
                let html = '<ul>';
                for (let i = 0; i < data.length; i++) {
                    html += '<li><a href="/w/' + opennamu_do_url_encode(data[i]) + '">' + opennamu_xss_filter(data[i]) + '</a></li>';
                }
                html += '</ul>';
                result_div.innerHTML = html;
            })
            .catch(function(error) {
                console.error('Autocomplete fetch error:', error);
                result_div.innerHTML = '';
            });
    });

    document.addEventListener('click', function(event) {
        if (search_input && result_div) {
            if (!search_input.contains(event.target) && !result_div.contains(event.target)) {
                result_div.innerHTML = '';
            }
        }
    });
}

window.addEventListener('DOMContentLoaded', function() {
    if(document.getElementById('search_input_not_mobile')) {
        opennamu_do_autocomplete('search_input_not_mobile', 'autocomplete_results_not_mobile');
    }
    if(document.getElementById('search_input_mobile')) {
        opennamu_do_autocomplete('search_input_mobile', 'autocomplete_results_mobile');
    }
});