from .tool.func import *
import requests
import datetime

async def bob(date = ''):
    with get_db_connect() as conn:
        if date == '':
            date = (datetime.datetime.now()).strftime('%Y%m%d')

        try:
            date_for_input = datetime.datetime.strptime(date, '%Y%m%d').strftime('%Y-%m-%d')
        except ValueError:
            date = (datetime.datetime.now()).strftime('%Y%m%d')
            date_for_input = datetime.datetime.strptime(date, '%Y%m%d').strftime('%Y-%m-%d')

        datepicker_html = f'''
            <form onsubmit="window.location.href = '/bob/' + document.getElementById('date_picker').value.replace(/-/g, ''); return false;">
                <input type="date" id="date_picker" name="date" value="{date_for_input}">
                <button type="submit">조회</button>
            </form>
            <hr class="main_hr">
        '''

        url = (
            "https://open.neis.go.kr/hub/mealServiceDietInfo"
            "?KEY=75f40bb14ddd41d1b5ecda3389258cb1"
            "&TYPE=JSON"
            "&ATPT_OFCDC_SC_CODE=E10"
            "&SD_SCHUL_CODE=7310058"
            f"&MLSV_YMD={date}"
            f"&"
        )

        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()

            try:
                meals = data['mealServiceDietInfo'][1]['row']
                meal_names = {
                    '1': '아침',
                    '2': '점심',
                    '3': '저녁'
                }

                result = [f"{date[0:4]}년 {date[4:6]}월 {date[6:8]}일 급식 정보:"]
                for meal in meals:
                    meal_type = meal_names.get(meal['MMEAL_SC_CODE'], '기타')
                    menu = html.escape(meal['DDISH_NM']).replace('&lt;br/&gt;', '\n')

                    result.append(f"\n[{meal_type}]\n{menu}")
                content = "\n".join(result)

            except (KeyError, IndexError):
                content = f"{date[0:4]}년 {date[4:6]}월 {date[6:8]}일에는 급식 정보가 없습니다."
        else:
            content = f"API 호출 실패: {response.status_code}"

        content = content.replace('\n', '<br>')
        
        final_content = datepicker_html + content

        return easy_minify(conn, flask.render_template(skin_check(conn),
            imp = ['급식', await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
            data = final_content,
            menu = [['bob', '오늘 급식']]
        ))
