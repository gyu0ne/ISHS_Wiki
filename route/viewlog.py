from .tool.func import *
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

def check_view_log():
    if flask.request.path.startswith('/w/'):
        if flask.session and 'id' in flask.session:
            user_id = flask.session['id']
            raw_title = flask.request.path[3:] 

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
            
            ip_html = ''
            if is_admin:
                ip_html = f' <span style="font-size: 0.8em; color: gray;">({log_ip})</span>'

            div += f'<li>{date} | <a href="/w/{url_pas(title)}">{html.escape(title)}</a>{ip_html}</li>'

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
