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
from dotenv import load_dotenv
from config import *
# 导入网关应用
from hermes.hermes_integration import get_hermes_multi_agent_bridge

# 加载环境配置
load_dotenv()

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

# Gateway | FastAPI 实例
bridge = get_hermes_multi_agent_bridge()
gateway_app = bridge.create_gateway_app()
fastapi_app = bridge.create_fastapi_app()
# 用全局变量记录服务状态，防止重复启动
gateway_running = False
fastapi_running = False

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
        
def start_gateway():
    """在后台启动 Hermes 网关"""
    uvicorn.run(gateway_app, host="0.0.0.0", port=8001)

def start_fastapi():
    """在后台启动 FastAPI 业务接口 网关"""
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

# ========== UI 界面 ==========
tab1, tab2, tab3, tab4, tab5 = st.tabs(["智能问答", "资料上传", "多模态", "审批后台", "记忆中"])

# 侧边栏
with st.sidebar:
    st.header("安全鉴权/网关控制")
    token = st.text_input("Token密钥", type="password", value="admin2026ai")
    username = st.text_input("用户名", value="admin")
    st.divider()

    if st.button("生成 SKILL.md 文件"):
        output_dir = "~/.hermes/skills" # 本地主机 windows 目录
        # output_dir = r"\\wsl.localhost\Ubuntu\home\wukai\.hermes\skills" # 虚拟主机 WSL 目录
        bridge.generate_skill_md_files(output_dir)
        st.success("SKILL.md 文件成功生成, 可在 Hermes Agent 通过 '/skills list --source local' 查询")
    if st.button("启动 Hermes 网关"):
        if not gateway_running:
            # 在新线程中启动网关
            # http://localhost:8001/docs 查看接口文档
            gateway_thread = threading.Thread(target=start_gateway, daemon=True)
            gateway_thread.start()
            gateway_running = True
            st.success("Hermes 网关已启动(端口: 8001)")
            st.info("支持Hermes/微信/钉钉/飞书/Telegram接入")
            st.caption("Hermes 端点: http://localhost:8001/api/skill/{skill_name}")
            st.caption("Hermes 端点: http://localhost:8001/api/skill/skills")
            st.caption("网关端点: http://localhost:8001/webhook/{platform}")
            st.caption("API端点: http://localhost:8001/api/chat")
            st.caption("健康检查: http://localhost:8001/health")
        else:
            st.warning("Hermes 网关已在运行中")
    if st.button("启动 FastAPI 业务接口"):
        if not fastapi_running:
            # 在新线程中启动网关
            # http://localhost:8000/docs 查看接口文档
            fastapi_thread = threading.Thread(target=start_fastapi, daemon=True)
            fastapi_thread.start()
            fastapi_running = True
            st.caption("LangGraph API端点: http://localhost:8000/api/chat")
            st.caption("LangGraph 健康检查: http://localhost:8000/health")
        else:
            st.warning("FastAPI 业务接口已在运行中")

    st.warning("已实现: 鉴权|脱敏|熔断|降级|清洗|优化|人机协同|企业级审批流程")

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