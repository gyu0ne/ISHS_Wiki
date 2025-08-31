from .tool.func import *
import datetime
import hmac, hashlib, html, unicodedata

# ===== 유틸 =====
def _valid_date(y, m, d):
    try:
        datetime.date(int(y), int(m), int(d))
        return True
    except:
        return False

def _norm(s: str) -> str:
    return unicodedata.normalize('NFKC', (s or '')).strip()

def _valid_student_id(s: str) -> bool:
    """
    학번 규칙:
      - '졸업생' 허용
      - 비어있지 않다면 정확히 4자리 숫자 abcd 여야 함
        a: 1~3, b: 1~4, cd: 1~22
    """
    s = (s or '').strip()
    if s == '졸업생':
        return True
    if len(s) != 4 or not s.isdigit():
        return False
    a = int(s[0])
    b = int(s[1])
    cd = int(s[2:4])
    return (1 <= a <= 3) and (1 <= b <= 4) and (1 <= cd <= 22)

def _save_profile_extra(conn, user_id, student_id, real_name, birth_y, birth_m, birth_d, gender, user_name, gen):
    curs = conn.cursor()
    def upsert(name, data):
        curs.execute(db_change("select data from user_set where id = ? and name = ?"), [user_id, name])
        if curs.fetchall():
            curs.execute(db_change("update user_set set data = ? where id = ? and name = ?"), [data, user_id, name])
        else:
            curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, name, data])

    upsert('student_id', student_id)
    upsert('real_name', real_name)
    upsert('birth_year', str(birth_y))
    upsert('birth_month', str(birth_m))
    upsert('birth_day', str(birth_d))
    upsert('gender', gender)
    upsert('user_name', user_name)
    upsert('generation', gen)

# ===== 회원가입 =====
async def login_register():
    with get_db_connect() as conn:
        curs = conn.cursor()

        if 'riro_verified' in flask.session or not flask.session.get['riro_verfied']:
            return redirect(conn, '/riro_login')
        
        if (await ban_check(None, 'register'))[0] == 1:
            return await re_error(conn, 0)

        ip = ip_check()
        admin = await acl_check(tool='owner_auth')
        admin = 1 if admin == 0 else 0

        if admin != 1 and ip_or_user(ip) == 0:
            return redirect(conn, '/user')

        if admin != 1:
            curs.execute(db_change('select data from other where name = "reg"'))
            set_d = curs.fetchall()
            if set_d and set_d[0][0] == 'on':
                return await re_error(conn, 0)

        if flask.request.method == 'POST':
            # 캡차 확인
            if await captcha_post(conn, flask.request.form.get('g-recaptcha-response',
                flask.request.form.get('g-recaptcha', ''))) == 1:
                return await re_error(conn, 13)

            # 입력값 수집 & 정규화
            student_id = _norm(flask.request.form.get('student_id', ''))
            user_name  = _norm(flask.request.form.get('user_name', ''))
            real_name  = _norm(flask.request.form.get('real_name', ''))
            birth_y    = _norm(flask.request.form.get('birth_year', ''))
            birth_m    = _norm(flask.request.form.get('birth_month', ''))
            birth_d    = _norm(flask.request.form.get('birth_day', ''))
            gender     = _norm(flask.request.form.get('gender', ''))
            gen        = _norm(flask.request.form.get('generation', ''))

            user_pw     = flask.request.form.get('pw', '')
            user_repeat = flask.request.form.get('pw2', '')

            # 필수항목 체크(학번 제외: 졸업생 공란 허용)
            if not user_name or not real_name or not birth_y or not birth_m or not birth_d or not gender:
                return await re_error(conn, 27)
            
            # 학번 공란 처리 → '졸업생' 치환
            if student_id == '':
                student_id = '졸업생'

            # 학번 규칙 검사
            if not _valid_student_id(student_id):
                return await re_error(conn, "유효하지 않은 학번입니다.")

            # 성별 검사
            if gender not in ['male', 'female']:
                return await re_error(conn, 27)

            # 생년월일 숫자 및 유효 날짜 검사
            if not (birth_y.isdigit() and birth_m.isdigit() and birth_d.isdigit()):
                return await re_error(conn, 27)
            if not _valid_date(int(birth_y), int(birth_m), int(birth_d)):
                return await re_error(conn, 27)

            # 비밀번호 검사
            if user_pw == '' or user_repeat == '':
                return await re_error(conn, 27)
            if user_pw != user_repeat:
                return await re_error(conn, 20)

            # 로그인 ID 는 user_name 사용 (학번 공란 허용 정책과 충돌 방지)
            user_id = user_name

            if user_id == user_pw:
                return await re_error(conn, 49)

            curs.execute(db_change("select data from other where name = 'password_min_length'"))
            db_data = curs.fetchall()
            if db_data and db_data[0][0] != '':
                password_min_length = int(number_check(db_data[0][0]))
                if password_min_length > len(user_pw):
                    return await re_error(conn, 40)

            # 중복 ID 체크
            if do_user_name_check(conn, user_id) == 1:
                return await re_error(conn, 8)

            # 사용자 생성 + 추가 프로필 저장
            add_user(conn, user_id, user_pw)
            _save_profile_extra(conn, user_id, student_id, real_name,
                                birth_y, birth_m, birth_d, gender, user_name, gen)
            
            flask.session.pop('riro_verified', None)
            flask.session.pop('riro_name', None)
            flask.session.pop('riro_hakbun', None)

            # 성공 화면
            now = datetime.datetime.now()
            return easy_minify(conn, flask.render_template(
                skin_check(conn),
                imp=[get_lang(conn, 'register'), await wiki_set(),
                     await wiki_custom(conn), wiki_css([0, 0])],
                data=f"""
                    <form method="post">
                        <div style="padding:8px 0;">
                            <input placeholder="아이디" name="user_name" type="text" value="{html.escape(user_name)}" readonly>
                            <hr class="main_hr">
                            <input placeholder="학번" name="student_id" type="text" inputmode="numeric" value="{html.escape(student_id)}" readonly>
                            <small style="display:block; margin-top:4px; color:#888; text-align:left;">
                            학번은 4자리로 입력하세요.(ex. 1307) 졸업생인 경우, 공란으로 비워두세요.
                            </small>
                        </div>
                        <hr class="main_hr">

                        <div style="padding:8px 0;">
                            <input placeholder="이름" name="real_name" type="text" value="{html.escape(real_name)}" readonly>
                        </div>
                        <hr class="main_hr">

                        <label>생년월일</label>
                        <div style="display:flex; gap:8px; align-items:center;">
                            <input name="birth_year" type="number" value="{html.escape(birth_y)}" style="width:6em;" readonly>
                            <span>년</span>
                            <input name="birth_month" type="number" value="{html.escape(birth_m)}" style="width:4em;" readonly>
                            <span>월</span>
                            <input name="birth_day" type="number" value="{html.escape(birth_d)}" style="width:4em;" readonly>
                            <span>일</span>

                            <input name="generation" type="number"
                                   value="{html.escape(gen or str(now.year - 1993))}"
                                   style="width:4em;" readonly>
                            <span>기</span>
                        </div>
                        <hr class="main_hr">



                        <label for="gender">성별</label>
                        <input type="text" value="{'남성' if gender=='male' else '여성'}" readonly>
                        <hr class="main_hr">

                        <div style="margin-top:12px; padding:10px; border:1px solid #c7e7c7; background:#eaffe6; color:#126b12; border-radius:6px;">
                            회원가입에 성공하였습니다. <a href="/login">로그인 하러 가기</a>
                        </div>
                    </form>
                """,
                menu=[['user', get_lang(conn, 'return')]]
            ))

        else:
            # GET: 빈 폼
            curs.execute(db_change('select data from other where name = "contract"'))
            data = curs.fetchall()
            contract = (data[0][0] + '<hr class="main_hr">') if data and data[0][0] != '' else ''

            curs.execute(db_change("select data from other where name = 'password_min_length'"))
            db_data = curs.fetchall()
            if db_data and db_data[0][0] != '':
                password_min_length = ' (' + get_lang(conn, 'password_min_length') + ' : ' + db_data[0][0] + ')'
            else:
                password_min_length = ''

            now = datetime.datetime.now()
            default_y = str(now.year - 16)
            default_m = "01"
            default_d = "01"
            default_g = str(now.year - 1993)

            verified_name = flask.session.get('riro_name', '')
            verified_hakbun = flask.session.get('riro_hakbun', '')

            return easy_minify(conn, flask.render_template(
                skin_check(conn),
                imp=[
                    get_lang(conn, 'register'),
                    await wiki_set(),
                    await wiki_custom(conn),
                    wiki_css([0, 0])
                ],
                data=f"""
                    <form method="post">
                        {contract}

                        <input placeholder="아이디" name="user_name" type="text" required>
                        <hr class="main_hr">

                        {'''''' if verified_hakbun else ''}
                        <input placeholder="학번"
                            name="student_id"
                            type="text"
                            value="{html.escape(verified_hakbun)}" {'readonly' if verified_hakbun else ''}>
                        <small style="display:block; margin-top:4px; color:#888; text-align:left;">
                        { '학생 인증 정보가 자동으로 입력됩니다.' if verified_hakbun else '학번은 4자리로 입력하세요.(ex. 1307) 졸업생인 경우, 공란으로 비워두세요.'}
                        </small>
                        <hr class="main_hr">

                        {'''''' if verified_name else ''}
                        <input placeholder="이름" name="real_name" type="text" value="{html.escape(verified_name)}" {'readonly' if verified_name else ''} required>
                        <hr class="main_hr">
                        ))

                        <label>생년월일</label>
                        <div style="display:flex; gap:8px; align-items:center;">
                            <input name="birth_year" type="number" min="1900" max="{now.year}" value="{default_y}" style="width:6em;" required>
                            <span>년</span>
                            <input name="birth_month" type="number" min="1" max="12" value="{default_m}" style="width:4em;" required>
                            <span>월</span>
                            <input name="birth_day" type="number" min="1" max="31" value="{default_d}" style="width:4em;" required>
                            <span>일</span>
                            
                            <input name="generation"
                                type="number"
                                inputmode="numeric"
                                min="1"
                                step="1"
                                value="{default_g}"
                                style="width:4em;"
                                required>
                            <span>기</span>
                        </div>
                        <hr class="main_hr">


                        <label for="gender">성별</label>
                        <select name="gender" id="gender" required>
                            <option value="" selected>선택</option>
                            <option value="male">남성</option>
                            <option value="female">여성</option>
                        </select>
                        <hr class="main_hr">

                        <input placeholder="{get_lang(conn, 'password')}{password_min_length}" name="pw" type="password" autocomplete="new-password" required>
                        <hr class="main_hr">

                        <input placeholder="{get_lang(conn, 'password_confirm')}" name="pw2" type="password" autocomplete="new-password" required>
                        <hr class="main_hr">

                        {await captcha_get(conn)}

                        <button type="submit">{get_lang(conn, 'save')}</button>
                        {http_warning(conn)}
                    </form>
                """,
                menu=[['user', get_lang(conn, 'return')]]
            ))