"""
完整集成: 将 Langraph 多智能体系统接入 Hermes
- 路径A: 封装为 Hermes 技能
- 路径B: 统一消息网关
- 路径C: 于一路由替代关键词匹配
"""
import os
import asyncio
import json
import requests
from typing import Dict, Any, Optional
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from contextlib import asynccontextmanager
from llama_index.llms.ollama import Ollama
from agents.component.approval_database_agent import handle_delete_kg
from config import *

# ========== 导入你的现有系统 ==========
from config import DATA_PATH, MEMORY_DB, SECRET_TOKEN, LLM_MODEL
from database.neo4j_conn import _neo4j_conn

class SkillRequest(BaseModel):
    """技能请求模型"""
    skill: str
    params: Dict[str, Any] = {}
    context: Dict[str, Any] = {}

class ChatRequest(BaseModel):
    user: str
    query: str
    thread_id: str = "default"
    from_skill: str = None

# ========== 集成层 ==========
class HermesMultiAgentBridge:
    """
    Hermes 与你的 LangGraph 多智能体系统的桥梁
    同时实现路径A、B、C
    """

    def __init__(self, graph):
        
        self.graph = graph
        self.action_sessions = {} # 会话管理
        self.app = None
        self.hermes_client = None
    
    # ========== 路径A: 技能封装 ==========
    def get_all_skill_definitions(self) -> Dict[str, Dict]:
        """
        获取所有技能定义
        这些定义会被写入 SKILL.md 文件供 Hermes 发现
        """
        return {
            "rag_query": {
                "name": "rag_query",
                "description": "检索知识库并回答问题. 支持文档搜索、知识图谱查询. 当用户询问知识库中的信息、任务介绍、技术问题时使用.",
                "parameters": {
                    "query": {
                        "type": "string",
                        "description": "用户的问题",
                        "required": True
                    }
                },
                "examples": [
                    {"query": "伍凯桃是谁"},
                    {"query": "介绍中山市"},
                    {"query": "什么是RAG"}
                ],
                "route": "rag"
            },
            "multimodal_generate": {
                "name": "multimodal_generate",
                "description": "生成图片、理解图片内容. 支持文生图、图生文.",
                "parameters": {
                    "prompt": {
                        "type": "string",
                        "description": "图片描述或生成指令",
                        "required": True
                    }
                },
                "examples": [
                    {"prompt": "生成一只可爱的柴犬"},
                    {"prompt": "画一幅山水画"}
                ],
                "route": "multimodal"
            },
            "approval_submit": {
                "name": "approval_submit",
                "description": "提交审批申请. 支持请假、报销、项目立项等. 当用户提交申请时使用.",
                "parameters": {
                    "content": {
                        "type": "string",
                        "description": "申请内容",
                        "required": True
                    },
                    "type": {
                        "type": "string",
                        "description": "申请类型 - leave(请假)/expense(报销)/project(项目)",
                        "required": False,
                        "default": "general"
                    }
                },
                "examples": [
                    {"content": "我想请3天年假", "type": "leave"},
                    {"content": "报销差旅费500元", "type": "expense"}
                ],
                "route": "approval"
            },
            "approval_handle": {
                "name": "approval_handle",
                "description": "处理审批 - 通过、驳回或转交. 当用户作为审批人需要处理待办申请时使用.",
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
                        "description": "审批意见|转交人",
                        "required": False
                    }
                },
                "examples": [
                    {"action": "approve", "request_id": "REQ202412011200001"},
                    {"action": "reject", "request_id": "REQ202412011200001", "comment": "理由不充分"},
                    {"action": "transfer", "request_id": "REQ202412011200001", "comment": "张三"}
                ],
                "route": "approval"
            },
            "delete_knowledge_graph": {
                "name": "delete_knowledge_graph",
                "description": "删除知识图谱中的所有数据. 危险操作, 需要二次确认. 当用户明确要求删除知识图谱时使用.",
                "parameters": {
                    "confirm": {
                        "type": "boolean",
                        "description": "是否确认删除",
                        "required": True
                    }
                },
                "warning": "此操作不可恢复, 必须要求用户二次确认后才能执行",
                "examples": [
                    {},
                    {"confirm": True},
                    {"confirm": False}
                ],
                "route": "approval"
            }
        }
    
    def get_skill_definition(self, skill_name: str) -> Optional[Dict]:
        """获取单个技能定义"""
        skills = self.get_all_skill_definitions()
        return skills.get(skill_name)
    
    def execute_skill(self, skill_name: str, params: Dict, context: Dict) -> Dict:
        """
        执行技能: 通过 HTTP API 调用你的 LangGraph Agent

        Args:
            skill_name: 技能名称(rag_query/multimodal_generate/approval_submit/approval_handle/delete_knowledge_graph等)
            params: 技能参数
            context: Hermes 上下文, 包含 user, thread_id 等
        Returns:
            {"response": "回答内容", "image": "图片路径(可选)"}
        """
        # 构建状态
        state = {
            "user": context.get("user", "hermes_user"),
            "token": SECRET_TOKEN,
            "from_skill": skill_name
        }

        # 根据技能类型构造查询
        if skill_name == "rag_query":
            state["query"] = params.get("query", "")
        elif skill_name == "multimodal_generate":
            state["query"] = f"生成图 {params.get("prompt", "")}"
        elif skill_name == "approval_submit":
            req_type = params.get("type", "general")
            state["query"] = params.get("content", "")
        elif skill_name == "approval_handle":
            action = params.get("action", "")
            req_id = params.get("request_id", "")
            comment = params.get("comment", "")
            state["query"] = f"{action} {req_id} {comment}"
        elif skill_name == "delete_knowledge_graph":
            result = handle_delete_kg(params, context)
            return {
                "response": result.get("response", "")
            }

        print(f"state:\n{state}")
        if not state.get("query"):
            return {"response": f"无法处理技能 {skill_name}, 请检查参数"}
        
        # 调用 LangGraph API
        try:
            response = requests.post(
                ANGET_API_URL,
                json={
                    "user": state["user"],
                    "query": state["query"],
                    "thread_id": context.get("thread_id", "hermes_default_thread"),
                    "from_skill": state["from_skill"]
                },
                headers={
                    "Authorization": f"Bearer {SECRET_TOKEN}"
                },
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    "response": result.get("response", "处理完成"),
                    "image": result.get("image")
                }
            else:
                print("666666666666")
                return {
                    "response": f"API 调用失败: {response.status_code}"
                }
        except requests.exceptions.ConnectionError:
            return {
                "response": "无法连接到 Agent 服务, 请确保 app.py 正在运行."
            }
        except Exception as e:
            return {
                "response": f"执行失败: {str(e)}"
            }
        
    def generate_skill_md_files(self, output_dir: str = "~/.hermes/skills"):
        """
        为每个技能生成独立的 SKILL.md 文件
        Hermes 会自动扫描这个目录并加载技能
        """
        skills = self.get_all_skill_definitions()

        # 展开用户目录
        output_dir = os.path.expanduser(output_dir)

        for skill_name, skill_def in skills.items():
            # 创建技能目录
            skill_dir = os.path.join(output_dir, skill_name)
            os.makedirs(skill_dir, exist_ok=True)

            # 生成 SKILL.md 内容
            skill_md = f"""---
name: {skill_def['name']}
description: {skill_def['description']}
version: 1.0.0
---

# {skill_def['name']}

## 描述
{self._format_params(skill_def.get('parameters', {}))}

## 示例
{self._format_examples(skill_def.get('examples', []))}

## 执行指令
当用户请求符合此技能描述时, 请构造以下 API 请求:

```json
POST http://localhost:8001/api/skill/{skill_name}
Content-Type: application/json
{{
    "skill": "{skill_name}",
    "params": {self._format_params_json(skill_def.get('parameters', {}))},
    "context": {{
        "user": "{{user}}",
        "thread_id": "{{thread_id}}"
    }}
}}
```
## 注意事项
- 必须等待 API 返回结果后再回复用户
- 如果 API 返回 image 字段, 需要以适当方式展示图片
- 对于 delete_knowledge_graph 技能, 必须先确认用户意图
"""
            # 写入文件
            md_path = os.path.join(skill_dir, "SKILL.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(skill_md)
                print(f"已生成技能文件: {md_path}")

        print(f"所有技能已生成到: {output_dir}")
        print(f"请重启 Hermes 或运行'/skills reload'加载新技能")
        
    def _format_params(self, params: Dict) -> str:
        """格式参数为 Markdown 表格"""
        if not params:
            return "无参数"
        
        lines = ["|参数名|类型|必填|描述|", "|------|----|----|----|"]
        for name, info in params.items():
            required = "是" if info.get("required") else "否"
            lines.append(f"|{name}|{info.get('type')}|{required}|{info.get('description')}|")
        return "\n".join(lines)

    def _format_examples(self, examples: list) -> str:
        """格式化示例"""
        if not examples:
            return "无示例"
        
        lines = []
        for ex in examples:
            lines.append(f"- {json.dumps(ex, ensure_ascii=False)}")
        return "\n".join(lines)
    
    def _format_params_json(self, params: Dict) -> str:
        """格式化参数为 JSON 示例"""
        if not params:
            return "{}"
        
        example = {}
        for name, info in params.items():
            if info.get("type") == "string":
                example[name] = f"<{name}>"
            elif info.get("type") == "boolean":
                example[name] = False
            elif info.get("type") == "integer":
                example[name] = 0
        return json.dumps(example, ensure_ascii=False)
    
    # ========== 路径C: 语义路由 ==========
    def semantic_router(self, state) -> str:
        """使用 LLM 进行语义路由, 替换关键词匹配"""
        # ========== skill.md 进入则跳过 ==========
        from_skill = state.get("from_skill", None)
        route = state.get("route", "")
        if from_skill and route:
            print(f"跳过语义路由, 使用预设路由from_skill: {from_skill} -> {route}")
            return state["route"]
        
        # ========== 语义路由 ==========
        query = state["query"]
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

        # ========== 降级: 关键词匹配 ==========
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


        app = FastAPI(title="Multi_Agent Hermes Gateway", description="将你的 LangGraph Agent 暴露为 Hermes 技能", lifespan=lifespan)

        # ========== 供 wechat/dingtalk/feishu/telegram 等平台接入 ==========
        @app.post("/webhook/{platform}")
        async def platform_webhook(platform: str, request: Request, background_tasks: BackgroundTasks):
            """接收各平台的消息"""
            data = await request.json()

            # 解析不同平台的消息格式
            if platform == "wechat":
                user = data.get("FromUserName", "")
                query = data.get("Content", "")
            elif platform == "dingtalk":
                user = data.get("senderStaffId", "")
                query = data.get("text", {}).get("content", "")
            elif platform == "feishu":
                user = data.get("sender", {}).get("sender_id", {}).get("user_id", "")
                query = data.get("message", {}).get("content", "")
            elif platform == "telegram":
                user = str(data.get("message", {}).get("from", {}).get("id", ""))
                query = data.get("message", {}).get("text", "")
            else:
                user = data.get("user_id", "unknown")
                query = data.get("message", "")

            # 后台处理, 不阻塞
            background_tasks.add_task(self._process_message, user, query, platform)

            # 立即返回(异步处理)
            return {
                "code": 0,
                "msg": "ok"
            }
        
        @app.post("/api/chat")
        async def chat_endpoint(request: Request):
            """HTTP API 端点, 供 Streamlit 等前端调用"""
            data = await request.json()
            user = data.get("user", "web_user")
            query = data.get("query", "")

            result =  await self._process_message_sync(user, query, "")
            return result
        
        # ========== 供 Hermes Agent 接入 ==========
        @app.post("/api/skill/{skill_name}")
        async def execute_skill(skill_name: str, request: SkillRequest):
            print("1111111111111111111111")
            """执行技能端点"""
            result = self.execute_skill(
                skill_name=skill_name,
                params=request.params,
                context=request.context
            )
            return result

        @app.get("/api/skills")
        async def list_skills():
            """列出所有可用技能"""
            return self.get_all_skill_definitions()
            
        @app.get("/health")
        async def health():
            """健康检查"""
            return {
                "status": "healthy",
                "timestamp": datetime.now().isoformat()
            }
        
        self.app = app
        return app
    
    # ========== FastAPI (可供 LangGraph 或 外部网关调用[跨域]) ==========
    def create_fastapi_app(self) -> FastAPI:
        """ 创建后端 FastAPI 接口: 可被 LangGraph 或外部网关调用[跨域] """
        app = FastAPI(title="Multi_Agent API", description="创建后端 FastAPI 接口")

        @app.post("/api/chat")
        async def chat_endpoint(request: ChatRequest):
            """供 Hermes 调用的 API 端点"""
            print("8888888888888888888666666666666666666")
            user = request.user
            query = request.query
            thread_id = request.thread_id
            from_skill = request.from_skill
            print("222222222")
            result = await self._process_message_sync(user, query, thread_id, from_skill)
            print(f"result:\n{result}")
            return {
                "response": result.get("response", ""),
                "image": result.get("image")
            }
        
        @app.get("/health")
        async def health():
            """健康检查"""
            return {
                "status": "ok"
            }
        
        self.app = app
        return app

    async def _process_message(self, user: str, query: str, platform: str):
        """异步处理消息"""
        try:
            # 语义路由
            # route = self.semantic_router(state)

            # 构建状态
            state = {
                "user": user,
                "token": SECRET_TOKEN,
                "query": query
            }

            config = {
                "configurable": {
                    "thread_id":  f"{platform}_{user}"
                }
            }
            result = self.graph.invoke(state, config=config)

            response = result.get("response", "处理完成")

            # 发送回复(根据平台格式)
            await self._send_reply(platform, user, response)
        except Exception as e:
            await self._send_reply(platform, user, f"处理失败: {str(e)}")

    async def _process_message_sync(self, user: str, query: str, thread_id: str = "default_id", from_skill: str = None) -> Dict:
        """同步处理消息(用于API)"""
        try:
            # route = self.semantic_router(state)

            skill_def = self.get_skill_definition(from_skill)
            if skill_def:
                route = skill_def.get("route", "chat")
            else:
                route = "chat"
            
            state = {
                "user": user,
                "token": SECRET_TOKEN,
                "query": query,
                "from_skill": from_skill,
                "route": route
            }
            print(f"from_skill:\n{state['from_skill']}")
            print(f"route:\n{state['route']}")

            config = {
                "configurable": {
                    "thread_id":  f"{thread_id}"
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
    from main_graph import graph
    return HermesMultiAgentBridge(graph)

# ========== 主入口 ==========
if __name__ == "__main__":
    import sys

    bridge = get_hermes_multi_agent_bridge()
    app = bridge.create_gateway_app()
    fastapi_app = bridge.create_fastapi_app()

    if len(sys.argv) > 1:
        if sys.argv[1] == "generate":
            # 生成 SKILL.md 文件
            output_dir = sys.argv[2] if len(sys.argv) > 2 else "~/.hermes/skills"
            bridge.generate_skill_md_files(output_dir)
        elif sys.argv[1] == "serve":
            # 启动 API 服务
            import uvicorn
            print(f"启动 Hermes Skill Bridge API 服务...")
            print("API 端点: http://localhost:8001/api/skill/{skill_name}")
            print("健康检查: http://localhost:8001/health")
            uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
            uvicorn.run(app, host="0.0.0.0", port=8001)
        else:
            print("用法:")
            print("python hermes_integration.py generate [输出目录] # 生成 SKILL.md 文件")
            print("python hermes_integration.py serve # 启动 API 服务")