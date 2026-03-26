"""
UI状態管理クラス
アプリケーションの状態を保存・復元
"""
import yaml
from pathlib import Path
from typing import Optional, Tuple


class UIStateManager:
    """UI状態管理クラス"""
    
    def __init__(self, state_file: str = "ui_state.yaml", config_file: str = "config.yaml"):
        self.state_file = Path(state_file)
        self.config_file = Path(config_file)
        self.state = self.load_state()
        self.config = self.load_config()
    
    def load_config(self) -> dict:
        """config.yamlからUI設定を読み込む"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                    return config.get('ui', {})
            except Exception as e:
                print(f"Config load error: {e}")
                return {}
        return {}
    
    def load_state(self) -> dict:
        """状態を読み込む"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                print(f"UI state load error: {e}")
                return {}
        else:
            # デフォルト状態
            return {
                'last_thread_id': None
            }
    
    def save_state(self):
        """状態を保存"""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                yaml.dump(self.state, f, allow_unicode=True, default_flow_style=False)
        except Exception as e:
            print(f"UI state save error: {e}")
    
    def get_last_thread_id(self) -> Optional[str]:
        """最後のスレッドIDを取得"""
        return self.state.get('last_thread_id')
    
    def set_last_thread_id(self, thread_id: str):
        """最後のスレッドIDを保存"""
        self.state['last_thread_id'] = thread_id
        self.save_state()
    
    def get_window_size(self) -> Tuple[int, int]:
        """ウィンドウサイズを取得（config.yaml優先、なければui_state.yaml）"""
        # まずconfigから取得
        if 'window' in self.config:
            width = self.config['window'].get('width', 1400)
            height = self.config['window'].get('height', 800)
            return (width, height)
        
        # configになければstateから
        window = self.state.get('window', {})
        return (window.get('width', 1400), window.get('height', 800))
    
    def set_window_size(self, width: int, height: int):
        """ウィンドウサイズを保存（ui_state.yamlに保存）"""
        if 'window' not in self.state:
            self.state['window'] = {}
        self.state['window']['width'] = width
        self.state['window']['height'] = height
        self.save_state()
    
    def get_splitter_ratio(self) -> Tuple[float, float]:
        """スプリッター比率を取得（ui_state.yamlから）"""
        ratio = self.state.get('splitter_ratio', {})
        return (ratio.get('character', 0.4), ratio.get('message', 0.6))
    
    def set_splitter_ratio(self, character: float, message: float):
        """スプリッター比率を保存（ui_state.yamlに保存）"""
        self.state['splitter_ratio'] = {
            'character': character,
            'message': message
        }
        self.save_state()
    
    def get_ui_config(self, key: str, default=None):
        """UI設定を取得"""
        return self.config.get(key, default)
