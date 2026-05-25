import sqlite3
from typing import List
from config import MEMORY_DB

# 短期记忆(内存)
short_memory_cache = []
MAX_SHORT_MEM = 12

def add_short_memory(content: str):
    short_memory_cache.append(content)
    if len(short_memory_cache) > MAX_SHORT_MEM:
        short_memory_cache.pop(0)

def get_short_memory() -> str:
    return "\n".join(short_memory_cache)

# 长期记忆(SQLite持久化)
def init_long_memory():
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS long_memory 
                (user TEXT,content TEXT,time TEXT)''')
    conn.commit()
    conn.close()

def save_long_memory(user: str, content: str):
    import time
    t = time.strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute("INSERT INTO long_memory VALUES (?, ?, ?)", (user, content, t))
    conn.commit()
    conn.close()

def get_long_memory(user: str, limit=10) -> List:
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    res = c.execute("SELECT * FROM long_memory WHERE user=? ORDER BY time DESC LIMIT ?", (user, limit)).fetchall()
    conn.close()
    return res

init_long_memory()