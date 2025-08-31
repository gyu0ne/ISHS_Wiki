from .tool.func import *

async def login_login():
    with get_db_connect() as conn:
        curs = conn.cursor()

        ip = ip_check()
        if ip_or_user(ip) == 0:
            return redirect(conn, '/user')

        if (await ban_check(None, 'login'))[0] == 1:
            return await re_error(conn, 0)

        if flask.request.method == 'POST':
            if await captcha_post(conn, flask.request.form.get('g-recaptcha-response', flask.request.form.get('g-recaptcha', ''))) == 1:
                return await re_error(conn, 13)

            user_agent = flask.request.headers.get('User-Agent', '')
            user_name = flask.request.form.get('id', '')
            user_pw = flask.request.form.get('pw', '')

            # user_name으로 student_id 찾기
            curs.execute(db_change("select id from user_set where name = 'user_name' and data = ?"), [user_name])
            row = curs.fetchone()
            if not row:
                return await re_error(conn, 2)   # 계정이 존재하지 않습니다

            student_id = row[0]  # 내부적으로는 학번을 user_id로 씀

            # 학번으로 pw 조회
            curs.execute(db_change("select data from user_set where id = ? and name = 'pw'"), [student_id])
            db_data = curs.fetchall()
            if not db_data:
                return await re_error(conn, 2)   # 계정이 존재하지 않습니다
            else:
                db_user_pw = db_data[0][0]

                
            curs.execute(db_change("select data from user_set where id = ? and name = 'encode'"), [student_id])
            db_data = curs.fetchall()
            if not db_data:
                return await re_error(conn, 2)
            else:
                db_user_encode = db_data[0][0]

            if pw_check(conn, user_pw, db_user_pw, db_user_encode, student_id) != 1:
                return await re_error(conn, 10)
            
            curs.execute(db_change("select data from user_set where id = ? and name = 'student_id'"), [student_id])
            student_id_data = curs.fetchall()
            if not student_id_data or not student_id_data[0][0]:
                flask.session['pending_riro_verification_for_user'] = student_id
                return redirect(conn, '/riro_login')

            if pw_check(conn, user_pw, db_user_pw, db_user_encode, student_id) != 1:
                return await re_error(conn, 10)

            # Owner 계정은 학생 인증 검사에서 제외
            if (await acl_check(tool = 'owner_auth', ip = student_id)) != 0:
                curs.execute(db_change("select data from user_set where id = ? and name = 'student_id'"), [student_id])
                if not curs.fetchall():
                    # 학생 정보가 연동되지 않은 경우, 인증 페이지로 이동
                    flask.session['pending_riro_verification_for_user'] = student_id
                    return redirect(conn, '/riro_login')

            curs.execute(db_change('select data from user_set where name = "2fa" and id = ?'), [student_id])
            fa_data = curs.fetchall()
            if fa_data and fa_data[0][0] != '':
                flask.session['login_id'] = student_id
                flask.session['user_name'] = user_name   # 추가 저장하면 편리

                return redirect(conn, '/login/2fa')
            else:
                flask.session['id'] = student_id
                flask.session['user_name'] = user_name   # 아이디 세션도 같이 저장

                ua_plus(conn, student_id, ip, user_agent, get_time())

                return redirect(conn, '/user')

        else:
            return easy_minify(conn, flask.render_template(skin_check(conn),
                imp = [get_lang(conn, 'login'), await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
                data =  '''
                        <form method="post">
                            <input placeholder="''' + get_lang(conn, 'id') + '''" name="id" type="text">
                            <hr class="main_hr">
                            <input placeholder="''' + get_lang(conn, 'password') + '''" name="pw" type="password">
                            <hr class="main_hr">
                            <!-- <label><input type="checkbox" name="auto_login"> ''' + get_lang(conn, 'auto_login') + ''' (''' + get_lang(conn, 'not_working') + ''')</label>
                            <hr class="main_hr"> -->
                            ''' + await captcha_get(conn) + '''
                            <button type="submit">''' + get_lang(conn, 'login') + '''</button>
                            ''' + http_warning(conn) + '''
                        </form>
                        ''',
                menu = [['user', get_lang(conn, 'return')]]
            ))