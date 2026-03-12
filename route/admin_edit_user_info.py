from .tool.func import *
import html as _html
import datetime

def _valid_date(y, m, d):
    try:
        datetime.date(int(y), int(m), int(d))
        return True
    except:
        return False

async def admin_edit_user_info(user_name=''):
    """
    관리자가 다른 사용자의 특정 정보(학번, 이름, 생년월일, 성별, 기수)를 개별 수정하는 페이지
    /admin/edit_user_info/<user_name>?field=...
    """
    with get_db_connect() as conn:
        curs = conn.cursor()
        
        # 권한 확인 (api_user_info.py와 동일한 조건: owner_auth 또는 ban_auth)
        if await acl_check(tool='owner_auth') != 0 and await acl_check(tool='ban_auth') != 0:
            return re_error(conn, '/error/3')

        field = flask.request.args.get('field', '')
        if not field:
            return redirect(conn, '/w/user:' + url_pas(user_name))

        # 현재 값 읽어오기 헬퍼
        def get_field(name):
            curs.execute(db_change("select data from user_set where id = ? and name = ?"), [user_name, name])
            row = curs.fetchall()
            return row[0][0] if row else ''

        def upsert(name, data):
            curs.execute(db_change("select data from user_set where id = ? and name = ?"), [user_name, name])
            if curs.fetchall():
                curs.execute(db_change("update user_set set data = ? where id = ? and name = ?"), [data, user_name, name])
            else:
                curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_name, name, data])

        error_msg = ''

        if flask.request.method == 'POST':
            try:
                if field == 'birth':
                    y = flask.request.form.get('birth_year', '').strip()
                    m = flask.request.form.get('birth_month', '').strip()
                    d = flask.request.form.get('birth_day', '').strip()
                    if not (y.isdigit() and m.isdigit() and d.isdigit()) or not _valid_date(y, m, d):
                        error_msg = '올바른 날짜를 입력하세요.'
                    else:
                        upsert('birth_year', y)
                        upsert('birth_month', m)
                        upsert('birth_day', d)
                elif field == 'gender':
                    gender = flask.request.form.get('gender', '').strip()
                    if gender in ['male', 'female', '']:
                        upsert('gender', gender)
                    else:
                        error_msg = '성별 값이 올바르지 않습니다.'
                else:
                    # student_id, real_name, generation
                    val = flask.request.form.get(field, '').strip()
                    upsert(field, val)

                if not error_msg:
                    # 저장 후 대상 사용자 문서로 이동
                    return redirect(conn, '/w/user:' + url_pas(user_name))
            except Exception as e:
                error_msg = f'저장 중 오류: {_html.escape(str(e))}'

        # GET 시 폼 표시 구성
        form_html = ''
        title_dict = {
            'student_id': '학번',
            'real_name': '이름',
            'birth': '생년월일',
            'gender': '성별',
            'generation': '기수'
        }
        f_title = title_dict.get(field, field)

        if field == 'birth':
            cur_y = get_field('birth_year')
            cur_m = get_field('birth_month')
            cur_d = get_field('birth_day')
            now_year = datetime.datetime.now().year
            form_html = f'''
                <div style="display:flex; gap:8px; align-items:center;">
                    <input name="birth_year" type="number" min="1900" max="{now_year}" value="{_html.escape(cur_y)}" style="width:6em;"><span>년</span>
                    <input name="birth_month" type="number" min="1" max="12" value="{_html.escape(cur_m)}" style="width:4em;"><span>월</span>
                    <input name="birth_day" type="number" min="1" max="31" value="{_html.escape(cur_d)}" style="width:4em;"><span>일</span>
                </div>
            '''
        elif field == 'gender':
            cur_v = get_field('gender')
            male_sel = 'selected' if cur_v == 'male' else ''
            female_sel = 'selected' if cur_v == 'female' else ''
            form_html = f'''
                <select name="gender">
                    <option value="">선택 안함</option>
                    <option value="male" {male_sel}>남성</option>
                    <option value="female" {female_sel}>여성</option>
                </select>
            '''
        else:
            cur_v = get_field(field)
            tt = "number" if field == "generation" else "text"
            form_html = f'<input name="{field}" type="{tt}" value="{_html.escape(cur_v)}">'

        err_disp = f'<div style="color:red; margin-bottom:10px;">{_html.escape(error_msg)}</div>' if error_msg else ''

        return easy_minify(conn, flask.render_template(
            skin_check(conn),
            imp=[f'사용자 정보 수정 ({_html.escape(user_name)})', await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
            data=f'''
                <h2>{f_title} 수정</h2>
                {err_disp}
                <form method="post">
                    {form_html}
                    <hr class="main_hr">
                    <button type="submit">저장</button>
                    <a href="/w/user:{url_pas(user_name)}">취소</a>
                </form>
            ''',
            menu=[['user:' + url_pas(user_name), '돌아가기']]
        ))
