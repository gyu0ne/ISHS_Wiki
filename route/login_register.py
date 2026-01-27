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
      - '졸업생', '교사'는 별도 처리
      - 그 외에는 정확히 4자리 숫자 abcd
        a: 1~3, b: 1~4, cd: 1~22
    """
    s = (s or '').strip()
    if s in ('졸업생', '교사'):
        return True
    if len(s) != 4 or not s.isdigit():
        return False
    a = int(s[0]); b = int(s[1]); cd = int(s[2:4])
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

def add_user(conn, user_id, user_pw):
    curs = conn.cursor()

    curs.execute(db_change('select data from other where name = "encode"'))
    db_data = curs.fetchall()
    encode_method = db_data[0][0] if db_data and db_data[0][0] != '' else 'sha3'

    hashed_pw = pw_encode(conn, user_pw, encode_method)

    curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, 'pw', hashed_pw])
    curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, 'encode', encode_method])

    # 아래 중복 insert 구간은 기존 구현을 유지
    curs = conn.cursor()
    curs.execute(db_change('select data from other where name = "encode"'))
    db_data = curs.fetchall()
    encode_method = db_data[0][0] if db_data and db_data[0][0] != '' else 'sha3'
    hashed_pw = pw_encode(conn, user_pw, encode_method)
    curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, 'pw', hashed_pw])
    curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, 'encode', encode_method])
    curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, 'acl', 'user'])
    curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, 'date', get_time()])
    curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, 'date', get_time()])

# ===== 학생 회원가입 (리로스쿨 인증 제거) =====
async def login_register_student():
    with get_db_connect() as conn:
        curs = conn.cursor()

        # 리로 인증 확인
        if not flask.session.get('riro_verified'):
            return redirect(conn, '/riro_login')

        # 학생이 아닌 경우(교사) 리다이렉트
        if str(flask.session.get('riro_student_number')) == '0':
            return redirect(conn, '/register_form_teacher')

        ip = ip_check()
        admin = await acl_check(tool='owner_auth')
        admin = 1 if admin == 0 else 0

        # 이미 로그인한 경우
        if admin != 1 and ip_or_user(ip) == 0:
            return redirect(conn, '/user')

        if admin != 1:
            curs.execute(db_change('select data from other where name = "reg"'))
            set_d = curs.fetchall()
            if set_d and set_d[0][0] == 'on':
                return "<h1>DEBUG: Error Code: 0 (Registration disabled)</h1>"

        if flask.request.method == 'POST':
            # 세션에서 인증된 정보 가져오기 (위변조 방지)
            real_name = str(flask.session.get('riro_name', ''))
            student_id = str(flask.session.get('riro_student_number', ''))
            gen = str(flask.session.get('riro_generation', ''))
            
            # 폼 입력값
            birth_y    = _norm(flask.request.form.get('birth_year', ''))
            birth_m    = _norm(flask.request.form.get('birth_month', ''))
            birth_d    = _norm(flask.request.form.get('birth_day', ''))
            gender     = _norm(flask.request.form.get('gender', ''))
            # gen        = _norm(flask.request.form.get('generation', '')) # 세션 값 사용
            user_name  = _norm(flask.request.form.get('user_name', ''))
            user_pw     = flask.request.form.get('pw', '')
            user_repeat = flask.request.form.get('pw2', '')

            # 약관
            if flask.request.form.get('agreement', '') != 'agree':
                return "<h1>DEBUG: Error Code: 999 (Agreement not checked)</h1>"

            # 필수값
            if not user_name or not real_name or not birth_y or not birth_m or not birth_d or not gender:
                return "<h1>DEBUG: Error Code: 27 (Missing required fields)</h1>"

            # 학번 검사(졸업생/교사 제외)
            if not _valid_student_id(student_id):
                return "<h1>DEBUG: Error Code: 998 (Invalid student ID)</h1>"

            # 성별
            if gender not in ['male', 'female']:
                return "<h1>DEBUG: Error Code: 27 (Invalid gender)</h1>"

            # 생년월일
            if not (birth_y.isdigit() and birth_m.isdigit() and birth_d.isdigit()):
                return "<h1>DEBUG: Error Code: 27 (Invalid birth date format)</h1>"
            if not _valid_date(int(birth_y), int(birth_m), int(birth_d)):
                return "<h1>DEBUG: Error Code: 27 (Invalid birth date)</h1>"

            # 비밀번호
            if user_pw == '' or user_repeat == '':
                return "<h1>DEBUG: Error Code: 27 (Password empty)</h1>"
            if user_pw != user_repeat:
                return "<h1>DEBUG: Error Code: 20 (Password mismatch)</h1>"

            user_id = user_name
            if user_id == user_pw:
                return "<h1>DEBUG: Error Code: 49 (ID and password are same)</h1>"

            curs.execute(db_change("select data from other where name = 'password_min_length'"))
            db_data = curs.fetchall()
            if db_data and db_data[0][0] != '':
                password_min_length = int(number_check(db_data[0][0]))
                if password_min_length > len(user_pw):
                    return "<h1>DEBUG: Error Code: 40 (Password too short)</h1>"

            if do_user_name_check(conn, user_id) == 1:
                return "<h1>DEBUG: Error Code: 8 (Duplicate ID)</h1>"

            # 생성 & 프로필 저장
            add_user(conn, user_id, user_pw)
            _save_profile_extra(conn, user_id, student_id, real_name,
                                birth_y, birth_m, birth_d, gender, user_name, gen)

            # 사용자 문서
            try:
                doc_title = f"{html.escape(real_name)}({gen}기)"
                doc_content = f"[[분류:재학생]][[분류:{gen}기]]\n[include(틀:인곽위키/인물)]\n==개요==\n{html.escape(real_name)}님의 사용자 문서입니다."
                today = get_time()
                curs.execute(db_change("select title from data where title = ?"), [doc_title])
                if not curs.fetchall():
                    leng = '+' + str(len(doc_content))
                    curs.execute(db_change("insert into data (title, data) values (?, ?)"), [doc_title, doc_content])
                    history_plus(conn, doc_title, doc_content, today, user_id, '회원가입', leng, mode='r1')
                    render_set(conn, doc_name=doc_title, doc_data=doc_content, data_type='backlink')
            except Exception as e:
                print(f"Error creating user document for {user_id}: {e}")

            # 성공
            return easy_minify(conn, flask.render_template(
                skin_check(conn),
                imp=[get_lang(conn, 'register'), await wiki_set(),
                     await wiki_custom(conn), wiki_css([0, 0])],
                data='''
                    <div style="margin-top:12px; padding:10px; border:1px solid #c7e7c7; background:#eaffe6; color:#126b12; border-radius:6px;">
                        회원가입에 성공하였습니다. <a href="/login">로그인 하러 가기</a>
                    </div>
                ''',
                menu=[[ 'user', get_lang(conn, 'return') ]]
            ))

        else:
            # 폼 표시 (인증된 정보는 disabled 처리하여 보여줌)
            curs.execute(db_change("select data from other where name = 'password_min_length'"))
            db_data = curs.fetchall()
            password_min_length = f" ({get_lang(conn, 'password_min_length')} : {db_data[0][0]})" if db_data and db_data[0][0] != '' else ''

            now = datetime.datetime.now()
            default_y = str(now.year - 16); default_m = "01"; default_d = "01"
            
            # 세션 정보
            sess_name = flask.session.get('riro_name', '')
            sess_std = flask.session.get('riro_student_number', '')
            sess_gen = flask.session.get('riro_generation', '')

            return easy_minify(conn, flask.render_template(
                skin_check(conn),
                imp=[get_lang(conn, 'register'), await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
                data=f'''
                    <style>
                        .yakgwan-article {{
                            display: block;
                            font-weight: 700;
                            margin-top: 6px;
                            margin-bottom: 4px;
                        }}
                    </style>
                    <form method="post">
                        <input placeholder="아이디" name="user_name" type="text" required>
                        <small style="display:block; margin-top:4px; color:#888; text-align:left;">아이디는 영문, 한글, 숫자만 사용 가능합니다.</small>
                        <hr class="main_hr">
                        
                        <label>이름</label>
                        <input value="{sess_name}" type="text" disabled>
                        <hr class="main_hr">
                        
                        <label>학번</label>
                        <input value="{sess_std}" type="text" disabled>
                        <hr class="main_hr">

                        <label>기수</label>
                        <input value="{sess_gen}기" type="text" disabled>
                        <hr class="main_hr">

                        <label>생년월일</label>
                        <div style="display:flex; gap:8px; align-items:center;">
                            <input name="birth_year" type="number" min="1900" max="{now.year}" value="{default_y}" style="width:6em;" required><span>년</span>
                            <input name="birth_month" type="number" min="1" max="12" value="{default_m}" style="width:4em;" required><span>월</span>
                            <input name="birth_day" type="number" min="1" max="31" value="{default_d}" style="width:4em;" required><span>일</span>
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

                        <label>
                            <div id="yakgwan" style="max-height:300px; overflow-y:auto; border:1px solid #ccc; padding:10px; white-space:pre-wrap; text-align:left; font-size:14px;"><span class="yakgwan-article">제1조 (목적)</span>
본 약관은 인곽위키(이하 “위키”)의 이용 조건, 권리와 의무, 책임 사항 등을 규정함을 목적으로 한다.

<span class="yakgwan-article">제2조 (회원의 의무)</span>
회원은 관련 법령, 본 약관, 위키 내 규정을 준수하여야 한다.

회원은 타인의 권리를 침해하거나 불법적인 콘텐츠를 게재해서는 안 된다.

계정의 관리 책임은 회원 본인에게 있으며, 타인에게 양도·대여할 수 없다.

<span class="yakgwan-article">제3조 (콘텐츠의 저작권 및 사용)</span>
회원이 위키에 기여한 모든 문서 및 자료는 CC-BY-SA 라이선스에 따라 공개된다.

회원은 기여한 콘텐츠에 대한 저작권을 보유하되, 위키 운영을 위해 무상·영구적으로 이용 허락한 것으로 간주한다.

<span class="yakgwan-article">제4조 (개인정보 보호)</span>
위키는 회원가입 및 운영에 필요한 최소한의 개인정보만을 수집·관리한다.

위키는 회원의 동의 없이 개인정보를 제3자에게 제공하지 않는다. 단, 법령에 따른 요청이 있는 경우 예외로 한다.

<span class="yakgwan-article">제5조 (운영자의 권한)</span>
운영자는 위키의 원활한 운영을 위하여 필요 시 회원의 접근을 제한하거나 게시물을 삭제할 수 있다.

운영자는 기술적, 정책적 사유에 따라 위키를 변경·중단할 수 있으며, 이에 대한 책임을 지지 않는다.

<span class="yakgwan-article">제6조 (면책 조항)</span>
위키는 회원이 작성한 콘텐츠의 정확성, 신뢰성에 대해 책임을 지지 않는다. 모든 콘텐츠는 작성자 본인의 책임 하에 게시된다.

<span class="yakgwan-article">제7조 (약관의 변경)</span>
본 약관은 필요 시 개정될 수 있으며, 변경 사항은 위키 내 공지를 통해 회원에게 알린다. 변경된 약관에 동의하지 않을 경우 회원 탈퇴를 요청할 수 있다.

<span class="yakgwan-article">제8조 (회원가입)</span>
1. 회원은 소정의 절차를 거쳐 본 약관에 동의함으로써 가입된다.

2. 회원은 가입 시 정확한 학번, 성명, 성별, 기수 등을 기재하여야 한다.

3. 회원가입과 동시에, 해당 학번·성명·성별·기수 정보를 기반으로 위키 내 인물 문서가 자동 생성됨에 동의한 것으로 간주한다.

4. 회원이 허위 정보를 기재할 경우, 위키 이용이 제한되거나 계정이 삭제될 수 있다.

                            </div>
                            <br>
                            <input type="checkbox" name="agreement" value="agree" required> 위 약관에 동의합니다.
                        </label>
                        <hr class="main_hr">

                        <button type="submit">{get_lang(conn, 'save')}</button>
                        {http_warning(conn)}
                        <span>기수, 성별 등이 실제와 다를 경우 향후 이용에 불이익이 있을 수 있습니다. 부적절한 아이디는 제제될 수 있습니다.</span>
                        <span>로그인은 아이디로 이루어집니다.</span>
                    </form>
                ''',
                menu=[[ 'user', get_lang(conn, 'return') ]]
            ))

# ===== 교사 회원가입 (리로스쿨 인증 제거) =====
async def login_register_teacher():
    with get_db_connect() as conn:
        curs = conn.cursor()

        # 리로 인증 확인
        if not flask.session.get('riro_verified'):
            return redirect(conn, '/riro_login')

        # 교사가 아닌 경우(학생) 리다이렉트
        if str(flask.session.get('riro_student_number')) != '0':
            return redirect(conn, '/register_form_student')

        ip = ip_check()
        admin = await acl_check(tool='owner_auth')
        admin = 1 if admin == 0 else 0

        # 이미 로그인한 경우
        if admin != 1 and ip_or_user(ip) == 0:
            return redirect(conn, '/user')

        if admin != 1:
            curs.execute(db_change('select data from other where name = "reg"'))
            set_d = curs.fetchall()
            if set_d and set_d[0][0] == 'on':
                return "<h1>DEBUG: Error Code: 0 (Registration disabled)</h1>"

        if flask.request.method == 'POST':
            # 세션에서 인증된 정보 가져오기
            real_name = str(flask.session.get('riro_name', ''))
            student_id = '교사'
            gen = '0' # 교사는 기수 없음
            
            # 입력값
            # real_name = _norm(flask.request.form.get('real_name', '')) # 세션값 사용
            # student_id = '교사'
            birth_y    = _norm(flask.request.form.get('birth_year', ''))
            birth_m    = _norm(flask.request.form.get('birth_month', ''))
            birth_d    = _norm(flask.request.form.get('birth_day', ''))
            gender     = _norm(flask.request.form.get('gender', ''))
            # gen        = _norm(flask.request.form.get('generation', ''))  # 교사는 빈 값 허용
            user_name  = _norm(flask.request.form.get('user_name', ''))
            user_pw     = flask.request.form.get('pw', '')
            user_repeat = flask.request.form.get('pw2', '')

            if flask.request.form.get('agreement', '') != 'agree':
                return "<h1>DEBUG: Error Code: 999 (Agreement not checked)</h1>"

            if not user_name or not real_name or not birth_y or not birth_m or not birth_d or not gender:
                return "<h1>DEBUG: Error Code: 27 (Missing required fields)</h1>"

            if not _valid_student_id(student_id):
                return "<h1>DEBUG: Error Code: 998 (Invalid student ID)</h1>"

            if gender not in ['male', 'female']:
                return "<h1>DEBUG: Error Code: 27 (Invalid gender)</h1>"

            if not (birth_y.isdigit() and birth_m.isdigit() and birth_d.isdigit()):
                return "<h1>DEBUG: Error Code: 27 (Invalid birth date format)</h1>"
            if not _valid_date(int(birth_y), int(birth_m), int(birth_d)):
                return "<h1>DEBUG: Error Code: 27 (Invalid birth date)</h1>"

            if user_pw == '' or user_repeat == '':
                return "<h1>DEBUG: Error Code: 27 (Password empty)</h1>"
            if user_pw != user_repeat:
                return "<h1>DEBUG: Error Code: 20 (Password mismatch)</h1>"

            user_id = user_name
            if user_id == user_pw:
                return "<h1>DEBUG: Error Code: 49 (ID and password are same)</h1>"

            curs.execute(db_change("select data from other where name = 'password_min_length'"))
            db_data = curs.fetchall()
            if db_data and db_data[0][0] != '':
                password_min_length = int(number_check(db_data[0][0]))
                if password_min_length > len(user_pw):
                    return "<h1>DEBUG: Error Code: 40 (Password too short)</h1>"

            if do_user_name_check(conn, user_id) == 1:
                return "<h1>DEBUG: Error Code: 8 (Duplicate ID)</h1>"

            add_user(conn, user_id, user_pw)
            _save_profile_extra(conn, user_id, student_id, real_name,
                                birth_y, birth_m, birth_d, gender, user_name, gen)

            try:
                doc_title = f"{html.escape(real_name)}(교사)"
                doc_content = f"[[분류:교사]]\n[include(틀:인곽위키/인물)]\n==개요==\n{html.escape(real_name)} 선생님의 사용자 문서입니다."
                today = get_time()
                curs.execute(db_change("select title from data where title = ?"), [doc_title])
                if not curs.fetchall():
                    leng = '+' + str(len(doc_content))
                    curs.execute(db_change("insert into data (title, data) values (?, ?)"), [doc_title, doc_content])
                    history_plus(conn, doc_title, doc_content, today, user_id, '회원가입', leng, mode='r1')
                    render_set(conn, doc_name=doc_title, doc_data=doc_content, data_type='backlink')
            except Exception as e:
                print(f"Error creating user document for {user_id}: {e}")

            return easy_minify(conn, flask.render_template(
                skin_check(conn),
                imp=[get_lang(conn, 'register'), await wiki_set(),
                     await wiki_custom(conn), wiki_css([0, 0])],
                data='''
                    <div style="margin-top:12px; padding:10px; border:1px solid #c7e7c7; background:#eaffe6; color:#126b12; border-radius:6px;">
                        회원가입에 성공하였습니다. <a href="/login">로그인 하러 가기</a>
                    </div>
                ''',
                menu=[[ 'user', get_lang(conn, 'return') ]]
            ))

        else:
            curs.execute(db_change("select data from other where name = 'password_min_length'"))
            db_data = curs.fetchall()
            password_min_length = f" ({get_lang(conn, 'password_min_length')} : {db_data[0][0]})" if db_data and db_data[0][0] != '' else ''

            now = datetime.datetime.now()
            default_y = str(now.year - 16); default_m = "01"; default_d = "01"

            sess_name = flask.session.get('riro_name', '')

            return easy_minify(conn, flask.render_template(
                skin_check(conn),
                imp=[get_lang(conn, 'register'), await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
                data=f'''
                    <style>
                        .yakgwan-article {{
                            display: block;
                            font-weight: 700;
                            margin-top: 6px;
                            margin-bottom: 4px;
                        }}
                    </style>
                    <form method="post">
                        <input placeholder="아이디" name="user_name" type="text" required>
                        <hr class="main_hr">
                        
                        <label>직책</label>
                        <input value="교사" type="text" disabled>
                        <hr class="main_hr">
                        
                        <label>이름</label>
                        <input value="{sess_name}" type="text" disabled>
                        <hr class="main_hr">

                        <label>생년월일</label>
                        <div style="display:flex; gap:8px; align-items:center;">
                            <input name="birth_year" type="number" min="1900" max="{now.year}" value="{default_y}" style="width:6em;" required><span>년</span>
                            <input name="birth_month" type="number" min="1" max="12" value="{default_m}" style="width:4em;" required><span>월</span>
                            <input name="birth_day" type="number" min="1" max="31" value="{default_d}" style="width:4em;" required><span>일</span>
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

                        <label>
                            <div id="yakgwan" style="max-height:300px; overflow-y:auto; border:1px solid #ccc; padding:10px; white-space:pre-wrap; text-align:left; font-size:14px;"><span class="yakgwan-article">제1조 (목적)</span>
본 약관은 인곽위키(이하 “위키”)의 이용 조건, 권리와 의무, 책임 사항 등을 규정함을 목적으로 한다.

<span class="yakgwan-article">제2조 (회원의 의무)</span>
회원은 관련 법령, 본 약관, 위키 내 규정을 준수하여야 한다.

회원은 타인의 권리를 침해하거나 불법적인 콘텐츠를 게재해서는 안 된다.

계정의 관리 책임은 회원 본인에게 있으며, 타인에게 양도·대여할 수 없다.

<span class="yakgwan-article">제3조 (콘텐츠의 저작권 및 사용)</span>
회원이 위키에 기여한 모든 문서 및 자료는 CC-BY-SA 라이선스에 따라 공개된다.

회원은 기여한 콘텐츠에 대한 저작권을 보유하되, 위키 운영을 위해 무상·영구적으로 이용 허락한 것으로 간주한다.

<span class="yakgwan-article">제4조 (개인정보 보호)</span>
위키는 회원가입 및 운영에 필요한 최소한의 개인정보만을 수집·관리한다.

위키는 회원의 동의 없이 개인정보를 제3자에게 제공하지 않는다. 단, 법령에 따른 요청이 있는 경우 예외로 한다.

<span class="yakgwan-article">제5조 (운영자의 권한)</span>
운영자는 위키의 원활한 운영을 위하여 필요 시 회원의 접근을 제한하거나 게시물을 삭제할 수 있다.

운영자는 기술적, 정책적 사유에 따라 위키를 변경·중단할 수 있으며, 이에 대한 책임을 지지 않는다.

<span class="yakgwan-article">제6조 (면책 조항)</span>
위키는 회원이 작성한 콘텐츠의 정확성, 신뢰성에 대해 책임을 지지 않는다. 모든 콘텐츠는 작성자 본인의 책임 하에 게시된다.

<span class="yakgwan-article">제7조 (약관의 변경)</span>
본 약관은 필요 시 개정될 수 있으며, 변경 사항은 위키 내 공지를 통해 회원에게 알린다. 변경된 약관에 동의하지 않을 경우 회원 탈퇴를 요청할 수 있다.

<span class="yakgwan-article">제8조 (회원가입)</span>
1. 회원은 소정의 절차를 거쳐 본 약관에 동의함으로써 가입된다.

2. 회원은 가입 시 정확한 학번, 성명, 성별, 기수 등을 기재하여야 한다.

3. 회원가입과 동시에, 해당 학번·성명·성별·기수 정보를 기반으로 위키 내 인물 문서가 자동 생성됨에 동의한 것으로 간주한다.

4. 회원이 허위 정보를 기재할 경우, 위키 이용이 제한되거나 계정이 삭제될 수 있다.

                            </div>
                            <br>
                            <input type="checkbox" name="agreement" value="agree" required> 위 약관에 동의합니다.
                        </label>
                        <hr class="main_hr">

                        <button type="submit">{get_lang(conn, 'save')}</button>
                        {http_warning(conn)}
                        <span>로그인은 아이디로 이루어집니다.</span>
                    </form>
                ''',
                menu=[[ 'user', get_lang(conn, 'return') ]]
            ))

