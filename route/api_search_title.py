from .tool.func import *

async def api_search_title(name = ''):
    with get_db_connect() as conn:
        curs = conn.cursor()

        if name == '':
            return flask.jsonify([])

        curs.execute(db_change("select title from data where title like ? collate nocase limit 10"), [name + '%'])
        db_data = curs.fetchall()
        
        return flask.jsonify([for_a[0] for for_a in db_data])