from .tool.func import *

async def api_search_title(name = ''):
    def get_chosung(text):
        CHOSUNGS = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']
        result = ''
        for char in text:
            if 0xAC00 <= ord(char) <= 0xD7A3:
                result += CHOSUNGS[(ord(char) - 0xAC00) // 588]
            else:
                result += char
        return result

    with get_db_connect() as conn:
        curs = conn.cursor()

        if name == '':
            return flask.jsonify([])

        # 한글 초성 검색 전용 매핑 (단일 초성 전용)
        chosung_map = {
            'ㄱ': ('가', '까'), 'ㄲ': ('까', '나'), 'ㄴ': ('나', '다'),
            'ㄷ': ('다', '따'), 'ㄸ': ('따', '라'), 'ㄹ': ('라', '마'),
            'ㅁ': ('마', '바'), 'ㅂ': ('바', '빠'), 'ㅃ': ('빠', '사'),
            'ㅅ': ('사', '싸'), 'ㅆ': ('싸', '아'), 'ㅇ': ('아', '자'),
            'ㅈ': ('자', '짜'), 'ㅉ': ('짜', '차'), 'ㅊ': ('차', '카'),
            'ㅋ': ('카', '타'), 'ㅌ': ('타', '파'), 'ㅍ': ('파', '하'),
            'ㅎ': ('하', '힣')
        }

        # 모든 글자가 초성인지 확인 (ㅇㄱㅇㅋ 등)
        is_all_chosung = all(char in chosung_map for char in name)
        if is_all_chosung and len(name) > 1:
            curs.execute(db_change("select title from data limit 1000"))
            db_data = curs.fetchall()
            titles = [for_a[0] for for_a in db_data]
            
            # 초성 매칭 필터링
            matched_titles = [t for t in titles if get_chosung(t).startswith(name)][:10]
            return flask.jsonify(matched_titles)

        last_char = name[-1]
        prefix = name[:-1]

        if last_char in chosung_map:
            # 마지막 글자가 초성인 경우 (예: '안ㄴ' -> '안나' ~ '안다' 사이 검색)
            start, end = chosung_map[last_char]
            curs.execute(db_change("select title from data where title >= ? and title < ? collate nocase limit 10"), [prefix + start, prefix + end])
        elif 0xAC00 <= ord(last_char) <= 0xD7A3:
            # 종성이 있는 경우와 없는 경우 모두 포함 가능하도록 범위 계산
            # S = (init, vowel, final)
            # base = (init, vowel, 0)
            char_code = ord(last_char) - 0xAC00
            final = char_code % 28

            if final == 0:
                # 종성이 없는 경우 (기존 로직 유지)
                start = name
                end = prefix + chr(ord(last_char) + 28)
                curs.execute(db_change("select title from data where title >= ? and title < ? collate nocase limit 10"), [start, end])
            else:
                # 종성이 있는 경우 (예: '핫' -> '하' + '사' ~ '하' + '싸' 범위 검색 시도)
                # 종성을 분리하고 이를 다음 글자의 초성으로 매핑 시도
                final_to_chosung = {
                    1: 'ㄱ', 4: 'ㄴ', 7: 'ㄷ', 8: 'ㄹ', 16: 'ㅁ', 17: 'ㅂ', 19: 'ㅅ', 21: 'ㅇ',
                    22: 'ㅈ', 23: 'ㅊ', 24: 'ㅋ', 25: 'ㅌ', 26: 'ㅍ', 27: 'ㅎ'
                }
                if final in final_to_chosung:
                    chosung = final_to_chosung[final]
                    if chosung in chosung_map:
                        base_char = chr(ord(last_char) - final + 0xAC00) # 종성 제거된 글자 (하)
                        s1, e1 = chosung_map[chosung]
                        # '안녕하' + '사' ~ '안녕하' + '자' (ㅅ 초성 범위)
                        # '안녕하세요'는 이 범위에 포함됨
                        curs.execute(db_change("select title from data where (title like ?) or (title >= ? and title < ?) collate nocase limit 10"), [name + '%', prefix + base_char + s1, prefix + base_char + e1])
                    else:
                        curs.execute(db_change("select title from data where title like ? collate nocase limit 10"), [name + '%'])
                else:
                    curs.execute(db_change("select title from data where title like ? collate nocase limit 10"), [name + '%'])
        else:
            # 일반적인 접두어 검색
            curs.execute(db_change("select title from data where title like ? collate nocase limit 10"), [name + '%'])
        db_data = curs.fetchall()
        
        return flask.jsonify([for_a[0] for for_a in db_data])