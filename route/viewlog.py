from .tool.func import *
import flask
import time
import html

ALLOW_NON_ADMIN_USER_VIEWLOG = False

def admin_check(conn):
    curs = conn.cursor()
    ip = ip_check()
    curs.execute(db_change("select data from user_set where id = ? and name = 'acl'"), [ip])
    user_acl = curs.fetchall()
    if not user_acl:
        return 0
    curs.execute(db_change("select acl from alist where name = ?"), [user_acl[0][0]])
    acl_data = curs.fetchall()
    if acl_data and acl_data[0][0] == 'owner':
        return 1
    return 0

def view_log_init(conn):
    curs = conn.cursor()
    try:
        curs.execute(db_change("select user_id from viewlog limit 1"))
    except:
        curs.execute(db_change("create table viewlog (user_id text, title text, date text, ip text)"))
        curs.execute(db_change("create index viewlog_index on viewlog (user_id)"))

    try:
        curs.execute(db_change("create index viewlog_date_index on viewlog (date)"))
    except:
        pass

    try:
        curs.execute(db_change("create index viewlog_user_date_index on viewlog (user_id, date)"))
    except:
        pass

    # 핵심 데이터 테이블 인덱스 자동 생성 (서버 가동 시 자동 최적화)
    try:
        curs.execute(db_change("create index if not exists data_index on data (title)"))
        curs.execute(db_change("create index if not exists back_index on back (title)"))
        curs.execute(db_change("create index if not exists back_link_index on back (link)"))
    except:
        pass

def check_view_log():
    if flask.request.path.startswith('/w/'):
        # 로그인 유무에 상관없이 수집
        if flask.session and 'id' in flask.session:
            user_id = flask.session['id']
        else:
            user_id = 'IP:' + ip_check()

        raw_title = flask.request.path[3:] 

        # 세션을 활용한 문서별 조회수 도배 방지 (최근 3개 문서 기억하여 DB 접근 차단)
        last_views = flask.session.get('last_viewed_docs', [])
        if raw_title in last_views:
            return
        
        last_views.append(raw_title)
        flask.session['last_viewed_docs'] = last_views[-3:]

        # 세션을 활용한 전체 조회수 도배 방지 (1초 연속 요청 무시)
        try:
            last_view_time = float(flask.session.get('last_view_time', 0))
        except:
            last_view_time = 0.0
            
        curr_time_sec = time.time()
        if curr_time_sec - last_view_time < 1:
            return
        flask.session['last_view_time'] = curr_time_sec

        with get_db_connect() as conn:
            curs = conn.cursor()
            
            curs.execute(db_change("select data from data where title = ?"), [raw_title])
            db_data = curs.fetchall()
            if not db_data:
                return
            
            content = db_data[0][0]
            
            if content.startswith('#redirect') or content.startswith('#넘겨주기'):
                return

            curs.execute(db_change("select title from viewlog where user_id = ? order by date desc limit 1"), [user_id])
            last_log = curs.fetchone()
            
            curr_time = get_time()
            ip = ip_check()

            if last_log and last_log[0] == raw_title:
                return

            curs.execute(db_change("insert into viewlog (user_id, title, date, ip) values (?, ?, ?, ?)"), [user_id, raw_title, curr_time, ip])
            conn.commit()

async def view_viewlog(name = None):
    with get_db_connect() as conn:
        curs = conn.cursor()

        if flask.session and 'id' in flask.session:
            my_user_id = flask.session['id']
        else:
            return redirect(conn, '/login')

        is_admin = (admin_check(conn) == 1)

        if name is None:
            target_user = my_user_id
        else:
            if not is_admin and not ALLOW_NON_ADMIN_USER_VIEWLOG:
                return await re_error(conn, 3)
            target_user = name

        num = int(number_check(flask.request.args.get('num', '1')))
        sql_num = (num * 50 - 50) if num * 50 - 50 >= 0 else 0

        div = '<ul class="opennamu_ul">'
        
        curs.execute(db_change("select title, date, ip from viewlog where user_id = ? order by date desc limit ?, 50"), [target_user, sql_num])
        data_list = curs.fetchall()

        for data in data_list:
            title = data[0]
            date = data[1]
            log_ip = data[2]
            
            # '문서 ACL 설정' 항목 제외
            if title == '문서 ACL 설정':
                continue
            
            # 사용자명(IP) 표시 제거
            div += f'<li>{date} | <a href="/w/{url_pas(title)}">{html.escape(title)}</a></li>'

        div += '</ul>'
        
        div += get_next_page_bottom(conn, '/viewlog' + ('/' + url_pas(target_user) if name else '') + '?num={}', num, data_list)

        title_html = '열람 기록'
        if name:
            title_html = f'열람 기록({name})'

        return easy_minify(conn, flask.render_template(skin_check(conn),
            imp = [title_html, await wiki_set(), await wiki_custom(conn), wiki_css(['', 0, '', '', '', '', '', 0])],
            data = div,
            menu = []
        ))
