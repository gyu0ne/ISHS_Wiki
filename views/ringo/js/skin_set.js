"use strict";

function ringo_do_regex_data(data) {
    return new RegExp('(?:^|; )' + data + '=([^;]*)');
}

function ringo_get_post() {
    const check = document.getElementById('invert');
    if(check) {
        document.cookie = check.checked ? 'main_css_darkmode=1; path=/' : 'main_css_darkmode=0; path=/';
    }

    const check_2 = document.getElementById('use_sys_darkmode');
    if(check_2) {
        window.localStorage.setItem('main_css_use_sys_darkmode', check_2.checked ? '1' : '0');
    }

    const check_rc = document.getElementById('recent_changes_hide');
    if(check_rc) {
        document.cookie = check_rc.checked ? 'main_css_recent_changes_hide=1; path=/' : 'main_css_recent_changes_hide=0; path=/';
    }

    const check_tr = document.getElementById('trending_hide');
    if(check_tr) {
        document.cookie = check_tr.checked ? 'main_css_trending_hide=1; path=/' : 'main_css_trending_hide=0; path=/';
    }



    history.go(0);
}

function ringo_load_skin_set() {
    let cookies = document.cookie;
    
    if(window.location.pathname === '/change/skin_set') {
        let set_language = {
            "en-US" : {
                "save" : "Save",
                "darkmode" : "Darkmode",
                "use_sys_darkmode" : "Use system darkmode set",
                "recent_changes_hide" : "Hide Recent Changes in Sidebar",
                "trending_hide" : "Hide Trending Documents in Sidebar"
            }, "ko-KR" : {
                "save" : "저장",
                "darkmode" : "다크모드",
                "use_sys_darkmode" : "시스템 다크모드 설정 사용",
                "recent_changes_hide" : "우측 사이드바: 최근 변경 숨기기",
                "trending_hide" : "우측 사이드바: 실시간 인기 문서 숨기기"
            }
        }

        let language = cookies.match(ringo_do_regex_data('language')) ? cookies.match(ringo_do_regex_data('language'))[1] : "en-US";
        let user_language = cookies.match(ringo_do_regex_data('user_language')) ? cookies.match(ringo_do_regex_data('user_language'))[1] : "";
        if(user_language in set_language) {
            language = user_language;
        }

        if(!(language in set_language)) {
            language = "en-US";
        }

        let set_data = {};

        if(cookies.match(ringo_do_regex_data('main_css_darkmode')) && cookies.match(ringo_do_regex_data('main_css_darkmode'))[1] === '1') {
            set_data["invert"] = "checked";
        } else {
            set_data["invert"] = "";
        }

        if(!window.localStorage.getItem('main_css_use_sys_darkmode') || window.localStorage.getItem('main_css_use_sys_darkmode') === '1') {
            set_data["use_sys_darkmode"] = "checked";
        } else {
            set_data["use_sys_darkmode"] = "";
        }

        if(cookies.match(ringo_do_regex_data('main_css_recent_changes_hide')) && cookies.match(ringo_do_regex_data('main_css_recent_changes_hide'))[1] === '1') {
            set_data["recent_changes_hide"] = "checked";
        } else {
            set_data["recent_changes_hide"] = "";
        }

        if(cookies.match(ringo_do_regex_data('main_css_trending_hide')) && cookies.match(ringo_do_regex_data('main_css_trending_hide'))[1] === '1') {
            set_data["trending_hide"] = "checked";
        } else {
            set_data["trending_hide"] = "";
        }





        document.getElementById("main_skin_set").innerHTML = ' \
            <label><input ' + set_data["use_sys_darkmode"] + ' type="checkbox" id="use_sys_darkmode" name="use_sys_darkmode" value="use_sys_darkmode"> ' + set_language[language]['use_sys_darkmode'] + '</label> \
            <hr class="main_hr"> \
            <label><input ' + set_data["invert"] + ' type="checkbox" id="invert" name="invert" value="invert"> ' + set_language[language]['darkmode'] + '</label> \
            <hr class="main_hr"> \
            <label><input ' + set_data["recent_changes_hide"] + ' type="checkbox" id="recent_changes_hide" name="recent_changes_hide" value="recent_changes_hide"> ' + set_language[language]['recent_changes_hide'] + '</label> \
            <hr class="main_hr"> \
            <label><input ' + set_data["trending_hide"] + ' type="checkbox" id="trending_hide" name="trending_hide" value="trending_hide"> ' + set_language[language]['trending_hide'] + '</label> \
            <hr class="main_hr"> \
            <button onclick="ringo_get_post();">' + set_language[language]['save'] + '</button> \
        ';
    }
}

window.addEventListener('DOMContentLoaded', ringo_load_skin_set);