from typing import TypedDict
from core.security import check_auth, rate_limit
from core.cleaner import clean_text

class AgentState(TypedDict):
    user: str
    token: str
    query: str
    prompt: str
    reference: str
    image: str
    response: str
    route: str

def supervisor_node(state: AgentState) -> AgentState:
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

    # 智能路由分发
    if any(k in q for k in ["图片", "生成图", "画图"]):
        state["route"] = "multimodal"
    elif any(k in q for k in ["上传", "文档", "知识", "资料", "图谱"]):
        state["route"] = "rag"
    elif any(k in q for k in ["天气", "歌词", "足球", "转会", "比赛", "代码"]):
        state["route"] = "tool"
    elif any(k in q for k in ["审批", "流程", "审核"]):
        state["route"] = "approval"
    else:
        state["route"] = "chat"
    return state