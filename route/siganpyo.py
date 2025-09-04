from .tool.func import *
import requests
import datetime

async def siganpyo(grade = '', class_nm = '', ymd = ''):
    with get_db_connect() as conn:
        curs = conn.cursor()
        ip = ip_check()

        if grade == '' and class_nm == '':
            if ip_or_user(ip) == 0:
                curs.execute(db_change("select data from user_set where id = ? and name = 'student_id'"), [ip])
                student_id_row = curs.fetchone()
                if student_id_row and student_id_row[0]:
                    student_id = student_id_row[0]
                    try:
                        if len(student_id) >= 2 and student_id.isdigit():
                            grade = student_id[0]
                            class_nm = student_id[1]
                            if not (1 <= int(grade) <= 3 and 1 <= int(class_nm) <= 7):
                                grade = '1'
                                class_nm = '1'
                        else:
                            grade = '1'
                            class_nm = '1'
                    except (ValueError, IndexError):
                        grade = '1'
                        class_nm = '1'
                else:
                    grade = '1'
                    class_nm = '1'
            else:
                grade = '1'
                class_nm = '1'

        if ymd == '':
            ymd = (datetime.datetime.now()).strftime('%Y%m%d')

        try:
            date_obj = datetime.datetime.strptime(ymd, '%Y%m%d')
            date_for_input = date_obj.strftime('%Y-%m-%d')
        except ValueError:
            ymd = (datetime.datetime.now()).strftime('%Y%m%d')
            date_obj = datetime.datetime.now()
            date_for_input = date_obj.strftime('%Y-%m-%d')

        current_month = date_obj.month
        current_year = date_obj.year

        if 3 <= current_month <= 8:
            sem = '1'
        else:
            sem = '2'
        
        ay = str(current_year)
        if current_month < 3:
            ay = str(current_year - 1)

        content = ''
        if grade != '' and class_nm != '':
            url = (
                "https://open.neis.go.kr/hub/hisTimetable"
                "?KEY=75f40bb14ddd41d1b5ecda3389258cb1"
                "&ATPT_OFCDC_SC_CODE=E10"
                "&SD_SCHUL_CODE=7310058"
                "&TYPE=JSON"
                f"&AY={ay}"
                f"&SEM={sem}"
                f"&GRADE={grade}"
                f"&CLASS_NM={class_nm}"
                f"&TI_FROM_YMD={ymd}"
                f"&TI_TO_YMD={ymd}"
            )

            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()

                try:
                    timetable = data['hisTimetable'][1]['row']
                    content = f"{ymd[0:4]}년 {ymd[4:6]}월 {ymd[6:8]}일 {grade}학년 {class_nm}반 시간표<br><br>"

                    for class_info in timetable:
                        period = class_info.get('PERIO', '교시 정보 없음')
                        subject = html.escape(class_info.get('ITRT_CNTNT', '수업 없음'))

                        content += f"{period}교시: {subject}<br>"
                except (KeyError, IndexError):
                    content = f"{ymd[0:4]}년 {ymd[4:6]}월 {ymd[6:8]}일에는 시간표 정보가 없습니다."
            else:
                content = f"API 호출 실패: {response.status_code}"
        
        form_html = f'''
            <form onsubmit="window.location.href = '/siganpyo/' + document.getElementById('grade').value + '/' + document.getElementById('class_nm').value + '/' + document.getElementById('date_picker').value.replace(/-/g, ''); return false;">
                <select id="grade" name="grade">
                    <option value="1" {"selected" if grade == '1' else ""}>1학년</option>
                    <option value="2" {"selected" if grade == '2' else ""}>2학년</option>
                    <option value="3" {"selected" if grade == '3' else ""}>3학년</option>
                </select>
                <select id="class_nm" name="class_nm">
                    {"".join([f'<option value="{i}" {"selected" if class_nm == str(i) else ""}>{i}반</option>' for i in range(1, 8)])}
                </select>
                <input type="date" id="date_picker" name="date" value="{date_for_input}">
                <button type="submit">조회</button>
            </form>
            <hr class="main_hr">
        '''

        final_content = form_html + content

        return easy_minify(conn, flask.render_template(skin_check(conn),
            imp = ['시간표', await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
            data = final_content,
            menu = [['siganpyo', '오늘 시간표']]
        ))