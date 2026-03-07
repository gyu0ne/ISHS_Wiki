import sqlite3

def reset_user(user_id):
    conn = sqlite3.connect('C:/Users/LeeDoHye/Desktop/ISHS_Wiki/data.db')
    curs = conn.cursor()
    
    # 리로스쿨 재인증 플래그 지우기
    curs.execute("DELETE FROM user_set WHERE id = ? AND name = 'riro_reauthed'", [user_id])
    
    # 기수를 32기로 강제 세팅 (배너 테스트용)
    curs.execute("SELECT * FROM user_set WHERE id = ? AND name = 'generation'", [user_id])
    if curs.fetchall():
        curs.execute("UPDATE user_set SET data = '32' WHERE id = ? AND name = 'generation'", [user_id])
    else:
        curs.execute("INSERT INTO user_set (id, name, data) VALUES (?, 'generation', '32')", [user_id])
        
    # 학번 세팅 (더미)
    curs.execute("SELECT * FROM user_set WHERE id = ? AND name = 'student_id'", [user_id])
    if curs.fetchall():
        curs.execute("UPDATE user_set SET data = '1101' WHERE id = ? AND name = 'student_id'", [user_id])
    else:
        curs.execute("INSERT INTO user_set (id, name, data) VALUES (?, 'student_id', '1101')", [user_id])
        
    conn.commit()
    conn.close()
    print(f"User {user_id} reset OK.")

reset_user('admin')
