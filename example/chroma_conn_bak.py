from llama_index.core import Settings, SimpleDirectoryReader, VectorStoreIndex, StorageContext
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.ollama import OllamaEmbedding
import chromadb
from config import *

Settings.embed_model = OllamaEmbedding(
    model_name=EMBED_MODEL,
    base_url=LLM_BASE_URL
)
Settings.chunk_size = 500

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
chroma_collection = chroma_client.get_or_create_collection("ai_knowledage")
vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
storage_context = StorageContext.from_defaults(vector_store=vector_store)

def upload_file_to_vector(file_path: str):
    doc = SimpleDirectoryReader(input_files=[file_path]).load_data()
    index = VectorStoreIndex.from_documents(doc, storage_context=storage_context)
    return index

def vector_search(query: str, top_k=3) -> list:
    index = VectorStoreIndex.from_vector_store(vector_store)
    ret = index.as_retriever(similarity_top_k=top_k)
    return ret.retrieve(query)