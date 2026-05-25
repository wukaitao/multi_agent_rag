import streamlit as st
import asyncio
from main_graph import graph
from database.chroma_conn import upload_file_to_vector
from database.neo4j_conn import batch_create_triples, batch_import_triples_with_fixed_format, build_kg_from_document
from core.cleaner import clean_filename
from core.memory_manager import get_long_memory
from core.optimizer import kg_input_format
from agents.approval_agent import init_approval_table
import sqlite3
import os
import re
from config import *

st.set_page_config(page_title="企业多Agent智能平台", layout="wide")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["智能问答", "资料上传", "多模态", "审批后台", "记忆中"])

# 侧边栏
with st.sidebar:
    st.header("安全鉴权")
    token = st.text_input("Token密钥", type="password", value="admin2026ai")
    username = st.text_input("用户名", value="admin")
    st.divider()
    st.warning("已全部实现: 鉴权|脱敏|熔断|降级|清洗|优化")

# 1. 智能问答
with tab1:
    st.title("多智能体问答中心")
    user_input = st.text_area("请输入问题", height=120)
    if st.button("发送请求"):
        with st.spinner("AI思考中..."):
            res = graph.invoke({
                "user": username,
                "token": token,
                "query": user_input,
                "prompt": "",
                "image": "",
                "reference": "",
                "response": "",
                "route": ""
            })
            st.markdown("### AI回答")
            if res["reference"]:
                st.write(res["reference"])
            if res["response"]:
                st.write(res["response"])
            if res["image"]:
                st.image(res["image"], caption=res["response"])

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
    conn = sqlite3.connect(MEMORY_DB)
    data = conn.execute("SELECT * FROM approval_list").fetchall()
    st.table(data)
    conn.close()

# 5. 记忆中心
with tab5:
    st.title("长期记忆查询")
    mem = get_long_memory(username)
    st.table(mem)

st.divider()
st.info("LangGraph多智能体|RAG混合检索(文档边界截断&强化Prompt&增加召回数&同义词检索&重排序)|知识图谱(邻居节点+关系)|多模态|工具调用|MPC审批|长短记忆|工程安全")