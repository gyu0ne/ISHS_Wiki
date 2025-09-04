from .tool.func import *
from .remote_riro_login_teacher import riro_login_check_teacher
import asyncio

async def register_teacher_page():
    with get_db_connect() as conn:
        curs = conn.cursor()
        ip = ip_check()

        if ip_or_user(ip) == 0:
            return redirect(conn, '/user')

        if flask.request.method == 'POST':
            riro_id = flask.request.form.get('riro_id', '')
            riro_pw = flask.request.form.get('riro_pw', '')

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, riro_login_check_teacher, riro_id, riro_pw)

            if result['status'] == 'success':
                flask.session['riro_verified'] = True
                flask.session['riro_name'] = result['name']
                flask.session['riro_hakbun'] = 'teacher'  # 교사 유형 식별
                return redirect(conn, '/register/submit')
            else:
                escaped_message = result['message'].replace("'", "\\'").replace('"', '\\"').replace('\\n', '\\\\n')
                return f'''
                    <script>
                        alert('{escaped_message}');
                        history.go(-1);
                    </script>
                '''
        else:
            return easy_minify(conn, flask.render_template(skin_check(conn),
                imp = ['교사 본인인증', await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
                data = '''
                    <form method="post">
                        <input placeholder="리로스쿨 ID" name="riro_id" type="text">
                        <hr class="main_hr">
                        <input placeholder="리로스쿨 PW" name="riro_pw" type="password">
                        <hr class="main_hr">
                        <button type="submit">인증하기</button>
                        <span>리로스쿨 ID, PW는 서버 측에 저장되지 않습니다.\\n서버 측에서 리로스쿨에 직접 로그인하는 방식이므로 1분 가량 시간이 걸릴 수 있습니다.</span>
                    </form>
                ''',
                menu = [['user', get_lang(conn, 'return')]]
            ))
