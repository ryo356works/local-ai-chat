"""
スレッド管理クラス
threads/ディレクトリ内のスレッドを管理
"""
import os
import json
import yaml
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional


class ThreadManager:
    """スレッド管理クラス"""
    
    def __init__(self, threads_dir: str = "threads"):
        self.threads_dir = Path(threads_dir)
        self.threads_dir.mkdir(exist_ok=True)
    
    def get_all_threads(self) -> List[str]:
        """すべてのスレッドIDを取得"""
        threads = []
        
        for item in self.threads_dir.iterdir():
            if item.is_dir():
                # config.yamlが存在するディレクトリのみ
                if (item / "config.yaml").exists():
                    threads.append(item.name)
        
        return sorted(threads)
    
    def get_thread_config(self, thread_id: str) -> Optional[Dict]:
        """スレッドの設定を取得"""
        config_path = self.threads_dir / thread_id / "config.yaml"
        
        if not config_path.exists():
            return None
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"Error loading config for {thread_id}: {e}")
            return None
    
    def save_thread_config(self, thread_id: str, config: Dict):
        """スレッドの設定を保存"""
        thread_dir = self.threads_dir / thread_id
        thread_dir.mkdir(exist_ok=True)
        
        config_path = thread_dir / "config.yaml"
        
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    def create_thread(self, thread_id: str, thread_name: str = None) -> bool:
        """新しいスレッドを作成"""
        thread_dir = self.threads_dir / thread_id
        
        if thread_dir.exists():
            print(f"Thread {thread_id} already exists")
            return False
        
        # ディレクトリ構造を作成
        thread_dir.mkdir(parents=True)
        (thread_dir / "embeddings").mkdir()
        (thread_dir / "images").mkdir()
        
        # template_config.yamlからconfig.yamlをコピー
        template_config_path = Path("template_config.yaml")
        target_config = thread_dir / "config.yaml"
        
        if template_config_path.exists():
            import shutil
            shutil.copy(template_config_path, target_config)
        else:
            # テンプレートがない場合はデフォルト作成
            default_config = {
                "thread_name": thread_name or thread_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "description": "",
                "pinned": False,
                "color": "#3399ff",
                "system_prompt": "あなたは親切なAIアシスタントです。",
                "backend": {
                    "url": "http://127.0.0.1:8000",
                    "timeout": 0
                },
                "llm_parameters": {
                    "temperature": 0.7,
                    "max_tokens": 512,
                    "top_p": 0.9,
                    "repeat_penalty": 1.1
                },
                "character": {
                    "image": ""
                }
            }
            with open(target_config, 'w', encoding='utf-8') as f:
                yaml.dump(default_config, f, allow_unicode=True, default_flow_style=False)
        
        # config.yamlを更新
        config = self.get_thread_config(thread_id)
        config['created_at'] = datetime.now(timezone.utc).isoformat()
        
        if thread_name:
            config['thread_name'] = thread_name
        else:
            config['thread_name'] = thread_id
        
        self.save_thread_config(thread_id, config)
        
        # 空のhistory.jsonを作成
        history_path = thread_dir / "history.json"
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump([], f)
        
        print(f"Created thread: {thread_id}")
        return True
    
    def delete_thread(self, thread_id: str) -> bool:
        """スレッドを削除"""
        thread_dir = self.threads_dir / thread_id
        
        if not thread_dir.exists():
            print(f"Thread {thread_id} does not exist")
            return False
        
        shutil.rmtree(thread_dir)
        print(f"Deleted thread: {thread_id}")
        return True
    
    def get_history_path(self, thread_id: str) -> Path:
        """スレッドの履歴ファイルパスを取得"""
        return self.threads_dir / thread_id / "history.json"
    
    def load_history(self, thread_id: str, limit: int = 50) -> List[Dict]:
        """スレッドの履歴を読み込む"""
        history_path = self.get_history_path(thread_id)
        
        if not history_path.exists():
            return []
        
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                full_history = json.load(f)
                return full_history[-limit:]
        except Exception as e:
            print(f"Error loading history for {thread_id}: {e}")
            return []
    
    def append_to_history(self, thread_id: str, role: str, content: str):
        """スレッドの履歴にメッセージを追加"""
        history_path = self.get_history_path(thread_id)
        
        # ディレクトリが存在しない場合は作成
        history_path.parent.mkdir(parents=True, exist_ok=True)
        
        history = []
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except json.JSONDecodeError:
                history = []
        
        entry = {
            "role": role,
            "content": content,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        history.append(entry)
        
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    
    def get_pinned_threads(self) -> List[str]:
        """ピン留めされたスレッドを取得"""
        all_threads = self.get_all_threads()
        pinned = []
        
        for thread_id in all_threads:
            config = self.get_thread_config(thread_id)
            if config and config.get('pinned', False):
                pinned.append(thread_id)
        
        return pinned
    
    def get_unpinned_threads(self) -> List[str]:
        """ピン留めされていないスレッドを取得"""
        all_threads = self.get_all_threads()
        unpinned = []
        
        for thread_id in all_threads:
            config = self.get_thread_config(thread_id)
            if config and not config.get('pinned', False):
                unpinned.append(thread_id)
        
        return unpinned
