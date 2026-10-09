from .tool.func import *

async def api_func_search(name = 'Test', search_type = 'title', num = 1):
    # Matching hidden document contents is itself an information oracle.
    # The Go search endpoint enforces its canonical ACL in the same IPC call.
    if search_type != 'title' and ip_or_user(ip_check()) == 1:
        return []
    other_set = {}
    other_set["name"] = name
    other_set["search_type"] = search_type
    other_set["num"] = str(num)

    return await python_to_golang(sys._getframe().f_code.co_name, other_set)

async def api_func_search_exter(name = 'Test', search_type = 'title', num = 1):
    return flask.jsonify(await api_func_search(name, search_type, num))
