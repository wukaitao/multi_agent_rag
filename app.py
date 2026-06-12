import streamlit as st
from main_graph import graph
from database.chroma_conn import upload_file_to_vector
from database.neo4j_conn import batch_create_triples, batch_import_triples_with_fixed_format, build_kg_from_document
from core.cleaner import clean_filename
from core.memory_manager import get_long_memory
from core.optimizer import kg_input_format
from agents.component.approval_workflow_agent import get_approval_engine
from langgraph.types import Command
import os
import re
import uvicorn
import threading
# import debugpy
from dotenv import load_dotenv
from config import *
# 导入网关应用
from hermes.hermes_integration import get_hermes_multi_agent_bridge
from hermes.wechat_integration import get_qrcode, load_qrcode_status, save_qrcode_status, run_bot, poll_login_status, get_bot_info, get_config
import sys
import asyncio
import nest_asyncio

# 加载环境配置
load_dotenv()

# nest_asyncio.apply()

# 页面配置
st.set_page_config(page_title="企业多Agent智能平台", layout="wide")

# 初始化 session_state
if "thread_id" not in st.session_state:
    st.session_state.thread_id = "default_thread"
if "waiting_approval" not in st.session_state:
    st.session_state.waiting_approval = False
if "pending_config" not in st.session_state:
    st.session_state.pending_config = None
if st.session_state.get('need_refresh', False):
    st.session_state['need_refresh'] = False
    st.rerun()
# if "bot_token_verify" not in st.session_state:
#     st.session_state.bot_token_verify = False

# Gateway | FastAPI 实例
bridge = get_hermes_multi_agent_bridge()
gateway_app = bridge.create_gateway_app()
fastapi_app = bridge.create_fastapi_app()
# 用全局变量记录服务状态，防止重复启动
gateway_running = False
fastapi_running = False
# 获取 ClawBot 的状态信息
qrcode_status = load_qrcode_status()

def run_graph_with_config(user_input: str, username: str, token: str, thread_id: str):
    """运行图, 支持 interrupt 恢复"""
    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    try:
        # 如果有待恢复的 interrupt
        if st.session_state.waiting_approval:
            print("woshi aaaa")
            # 恢复执行, 传入用户决策
            decision = "确认删除" if "确认" in user_input else "取消操作" if "取消" in user_input else "未知操作"
            result = graph.invoke(Command(resume=decision), config=config)
            st.session_state.waiting_approval = False
        else:
            # 正常执行
            result = graph.invoke({
                "user": username,
                "token": token,
                "query": user_input,
                "prompt": "",
                "image": "",
                "reference": "",
                "response": "",
                "route": ""
            }, config=config)

            # 检查是否触发了 interrupt
            # 如果返回结果中可能包含 interrupt 信息, 需要标记等待状态
            graphState = graph.get_state(config)
            for task in graphState.tasks if hasattr(graphState, "tasks") else []:
                if hasattr(task, "interrupts"):
                    interrupt_info = task.interrupts[0].value
                    print(f"interrupt_info:\n{interrupt_info}")
                    st.session_state.waiting_approval = True
                    st.session_state.pending_config = config
        
        return result
    except Exception as e:
        # 捕获 interrupt 异常 (根据 LangGraph 版本可能不同)
        error_msg = str(e)
        if "interrupt" in error_msg.lower():
            st.session_state.waiting_approval = True
            st.session_state.pending_config = config
            return {"response": f"需要人工确认: 是否执行删除知识图谱操作?\n\n请在输入框中输入[确认删除]或[取消操作]"}
        else:
            return {"response": f"执行失败: {error_msg}", "route": "end"}
        
def start_gateway(port: int = 8001, debug_port: int = 5678):
    """在后台启动 Hermes 网关"""
    # 启动调试监听
    # debugpy.listen(("localhost", debug_port))
    print(f"Hermes 网关 调试器已启动, 监听端口 {debug_port}")
    uvicorn.run(gateway_app, host="0.0.0.0", port=port, reload=False)

def start_fastapi(port: int = 8000, debug_port: int = 5677):
    """在后台启动 FastAPI 业务接口 网关"""
    # 启动调试监听
    # debugpy.listen(("localhost", debug_port))
    print(f"FastAPI 业务接口 网关 调试器已启动, 监听端口 {debug_port}")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port, reload=False)
    
async def run_async(coro):
    """安全运行异步函数的辅助函数"""
    try:
        # 尝试获取当前运行的事件循环
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 没有运行的事件循环, 直接使用 asyncio.run()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    # 已有运行的时间循环, 使用 nest_asyncio 或创建新任务
    return loop.run_until_complete(coro)

def start_bot_in_background(qrcode_status: dict):
    """在后台线程中启动机器人主循环"""
    def bot_task():
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 运行主循环
            loop.run_until_complete(run_bot(qrcode_status.get('bot_token')))

            loop.close()
        except Exception as e:
            print(f"机器人运行异常: {str(e)}")
        
    thread = threading.Thread(target=bot_task, daemon=True)
    thread.start()

def start_login_and_bot_in_background(qrcode: str):
    """
    在后台线程中执行完整流程:
    1. 轮询获取 bot_token
    2. 获取配置
    3. 启动机器人
    """
    def login_and_bot_task():
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 1. 轮询获取 bot_token
            print(f"开始轮询登录状态...")
            qrcode_status = loop.run_until_complete(poll_login_status(qrcode))

            if not qrcode_status:
                loop.close()
                return
            # 2. 保存 qrcode_status
            save_qrcode_status(qrcode_status)

            # 3. 获取配置
            # config = loop.run_until_complete(get_bot_info(qrcode_status.get('bot_token')))
            # if config:
            #     print(f"登录成功, 机器人名称: {config['bot_name']}")

            # 4. 自动启动机器人
            loop.run_until_complete(run_bot(qrcode_status.get('bot_token')))

            loop.close()
        
        except Exception as e:
            print(f"登录流程异常: {str(e)}")
    
    thread = threading.Thread(target=login_and_bot_task, daemon=True)
    thread.start()

# ========== UI 界面 ==========
tab1, tab2, tab3, tab4, tab5 = st.tabs(["智能问答", "资料上传", "多模态", "审批后台", "记忆中"])

# 侧边栏
with st.sidebar:
    st.header("安全鉴权/网关控制")
    token = st.text_input("Token密钥", type="password", value="admin2026ai")
    username = st.text_input("用户名", value="admin")
    st.divider()

    if st.button("生成 SKILL.md 文件"):
        bridge.generate_skill_md_files(SKILL_PATH)
        st.success("SKILL.md 文件成功生成, 可在 Hermes Agent 通过 '/skills list --source local' 查询")
    if st.button("启动 Hermes 网关"):
        if not gateway_running:
            # 在新线程中启动网关
            # http://localhost:8001/docs 查看接口文档
            gateway_thread = threading.Thread(target=start_gateway, args=(8001, 5678), daemon=True)
            gateway_thread.start()
            gateway_running = True
            st.success("Hermes 网关已启动(端口: 8001)")
            st.info("支持Hermes/微信/钉钉/飞书/Telegram接入")
            st.caption("Hermes 端点: http://localhost:8001/api/skill/{skill_name}")
            st.caption("Hermes 端点: http://localhost:8001/api/skills")
            st.caption("网关端点: http://localhost:8001/webhook/{platform}")
            st.caption("API端点: http://localhost:8001/api/chat")
            st.caption("健康检查: http://localhost:8001/health")
        else:
            st.warning("Hermes 网关已在运行中")
    if st.button("启动 FastAPI 业务接口"):
        if not fastapi_running:
            # 在新线程中启动网关
            # http://localhost:8000/docs 查看接口文档
            fastapi_thread = threading.Thread(target=start_fastapi, args=(8000, 5677), daemon=True)
            fastapi_thread.start()
            fastapi_running = True
            st.caption("LangGraph API端点: http://localhost:8000/api/chat")
            st.caption("LangGraph 健康检查: http://localhost:8000/health")
        else:
            st.warning("FastAPI 业务接口已在运行中")
    if st.button("生成微信 ClawBot 登录二维码"):
        print("生成微信 ClawBot 登录二维码...")
        qrcode_result = asyncio.run(get_qrcode())
        print(f"---------- qrcode_result: {qrcode_result} ----------")
        qrcode_url = qrcode_result.get('qrcode_img_content', '')
        qrcode = qrcode_result.get('qrcode', None)
        print(f"---------- qrcode: {qrcode} ----------")
        # 启动后台登录流程(会自动轮询并启动机器人)
        start_login_and_bot_in_background(qrcode)
        print(f"========== 启动后台登录流程(会自动轮询并启动机器人) ==========")
        st.markdown(f"[点击打开二维码链接扫码]({qrcode_url})", unsafe_allow_html=True)
        st.info("打开微信 -> 扫一扫 -> 扫描二维码")

    st.warning("已实现: 鉴权|脱敏|熔断|降级|清洗|优化|人机协同|企业级审批流程|接入Hermes Agent(SKILL.md生成&gateway网关&API接口&WSL环境和Docker环境调用宿主机Ollama、Sqlite、Neo4j)|接入微信 ClawBot")
    st.warning("工程化: Poetry依赖管理及虚拟环境|launch.json代码调试|Cython编译核心模块|PyArmor混淆加密|Docker容器化部署|")

# 1. 智能问答
with tab1:
    st.title("多智能体问答中心")

    # 显示当前状态
    if st.session_state.waiting_approval:
        st.warning(f"有操作等待您确认, 请输入 [确认删除] 或 [取消操作]")

    user_input = st.text_area("请输入问题", height=120,
                               placeholder="例如: 知识: 张三是谁?\n或者: 你是谁?\n或者: 删除知识图谱")
    
    if st.button("发送请求"):
        if not user_input.strip():
            st.error("请输入问题")
        else:
            with st.spinner("AI 思考中..."):
                # 使用支持 interrupt 的运行函数
                result = run_graph_with_config(
                    user_input=user_input,
                    username=username,
                    token=token,
                    thread_id=st.session_state.thread_id
                )
                st.markdown("### AI回答")

                if result.get("reference"):
                    st.write(result.get("reference"))
                if result.get("response"):
                    st.write(result.get("response"))
                if result.get("image"):
                    st.image(result.get("image"), caption=result.get("response"))

                # 如果是等待审批状态, 提示用户
                if st.session_state.waiting_approval:
                    st.warning("**等待确认**: 请输入 [确认删除] 或 [取消操作] 继续")

# 2. 资料上传
with tab2:
    st.title("数据中心")
    st.subheader("RAG知识库上传")
    up_vec_file = st.file_uploader("上传文档(txt/pdf/md)", type=["txt", "pdf", "md"])
    if  up_vec_file:
        save_vec_name = clean_filename(up_vec_file.name)
        save_vec_path = os.path.join(DATA_PATH, save_vec_name)
        with open(save_vec_path, "wb") as f:
            f.write(up_vec_file.read())
        upload_file_to_vector(save_vec_path)
        st.success("上传并向量化完成, 已存入向量库")
    st.subheader("知识图谱上传")
    up_kg_file = st.file_uploader("上传文档(csv: 标题需包含source, relation, target, source_label, target_label; pdf: 由大模型解析)", type=["csv", "pdf"])
    if  up_kg_file:
        file_ext = up_kg_file.name.split(".")[-1].lower()
        save_kg_name = clean_filename(up_kg_file.name)
        save_kg_path = os.path.join(DATA_PATH, save_kg_name)
        with open(save_kg_path, "wb") as f:
            f.write(up_kg_file.read())
        if file_ext == "csv":
            batch_import_triples_with_fixed_format(save_kg_path)
        elif file_ext == "pdf":
            build_kg_from_document(save_kg_path)
        st.success("上传知识图谱完成, 已存入Neo4j数据库")
    triple_input = st.text_area(
        "录入三元组数据(每行一条, 格式: 实体1 -> 关系 -> 实体2 或 实体1,关系,实体2)",
        height=100,
        placeholder="[张无忌] -> [父亲] -> [张翠山]",
        key="manual_triple_input",
        help=kg_input_format()["example"]
    )
    if st.button("提交") and triple_input:
        triples = []
        lines = triple_input.strip().split('\n')
        for line in lines:
            line = line.strip()

            if not line:
                continue

            match = re.search(kg_input_format()["pattern"], line, re.VERBOSE)
            if match:
                source = match.group(1).strip()
                relation = match.group(2).strip()
                target = match.group(3).strip()
                
                if source and relation and target:
                    triples.append((source, relation, target))
        batch_create_triples(triples)

        st.success("提交知识图谱完成, 已存入Neo4j数据库")

# 3. 多模态
with tab3:
    st.title("多模态中心")
    img_file= st.file_uploader("上传图片", type=["jpg", "jpeg", "png"])
    audio_file = st.file_uploader("上传语音", type=["mp3", "wav"])
    if img_file:
        st.image(img_file)
    if audio_file:
        st.audio(audio_file)
    
# 4. 审批后台
with tab4:
    st.title("MPC人工审批后台")
    view_type = st.radio("", ["待我审批", "我的申请", "审批配置"], horizontal=True)
    engine = get_approval_engine()

    if view_type == "待我审批":
        st.subheader(f"待 {username} 审批的申请")

        pending_list = engine.get_pending_requests(username)

        if not pending_list:
            st.info("暂无待审批事项")
        else:
            for req in pending_list:
                with st.expander(f"[{req["flow_type"]}] {req["content"][:50]}..."):
                    st.write(f"**申请单号**: {req['request_id']}")
                    st.write(f"**申请人**: {req['user']}")
                    st.write(f"**申请内容**: {req['content']}")
                    st.write(f"**申请时间**: {req['created_at']}")
                    st.write(f"**当前级别**: 第 {req['current_level']} 级审批")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button(f"通过", key=f"approve_{req['request_id']}"):
                            result = engine.approve(req["request_id"], username, "")
                            st.success(result["message"])
                            st.session_state['need_refresh'] = True
                    with col2:
                        if st.button(f"驳回", key=f"reject_{req['request_id']}"):
                            comment = st.text_input("驳回理由", key=f"comment_{req['request_id']}")
                            if comment:
                                result = engine.reject(req["request_id"], username, comment)
                                st.warning(result["message"])
                                st.session_state['need_refresh'] = True
                    with col3:
                        if st.button(f"转交", key=f"transfer_{req['request_id']}"):
                            target = st.text_input("转交给", key=f"target_{req['request_id']}")
                            if target:
                                result = engine.transfer(req["request_id"], username, target, "")
                                st.info(result["message"])
                                st.session_state['need_refresh'] = True
    elif view_type == "我的申请":
        st.subheader(f"{username} 的申请记录")

        my_requests = engine.get_my_requests(username)

        if not my_requests:
            st.info("暂无申请记录")
        else:
            for req in my_requests:
                with st.expander(f"[{req['status']}] {req['content'][:50]}..."):
                    st.write(f"**申请单号**: {req['request_id']}")
                    st.write(f"**申请内容**: {req['content']}")
                    st.write(f"**状态**: {req['status']}")
                    st.write(f"**申请时间**: {req['created_at']}")

                    # 显示审批进度
                    history = engine.get_approval_history(req["request_id"])
                    if history:
                        st.write("**审批进度**")
                        for h in history:
                            status_icon = f"✅" if h['action'] == "approve" else f"❌" if h['action'] == "reject" else f"⏳"
                            st.write(f"{status_icon} 第{h['level']}级: {h['approver']} - {h['action']}")
    else:
        st.subheader(f"审批流程配置")
        st.info("审批人配置、流程定义等功能开发中")

# 5. 记忆中心
with tab5:
    st.title("长期记忆查询")
    mem = get_long_memory(username)
    st.table(mem)

st.divider()
st.info("LangGraph多智能体|RAG混合检索(文档边界截断&强化Prompt&增加召回数&同义词检索&重排序)|知识图谱(邻居节点+关系)|多模态|工具调用|MPC审批|长短记忆|工程安全")

# ========== 主入口 ==========
if __name__ == "__main__":

    # 执行文件 Python 命令
    if len(sys.argv) > 1:
        if sys.argv[1] == "generate":
            # 生成 SKILL.md 文件
            output_dir = sys.argv[2] if len(sys.argv) > 2 else SKILL_PATH
            bridge.generate_skill_md_files(output_dir)
        elif sys.argv[1] == "gateway":
            # 启动 API 服务
            print("启动 Hermes Skill Bridge API 服务...")
            print("Hermes 网关已启动(端口: 8001)")
            print("支持Hermes/微信/钉钉/飞书/Telegram接入")
            print("Hermes 端点: http://localhost:8001/api/skill/{skill_name}")
            print("Hermes 端点: http://localhost:8001/api/skills")
            print("网关端点: http://localhost:8001/webhook/{platform}")
            print("API端点: http://localhost:8001/api/chat")
            print("健康检查: http://localhost:8001/health")
            uvicorn.run(gateway_app, host="0.0.0.0", port=8001, reload=False)
        elif sys.argv[1] == "serve":
            print("FastAPI 业务接口已启动(端口: 8000)")
            print("LangGraph API端点: http://localhost:8000/api/chat")
            print("LangGraph 健康检查: http://localhost:8000/health")
            uvicorn.run(fastapi_app, host="0.0.0.0", port=8000, reload=False)
        else:
            print("用法:")
            print("python hermes_integration.py generate [输出目录] # 生成 SKILL.md 文件")
            print("python hermes_integration.py serve # 启动 API 服务")
    
    # 检验 bot_token 是否有效
    # st.session_state.bot_token_verify = qrcode_status and asyncio.run(get_bot_info(qrcode_status.get("bot_token"), "", ""))
    # print(f"已存储的 bot_token 有效性: {'是' if st.session_state.bot_token_verify else '否'}")