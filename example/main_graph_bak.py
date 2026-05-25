import os
from langgraph.graph import StateGraph, END
from agents.supervisor_agent import AgentState, supervisor_node
from agents.rag_agent import rag_agent_node
from agents.multimodal_agent import multimodal_agent_node
from agents.tool_agent import tool_agent_node
from agents.approval_agent import approval_agent_node
from agents.chat_agent import chat_agent_node
from config import *

# 路由判断
def route_node(state: AgentState):
    return state["route"]

# 构建流程图
workflow = StateGraph(AgentState)
workflow.add_node("supervisor", supervisor_node)
workflow.add_node("rag", rag_agent_node)
workflow.add_node("multimodal", multimodal_agent_node)
workflow.add_node("tool", tool_agent_node)
workflow.add_node("approval", approval_agent_node)
workflow.add_node("chat", chat_agent_node)

workflow.set_entry_point("supervisor")
workflow.add_conditional_edges(
    "supervisor",
    route_node,
    {
        "multimodal": "multimodal",
        "rag": "rag",
        "tool": "tool",
        "approval": "approval",
        "chat": "chat",
        "end": END
    }
)
workflow.add_edge("multimodal", END)
workflow.add_edge("rag", 'chat')
workflow.add_edge("tool", END)
workflow.add_edge("approval", END)
workflow.add_edge("chat", END)

graph = workflow.compile()

# 生成Graph图
png_bytes = graph.get_graph().draw_mermaid_png()
file_path = GRAPH_FILE_PATH
# 确保文件存在
os.makedirs(os.path.dirname(file_path), exist_ok=True)
with open(file_path, "wb") as file:
    file.write(png_bytes)