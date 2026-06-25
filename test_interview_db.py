import sqlite3
import os

dbs = ["interviewsense.db", "zora.db"]

for db_name in dbs:
    print(f"\n=== DB Name: {db_name} ===")
    if not os.path.exists(db_name):
        print("Does not exist")
        continue
    
    conn = sqlite3.connect(db_name)
    conn.row_factory = sqlite3.Row
    
    try:
        r = conn.execute("SELECT count(*) FROM interview_sessions").fetchone()
        print("Sessions:", r[0])
    except Exception as e:
        print("Error sessions:", e)

    try:
        r = conn.execute("SELECT count(*) FROM interview_qa").fetchone()
        print("QAs:", r[0])
    except Exception as e:
        print("Error QAs:", e)

    try:
        rows = conn.execute("SELECT chat_id, q_index, question, score FROM interview_qa LIMIT 5").fetchall()
        for r in rows:
            print(dict(r))
    except Exception as e:
        print("Error sample QAs:", e)
        
    conn.close()

