from py2neo import Graph
from config import *

neo4j_graph = Graph(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASSWORD))

def kg_search(query: str) -> list:
    cypher = """MATCH (n)-[r]->(m)
    WHERE n.name CONTAINS $q OR m.name CONTAINS $q
    RETURN n,r,m LIMIT 5"""
    return neo4j_graph.run(cypher, q = query).data()

def kg_clear_all():
    neo4j_graph.run("MATCH (n) DETACH DELETE n")