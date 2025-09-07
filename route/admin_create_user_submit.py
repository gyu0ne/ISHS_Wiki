from .tool.func import *
import datetime
import html, unicodedata

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
    if s == '교사':
        return True
    if not s: # Empty string is allowed for "졸업생"
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

def add_user(conn, user_id, user_pw):
    curs = conn.cursor()

    curs.execute(db_change('select data from other where name = "encode"'))
    db_data = curs.fetchall()
    encode_method = db_data[0][0] if db_data and db_data[0][0] != '' else 'sha3'

    hashed_pw = pw_encode(conn, user_pw, encode_method)

    curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, 'pw', hashed_pw])
    curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, 'encode', encode_method])
    curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, 'acl', 'user'])
    curs.execute(db_change("insert into user_set (id, name, data) values (?, ?, ?)"), [user_id, 'date', get_time()])


# ===== 관리자 계정 생성 제출 =====
async def admin_create_user_submit():
    with get_db_connect() as conn:
        curs = conn.cursor()

        # 관리자 권한 확인
        if await acl_check(tool='owner_auth') == 1:
            return await re_error(conn, 3) # 권한 없음

        if flask.request.method == 'POST':
            # 입력값 수집 & 정규화
            real_name = _norm(flask.request.form.get('real_name', ''))
            student_id = _norm(flask.request.form.get('student_id', ''))

            birth_y    = _norm(flask.request.form.get('birth_year', ''))
            birth_m    = _norm(flask.request.form.get('birth_month', ''))
            birth_d    = _norm(flask.request.form.get('birth_day', ''))
            gender     = _norm(flask.request.form.get('gender', ''))
            gen        = _norm(flask.request.form.get('generation', ''))
            user_name  = _norm(flask.request.form.get('user_name', ''))
            user_pw     = flask.request.form.get('pw', '')
            user_repeat = flask.request.form.get('pw2', '')

            # 필수항목 체크
            if not user_name or not real_name or not birth_y or not birth_m or not birth_d or not gender or not gen:
                return await re_error(conn, 27) # 필수 항목 누락

            # 학번 규칙 검사
            if not _valid_student_id(student_id):
                return await re_error(conn, 998) # 유효하지 않은 학번

            # 성별 검사
            if gender not in ['male', 'female']:
                return await re_error(conn, 27) # 유효하지 않은 성별

            # 생년월일 숫자 및 유효 날짜 검사
            if not (birth_y.isdigit() and birth_m.isdigit() and birth_d.isdigit()):
                return await re_error(conn, 27) # 유효하지 않은 생년월일 형식
            if not _valid_date(int(birth_y), int(birth_m), int(birth_d)):
                return await re_error(conn, 27) # 유효하지 않은 생년월일

            # 비밀번호 검사
            if user_pw == '' or user_repeat == '':
                return await re_error(conn, 27) # 비밀번호 공백
            if user_pw != user_repeat:
                return await re_error(conn, 20) # 비밀번호 불일치

            # 로그인 ID 는 user_name 사용
            user_id = user_name

            if user_id == user_pw:
                return await re_error(conn, 49) # 아이디와 비밀번호가 같음

            curs.execute(db_change("select data from other where name = 'password_min_length'"))
            db_data = curs.fetchall()
            if db_data and db_data[0][0] != '':
                password_min_length = int(number_check(db_data[0][0]))
                if password_min_length > len(user_pw):
                    return await re_error(conn, 40) # 비밀번호가 너무 짧음

            # 중복 ID 체크
            if do_user_name_check(conn, user_id) == 1:
                return await re_error(conn, 8) # 중복 ID
            
            if student_id == '' or not student_id:
                student_id = '졸업생'

            # 사용자 생성 + 추가 프로필 저장
            add_user(conn, user_id, user_pw)
            _save_profile_extra(conn, user_id, student_id, real_name,
                                birth_y, birth_m, birth_d, gender, user_name, gen)

            # 사용자 문서 자동 생성
            if student_id == '졸업생':
                try:
                    doc_title = f"{html.escape(real_name)}({gen}기)"
                    doc_content = f"[[분류:졸업생]][[분류:{gen}기]]\n[include(틀:인곽위키/인물)]\n==개요==\n{html.escape(real_name)}님의 사용자 문서입니다."

                    today = get_time()
                    
                    curs.execute(db_change("select title from data where title = ?"), [doc_title])
                    if not curs.fetchall():
                        leng = '+' + str(len(doc_content))
                        
                        curs.execute(db_change("insert into data (title, data) values (?, ?)"), [doc_title, doc_content])
                        
                        history_plus(
                            conn,
                            doc_title,
                            doc_content,
                            today,
                            user_id,
                            '회원가입',
                            leng,
                            mode='r1'
                        )
                        
                        render_set(
                            conn,
                            doc_name = doc_title,
                            doc_data = doc_content,
                            data_type = 'backlink'
                        )
                except Exception as e:
                    print(f"Error creating user document for {user_id}: {e}")
                
                # 성공 화면
                return easy_minify(conn, flask.render_template(
                    skin_check(conn),
                    imp=[get_lang(conn, 'add_user'), await wiki_set(),
                        await wiki_custom(conn), wiki_css([0, 0])],
                    data=f'''
                        <div style="margin-top:12px; padding:10px; border:1px solid #c7e7c7; background:#eaffe6; color:#126b12; border-radius:6px;">
                            계정 생성에 성공하였습니다.
                        </div>
                    ''',
                    menu=[['manager', get_lang(conn, 'return')]]
                ))
            else:
                try:
                    doc_title = f"{html.escape(real_name)}({gen}기)"
                    doc_content = f"[[분류:재학생]][[분류:{gen}기]]\n[include(틀:인곽위키/인물)]\n==개요==\n{html.escape(real_name)}님의 사용자 문서입니다."

                    today = get_time()
                    
                    curs.execute(db_change("select title from data where title = ?"), [doc_title])
                    if not curs.fetchall():
                        leng = '+' + str(len(doc_content))
                        
                        curs.execute(db_change("insert into data (title, data) values (?, ?)"), [doc_title, doc_content])
                        
                        history_plus(
                            conn,
                            doc_title,
                            doc_content,
                            today,
                            user_id,
                            '회원가입',
                            leng,
                            mode='r1'
                        )
                        
                        render_set(
                            conn,
                            doc_name = doc_title,
                            doc_data = doc_content,
                            data_type = 'backlink'
                        )
                except Exception as e:
                    print(f"Error creating user document for {user_id}: {e}")
                
                # 성공 화면
                return easy_minify(conn, flask.render_template(
                    skin_check(conn),
                    imp=[get_lang(conn, 'add_user'), await wiki_set(),
                        await wiki_custom(conn), wiki_css([0, 0])],
                    data=f'''
                        <div style="margin-top:12px; padding:10px; border:1px solid #c7e7c7; background:#eaffe6; color:#126b12; border-radius:6px;">
                            계정 생성에 성공하였습니다.
                        </div>
                    ''',
                    menu=[['manager', get_lang(conn, 'return')]]
                ))

        else:
            # POST 요청이 아니면 폼 페이지로 리다이렉트
            return redirect(conn, '/admin/create_user')
