from .tool.func import *

async def main_view_image(name = ''):
    with get_db_connect() as conn:
        if '..' in name or name.startswith(('/', '\\')):
            return await re_error(conn, 0)

        if await acl_check('', 'render') != 1:
            name = re.sub(r'\.cache_v(?:[0-9]+)$', '', name)
            mime_type = re.search(r'([^.]+)$', name)
            if mime_type:
                mime_type = mime_type.group(1).lower()
                if mime_type == 'svg':
                    mime_type = 'svg+xml'

                response = flask.send_from_directory('./' + load_image_url(conn), name, mimetype = 'image/' + mime_type)
                # SVG remains displayable as an image, but cannot run same-origin scripts.
                response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
                response.headers['X-Content-Type-Options'] = 'nosniff'
                return response
            else:
                return ''
        else:
            return await re_error(conn, 0)
