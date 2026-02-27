from .tool.func import *
import traceback as _tb

async def api_move_multiple():
    with get_db_connect() as conn:
        curs = conn.cursor()

        # 권한 확인
        if await acl_check('', 'document_move') == 1:
            return flask.jsonify({'result': 'error', 'msg': 'no_auth'})

        if flask.request.method != 'POST':
            return flask.jsonify({'result': 'error', 'msg': 'method_not_allowed'})

        try:
            req = flask.request.get_json(force=True)
        except Exception:
            return flask.jsonify({'result': 'error', 'msg': 'invalid_json'})

        titles   = req.get('titles', [])
        from_text = req.get('from', '')
        to_text   = req.get('to', '')
        send      = req.get('send', '')

        if not titles or not from_text:
            return flask.jsonify({'result': 'error', 'msg': 'missing_params'})

        cur_time = get_time()
        ip = ip_check()
        results = []

        for name in titles:
            name = name.strip()
            if not name:
                continue

            # ── 루프 전체를 하나의 try로 감싼다 ─────────────────────────────
            try:
                move_title = name.replace(from_text, to_text, 1)

                if move_title == name:
                    results.append({'title': name, 'result': 'skip', 'msg': 'no_change'})
                    continue

                if await acl_check(name, 'document_move') == 1:
                    results.append({'title': name, 'result': 'error', 'msg': 'no_auth'})
                    continue

                # 대상 문서 존재 여부
                curs.execute(db_change("select title from history where title = ? limit 1"), [move_title])
                target_exists = bool(curs.fetchall())

                # 원본 문서 존재 여부
                curs.execute(db_change("select title from history where title = ? limit 1"), [name])
                if not curs.fetchall():
                    results.append({'title': name, 'result': 'error', 'msg': 'not_found'})
                    continue

                if target_exists:
                    # ── 바꿔치기(swap) ────────────────────────────────────────
                    # 스왑 전 양쪽 데이터 미리 저장
                    curs.execute(db_change("select data from data where title = ?"), [name])
                    d = curs.fetchall()
                    data_in_name = d[0][0] if d else ''

                    curs.execute(db_change("select data from data where title = ?"), [move_title])
                    d = curs.fetchall()
                    data_in_target = d[0][0] if d else ''

                    # 임시 제목 생성 (edit_move.py 와 동일 방식)
                    i = 0
                    temp_title = ''
                    while not temp_title:
                        candidate = 'test ' + load_random_key() + ' ' + str(i)
                        curs.execute(db_change("select title from history where title = ? limit 1"), [candidate])
                        if not curs.fetchall():
                            temp_title = candidate
                        else:
                            i += 1

                    # name→temp, move_title→name, temp→move_title
                    for src, dst in [(name, temp_title), (move_title, name), (temp_title, move_title)]:
                        curs.execute(db_change("update data    set title = ? where title = ?"), [dst, src])
                        curs.execute(db_change("update back    set link  = ? where link  = ?"), [dst, src])
                        curs.execute(db_change("update history set title = ? where title = ?"), [dst, src])
                        curs.execute(db_change("update rc      set title = ? where title = ?"), [dst, src])
                        curs.execute(db_change("update rd      set title = ? where title = ?"), [dst, src])

                    # 이동 기록 — 미리 저장한 data 사용
                    history_plus(conn, name,       data_in_target, cur_time, ip, send, '0',
                        t_check = '<a>' + name + '</a> ⇋ <a>' + move_title + '</a>', mode = 'move')
                    history_plus(conn, move_title, data_in_name,   cur_time, ip, send, '0',
                        t_check = '<a>' + move_title + '</a> ⇋ <a>' + name + '</a>', mode = 'move')

                    results.append({'title': name, 'result': 'swap', 'target': move_title})

                else:
                    # ── 일반 이동 ─────────────────────────────────────────────
                    curs.execute(db_change("select data from data where title = ?"), [name])
                    d = curs.fetchall()
                    data_in = d[0][0] if d else ''

                    curs.execute(db_change("update data    set title = ? where title = ?"), [move_title, name])
                    curs.execute(db_change("update back    set link  = ? where link  = ?"), [move_title, name])

                    curs.execute(db_change("select distinct link from back where title = ?"), [name])
                    backlink = [[r[0], name, 'no', ''] for r in curs.fetchall()]
                    curs.executemany(db_change("insert into back (link, title, type, data) values (?, ?, ?, ?)"), backlink)
                    curs.execute(db_change("delete from back where title = ? and type = 'no'"), [move_title])

                    curs.execute(db_change("update history set title = ? where title = ?"), [move_title, name])
                    curs.execute(db_change("update rc      set title = ? where title = ?"), [move_title, name])
                    curs.execute(db_change("update rd      set title = ? where title = ?"), [move_title, name])

                    history_plus(conn, move_title, data_in, cur_time, ip, send, '0',
                        t_check = '<a>' + name + '</a> → <a>' + move_title + '</a>', mode = 'move')

                    results.append({'title': name, 'result': 'ok', 'target': move_title})

            except Exception as e:
                err_msg = type(e).__name__ + ': ' + repr(e)
                print('[api_move_multiple] ERROR for "' + name + '":', err_msg, flush=True)
                print(_tb.format_exc(), flush=True)
                results.append({'title': name, 'result': 'error', 'msg': err_msg})

        return flask.jsonify({'result': 'ok', 'data': results})
