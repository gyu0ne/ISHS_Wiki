from .tool.func import *
from .remote_riro_login import riro_login_check
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

            # 블로킹 함수를 비동기적으로 실행
            # app.py가 asyncio 기반으로 동작하므로, to_thread를 사용해 블로킹 I/O를 별도 스레드에서 처리
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, riro_login_check, riro_id, riro_pw)

            if result['status'] == 'success':
                pending_user_id = flask.session.get('pending_riro_verification_for_user', None)
                if pending_user_id:
                    def upsert(name, data):
                        curs.execute(db_change("select data from user_set where id = ? and name = ?"), [pending_user_id, name])
                        if curs.fetchall():
                            curs.execute(db_change("update user_set set data = ? where id = ? and name = ?"), [data, pending_user_id, name])
                        else:
                            curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [pending_user_id, name, data])

                    upsert('student_id', result['hakbun'])
                    upsert('real_name', result['name'])
                    
                    flask.session.pop('pending_riro_verification_for_user', None)
                    flask.session['id'] = pending_user_id
                    return redirect(conn, '/user')
                # 인증 성공 시, 세션에 인증 정보 저장 후 회원가입 페이지로 이동
                else:
                    flask.session['riro_verified'] = True
                    flask.session['riro_name'] = result['name']
                    flask.session['riro_hakbun'] = result['hakbun']
                    return redirect(conn, '/register_form')
            else:
                # 인증 실패 시, 자바스크립트 alert로 에러 메시지 표시
                escaped_message = result['message'].replace("'", "\'" ).replace('"', '\"').replace('\n', '\\n')
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
                        <span>리로스쿨 ID, PW는 서버 측에 저장되지 않습니다.\n서버 측에서 리로스쿨에 직접 로그인하는 방식이므로 1분 가량 시간이 걸릴 수 있습니다.</span>
                    </form>
                ''',
                menu = [['user', get_lang(conn, 'return')]]
            ))
