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
    pending_delete: bool

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

    # 删除知识图谱识别(走审批节点)
    delete_keywords = [
        "删除知识图谱", "清除知识图谱", "清空知识图谱",
        "删除所有数据", "清空数据库", "重置知识库",
        "删除图谱", "清除图谱"
    ]
    if any(keyword in q for keyword in delete_keywords):
        state["route"] = "approval"
        state["pending_delete"] = True
        return state

    # 智能路由分发
    if any(k in q for k in ["图片", "生成图", "画图"]):
        state["route"] = "multimodal"
    elif any(k in q for k in ["上传", "文档", "知识", "资料", "图谱"]):
        state["route"] = "rag"
    elif any(k in q for k in ["天气", "歌词", "足球", "转会", "比赛", "代码"]):
        state["route"] = "tool"
    elif any(k in q for k in ["审批", "流程", "审核", "请假", "报销", "项目", "立项", "通过", "驳回", "转交"]):
        state["route"] = "approval"
    else:
        state["route"] = "chat"
    return state