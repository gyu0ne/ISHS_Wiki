from .tool.func import *

async def login_logout():
    with get_db_connect() as conn:
        curs = conn.cursor()
        
        user_id = flask.session.get('id')
        if user_id:
            try:
                curs.execute(db_change("DELETE FROM login_token WHERE user_id = ?"), [user_id])
            except:
                pass

        flask.session.pop('state', None)
        flask.session.pop('id', None)
        flask.session.pop('user_name', None)

        resp = flask.make_response(redirect(conn, '/user'))
        resp.set_cookie('auto_login', '', expires=0)

        return resp