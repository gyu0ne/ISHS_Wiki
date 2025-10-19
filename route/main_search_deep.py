# route/main_search_deep.py

async def main_search(name='Test', num=1):
    from .tool.func import (
        get_db_connect, redirect, url_pas, get_lang, easy_minify,
        wiki_set, wiki_custom, wiki_css, skin_check, db_change,
        get_next_page_bottom,
    )
    from .go_api_func_search import api_func_search
    import flask, html, re

    with get_db_connect() as conn:
        curs = conn.cursor()

        if name == '':
            return redirect(conn)

        div = '''
            <form method="post" action="/search_page/1/''' + url_pas(name) + '''"
                  onsubmit="event.preventDefault(); location.href='/search/' + encodeURIComponent(this.search.value);">
                <input class="opennamu_width_200" name="search" value="''' + html.escape(name) + '''">
                <button type="submit">''' + get_lang(conn, 'search') + '''</button>
            </form>
            <hr class="main_hr">
        '''

        div += '<a href="/w/' + url_pas(name) + '">(문서 생성하기)</a>'

        name_new = ''
        if re.search(r'^분류:', name):
            name_new = re.sub(r"^분류:", 'category:', name)
        elif re.search(r"^사용자:", name):
            name_new = re.sub(r"^사용자:", 'user:', name)
        elif re.search(r"^파일:", name):
            name_new = re.sub(r"^파일:", 'file:', name)
        if name_new != '':
            div += ' <a href="/search/' + url_pas(name_new) + '">(' + html.escape(name_new) + ')</a>'

        curs.execute(db_change("select title from data where title = ? collate nocase"), [name])
        link_id = '' if curs.fetchone() else 'class="opennamu_not_exist_link"'
        div += '''
            <ul>
                <li>''' + get_lang(conn, 'go') + ''' : <a ''' + link_id + ' href="/w/' + url_pas(name) + '">' + html.escape(name) + '''</a></li>
            </ul>
        '''

        title_list = await api_func_search(name, 'title', num)
        div += '<h2>문서명 검색 결과</h2><ul>'
        for t in title_list:
            div += '<li><a href="/w/' + url_pas(t) + '">' + html.escape(t) + '</a></li>'
        div += '</ul>'
        div += get_next_page_bottom(conn, '/search/{}/' + url_pas(name), num, title_list)

        div += '<hr class="main_hr">'

        data_list = await api_func_search(name, 'data', num)
        div += '<h2>문서내용 검색 결과</h2><ul>'
        for d in data_list:
            curs.execute(db_change("select 1 from data where title = ? collate nocase"), [d])
            if curs.fetchone():
                div += '<li><a href="/w/' + url_pas(d) + '">' + html.escape(d) + '</a></li>'
        div += '</ul>'
        div += get_next_page_bottom(conn, '/search/{}/' + url_pas(name), num, data_list)

        return easy_minify(conn, flask.render_template(
            skin_check(conn),
            imp=[name, await wiki_set(), await wiki_custom(conn), wiki_css(['(' + get_lang(conn, 'search') + ')', 0])],
            data=div,
            menu=0
        ))


async def main_search_deep(name='Test', search_type='title', num=1):
    from .tool.func import (
        get_db_connect, redirect, url_pas, get_lang, easy_minify,
        wiki_set, wiki_custom, wiki_css, skin_check, get_next_page_bottom,
        db_change,
    )
    from .go_api_func_search import api_func_search
    import flask, html, re

    with get_db_connect() as conn:
        curs = conn.cursor()

        if name == '':
            return redirect(conn)

        if flask.request.method == 'POST':
            query = flask.request.form.get('search', 'test')
            if search_type == 'title':
                return redirect(conn, '/search_page/1/' + url_pas(query))
            else:
                return redirect(conn, '/search_data_page/1/' + url_pas(query))

        div = '''
            <form method="post">
                <input class="opennamu_width_200" name="search" value="''' + html.escape(name) + '''">
                <button type="submit">''' + get_lang(conn, 'search') + '''</button>
            </form>
            <hr class="main_hr">
        '''

        if search_type == 'title':
            div += '<a href="/w/' + url_pas(name) + '">(문서 생성하기)</a>'
        else:
            div += '<a href="/search_page/1/' + url_pas(name) + '">(' + get_lang(conn, 'search_document_name') + ')</a>'

        name_new = ''
        if re.search(r'^분류:', name):
            name_new = re.sub(r"^분류:", 'category:', name)
        elif re.search(r"^사용자:", name):
            name_new = re.sub(r"^사용자:", 'user:', name)
        elif re.search(r"^파일:", name):
            name_new = re.sub(r"^파일:", 'file:', name)
        if name_new != '':
            div += ' <a href="/search_page/1/' + url_pas(name_new) + '">(' + html.escape(name_new) + ')</a>'

        curs.execute(db_change("select title from data where title = ? collate nocase"), [name])
        link_id = '' if curs.fetchone() else 'class="opennamu_not_exist_link"'
        div += '''
            <ul>
                <li>''' + get_lang(conn, 'go') + ''' : <a ''' + link_id + ' href="/w/' + url_pas(name) + '">' + html.escape(name) + '''</a></li>
            </ul>
        '''

        if search_type == 'title':
            title_list = await api_func_search(name, 'title', num)
            div += '<h2>문서명 검색 결과</h2><ul>'
            for t in title_list:
                div += '<li><a href="/w/' + url_pas(t) + '">' + html.escape(t) + '</a></li>'
            div += '</ul>'
            div += get_next_page_bottom(conn, '/search_page/{}/' + url_pas(name), num, title_list)

            div += '<hr class="main_hr">'

            data_list = await api_func_search(name, 'data', num)
            div += '<h2>문서내용 검색 결과</h2><ul>'
            for d in data_list:
                curs.execute(db_change("select 1 from data where title = ? collate nocase"), [d])
                if curs.fetchone():
                    div += '<li><a href="/w/' + url_pas(d) + '">' + html.escape(d) + '</a></li>'
            div += '</ul>'
            div += get_next_page_bottom(conn, '/search_page/{}/' + url_pas(name), num, data_list)
        else:
            all_list = await api_func_search(name, 'data', num)
            div += '<ul>'
            for data in all_list:
                div += '<li><a href="/w/' + url_pas(data) + '">' + html.escape(data) + '</a></li>'
            div += '</ul>'
            div += get_next_page_bottom(conn, '/search_data_page/{}/' + url_pas(name), num, all_list)

        return easy_minify(conn, flask.render_template(
            skin_check(conn),
            imp=[name, await wiki_set(), await wiki_custom(conn), wiki_css(['(' + get_lang(conn, 'search') + ')', 0])],
            data=div,
            menu=0
        ))
