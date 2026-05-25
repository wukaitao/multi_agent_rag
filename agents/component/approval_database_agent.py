import time
from datetime import datetime
from typing import Dict, Any
from langgraph.types import interrupt
from database.neo4j_conn import _neo4j_conn
from core.memory_manager import save_long_memory
from core.security import data_desensitize
from agents.component.approval_workflow_agent import log_to_sqlite, update_log_to_sqlite

def generate_request_id():
    """生成唯一请求ID"""
    return f"DBQ{datetime.now().strftime('%Y%m%d%H%M%S')}{int (time.time() * 1000) % 1000:03d}"

def handle_delete_kg_human_in_loop(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    使用 Human-in-Loop 处理删除知识图谱
    暂停图执行, 等待用户确认
    """
    user = state["user"]
    query = state["query"]
    content = data_desensitize(query)
    request_id = generate_request_id()

    # 1. 记录到 SQLite (待审批状态)
    log_to_sqlite(request_id, user, content, "delete_kg", "删除知识图谱", "待审批")

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
            update_log_to_sqlite(request_id, "已执行")

            state["response"] = f"""
            **知识图谱删除成功!**

            - **操作人**: {user}
            - **操作时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            - **删除内容**: {content}

            注意: 所有节点和关系已被清空, 如需恢复请重新导入数据.
            """
        except Exception as e:
            # 记录失败日志
            update_log_to_sqlite(request_id, f"执行失败: {str(e)}")

            state["response"] = f"""
            **知识图谱删除失败!**

            - **错误信息**: {str(e)}
            - **请检查 Neo4j 连接后重试**
            """
    elif human_decision == "取消操作" or human_decision == "cancel":
        # 记录取消日志
        update_log_to_sqlite(request_id, "已取消")

        state["response"] = f"""
            **知识图谱删除已取消**

            - **操作人**: {user}
            - **操作时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            - **原操作**: {content}

            知识图谱数据保持不变.
        """
    else:
        # 未知决策, 默认取消
        update_log_to_sqlite(request_id, "已取消(未知决策)")
        state["response"] = "无法识别的决策, 操作已取消."
    
    state["pending_delete"] = False
    return state