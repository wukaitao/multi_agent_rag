from neo4j import GraphDatabase
from typing import List, Dict, Any, Optional
from config import *
import re
# LLM 自动构建
import os
import asyncio
from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline
from neo4j_graphrag.llm import OllamaLLM
from neo4j_graphrag.embeddings import OllamaEmbeddings
from neo4j_graphrag.experimental.components.lexical_graph import LexicalGraphConfig
from neo4j_graphrag.experimental.components.entity_relation_extractor import ERExtractionTemplate

class Neo4jConnection:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD)
        )

    def close(self):
        self.driver.close()
    
    def kg_search(self, query: str) -> list:
        """基础知识图谱检索"""
        # 提取实体
        entities = self._extract_entities(query)

        if not entities:
            return "未识别到实体"
        
        results =[]
        for entity in entities:
            with self.driver.session() as session:
                # 查询实体属性
                result = session.run(
                    """
                    MATCH (n {name: $entity})
                    RETURN n.name as name, keys(n) as props,
                        [k in keys(n) WHERE k <> 'name' | k + ':' + toString(n[k])] as prop_list
                    LIMIT 5
                    """,
                    entity=entity
                )
                for record in result:
                    results.append(f"{record["name"]}: {', '.join(record['prop_list'])}")
        return "\n".join(results) if results else "未找到相关知识"

    def kg_search_with_context(self, query: str, depth=1) -> str:
        """带上下文的知识图谱检索(邻居节点)"""
        entities = self._extract_entities(query)

        if not entities:
            return ""
        
        contexts = []
        for entity in entities:
            with self.driver.session() as session:
                # 查询实体及其邻居
                result = session.run(
                    """
                    MATCH (n {name: $entity})
                    OPTIONAL MATCH (n)-[r]-(neighbor)
                    RETURN n.name as main,
                        collect(DISTINCT neighbor.name) as neighbors,
                        collect(DISTINCT type(r)) as relations
                    """,
                    entity=entity
                )
                for record in result:
                    neighbors = [n for n in record["neighbors"] if n]
                    if neighbors:
                        contexts.append(
                            f"{record["main"]}关联: {', '.join(neighbors[:5])} "
                            f"(关系: {', '.join(record['relations'][:3])})"
                        )
        return "\n".join(contexts) if contexts else ""
    
    def kg_clear_all(self):
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    def _extract_entities(self, text: str) -> list:
        print(f"=== text:{text} ===")
        """实体抽取(改进版)"""
        entities = []

        # 1. 人名识别(中文)
        chinese_names = re.findall(r"[\u4e00-\u9fa5]{2,4}(?:是|的|指|叫)", text)
        if chinese_names:
            entities.extend([name[:-1] for name in chinese_names])
        print(f"=== chinese_names:{chinese_names} ===")

        # 2. 英文单词识别(首字母大写或全大写)
        english_entities = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text)
        entities.extend(english_entities)

        # 3. 关键词提取(分词后去名词, 简版)
        words = text.split()
        potential_nouns = [w for w in words if len(w) > 1 and w.isalnum()]
        entities.extend(potential_nouns[:3])
        print(f"=== entities:{entities} ===")

        # 去重
        return list(set(entities))[:5]
    
    # ========== 知识图谱写入方法 ==========
    def create_node_if_not_exists(self, label: str, name: str, **extra_props) -> bool:
        """使用MERGE避免重复创建节点(基于name属性)"""
        try:
            with self.driver.session() as session:
                props = {"name": name, **extra_props}
                prop_str = ", ".join([f"{k}: ${k}" for k in props.keys()])
                session.run(
                    f"MERGE (n:{label} {{{prop_str}}})",
                    **props
                )
                return True
        except Exception as e:
            print(f"创建节点失败: {e}")
            return False
        
    def create_relationship(self, from_node: Dict, to_node: Dict, rel_type: str) -> bool:
        """创建两个节点之间的关系"""
        try:
            with self.driver.session() as session:
                result = session.run(
                    f"""
                    MATCH (a {{name: $from_name}})
                    MATCH (b {{name: $to_name}})
                    MERGE (a)-[:{rel_type}] -> (b)
                    """,
                    from_name=from_node.get("name", from_node.get("id")),
                    to_name=to_node.get("name", to_node.get("id"))
                )
                return True
        except Exception as e:
            print(f"创建关系失败: {e}")
            return False
        
    def batch_create_triples(self, triples: List[tuple]) -> int:
        """批量创建三元组(实体1, 关系, 实体2, 可选标签/属性)
        Args: triples: 三元组列表, 格式为 [(head, relation, tail, labal, props), ...]
                       或 [(head, relation, tail), ...]
        """
        count = 0
        with self.driver.session() as session:
            for triple in triples:
                try:
                    if len(triple) == 3:
                        head, relation, tail = triple
                        label = "Entity"
                        props = {}
                    elif len(triple) == 4:
                        head, relation, tail, label = triple
                        props = {}
                    else:
                        head, relation, tail, label, props = triple

                    # 使用MERGE避免重复
                    session.run(
                        f"""
                        MERGE (a:{label} {{name: $head}})
                        MERGE (b:{label} {{name: $tail}})
                        MERGE (a)-[:{relation}]->(b)
                        """,
                        head=head, tail=tail
                    )
                    count += 1
                except Exception as e:
                    print(f"创建三元组失败 {head} - {relation} -> {tail}: {e}")
            return count

    
# 全局实例
_neo4j_conn = Neo4jConnection()

def kg_search(query: str) -> str:
    return _neo4j_conn.kg_search(query)

def kg_search_with_context(query: str) -> str:
    return _neo4j_conn.kg_search_with_context(query)

def kg_clear_all():
    _neo4j_conn.kg_clear_all()

def create_node(label: str, name: str, **props):
    return _neo4j_conn.create_node_if_not_exists(label, name, **props)

def create_relationship(from_name: str, to_name: str, rel_type: str):
    return _neo4j_conn.create_relationship(from_name, to_name, rel_type)

def batch_create_triples(triples: List[tuple]):
    return _neo4j_conn.batch_create_triples(triples)

def batch_import_triples(triples_file: str):
    """从CSV文件批量导入三元组(走批量创建三元组方法, 无标题栏)"""
    import csv
    triples = []
    with open(triples_file, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) >= 3:
                triples.append((row[0], row[1], row[2]))
    return _neo4j_conn.batch_create_triples(triples)

def batch_import_triples_with_fixed_format(triples_file: str):
    """从CSV文件导出三元组(遍历行走创建节点和关系的方法, 固定标题栏: source, relation, target, source_label, target_label)"""
    import csv
    with open(triples_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            source = row.get("source")
            relation = row.get("relation")
            target = row.get("target")
            label = row.get("source_label", "Entity")

            if not all([source, relation, target]):
                print(f"跳过无效行: {row}")
                continue

            # 创建源节点和目标节点
            _neo4j_conn.create_node_if_not_exists(label, source)
            _neo4j_conn.create_node_if_not_exists(label, target)

            # 创建关系
            _neo4j_conn.create_relationship({"name": source}, {"name": target}, relation)
            count += 1
            print(f"已导入: {source} - [{relation}] -> {target}")
        print(f"\n导入完成, 共导入 {count} 条关系")

def build_kg_from_document(file_path: str):
    """通过 LLM 智能抽取文档中数据构建知识图谱"""
    print("========== build_kg_from_document ==========")

    # 使用Ollama的LLM和Embedding(免费本地)
    llm = OllamaLLM(
        model_name="deepseek-r1:1.5b"
    )
    embed_model = OllamaEmbeddings(
        model=EMBED_MODEL,
        base_url=LLM_BASE_URL
    )

    system_instruction=UNIVERSAL_HIGH_PRECISION_PROMPT

    # 构建知识图谱管道
    kg_builder = SimpleKGPipeline(
        llm=llm,
        embedder=embed_model,
        driver=_neo4j_conn.driver,
        from_pdf=file_path.endswith(".pdf"),

        # ========== 关键优化参数 ==========

        # 1. 自定义提取提示词
        # prompt_template=ERExtractionTemplate(
        #     system_instructions=system_instruction
        # ),

        # 2. 明确定义你关心的实体和关系类型
        schema={
            "node_types": ["Person", "TVSeries", "Book", "Role", "Director"],
            "relationship_types": ["父亲", "师从于", "教导", "主演", "导演", "改编自", "作者"],
            "patterns": [
                ("Person", "父亲", "Person"),
                ("Person", "师从于", "Person"),
                ("Person", "主演", "TVSeries"),
                ("Person", "导演", "TVSeries"),
                ("TVSeries", "改编自", "Book"),
                ("Person", "作者", "Book"),
            ],
            "additional_node_types": False,
            "additional_relationship_types": False
        },
        
        # 3. 保持实体解析开启，确保同名实体合并（如“张三丰”不会重复出现）
        perform_entity_resolution=True,
        
        # 4. 【可选】如果想彻底关闭文档溯源节点，保留方案二中的配置
        lexical_graph_config=LexicalGraphConfig(enabled=False)
    )

    # 运行
    result = asyncio.run(kg_builder.run_async(file_path=file_path))
    print(f"构建完成:\n {result}")

    # 输出结果
    if hasattr(result, 'triples'):
        print(f"\n共提取 {len(result.triples)} 条三元组")
        for triple in result.triples[:10]:
            print(f"{triple.subject} -> {triple.relation} -> {triple.object}")
    
    return result