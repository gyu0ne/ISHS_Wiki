from .tool.func import *

async def register_select_page():
    with get_db_connect() as conn:
        curs = conn.cursor()
        ip = ip_check()

        if ip_or_user(ip) == 0:
            return redirect(conn, '/user')

        return easy_minify(conn, flask.render_template(skin_check(conn),
            imp = ['회원가입 유형 선택', await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
            data = '''
                <div style="text-align: center; padding: 20px;">
                    <h2>회원가입</h2>
                    <p>회원가입 유형을 선택해주세요.</p>
                    <br>
                    <div style="display: flex; justify-content: center; gap: 20px;">
                        <a href="/riro_login" style="text-decoration: none;">
                            <button type="button" style="padding: 10px 20px; font-size: 16px;">재학생</button>
                        </a>
                        <a href="/register_teacher" style="text-decoration: none;">
                            <button type="button" style="padding: 10px 20px; font-size: 16px;">교사</button>
                        </a>
                    </div>
                </div>
            ''',
            menu = [['user', get_lang(conn, 'return')]]
        ))
