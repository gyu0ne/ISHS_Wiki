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

# ===== 관리자 계정 생성 =====
async def admin_create_user():
    with get_db_connect() as conn:
        curs = conn.cursor()

        # 관리자 권한 확인
        if await acl_check(tool='owner_auth') == 1:
            return redirect(conn, '/') # 권한 없음

        if flask.request.method == 'POST':
            # POST 요청은 admin_create_user_submit.py에서 처리
            # 여기서는 폼을 보여주는 역할만 함
            pass
        else:
            # GET: 빈 폼
            curs.execute(db_change("select data from other where name = 'password_min_length'"))
            db_data = curs.fetchall()
            password_min_length = f" ({get_lang(conn, 'password_min_length')} : {db_data[0][0]})" if db_data and db_data[0][0] != '' else ''

            now = datetime.datetime.now()
            default_y = str(now.year - 16)
            default_m = "01"
            default_d = "01"
            default_g = str(now.year - 1993)

            return easy_minify(conn, flask.render_template(
                skin_check(conn),
                imp=[get_lang(conn, 'add_user'), await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
                data=f'''
                    <form method="post" action="/admin/create_user_submit">
                        <input placeholder="아이디" name="user_name" type="text" required>
                        <small style="display:block; margin-top:4px; color:#888; text-align:left;">아이디는 영문, 한글, 숫자만 사용 가능합니다.</small>
                        <hr class="main_hr">
                        <input placeholder="학번 (졸업생은 공란)" name="student_id" type="text">
                        <small style="display:block; margin-top:4px; color:#888; text-align:left;">
                        학번은 4자리로 입력하세요.(ex. 1307) 졸업생인 경우, 공란으로 비워두세요. 교사인 경우 '교사'라고 입력하세요.
                        </small>
                        <hr class="main_hr">
                        <input placeholder="이름" name="real_name" type="text" required>
                        <hr class="main_hr">
                        <input placeholder="기수" name="generation" type="number" min="1" value="{default_g}" required>
                        <span>기</span>
                        <hr class="main_hr">

                        <label>생년월일</label>
                        <div style="display:flex; gap:8px; align-items:center;">
                            <input name="birth_year" type="number" min="1900" max="{now.year}" value="{default_y}" style="width:6em;" required>
                            <span>년</span>
                            <input name="birth_month" type="number" min="1" max="12" value="{default_m}" style="width:4em;" required>
                            <span>월</span>
                            <input name="birth_day" type="number" min="1" max="31" value="{default_d}" style="width:4em;" required>
                            <span>일</span>
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

                        <button type="submit">{get_lang(conn, 'save')}</button>
                        {http_warning(conn)}
                        <span>기수, 성별 등이 실제와 다를 경우 향후 이용에 불이익이 있을 수 있습니다. 부적절한 아이디는 제제될 수 있습니다.</span>
                        <span>로그인은 아이디로 이루어집니다.</span>
                    </form>
                ''',
                menu=[['manager', get_lang(conn, 'return')]]
            ))
