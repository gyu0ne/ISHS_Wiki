from .tool.func import *
from .riroschoolauth import check_riro_login
import asyncio
import html as _html

from route.riro_reauth_target import REAUTH_YEAR, REAUTH_TARGET_GENERATIONS

async def riro_reauth():
    """
    재학생 재인증 페이지.
    - 로그인된 상태에서만 접근 가능
    - 이미 재인증한 경우 /user 로 리다이렉트
    - 인증 성공 시 student_id 업데이트 + riro_reauthed 플래그 설정
    """
    with get_db_connect() as conn:
        curs = conn.cursor()
        ip = ip_check()

        # 로그인 필수
        if ip_or_user(ip) != 0:
            return redirect(conn, '/login')

        user_id = flask.session.get('id', '')

        # 이미 재인증 완료 확인
        curs.execute(db_change("select data from user_set where id = ? and name = 'riro_reauthed'"), [user_id])
        already_done = curs.fetchall()
        if already_done and already_done[0][0] == '1':
            return redirect(conn, '/user')

        # 기수 가져오기 (안내 메시지용)
        curs.execute(db_change("select data from user_set where id = ? and name = 'generation'"), [user_id])
        gen_row = curs.fetchall()
        user_gen = int(gen_row[0][0]) if gen_row and gen_row[0][0].isdigit() else 0

        error_msg = ''

        if flask.request.method == 'POST':
            riro_id = flask.request.form.get('riro_id', '').strip()
            riro_pw = flask.request.form.get('riro_pw', '')

            if not riro_id or not riro_pw:
                error_msg = '아이디와 비밀번호를 모두 입력해 주세요.'
            else:
                try:
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(None, check_riro_login, riro_id, riro_pw)
                except Exception as e:
                    result = {'status': 'error', 'message': f'인증 중 오류: {e}'}

                if result.get('status') != 'success':
                    error_msg = result.get('message', '인증에 실패했습니다.')
                else:
                    # 인증 성공 → DB 업데이트
                    new_student_id = result.get('student_number', '')
                    new_real_name  = result.get('name', '')
                    new_generation = str(result.get('generation', ''))

                    def upsert(name, data):
                        curs.execute(db_change("select data from user_set where id = ? and name = ?"), [user_id, name])
                        if curs.fetchall():
                            curs.execute(db_change("update user_set set data = ? where id = ? and name = ?"), [data, user_id, name])
                        else:
                            curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, name, data])

                    try:
                        upsert('student_id', new_student_id)
                        upsert('real_name',  new_real_name)
                        upsert('generation', new_generation)
                        upsert('riro_reauthed', '1')  # 재인증 완료 플래그
                    except Exception as e:
                        return f'<h2>DB 오류: {_html.escape(str(e))}</h2><p><a href="/user">돌아가기</a></p>'

                    return easy_minify(conn, flask.render_template(
                        skin_check(conn),
                        imp=['재인증 완료', await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
                        data=f'''
                            <div style="margin-top:16px; padding:14px; border:1px solid #c7e7c7;
                                        background:#eaffe6; color:#126b12; border-radius:8px; text-align:center;">
                                <strong>재인증이 완료되었습니다!</strong><br>
                                이름: {_html.escape(new_real_name)} &nbsp;|&nbsp;
                                학번: {_html.escape(new_student_id)} &nbsp;|&nbsp;
                                기수: {_html.escape(new_generation)}기<br><br>
                                <a href="/user">내 정보 페이지로 이동</a>
                            </div>
                        ''',
                        menu=[['user', '돌아가기']]
                    ))

        # GET 또는 오류 시 폼 표시
        error_html = ''
        if error_msg:
            error_html = f'<div style="color:red; margin-bottom:10px; padding:8px; border-radius:5px; background:#fff0f0;">{_html.escape(error_msg)}</div>'

        notice = ''
        if user_gen in REAUTH_TARGET_GENERATIONS:
            notice = '<p style="color:#555; font-size:0.95em;">신학기부터 리로스쿨 학번 체계가 변경되어 재인증이 필요합니다.<br>리로스쿨 아이디/비밀번호로 인증해 주세요.</p>'

        return easy_minify(conn, flask.render_template(
            skin_check(conn),
            imp=['리로스쿨 재인증', await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
            data=f'''
                <h2 style="margin-bottom:8px;">리로스쿨 재인증</h2>
                {notice}
                {error_html}
                <form method="post">
                    <input placeholder="리로스쿨 ID" name="riro_id" type="text" autocomplete="username">
                    <hr class="main_hr">
                    <input placeholder="리로스쿨 PW" name="riro_pw" type="password" autocomplete="current-password">
                    <hr class="main_hr">
                    <button type="submit">재인증하기</button>
                    <span>리로스쿨 ID, PW는 서버에 저장되지 않습니다.</span>
                </form>
            ''',
            menu=[['user', '돌아가기']]
        ))
