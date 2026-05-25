from database.chroma_conn import vector_search
from database.neo4j_conn import kg_search
from core.optimizer import truncate_text
from core.security import circuit_breaker
from agents.chat_agent import chat_agent_node
import re

@circuit_breaker
def rag_agent_node(state):
    q = state["query"]
    vec_res = vector_search(q)
    print(f"vec_res:\n{vec_res}")
    kg_res = kg_search(q)
    res_text = "[向量检索片段]\n"
    for n in vec_res:
        res_text += truncate_text(n.text) + "\n"
    res_text += "\n[知识图谱事实]\n" + str(kg_res)
    state["prompt"] = f"""
        你是一个多智能体问答助手，请基于以下两种来源的信息回答用户问题。
        {res_text}
        用户问题：{q}

        要求：
        - 优先使用知识图谱中的精确事实
        - 用向量检索内容补充细节
        - 如果信息冲突，说明冲突点
        - 回答要自然、完整、口语化
        """
    state["reference"] = res_text
    return state