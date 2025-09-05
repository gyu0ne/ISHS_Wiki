from .tool.func import *
from .go_api_w_raw import api_w_raw

async def api_list_recent_change(num = 1, set_type = 'normal', limit = 10, legacy = 'on'):
    other_set = {}
    other_set["num"] = str(num)
    other_set["limit"] = str(limit)
    other_set["set_type"] = set_type
    other_set["legacy"] = legacy

    return await python_to_golang(sys._getframe().f_code.co_name, other_set)

async def api_list_recent_change_exter(num = 1, set_type = 'normal', limit = 10, legacy = 'on'):
    ip = ip_check()
    data = await api_list_recent_change(num, set_type, limit, legacy)

    if ip_or_user(ip) == 1:
        if "data" in data and data["data"] is not None:
            new_data = []
            for item in data["data"]:
                doc_name = item[0]
                doc_raw_data = await api_w_raw(doc_name)
                if doc_raw_data["response"] == "ok" and '[include(틀:인곽위키/인물)]' in doc_raw_data["data"]:
                    continue

                new_data.append(item)

            data["data"] = new_data

    response = flask.make_response(flask.jsonify(data))
    
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add('Access-Control-Allow-Headers', "Content-Type")
    response.headers.add('Access-Control-Allow-Methods', "GET")

    return response