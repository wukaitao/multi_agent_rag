import sqlite3
import re
import time
from datetime import datetime
from typing import Dict, Any
from langgraph.types import interrupt, Command
from database.neo4j_conn import _neo4j_conn
from core.memory_manager import save_long_memory
from core.security import data_desensitize
from config import MEMORY_DB

def init_approval_table():
    """初始化审批表"""
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS approval_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            content TEXT,
            state TEXT,
            time TEXT,
            operation_type TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'pending'
        )
    ''')
    conn.commit()
    conn.close()

init_approval_table()

def log_to_sqlite(user: str, content: str, state: str, operation_type: str="normal") -> int:
    """记录审批日志到 Sqlite"""
    t = time.strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute(
        "INSERT INTO approval_list(user, content, state, time, operation_type, status) VALUES (?, ?, ?, ?, ?, ?)", 
        (user, content, state, t, operation_type, "completed" if state == "已执行" else "pending")
    )
    conn.commit()
    last_id = c.lastrowid
    conn.close()
    return last_id

def handle_delete_kg_human_in_loop(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    使用 Human-in-Loop 处理删除知识图谱
    暂停图执行, 等待用户确认
    """
    user = state["user"]
    query = state["query"]
    content = data_desensitize(query)

    # 1. 记录到 SQLite (待审批状态)
    log_to_sqlite(user, content, "待审批", "delete_kg")

    # 2. 使用 interrupt 暂停图, 等待人工决策
    human_decision = interrupt({
        "type": "delete_knowleage_graph",
        "question": "危险操作确认: 是否执行删除知识图谱?",
        "action": content,
        "risk_level": "高",
        "warning": "此操作将永久删除 Neo4j 数据库中的所有节点和关系, 不可恢复!",
        "options": ["确认删除", "取消操作"],
        "user": user,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    # 3. 根据决策执行
    if human_decision == "确认删除" or human_decision == "confirm":
        try:
            # 执行删除
            _neo4j_conn.kg_clear_all()

            # 记录成功日志
            log_to_sqlite(user, content, "已执行", "delete_kg")

            state["response"] = f"""
            **知识图谱删除成功!**

            - **操作人**: {user}
            - **操作时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            - **删除内容**: {content}

            注意: 所有节点和关系已被清空, 如需恢复请重新导入数据.
            """
        except Exception as e:
            # 记录失败日志
            log_to_sqlite(user, content, f"执行失败: {str(e)}", "delete_kg")

            state["response"] = f"""
            **知识图谱删除失败!**

            - **错误信息**: {str(e)}
            - **请检查 Neo4j 连接后重试**
            """
    elif human_decision == "取消操作" or human_decision == "cancel":
        # 记录取消日志
        log_to_sqlite(user, content, "已取消", "delete_kg")

        state["response"] = f"""
            **知识图谱删除已取消**

            - **操作人**: {user}
            - **操作时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            - **原操作**: {content}

            知识图谱数据保持不变.
        """
    else:
        # 未知决策, 默认取消
        log_to_sqlite(user, content, "已取消(未知决策)", "delete_kg")
        state["response"] = "无法识别的决策, 操作已取消."
    
    state["route"] = "end"
    state["pending_delete"] = False
    return state

def handle_normal_approval(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    普通审批流程
    只记录到 SQLite, 不暂停图
    """
    user = state["user"]
    content = data_desensitize(state["query"])

    # 记录到 SQLite
    log_to_sqlite(user, content, "待审批", "normal")
    res = f"""
    **MPC人工审批流程**
    - **申请人**: {user}
    - **申请内容**: {content}
    - **当前状态**: 待管理人员人工审核
    - **流程链路**: 提交 -> 初审 -> 终审 -> 办结
    """
    state["response"] = res
    state["route"] = "end"
    return state

def approval_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    审批节点: 区分处理
    - 删除知识图谱: 使用 Human - in - Loop (暂停等待确认)
    - 其他审批: 使用原有 SQLite 方式
    """
    query = state["query"]
    pending_delete = state.get("pending_delete", False)

    # 判断是否是删除知识图谱操作
    delete_keywords = ["删除知识图谱", "清除知识图谱", "清空知识图谱", "删除所有数据", "清空数据库"]
    is_delete_kg = pending_delete or any(kw in query for kw in delete_keywords)

    if is_delete_kg:
        # 使用人机协作
        return handle_delete_kg_human_in_loop(state)
    else:
        # 使用审批流程
        return handle_normal_approval(state)