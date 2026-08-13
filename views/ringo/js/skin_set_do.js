"use strict";

function ringo_do_regex_data(data) {
    return new RegExp('(?:^|; )' + data + '=([^;]*)');
}

function ringo_do_skin_set() {
    let cookies = document.cookie;

    if(!window.localStorage.getItem('main_css_use_sys_darkmode') || window.localStorage.getItem('main_css_use_sys_darkmode') === '1') {
        if(cookies.match(ringo_do_regex_data('main_css_darkmode')) && cookies.match(ringo_do_regex_data('main_css_darkmode'))[1] === '1') {
            if(!window.matchMedia('(prefers-color-scheme: dark)').matches) {
                document.cookie = 'main_css_darkmode=0; path=/';
                history.go(0);
            }
        }
        
        if(!cookies.match(ringo_do_regex_data('main_css_darkmode')) || cookies.match(ringo_do_regex_data('main_css_darkmode'))[1] === '0') {
            if(window.matchMedia('(prefers-color-scheme: dark)').matches) {
                document.cookie = 'main_css_darkmode=1; path=/';
                history.go(0);
            }
        }
    }

    // Removed main_css_off_sidebar since it causes confusion.
    // Ensure it is always 0 for Ringo skin.
    if (window.localStorage.getItem('main_css_off_sidebar') === '1') {
        window.localStorage.setItem('main_css_off_sidebar', '0');
    }

    if(window.localStorage.getItem('main_css_fixed_width') && window.localStorage.getItem('main_css_fixed_width') !== '') {
        let fixed_width_data = window.localStorage.getItem('main_css_fixed_width');
        let style_target = document.getElementById('ringo_add_style');
        if (style_target) {
            style_target.innerHTML += `
                article.main {
                    max-width: ` + fixed_width_data + `px !important;
                }
            `;
        }
    }

    if(window.localStorage.getItem('main_css_sidebar_right') && window.localStorage.getItem('main_css_sidebar_right') === '1') {
        let style_target = document.getElementById('ringo_add_style');
        if (style_target) {
            style_target.innerHTML += `
                .do_fixed {
                    float: right !important;
                }
            `;
        }
    }

    let dynamic_css = "";

    if(cookies.match(ringo_do_regex_data('main_css_recent_changes_hide')) && cookies.match(ringo_do_regex_data('main_css_recent_changes_hide'))[1] === '1') {
        dynamic_css += `
            .do_fixed > div:nth-of-type(1), #sidebar_recent_changes {
                display: none !important;
            }
        `;
    }

    if(cookies.match(ringo_do_regex_data('main_css_trending_hide')) && cookies.match(ringo_do_regex_data('main_css_trending_hide'))[1] === '1') {
        dynamic_css += `
            .do_fixed > div:nth-of-type(2), #sidebar_trending {
                display: none !important;
            }
        `;
    }



    if (dynamic_css) {
        let style = document.createElement('style');
        style.innerHTML = dynamic_css;
        document.head.appendChild(style);
    }
}

ringo_do_skin_set();