"""
ベクトルDB抽象化レイヤー
ChromaDB、Qdrant、FAISSなど複数のDBに対応
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pathlib import Path


class VectorDBAdapter(ABC):
    """ベクトルDB抽象基底クラス"""
    
    @abstractmethod
    def add(self, ids: List[str], vectors: List[List[float]], metadatas: List[Dict[str, Any]]) -> None:
        """ベクトルを追加"""
        pass
    
    @abstractmethod
    def search(self, query_vector: List[float], top_k: int = 5, filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """ベクトル検索"""
        pass
    
    @abstractmethod
    def delete(self, ids: List[str]) -> None:
        """ベクトルを削除"""
        pass
    
    @abstractmethod
    def get_all(self) -> List[Dict[str, Any]]:
        """全ベクトルを取得"""
        pass


class ChromaDBAdapter(VectorDBAdapter):
    """ChromaDB アダプター"""
    
    def __init__(self, collection_name: str, persist_directory: str):
        try:
            import chromadb
        except ImportError:
            raise ImportError("chromadb is not installed. Run: pip install chromadb")
        
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(name=collection_name)
    
    def add(self, ids: List[str], vectors: List[List[float]], metadatas: List[Dict[str, Any]]) -> None:
        """ベクトルを追加"""
        # ChromaDBはdocumentsも必須なので、メタデータからテキストを取得
        documents = [meta.get('text', '') for meta in metadatas]
        self.collection.add(
            ids=ids,
            embeddings=vectors,
            metadatas=metadatas,
            documents=documents
        )
    
    def search(self, query_vector: List[float], top_k: int = 5, filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """ベクトル検索"""
        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=filter
        )
        
        # 結果を整形
        formatted_results = []
        if results['ids'] and len(results['ids']) > 0:
            for i in range(len(results['ids'][0])):
                formatted_results.append({
                    'id': results['ids'][0][i],
                    'distance': results['distances'][0][i] if 'distances' in results else None,
                    'metadata': results['metadatas'][0][i] if results['metadatas'] else {},
                    'document': results['documents'][0][i] if results['documents'] else ''
                })
        
        return formatted_results
    
    def delete(self, ids: List[str]) -> None:
        """ベクトルを削除"""
        self.collection.delete(ids=ids)
    
    def get_all(self) -> List[Dict[str, Any]]:
        """全ベクトルを取得"""
        results = self.collection.get()
        formatted_results = []
        
        if results['ids']:
            for i in range(len(results['ids'])):
                formatted_results.append({
                    'id': results['ids'][i],
                    'metadata': results['metadatas'][i] if results['metadatas'] else {},
                    'document': results['documents'][i] if results['documents'] else ''
                })
        
        return formatted_results


class QdrantAdapter(VectorDBAdapter):
    """Qdrant アダプター"""
    
    def __init__(self, collection_name: str, url: str):
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams, PointStruct
        except ImportError:
            raise ImportError("qdrant-client is not installed. Run: pip install qdrant-client")
        
        self.client = QdrantClient(url=url)
        self.collection_name = collection_name
        self.Distance = Distance
        self.VectorParams = VectorParams
        self.PointStruct = PointStruct
        
        # コレクション作成（存在しない場合）
        try:
            self.client.get_collection(collection_name)
        except:
            # ベクトル次元数は後で設定（最初のadd時に決定）
            pass
    
    def add(self, ids: List[str], vectors: List[List[float]], metadatas: List[Dict[str, Any]]) -> None:
        """ベクトルを追加"""
        # コレクションが存在しない場合は作成
        try:
            self.client.get_collection(self.collection_name)
        except:
            vector_size = len(vectors[0])
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=self.VectorParams(size=vector_size, distance=self.Distance.COSINE)
            )
        
        points = [
            self.PointStruct(id=hash(id_), vector=vector, payload=metadata)
            for id_, vector, metadata in zip(ids, vectors, metadatas)
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)
    
    def search(self, query_vector: List[float], top_k: int = 5, filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """ベクトル検索"""
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=top_k,
            query_filter=filter
        )
        
        formatted_results = []
        for result in results:
            formatted_results.append({
                'id': str(result.id),
                'distance': result.score,
                'metadata': result.payload
            })
        
        return formatted_results
    
    def delete(self, ids: List[str]) -> None:
        """ベクトルを削除"""
        point_ids = [hash(id_) for id_ in ids]
        self.client.delete(collection_name=self.collection_name, points_selector=point_ids)
    
    def get_all(self) -> List[Dict[str, Any]]:
        """全ベクトルを取得"""
        # Qdrantは全件取得APIがないので、スクロールを使用
        results = []
        offset = None
        
        while True:
            response = self.client.scroll(
                collection_name=self.collection_name,
                limit=100,
                offset=offset
            )
            
            for point in response[0]:
                results.append({
                    'id': str(point.id),
                    'metadata': point.payload
                })
            
            if response[1] is None:
                break
            offset = response[1]
        
        return results


def create_vector_db(config: Dict[str, Any], group_name: str) -> VectorDBAdapter:
    """
    設定に基づいてベクトルDBを作成
    
    Args:
        config: embedding設定
        group_name: グループ名
    
    Returns:
        VectorDBAdapter: ベクトルDBアダプター
    """
    db_url = config.get('db_url', '')
    
    # URLが空ならローカルChromaDB
    if not db_url:
        persist_dir = f"threads/_vector_db_{group_name}"
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        return ChromaDBAdapter(collection_name="messages", persist_directory=persist_dir)
    
    # URLからDB種類を判定
    if 'qdrant' in db_url or ':6333' in db_url:
        collection_name = f"messages_{group_name}"
        return QdrantAdapter(collection_name=collection_name, url=db_url)
    
    # デフォルトはChromaDB
    persist_dir = f"threads/_vector_db_{group_name}"
    Path(persist_dir).mkdir(parents=True, exist_ok=True)
    return ChromaDBAdapter(collection_name="messages", persist_directory=persist_dir)
