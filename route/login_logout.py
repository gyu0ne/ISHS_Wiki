from .tool.func import *
from .tool.auth_state import clear_logout_state

async def login_logout():
    with get_db_connect() as conn:
        curs = conn.cursor()
        
        user_id = flask.session.get('id')
        if user_id:
            token_cookie = flask.request.cookies.get('auto_login')
            if token_cookie:
                try:
                    _, token = token_cookie.split(':', 1)
                except ValueError:
                    token = None
                if token:
                    import hashlib
                    hashed_token = hashlib.sha256(token.encode('utf-8')).hexdigest()
                    curs.execute(db_change("DELETE FROM login_token WHERE user_id = ? AND token = ?"), [user_id, hashed_token])

        clear_logout_state(flask.session)

        resp = flask.make_response(redirect(conn, '/user'))
        resp.set_cookie('auto_login', '', expires=0)

        return resp
