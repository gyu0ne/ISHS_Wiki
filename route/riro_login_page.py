from .tool.func import *
import requests
import asyncio

async def riro_login_page():
    with get_db_connect() as conn:
        curs = conn.cursor()
        ip = ip_check()

        # 이미 위키에 로그인된 사용자는 이 페이지에 접근할 필요 없음
        if ip_or_user(ip) == 0:
            return redirect(conn, '/user')

        if flask.request.method == 'POST':
            riro_id = flask.request.form.get('riro_id', '')
            riro_pw = flask.request.form.get('riro_pw', '')

            try:
                api_url = "http://127.0.0.1:5001/api/riro_login"
                post_data = {'id': riro_id, 'password': riro_pw}
                response = requests.post(api_url, data=post_data, timeout=30)
                response.raise_for_status()
                result = response.json()
            except requests.exceptions.RequestException as e:
                result = {'status': 'error', 'message': f'인증 서버에 연결할 수 없습니다: {e}'}
            except ValueError:
                result = {'status': 'error', 'message': '인증 서버에서 잘못된 응답을 받았습니다.'}

            if result.get('status') == 'success':
                pending_user_id = flask.session.get('pending_riro_verification_for_user', None)
                if pending_user_id:
                    def upsert(name, data):
                        curs.execute(db_change("select data from user_set where id = ? and name = ?"), [pending_user_id, name])
                        if curs.fetchall():
                            curs.execute(db_change("update user_set set data = ? where id = ? and name = ?"), [data, pending_user_id, name])
                        else:
                            curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [pending_user_id, name, data])

                    upsert('student_id', result.get('student_number', ''))
                    upsert('real_name', result.get('name', ''))
                    upsert('generation', str(result.get('generation', '')))
                    
                    flask.session.pop('pending_riro_verification_for_user', None)
                    flask.session['id'] = pending_user_id
                    return redirect(conn, '/user')
                # 인증 성공 시, 세션에 인증 정보 저장 후 회원가입 페이지로 이동
                else:
                    flask.session['riro_verified'] = True
                    flask.session['riro_name'] = result.get('name')
                    # 'hakbun' 대신 'student_number' 사용
                    flask.session['riro_student_number'] = result.get('student_number')
                    flask.session['riro_generation'] = result.get('generation')
                    
                    if result.get('student_number') == '0':
                        return redirect(conn, '/register_form_teacher')
                    else:
                        return redirect(conn, '/register_form_student')
            else:
                # 인증 실패 시, 자바스크립트 alert로 에러 메시지 표시
                escaped_message = result['message'].replace("'", "'" ).replace('"', '"').replace('\n', '\n')
                return f'''
                    <script>
                        alert(\'{escaped_message}\');
                        history.go(-1);
                    </script>
                '''
        else:
            # GET 요청 시, 로그인 폼을 보여줌
            return easy_minify(conn, flask.render_template(skin_check(conn),
                imp = ['리로스쿨 본인인증', await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
                data = '''
                    <form method="post">
                        <input placeholder="리로스쿨 ID" name="riro_id" type="text">
                        <hr class="main_hr">
                        <input placeholder="리로스쿨 PW" name="riro_pw" type="password">
                        <hr class="main_hr">
                        <button type="submit">인증하기</button>
                        <span>리로스쿨 ID, PW는 서버 측에 저장되지 않습니다.</span>
                    </form>
                ''',
                menu = [['user', get_lang(conn, 'return')]]
            ))
