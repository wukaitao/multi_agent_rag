import sqlite3
from config import MEMORY_DB

# ========== 数据表初始化 ==========
def init_message_queue():
    """初始化 ClawBot 消息队列"""
    conn = sqlite3.connect(MEMORY_DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 消息队列表
    c.execute("""
        CREATE TABLE IF NOT EXISTS message_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            to_user_id TEXT NOT NULL,
            msg_type TEXT NOT NULL,
            content TEXT NOT NULL,
            context_token TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def log_message_queue(to_user_id: str, msg_type: str, content: str, context_token: str):
    """存储 ClawBot 消息队列"""
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO message_queue
        (to_user_id, msg_type, content, context_token)
        VALUES (?, ?, ?, ?)
        """, 
        (to_user_id, msg_type, content, context_token)
    )
    conn.commit()
    last_id = c.lastrowid
    conn.close()
    return last_id

def get_message_queue():
    """获取 ClawBot 消息队列"""
    conn = sqlite3.connect(MEMORY_DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM message_queue")
    return [dict(row) for row in c.fetchall()]

# ========== 初始化数据表 ==========
if __name__ == "__main__":
    init_message_queue()