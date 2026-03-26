"""
Embeddingマネージャー
メッセージのベクトル化と検索を管理
チャンク化により文脈を保持
"""
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


class EmbeddingManager:
    """Embeddingマネージャー"""
    
    def __init__(self, llm_config_path: str = "config.yaml"):
        self.config = self.load_config(llm_config_path)
        self.model = None
        self.vector_dbs = {}  # グループ名 -> VectorDBAdapter
        self.message_buffers = {}  # グループ名 -> メッセージバッファ（チャンク化用）
        
        # chunk_sizeを設定から読み込み
        self.chunk_size = self.config.get('embedding', {}).get('chunk_size', 3)
        
        # verbose設定を取得
        self.verbose = self.config.get('ui', {}).get('verbose', False)
    
    def load_config(self, config_path: str) -> Dict[str, Any]:
        """設定ファイルを読み込む"""
        path = Path(config_path)
        if not path.exists():
            return {
                'embedding': {
                    'enabled': False,
                    'model_name': 'BAAI/bge-m3',
                    'db_url': ''
                }
            }
        
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def is_enabled(self) -> bool:
        """Embedding機能が有効かどうか"""
        return self.config.get('embedding', {}).get('enabled', False)
    
    def load_model(self):
        """Embeddingモデルをロード"""
        if self.model is not None:
            return  # 既にロード済み
        
        if not self.is_enabled():
            if self.verbose:
                print("Embedding is disabled")
            return
        
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError("sentence-transformers is not installed. Run: pip install sentence-transformers")
        
        model_name = self.config['embedding'].get('model_name', 'BAAI/bge-m3')
        if self.verbose:
            print(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        if self.verbose:
            print("Embedding model loaded successfully")
    
    def get_vector_db(self, group_name: str):
        """グループのベクトルDBを取得（キャッシュ）"""
        if group_name not in self.vector_dbs:
            from vector_db_adapter import create_vector_db
            self.vector_dbs[group_name] = create_vector_db(
                self.config.get('embedding', {}),
                group_name
            )
        return self.vector_dbs[group_name]
    
    def add_message(self, group_name: str, message_id: str, role: str, content: str, thread_id: str):
        """メッセージをベクトルDBに追加（チャンク化）"""
        if not self.is_enabled():
            return
        
        # バッファキーを作成（グループ + スレッド）
        buffer_key = f"{group_name}:{thread_id}"
        
        # バッファ初期化
        if buffer_key not in self.message_buffers:
            self.message_buffers[buffer_key] = []
        
        # メッセージをバッファに追加
        message_obj = {
            'id': message_id,
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat()
        }
        self.message_buffers[buffer_key].append(message_obj)
        
        # チャンクサイズに達したらベクトル化
        if len(self.message_buffers[buffer_key]) >= self.chunk_size:
            self._create_chunk(group_name, thread_id, buffer_key)
    
    def _create_chunk(self, group_name: str, thread_id: str, buffer_key: str):
        """チャンクを作成してベクトルDBに追加"""
        import json
        
        # モデルロード
        self.load_model()
        
        # バッファからチャンク取得
        messages = self.message_buffers[buffer_key][:self.chunk_size]
        
        # チャンク全体のテキストを結合
        chunk_text = "\n".join([
            f"{msg['role']}: {msg['content']}" 
            for msg in messages
        ])
        
        # ベクトル化
        vector = self.model.encode(chunk_text).tolist()
        
        # チャンクID生成
        chunk_id = f"{thread_id}_chunk_{datetime.now().timestamp()}"
        
        # メタデータ（messagesはJSON文字列に変換）
        metadata = {
            'text': chunk_text,
            'messages_json': json.dumps(messages, ensure_ascii=False),  # JSON文字列化
            'thread_id': thread_id,
            'group': group_name,
            'timestamp': datetime.now().isoformat(),
            'message_count': len(messages)
        }
        
        # ベクトルDBに追加
        db = self.get_vector_db(group_name)
        db.add(ids=[chunk_id], vectors=[vector], metadatas=[metadata])
        if self.verbose:
            print(f"Added chunk to vector DB: {chunk_id} (group: {group_name}, {len(messages)} messages)")
        
        # バッファから最初の1メッセージを削除（スライディングウィンドウ）
        self.message_buffers[buffer_key].pop(0)
    
    def flush_buffer(self, group_name: str, thread_id: str):
        """バッファに残ったメッセージを強制的にベクトル化"""
        import json
        
        if not self.is_enabled():
            return
        
        buffer_key = f"{group_name}:{thread_id}"
        
        # バッファが空なら何もしない
        if buffer_key not in self.message_buffers or not self.message_buffers[buffer_key]:
            return
        
        messages = self.message_buffers[buffer_key]
        
        # 1発言以上あればチャンク化
        if len(messages) >= 1:
            # モデルロード
            self.load_model()
            
            # チャンク全体のテキストを結合
            chunk_text = "\n".join([
                f"{msg['role']}: {msg['content']}" 
                for msg in messages
            ])
            
            # ベクトル化
            vector = self.model.encode(chunk_text).tolist()
            
            # チャンクID生成
            chunk_id = f"{thread_id}_chunk_{datetime.now().timestamp()}"
            
            # メタデータ（messagesはJSON文字列に変換）
            metadata = {
                'text': chunk_text,
                'messages_json': json.dumps(messages, ensure_ascii=False),  # JSON文字列化
                'thread_id': thread_id,
                'group': group_name,
                'timestamp': datetime.now().isoformat(),
                'message_count': len(messages)
            }
            
            # ベクトルDBに追加
            db = self.get_vector_db(group_name)
            db.add(ids=[chunk_id], vectors=[vector], metadatas=[metadata])
            if self.verbose:
                print(f"Flushed buffer to vector DB: {chunk_id} (group: {group_name}, {len(messages)} messages)")
            
            # バッファをクリア
            self.message_buffers[buffer_key] = []
    
    def flush_all_buffers(self):
        """全バッファをフラッシュ"""
        for buffer_key in list(self.message_buffers.keys()):
            # buffer_key = "group_name:thread_id"
            parts = buffer_key.split(':', 1)
            if len(parts) == 2:
                group_name, thread_id = parts
                self.flush_buffer(group_name, thread_id)
    
    def search(self, group_name: str, query: str, top_k: int = 5, thread_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """類似メッセージを検索"""
        import json
        
        if not self.is_enabled():
            return []
        
        # モデルロード
        self.load_model()
        
        # クエリをベクトル化
        query_vector = self.model.encode(query).tolist()
        
        # フィルタ設定
        filter_dict = None
        if thread_id:
            filter_dict = {'thread_id': thread_id}
        
        # 検索
        db = self.get_vector_db(group_name)
        results = db.search(query_vector, top_k=top_k, filter=filter_dict)
        
        # 結果を整形（JSON文字列をデコード）
        formatted_results = []
        for result in results:
            metadata = result.get('metadata', {})
            
            # チャンク全体のテキストを取得
            chunk_text = metadata.get('text', '')
            
            # messages_jsonをデコード
            messages_json = metadata.get('messages_json', '[]')
            try:
                messages = json.loads(messages_json)
            except:
                messages = []
            
            formatted_results.append({
                'chunk_text': chunk_text,
                'messages': messages,
                'thread_id': metadata.get('thread_id'),
                'group': metadata.get('group'),
                'timestamp': metadata.get('timestamp'),
                'distance': result.get('distance'),
                'message_count': metadata.get('message_count', 0)
            })
        
        return formatted_results
    
    def delete_message(self, group_name: str, message_id: str):
        """メッセージを削除"""
        if not self.is_enabled():
            return
        
        db = self.get_vector_db(group_name)
        db.delete(ids=[message_id])
        if self.verbose:
            print(f"Deleted message from vector DB: {message_id}")
    
    def rename_group_vector_db(self, old_group_name: str, new_group_name: str):
        """グループのベクトルDBをリネーム"""
        old_dir = Path(f"threads/_vector_db_{old_group_name}")
        new_dir = Path(f"threads/_vector_db_{new_group_name}")
        
        if old_dir.exists():
            old_dir.rename(new_dir)
            if self.verbose:
                print(f"Renamed vector DB: {old_group_name} -> {new_group_name}")
            
            # キャッシュをクリア
            if old_group_name in self.vector_dbs:
                del self.vector_dbs[old_group_name]
    
    def delete_group_vector_db(self, group_name: str):
        """グループのベクトルDBを削除"""
        import shutil
        db_dir = Path(f"threads/_vector_db_{group_name}")
        
        if db_dir.exists():
            shutil.rmtree(db_dir)
            if self.verbose:
                print(f"Deleted vector DB: {group_name}")
            
            # キャッシュをクリア
            if group_name in self.vector_dbs:
                del self.vector_dbs[group_name]
