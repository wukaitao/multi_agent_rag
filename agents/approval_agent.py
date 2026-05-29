import sqlite3
import re
import time
from datetime import datetime
from typing import Dict, Any
from langgraph.types import interrupt, Command
from database.neo4j_conn import _neo4j_conn
from core.memory_manager import save_long_memory
from core.security import data_desensitize
from agents.component.approval_workflow_agent import *
from agents.component.approval_database_agent import *
from config import MEMORY_DB

# ========== 初始化所有表 ==========
init_apprval_tables()

# ========== 分发流程处理 ==========
def approval_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    审批节点入口: 区分处理
    - 删除知识图谱: 使用 Human-in-Loop
    - 其他审批: 使用企业级审批流程(Sqlite)
    """
    query = state["query"]

    # 判断是否是删除知识图谱操作
    delete_keywords = [
        "删除知识图谱", "清除知识图谱", "清空知识图谱",
        "删除所有数据", "清空数据库", "重置知识库",
        "删除图谱", "清除图谱"
    ]
    is_delete_kg = any(kw in query for kw in delete_keywords)

    # 判断是否是审批操作(通过/驳回/转交等)
    aciton_keywords = ["通过", "驳回", "转交", "审批", "approve", "reject", "transfer"]
    is_approval_action = any(kw in query for kw in aciton_keywords) and "REQ" in query

    if is_delete_kg:
        print("aaaaaaaaaaaaaa")
        # 删除知识图谱 Human-in-Loop
        return handle_delete_kg_human_in_loop(state)
    elif is_approval_action:
        print("bbbbbbbbbb")
        # 处理审批动作
        return handle_workflow_approval(state)
    else:
        print("ccccccccccc")
        # 普通审批流程
        return handle_workflow_submit(state)