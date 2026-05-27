"""
完整集成: 将 Langraph 多智能体系统接入 Hermes
- 路径A: 封装为 Hermes 技能
- 路径B: 统一消息网关
- 路径C: 于一路由替代关键词匹配
"""
import os
import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime
from fastapi import FastAPI, Request, BackgroundTasks
from contextlib import asynccontextmanager
from llama_index.llms.ollama import Ollama

# ========== 导入你的现有系统 ==========
from config import DATA_PATH, MEMORY_DB, SECRET_TOKEN, LLM_MODEL
from database.neo4j_conn import _neo4j_conn

# ========== 集成层 ==========
class HermesMultiAgentBridge:
    """
    Hermes 与你的 LangGraph 多智能体系统的桥梁
    同时实现路径A、B、C
    """

    def __init__(self):
        from main_graph import graph
        
        self.graph = graph
        self.action_sessions = {} # 会话管理
        self.app = None
        self.hermes_client = None
    
    # ========== 路径A: 技能封装 ==========
    def get_skill_definition(self, skill_name: str) -> Dict:
        """获取技能定义(供 Hermes 发现)"""
        skills = {
            "rag_query": {
                "name": "rag_query",
                "description": "检索知识库并回答问题. 支持文档搜索、知识图谱查询.",
                "parameters": {
                    "query": {
                        "type": "string",
                        "description": "用户的问题",
                        "required": True
                    }
                }
            },
            "multimodal_generate": {
                "name": "multimodal_generate",
                "description": "生成图片、理解图片内容. 支持文生图、图生文.",
                "parameters": {
                    "query": {
                        "type": "string",
                        "description": "图片描述或生成指令",
                        "required": True
                    }
                }
            },
            "approval_submit": {
                "name": "approval_submit",
                "description": "提交审批申请. 支持请假、报销、项目立项等.",
                "parameters": {
                    "content": {
                        "type": "string",
                        "description": "申请内容",
                        "required": True
                    },
                    "type": {
                        "type": "string",
                        "description": "申请类型: leave/expense/project",
                        "required": False
                    }
                }
            },
            "approval_handle": {
                "name": "approval_handle",
                "description": "处理审批: 通过、驳回或转交.",
                "parameters": {
                    "action": {
                        "type": "string",
                        "description": "操作: approve/reject/transfer",
                        "required": True
                    },
                    "request_id": {
                        "type": "string",
                        "description": "申请单号",
                        "required": True
                    },
                    "comment": {
                        "type": "string",
                        "description": "审批意见",
                        "required": False
                    }
                }
            },
            "delete_knowledge_graph": {
                "name": "delete_knowledge_graph",
                "description": "删除知识图谱中的所有数据. 危险操作, 需要二次确认.",
                "parameters": {
                    "confirm": {
                        "type": "boolean",
                        "description": "是否确认删除",
                        "required": True
                    }
                }
            }
        }
        return skills.get(skill_name)
    
    def execute_skill(self, skill_name: str, params: Dict, context: Dict) -> Dict:
        """执行技能(调用你的 LangGraph节点)"""
        # 构建状态
        state = {
            "user": context.get("user", "hermes_user"),
            "token": SECRET_TOKEN,
            "query": "",
            "prompt": "",
            "image": "",
            "reference": "",
            "response": "",
            "route": "",
            "pending_delete": False
        }

        # 根据技能类型构造查询
        if skill_name == "rag_query":
            state["query"] = params.get("query", "")
        elif skill_name == "mulimodal_generate":
            state["query"] = f"生成图 {params.get('prompt', '')}"
        elif skill_name == "approval_submit":
            req_type = params.get("type", "general")
            state["query"] = params.get("content", "")
        elif skill_name == "approve_handle":
            action = params.get("action", "")
            req_id = params.get("request_id", "")
            comment = params.get("comment", "")
            state["query"] = f"{action} {req_id} {comment}"
        elif skill_name == "delete_knowledge_graph":
            if params.get("confirm"):
                state["query"] = "删除知识图谱"
            else:
                return {
                    "response": "删除操作已取消, 需要确认才能执行."
                }
        # 调用你的 LangGraph
        config = {
            "configurable": {
                "thread_id": context.get("thread_id", "hermes_default")
            }
        }
        result = self.graph.invoke(state, config=config)

        return {
            "response": result.get("response", ""),
            "route": result.get("route", "chat"),
            "image": result.get("image")
        }
    
    # ========== 路径C: 语义路由 ==========
    def semantic_router(self, query: str) -> str:
        """使用 LLM 进行语义路由, 替换关键词匹配"""
        llm = Ollama(model=LLM_MODEL, temperature=0)
        prompt = f"""分析以下用户问题, 判断应该路由到哪个Agent.
        可选Agent:
        - rag: 知识检索、文档回答、信息查询
        - multimodal: 图片生成、图片理解
        - tool: 天气查询、代码生成、足球信息
        - approval: 审批流程、删除知识图谱
        - chat: 普通对话、闲聊

        用户问题: {query}

        只输出Agent名称, 不要输出其他内容:"""
        try: 
            result = llm.complete(prompt).text.strip().lower()
            print(f"语义路由判断结果:\n{result}")
            if result in ["rag", "multimodal", "tool", "approval", "chat"]:
                return result
            else:
             print("语义路由识别不出结果")
        except:
            pass

        # 降级: 关键词匹配
        if any(k in query for k in ["图片", "生成图", "画图"]):
            return "multimodal"
        elif any(k in query for k in ["知识", "文档", "资料", "是谁", "什么是"]):
            return "rag"
        elif any(k in query for k in ["天气", "代码", "足球"]):
            return "tool"
        elif any(k in query for k in [
            # 普通申请流程
            "流程", "审核",
            # 申请流程
            "请假", "报销", "项目", "立项",
            # 审批流程
            "通过", "驳回", "转交", "审批",
            # 删除知识图谱识别(走审批节点)
            "删除知识图谱", "清除知识图谱", "清空知识图谱",
            "删除所有数据", "清空数据库", "重置知识库",
            "删除图谱", "清除图谱"]):
            return "approval"
        else:
            return "chat"

    # ========== 路径B: 消息网关 ==========
    def create_gateway_app(self) -> FastAPI:
        """创建统一消息网关的 FastAPI 应用"""
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # 启动时初始化
            print("Hermes 网关已启动")
            yield
            # 关闭时清理
            print("Hermes 网关已关闭")


        app = FastAPI(title="Multi_Agent Hermes Gateway", lifespan=lifespan)

        @app.post("/webhook/{platform}")
        async def platform_webhook(platform: str, request: Request, background_tasks: BackgroundTasks):
            """接收各平台的消息"""
            data = await request.json()

            # 解析不同平台的消息格式
            if platform == "wechat":
                user_id = data.get("FromUserName", "")
                message = data.get("Content", "")
            elif platform == "dingtalk":
                user_id = data.get("senderStaffId", "")
                message = data.get("text", {}).get("content", "")
            elif platform == "feishu":
                user_id = data.get("sender", {}).get("sender_id", {}).get("user_id", "")
                message = data.get("message", {}).get("content", "")
            elif platform == "telegram":
                user_id = str(data.get("message", {}).get("from", {}).get("id", ""))
                message = data.get("message", {}).get("text", "")
            else:
                user_id = data.get("user_id", "unknown")
                message = data.get("message", "")

            # 后台处理, 不阻塞
            background_tasks.add_task(self._process_message, user_id, message, platform)

            # 立即返回(异步处理)
            return {
                "code": 0,
                "msg": "ok"
            }
        
        @app.post("/api/chat")
        async def chat_endpoint(request: Request):
            """HTTP API 端点, 供 Streamlit 等前端调用"""
            data = await request.json()
            user_id = data.get("user_id", "web_user")
            message = data.get("message", "")

            result =  await self._process_message_sync(user_id, message)
            return result
            
        @app.get("/health")
        async def health():
            return {
                "status": "healthy",
                "timestamp": datetime.now().isoformat()
            }
        
        self.app = app
        return app

    async def _process_message(self, user_id: str, message: str, platform: str):
        """异步处理消息"""
        try:
            # 语义路由
            route = self.semantic_router(message)

            # 构建状态
            thread_id = f"{platform}_{user_id}"
            state = {
                "user": user_id,
                "token": SECRET_TOKEN,
                "query": message,
                "prompt": "",
                "image": "",
                "reference": "",
                "response": "",
                "route": route,
                "pending_delete": False
            }

            config = {
                "configurable": {
                    "thread_id":  thread_id
                }
            }
            result = self.graph.invoke(state, config=config)

            response = result.get("response", "处理完成")

            # 发送回复(根据平台格式)
            await self._send_reply(platform, user_id, response)
        except Exception as e:
            await self._send_reply(platform, user_id, f"处理失败: {str(e)}")

    async def _process_message_sync(self, user_id: str, message: str) -> Dict:
        """同步处理消息(用于API)"""
        try:
            route = self.semantic_router(message)

            state = {
                "user": user_id,
                "token": SECRET_TOKEN,
                "query": message,
                "prompt": "",
                "image": "",
                "reference": "",
                "response": "",
                "route": route,
                "pending_delete": False
            }

            config = {
                "configurable": {
                    "thread_id":  f"api_{user_id}"
                }
            }
            result = self.graph.invoke(state, config=config)

            return {
                "success": True,
                "response": result.get("response", ""),
                "route": result.get("route", "chat")
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def _send_reply(self, platform: str, user_id: str, message: str):
        """发送回复到各平台(简化版)"""
        # 这里需要根据各平台API实现
        print(f"[{platform}] To {user_id}: {message[:100]}")
        # 实际接入需要调用各平台API

# ========== 初始化 ==========
def get_hermes_multi_agent_bridge():
    """桥接器实例化"""
    return HermesMultiAgentBridge()