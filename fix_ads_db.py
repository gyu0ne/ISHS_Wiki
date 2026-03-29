import sqlite3
import os

db_path = 'data.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    curs = conn.cursor()
    # 기존 오설정된 데이터를 올바른 경로로 업데이트
    curs.execute("UPDATE other SET data = '/image/ad1.png | https://forms.gle/5FmWoxERVCw9hEbo8' WHERE name = 'ads_list' AND data LIKE '%/views/ringo/img/%'")
    conn.commit()
    print(f"Updated {curs.rowcount} rows.")
    conn.close()
else:
    print("DB not found")
