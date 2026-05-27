from typing import TypedDict
from core.security import check_auth, rate_limit
from core.cleaner import clean_text
from hermes.hermes_integration import get_hermes_multi_agent_bridge

class AgentState(TypedDict):
    user: str
    token: str
    query: str
    prompt: str
    reference: str
    image: str
    response: str
    route: str
    pending_delete: bool

# ========== 替换原有 supervisor_node 的语义路由(路径C) ==========
def semantic_supervisor_node(state: AgentState) -> AgentState:
    """
    语义路由版 supervisor_node
    替换原有的关键词匹配
    """
    # 鉴权
    if not check_auth(state["token"]):
        state["response"] = "鉴权失败, Token错误"
        state["route"] = "end"
        return state
    # 限流
    if not rate_limit():
        state["response"] = "访问频繁, 触发熔断限流"
        state["route"] = "end"
        return state
    # 清洗
    q = clean_text(state["query"])
    state["query"] = q

    # 使用语义路由低缓关键词匹配
    route = get_hermes_multi_agent_bridge().semantic_router(q)
    state["route"] = route

    return state