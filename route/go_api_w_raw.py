from .tool.func import *

async def api_w_raw(name = 'Test', rev = '', exist_check = ''):
    other_set = {}
    other_set["name"] = name
    other_set["rev"] = str(rev)
    other_set["exist_check"] = exist_check

    data = await python_to_golang(sys._getframe().f_code.co_name, other_set)
    cache_view_context(data, ip_check())
    if isinstance(data, dict):
        data.pop('view_context', None)
    if (ip_or_user(ip_check()) == 1 and isinstance(data, dict)
            and data.get('response') == 'ok' and is_person_document(name, data.get('data', ''))):
        return {'response': 'require auth'}
    return data

async def api_w_raw_exter(name = 'Test', rev = '', exist_check = ''):
    return flask.jsonify(await api_w_raw(name, rev, exist_check))
