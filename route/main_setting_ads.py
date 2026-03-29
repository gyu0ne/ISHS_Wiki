from .tool.func import *

async def main_setting_ads():
    with get_db_connect() as conn:
        curs = conn.cursor()

        if flask.request.method == 'POST':
            if await acl_check(tool = 'owner_auth') == 1:
                return await re_error(conn, 3)

            curs.execute(db_change("select name from other where name = 'ads_list'"))
            if curs.fetchall():
                curs.execute(db_change("update other set data = ? where name = 'ads_list'"), [flask.request.form.get('content', '')])
            else:
                curs.execute(db_change("insert into other (name, data, coverage) values ('ads_list', ?, '')"), [flask.request.form.get('content', '')])

            return redirect(conn, '/setting/ads')
        else:
            curs.execute(db_change("select data from other where name = 'ads_list'"))
            db_data = curs.fetchall()
            if db_data:
                data = db_data[0][0]
            else:
                # 기본값 설정
                data = '/image/ad1.png | /'
                curs.execute(db_change("insert into other (name, data, coverage) values ('ads_list', ?, '')"), [data])

            return easy_minify(conn, flask.render_template(skin_check(conn),
                imp = ['광고 관리', await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
                data = '''
                    <form method="post">
                        <textarea class="opennamu_textarea_500" name="content">''' + html.escape(data) + '''</textarea>
                        <hr class="main_hr">
                        <span>''' + get_lang(conn, 'format') + ''' : 이미지주소 | 링크주소 (한 줄에 하나씩)</span>
                        <hr class="main_hr">
                        <button type="submit">''' + get_lang(conn, 'save') + '''</button>
                    </form>
                ''',
                menu = [['setting', get_lang(conn, 'return')]]
            ))
