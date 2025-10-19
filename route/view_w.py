from .tool.func import *
import html
import re

from .go_api_w_raw import api_w_raw
from .go_api_w_render import api_w_render
from .go_api_w_page_view import api_w_page_view

def _recent_changes_sidebar_html(conn, limit=10):
    c = conn.cursor()
    # rc(최근변경 인덱스)에서 최신 id를 가져오고 history에서 상세를 합친다
    c.execute(db_change('select title, id from rc where type = ? order by date desc limit ?'), ['normal', limit])
    items = []
    for title, hid in c.fetchall():
        c.execute(db_change('select id, title, date, ip, send, leng, hide, type from history where title = ? and id = ?'), [title, hid])
        row = c.fetchone()
        if not row:
            continue
        _id, _title, _date, _ip, _msg, _len, _hide, _type = row
        # (여기서 원래는 날짜·증감·r1 같은 텍스트를 합쳐서 items.append(...) 하던 로직이 있음)
        # ...
    return '<ul class="opennamu_recent_change">' + ''.join(items) + '</ul>'


def _recent_changes_sidebar_simple_html(conn, limit=10):
    """
    최근 변경 '사이드바용' 확장 버전:
    문서명 + r번호 + 글자수 증감(녹색/빨강)
    """
    c = conn.cursor()
    c.execute(db_change('select title, id from rc where type = ? order by date desc limit ?'), ['normal', limit])
    items = []
    for title, hid in c.fetchall():
        # history 정보 불러오기
        c.execute(db_change('select id, title, date, ip, send, leng, hide, type from history where title = ? and id = ?'),
                  [title, hid])
        row = c.fetchone()
        if not row:
            continue
        _id, _title, _date, _ip, _msg, _len, _hide, _type = row

        # 글자수 증감 색상
        if re.search(r'\+', _len):
            len_html = f'<span style="color:green;">({_len})</span>'
        elif re.search(r'-', _len):
            len_html = f'<span style="color:red;">({_len})</span>'
        else:
            len_html = f'<span style="color:gray;">({_len})</span>'

        # r번호 링크
        if int(_id) < 2:
            r_link = f'<a href="/history/{url_pas(_title)}">(r{_id})</a>'
        else:
            r_link = f'<a href="/diff/{int(_id)-1}/{_id}/{url_pas(_title)}">(r{_id})</a>'

        safe_title = html.escape(_title)
        items.append(f'<li><a href="/w/{url_pas(_title)}">{safe_title}</a> {r_link} {len_html}</li>')

    return '<ul class="opennamu_recent_change">' + ''.join(items) + '</ul>'




def _get_user_profile_table_html(conn, user_id: str) -> str:
    """
    user_set 테이블에서 user_id의 프로필을 읽어 안전한 HTML 표로 반환.
    값 없으면 '-' 처리. DB 조회에는 raw user_id를 사용한다.
    """
    c = conn.cursor()

    def _get(name: str) -> str:
        c.execute(db_change("select data from user_set where id = ? and name = ?"), [user_id, name])
        row = c.fetchone()
        return (row[0] or '').strip() if row and row[0] is not None else ''

    student_id = _get('student_id') or '졸업생'
    real_name  = _get('real_name')
    by = _get('birth_year')
    bm = _get('birth_month')
    bd = _get('birth_day')
    gender     = _get('gender')
    generation = _get('generation')
    acl_val    = (_get('acl') or 'user').lower()

    # 생년월일 조합
    if (by or '').isdigit() and (bm or '').isdigit() and (bd or '').isdigit():
        birth_str = f"{by}-{bm.zfill(2)}-{bd.zfill(2)}"
    else:
        birth_str = '-'

    # 성별/권한 표기
    gender_kr = '남성' if gender == 'male' else ('여성' if gender == 'female' else '-')
    acl_kr_map = {'owner': '운영자', 'admin': '관리자', 'user': '일반'}
    acl_kr = acl_kr_map.get(acl_val, acl_val)

    # 이스케이프
    sid = html.escape(student_id or '-')
    rnm = html.escape(real_name  or '-')
    bth = html.escape(birth_str)
    gen = html.escape(generation or '-')
    aclh = html.escape(acl_kr or '-')

    return f"""
    <div class="opennamu-user-profile">
      <h2>사용자 정보</h2>
      <table class="user-info" style="width:100%; max-width:720px;">
        <tr><th style="text-align:left; width:120px;">학번</th><td>{sid}</td></tr>
        <tr><th style="text-align:left;">이름</th><td>{rnm}</td></tr>
        <tr><th style="text-align:left;">생년월일</th><td>{bth}</td></tr>
        <tr><th style="text-align:left;">성별</th><td>{gender_kr}</td></tr>
        <tr><th style="text-align:left;">기수</th><td>{gen}</td></tr>
        <tr><th style="text-align:left;">권한</th><td>{aclh}</td></tr>
      </table>
      <hr class="main_hr">
    </div>
    """


async def view_w(name = '대문', do_type = ''):
    with get_db_connect() as conn:
        curs = conn.cursor()

        sub = 0
        history_color = 0
        menu = []

        user_doc = ''
        category_total = ''
        file_data = ''

        doc_type = ''
        redirect_to = None

        now_time = get_time()
        ip = ip_check()

        # 특정 틀 포함 시 비로그인 사용자 접근 제한
        doc_data_raw = await api_w_raw(name)
        if doc_data_raw["response"] == "ok" and '[include(틀:인곽위키/인물)]' in doc_data_raw["data"]:
            if ip_or_user(ip) == 1:
                return await re_error(conn, 1)
            
        # ★ user: 문서도 비로그인 접근 제한 (프로필 표 포함 페이지)
        if re.search(r"^user:([^/]*)", name):
            if ip_or_user(ip) == 1:
                return await re_error(conn, 1)
            
            
        uppage = re.sub(r"/([^/]+)$", '', name)
        uppage = 0 if uppage == name else uppage

        curs.execute(db_change("select sub from rd where title = ? and not stop = 'O' order by date desc"), [name])
        topic = 1 if curs.fetchall() else 0

        curs.execute(db_change("select title from data where title like ?"), [name + '/%'])
        down = 1 if curs.fetchall() else 0

        if re.search(r'^category:', name):
            name_view = name
            doc_type = 'category'

            category_doc = ''
            category_sub = ''

            count_sub_category = 0
            count_category = 0

            curs.execute(db_change("select distinct link from back where title = ? and type = 'cat' order by link asc"), [name])
            category_sql = curs.fetchall()
            for data in category_sql:
                link_view = data[0]
                if get_main_skin_set(conn, flask.session, 'main_css_category_change_title', ip) != 'off':
                    curs.execute(db_change("select data from back where title = ? and link = ? and type = 'cat_view' limit 1"), [name, data[0]])
                    db_data = curs.fetchall()
                    if db_data and db_data[0][0] != '':
                        link_view = db_data[0][0]
                        
                link_blur = ''
                curs.execute(db_change("select data from back where title = ? and link = ? and type = 'cat_blur' limit 1"), [name, data[0]])
                db_data = curs.fetchall()
                if db_data:
                    link_blur = 'opennamu_category_blur'

                if data[0].startswith('category:'):
                    category_sub += '<li><a class="' + link_blur + '" href="/w/' + url_pas(data[0]) + '">' + html.escape(link_view) + '</a></li>'
                    count_sub_category += 1
                else:
                    category_doc += '' + \
                        '<li>' + \
                            '<a class="' + link_blur + '" href="/w/' + url_pas(data[0]) + '">' + html.escape(link_view) + '</a> ' + \
                            '<a class="opennamu_link_inter" href="/xref/' + url_pas(data[0]) + '">(' + get_lang(conn, 'backlink') + ')</a>' + \
                        '</li>' + \
                    ''
                    count_category += 1

            if category_sub != '':
                category_total += '' + \
                    '<h2 id="cate_under">' + get_lang(conn, 'under_category') + '</h2>' + \
                    '<ul>' + \
                        '<li>' + get_lang(conn, 'all') + ' : ' + str(count_sub_category) + '</li>' + \
                        category_sub + \
                    '</ul>' + \
                ''

            if category_doc != '':
                category_total += '' + \
                    '<h2 id="cate_normal">' + get_lang(conn, 'category_title') + '</h2>' + \
                    '<ul>' + \
                        '<li>' + get_lang(conn, 'all') + ' : ' + str(count_category) + '</li>' + \
                        category_doc + \
                    '</ul>' + \
                ''
        elif re.search(r"^user:([^/]*)", name):
            name_view = name
            doc_type = 'user'
            user_name = ''
            raw_user_name = ''   # DB 조회용
            esc_user_name = ''   # 출력용

            match = re.search(r"^user:([^/]*)", name)
            if match:
                raw_user_name = match.group(1).strip()
                esc_user_name = html.escape(raw_user_name)
                user_name = esc_user_name   # 나머지 기존 로직과 호환을 위해 유지
            
            user_doc = ''

            # ★ 프로필 표: 본문 맨 위에 주입
            try:
                if raw_user_name:
                    user_doc += _get_user_profile_table_html(conn, raw_user_name)
            except Exception as e:
                print(f"USER PROFILE RENDER ERROR for {raw_user_name}: {e}")

            # S admin or owner 특수 틀 추가
            if await acl_check(tool = 'all_admin_auth', ip = user_name) != 1:
                if await acl_check(tool = 'owner_auth', ip = user_name) != 1:
                    curs.execute(db_change('select data from other where name = "phrase_user_page_owner"'))
                    db_data = curs.fetchall()
                    if db_data and db_data[0][0] != '':
                        user_doc += db_data[0][0] + '<br>'
                    else:
                        curs.execute(db_change('select data from other where name = "phrase_user_page_admin"'))
                        db_data = curs.fetchall()
                        if db_data and db_data[0][0] != '':
                            user_doc += db_data[0][0] + '<br>'
                else:
                    curs.execute(db_change('select data from other where name = "phrase_user_page_admin"'))
                    db_data = curs.fetchall()
                    if db_data and db_data[0][0] != '':
                        user_doc += db_data[0][0] + '<br>'
            # E

            # (중요) 기존의 작은 "사용자 이름/권한/상태/레벨" 박스를 띄우던 블록을 제거했습니다.
            # user_doc += '''
            #     <div id="opennamu_get_user_info">''' + esc_user_name + '''</div>
            #     <hr class="main_hr">
            # '''

        elif re.search(r"^file:", name):
            curs.execute(db_change('select id from history where title = ? order by date desc limit 1'), [name])
            db_data = curs.fetchall()
            rev = db_data[0][0] if db_data else '1' 

            name_view = name
            doc_type = 'file'

            mime_type = re.search(r'([^.]+)$', name)
            if mime_type:
                mime_type = mime_type.group(1)
            else:
                mime_type = 'jpg'

            file_name = re.sub(r'\.([^.]+)$', '', name)
            file_name = re.sub(r'^file:', '', file_name)

            file_all_name = sha224_replace(file_name) + '.' + mime_type
            file_path_name = os.path.join(load_image_url(conn), file_all_name)
            if os.path.exists(file_path_name):
                try:
                    img = Image.open(file_path_name)
                    width, height = img.size
                    file_res = str(width) + 'x' + str(height)
                except:
                    file_res = 'Vector'
                
                file_size = str(round(os.path.getsize(file_path_name) / 1000, 1))
                
                file_data = '''
                    <img src="/image/''' + url_pas(file_all_name) + '''.cache_v''' + rev + '''">
                    <h2>''' + get_lang(conn, 'data') + '''</h2>
                    <table>
                        <tr><td>''' + get_lang(conn, 'url') + '''</td><td><a href="/image/''' + url_pas(file_all_name) + '''">''' + get_lang(conn, 'link') + '''</a></td></tr>
                        <tr><td>''' + get_lang(conn, 'volume') + '''</td><td>''' + file_size + '''KB</td></tr>
                        <tr><td>''' + get_lang(conn, 'resolution') + '''</td><td>''' + file_res + '''</td></tr>
                    </table>
                    <h2>''' + get_lang(conn, 'content') + '''</h2>
                '''

                menu += [['delete_file/' + url_pas(name), get_lang(conn, 'file_delete')]]
            else:
                file_data = ''
        else:
            curs.execute(db_change("select link from back where title = ? and type = 'include' limit 1"), [name])
            doc_type = 'include' if curs.fetchall() else doc_type

            curs.execute(db_change("select title, data from back where link = ? and type = 'redirect' limit 1"), [name])
            db_data = curs.fetchall()
            if db_data:
                doc_type = 'redirect'

                curs.execute(db_change("select title from data where title = ?"), [db_data[0][0]])
                if curs.fetchall():
                    redirect_to = url_pas(db_data[0][0]) + db_data[0][1]

            name_view = name

        doc_data = await api_w_raw(name)
        if doc_data["response"] == "ok":
            render_data = await api_w_render(name, request_method = 'POST', request_data = {
                'name' : name,
                'data' : doc_data["data"]
            })
            # 글자크기
            end_data = (
                '<div class="article-scale" style="font-size: 1.16em;">'
                + render_data["data"] +
                '</div>'
                + '<script>document.addEventListener("DOMContentLoaded", function() {'
                + render_data["js_data"] +
                '});</script>'
            )
        else:
            end_data = ''

        asyncio.create_task(api_w_page_view(name))

        curs.execute(db_change("select data from data where title = ?"), [name])
        data = curs.fetchall()

        description = ''
        if await acl_check(name, 'render') == 1:
            response_data = 401

            curs.execute(db_change('select data from other where name = "error_401"'))
            sql_d = curs.fetchall()
            if sql_d and sql_d[0][0] != '':
                end_data = '<h2>' + get_lang(conn, 'error') + '</h2><ul><li>' + sql_d[0][0] + '</li></ul>'
            else:
                end_data = '<h2>' + get_lang(conn, 'error') + '</h2><ul><li>' + get_lang(conn, 'authority_error') + '</li></ul>'
        elif not data:
            response_data = 404

            curs.execute(db_change('select data from other where name = "error_404"'))
            db_data = curs.fetchall()
            if db_data and db_data[0][0] != '':
                end_data = '<h2>' + get_lang(conn, 'error') + '</h2><ul><li>' + db_data[0][0] + '</li></ul>'
            else:
                end_data = '<h2>' + get_lang(conn, 'error') + '</h2><ul><li>' + get_lang(conn, 'decument_404_error') + '</li></ul>'

            curs.execute(db_change('select ip from history where title = ? limit 1'), [name])
            db_data = curs.fetchall()
            history_color = 1 if db_data else 0
        else:
            response_data = 200
            description = data[0][0].replace('\r', '').replace('\n', ' ')[0:200]

        curs.execute(db_change("select title from acl where title = ?"), [name])
        acl = 1 if curs.fetchall() else 0
        menu_acl = 1 if await acl_check(name, 'document_edit') == 1 else 0
        if response_data == 404:
            menu += [['edit/' + url_pas(name), get_lang(conn, 'create'), menu_acl]] 
        else:
            menu += [['edit/' + url_pas(name), get_lang(conn, 'edit'), menu_acl]]

        menu += [
            ['topic/' + url_pas(name), get_lang(conn, 'discussion'), topic], 
            ['history/' + url_pas(name), get_lang(conn, 'history'), history_color], 
            ['xref/' + url_pas(name), get_lang(conn, 'backlink')], 
            ['acl/' + url_pas(name), get_lang(conn, 'setting'), acl],
        ]

        if flask.session and 'lastest_document' in flask.session:
            if type(flask.session['lastest_document']) != type([]):
                flask.session['lastest_document'] = []
        else:
            flask.session['lastest_document'] = []

        if do_type == 'from':
            menu += [['w/' + url_pas(name), get_lang(conn, 'pass')]]
            
            last_page = ''
            for for_a in reversed(range(0, len(flask.session['lastest_document']))):
                last_page = flask.session['lastest_document'][for_a]

                curs.execute(db_change("select link from back where (title = ? or link = ?) and type = 'redirect' limit 1"), [last_page, last_page])
                if curs.fetchall():
                    break

            if last_page != name:
                redirect_text = '{0} ➤ {1}'

                curs.execute(db_change('select data from other where name = "redirect_text"'))
                db_data = curs.fetchall()
                if db_data and db_data[0][0] != '':
                    redirect_text = db_data[0][0]

                try:
                    redirect_text = redirect_text.format('<a href="/w_from/' + url_pas(last_page) + '">' + html.escape(last_page) + '</a>', '<b>' + html.escape(name) + '</b>')
                except:
                    redirect_text = '{0} ➤ {1}'
                    redirect_text = redirect_text.format('<a href="/w_from/' + url_pas(last_page) + '">' + html.escape(last_page) + '</a>', '<b>' + html.escape(name) + '</b>')

                end_data = '''
                    <div class="opennamu_redirect" id="redirect">
                        ''' + redirect_text + '''
                    </div>
                    <hr class="main_hr">
                ''' + end_data
                
        if len(flask.session['lastest_document']) >= 10:
            flask.session['lastest_document'] = flask.session['lastest_document'][-9:] + [name]
        else:
            flask.session['lastest_document'] += [name]
        
        flask.session['lastest_document'] = list(reversed(dict.fromkeys(reversed(flask.session['lastest_document']))))

        if redirect_to and do_type != 'from':
            return redirect(conn, '/w_from/' + redirect_to)

        view_history_on = get_main_skin_set(conn, flask.session, 'main_css_view_history', ip)
        if view_history_on == 'on':
            end_data = '' + \
                '<div class="opennamu_trace">' + \
                    '<a class="opennamu_trace_button" href="javascript:opennamu_do_trace_spread();"> (+)</a>' + \
                    get_lang(conn, 'trace') + ' : ' + \
                    ' ← '.join(
                        [
                            '<a href="/w/' + url_pas(for_a) + '">' + html.escape(for_a) + '</a>'
                            for for_a in reversed(flask.session['lastest_document'])
                        ]
                    ) + \
                '</div>' + \
                '<hr class="main_hr">' + \
            '' + end_data

        if uppage != 0:
            menu += [['w/' + url_pas(uppage), get_lang(conn, 'upper')]]

        if down:
            menu += [['down/' + url_pas(name), get_lang(conn, 'sub')]]

        curs.execute(db_change("select set_data from data_set where doc_name = ? and set_name = 'last_edit'"), [name])
        r_date = curs.fetchall()
        r_date = r_date[0][0] if r_date else 0

        curs.execute(db_change("select data from other where name = 'not_use_view_count'"))
        view_count_set = curs.fetchall()
        if view_count_set and view_count_set[0][0] != "":
            view_count = 0
        else:
            curs.execute(db_change("select set_data from data_set where doc_name = ? and set_name = 'view_count' and doc_rev = ''"), [name])
            view_count = curs.fetchall()
            view_count = view_count[0][0] if view_count else 0

        ad_banner = '''
        <div style="text-align:center; margin: 40px 0;">
            <a href="https://forms.gle/5FmWoxERVCw9hEbo8" target="_blank" rel="noopener noreferrer">
                <img src="/image/ad1.png" alt="ad1" style="max-width:90%; height:auto; border-radius:12px; box-shadow:0 4px 12px rgba(0,0,0,0.2); transition:transform 0.2s;">
            </a>
        </div>
        <hr class="main_hr">
        '''
        div = file_data + user_doc + ad_banner + end_data + category_total
         
        if doc_type == '':
            curs.execute(db_change('select data from other where name = "outdated_doc_warning_date"'))
            db_data = curs.fetchall()
            if db_data and db_data[0][0] != '' and r_date != 0:
                time_1 = datetime.datetime.strptime(r_date, '%Y-%m-%d %H:%M:%S') + datetime.timedelta(days = int(number_check(db_data[0][0])))
                time_2 = datetime.datetime.strptime(now_time, '%Y-%m-%d %H:%M:%S')
                if time_2 > time_1:
                    curs.execute(db_change('select data from other where name = "outdated_doc_warning"'))
                    db_data = curs.fetchall()
                    div = (db_data[0][0] if db_data and db_data[0][0] != '' else get_lang(conn, 'old_page_warning')) + '<hr class="main_hr">' + div


        curs.execute(db_change("select data from other where name = 'body'"))
        body = curs.fetchall()
        div = (body[0][0] + div) if body else div

        curs.execute(db_change("select data from other where name = 'bottom_body'"))
        body = curs.fetchall()
        div += body[0][0] if body else ''

        curs.execute(db_change("select set_data from data_set where doc_name = ? and set_name = 'document_top'"), [name])
        body = curs.fetchall()
        div = (body[0][0] + div) if body else div

        # ★ 편집 옆 별 버튼 (항상 표시 / 비로그인은 로그인으로, 로그인은 토글로)
        logged_in = (ip_or_user(ip) == 0)

        # 이 문서를 별표한 전체 사용자 수
        curs.execute(db_change(
            "select count(*) from user_set "
            "where (name = 'star_doc' or name = 'star_doc_from') and data = ?"
        ), [name])
        row = curs.fetchone()
        star_count = row[0] if row and row[0] else 0

        # 내 별 여부 (로그인일 때만 확인)
        if logged_in:
            curs.execute(db_change("select 1 from user_set where id = ? and data = ? limit 1"), [ip, name])
            is_starred = True if curs.fetchone() else False
        else:
            is_starred = False

        star_symbol = '★' if is_starred else '☆'
        star_label  = f"{star_symbol} {star_count}"
        star_href   = ('star_doc_from/' + url_pas(name)) if logged_in else 'login'

        menu.insert(0, [star_href, star_label, 1])





        # 기존 주시 목록 관련 메뉴 제거 (아래 두 줄 삭제)
        # menu += [['star_doc_from/' + url_pas(name), ('☆' if watch_list == 1 else '★'), watch_list - 1]]
        # menu += [['doc_watch_list/1/' + url_pas(name), get_lang(conn, 'watchlist')]]

        try:
            recent_sidebar = _recent_changes_sidebar_simple_html(conn, limit = 10)
        except Exception as e:
            print(f"RECENT SIDEBAR ERROR: {e}")
            recent_sidebar = ''  # ← 빈 문자열
        # 로그인 O: 2(별표됨) / 1(별표안됨), 로그인 X: 0
        if logged_in:
            watch_list = 2 if is_starred else 1
        else:
            watch_list = 0
        return easy_minify(conn, flask.render_template(
            skin_check(conn),
            imp = [
                name_view,
                await wiki_set(),
                await wiki_custom(conn),
                wiki_css([sub, r_date, watch_list, description, view_count])
            ],
            data = div,
            menu = menu,
            recent_sidebar = recent_sidebar
        )), response_data
