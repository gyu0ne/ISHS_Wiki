from .tool.func import *

async def main_search():
    with get_db_connect() as conn:
        curs = conn.cursor()
        
        search_query = flask.request.form.get('search', 'test')
        
        # 완전 일치하는 문서가 있으면 바로 해당 문서로 이동
        curs.execute(db_change("select title from data where title = ? collate nocase"), [search_query])
        db_data = curs.fetchone()
        if db_data:
            return redirect(conn, '/w/' + url_pas(db_data[0]))
        
        return redirect(conn, '/search/' + url_pas(search_query))