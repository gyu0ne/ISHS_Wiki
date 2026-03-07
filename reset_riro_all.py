import sqlite3

def reset_all_users():
    conn = sqlite3.connect('C:/Users/LeeDoHye/Desktop/ISHS_Wiki/data.db')
    curs = conn.cursor()
    
    # 모든 사용자의 재인증 플래그 초기화
    curs.execute("DELETE FROM user_set WHERE name = 'riro_reauthed'")
    
    conn.commit()
    conn.close()
    print("All users reset OK.")

reset_all_users()
