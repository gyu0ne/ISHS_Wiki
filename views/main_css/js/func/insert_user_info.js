"use strict";

function do_insert_user_info() {
    if(document.getElementById('opennamu_get_user_info')) {
        let name = document.getElementById('opennamu_get_user_info').innerHTML;

        fetch("/api/user_info/" + opennamu_do_url_encode(name)).then(function(res) {
            return res.json();
        }).then(function(data) {
            let lang_data = data["language"];

            let get_data_auth = data['data']['auth'];
            let get_data_auth_date = data['data']['auth_date'];
            if(get_data_auth_date !== '0') {
                get_data_auth += ' (~' + get_data_auth_date + ')';
            }
            
            let get_data_ban = data['data']['ban'];
            let ban_state = '';
            
            if(get_data_ban === '0') {
                ban_state = lang_data['normal'];
            } else {
                let get_ban_do_type = get_data_ban[1].replace(/[a-zA-Z]/g, '');
                let get_ban_range_type = get_data_ban[1].replace(/[0-9]/g, '');

                if(get_ban_range_type === 'a') {
                    ban_state = '<a href="/recent_block/regex">' + lang_data['ban'] + '</a>';
                } else if(get_ban_range_type === 'b') {
                    ban_state = '<a href="/recent_block/cidr">' + lang_data['ban'] + '</a>';
                } else if(get_ban_range_type === 'c') {
                    ban_state = data['data']['auth'];
                } else {
                    ban_state = '<a href="/recent_block/user/' + opennamu_do_url_encode(name) + '">' + lang_data['ban'] + '</a>';
                }

                if(get_data_ban[1] !== '') {
                    ban_state += '<br>'
                    ban_state += lang_data['type'] + ' : ' + get_data_ban[1];
                }
            }
            
            // 성별 표시 변환
            let gender_display = '-';
            if(data['data']['gender'] === 'male') {
                gender_display = '남성';
            } else if(data['data']['gender'] === 'female') {
                gender_display = '여성';
            }

            let end_data = '' +
                '<table class="user_info_table">' +
                    '<tr>' +
                        '<td>' + lang_data['user_name'] + '</td>' +
                        '<td>' + data['data']['render'] + '</td>' +
                    '</tr>' +
                    '<tr>' +
                        '<td>' + lang_data['authority'] + '</td>' +
                        '<td>' + get_data_auth + '</td>' +
                    '</tr>' +
                    '<tr>' +
                        '<td>' + lang_data['state'] + '</td>' +
                        '<td>' + ban_state + '</td>' +
                    '</tr>' +
                    '<tr>' +
                        '<td>학번</td>' +
                        '<td>' + opennamu_xss_filter(data['data']['student_id']) + '</td>' +
                    '</tr>' +
                    '<tr>' +
                        '<td>이름</td>' +
                        '<td>' + opennamu_xss_filter(data['data']['real_name']) + '</td>' +
                    '</tr>' +
                    '<tr>' +
                        '<td>생년월일</td>' +
                        '<td>' + opennamu_xss_filter(data['data']['birth']) + '</td>' +
                    '</tr>' +
                    '<tr>' +
                        '<td>성별</td>' +
                        '<td>' + gender_display + '</td>' +
                    '</tr>' +
                    '<tr>' +
                        '<td>기수</td>' +
                        '<td>' + opennamu_xss_filter(data['data']['generation']) + '</td>' +
                    '</tr>' +
                '</table>' +
            '';
            
            document.getElementById('opennamu_get_user_info').innerHTML = end_data;
        });
    }
}

do_insert_user_info();