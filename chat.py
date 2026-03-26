"""
PyQt5版 AIチャットアプリケーション（サイドバー付き）
"""
import sys
import os
import json
import yaml
import httpx
import uuid
import subprocess
import atexit
from pathlib import Path
from datetime import datetime, timezone
from io import BytesIO

# IMEを有効化（PyQt5起動前に設定）
os.environ['QT_IM_MODULE'] = 'fcitx'

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem,
    QSplitter, QFrame, QInputDialog, QMessageBox, QAction
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import Qt, QUrl, QTimer, QSize
from PyQt5.QtGui import QPixmap, QFont, QColor

from new_thread_dialog import NewThreadDialog
from ui_state_manager import UIStateManager

try:
    from PIL import Image, ImageOps
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("Warning: Pillow not installed. EXIF rotation will not work.")


# グローバル変数：バックエンドプロセスとアクティビティ
backend_processes = {}  # {backend_url: process}
backend_activities = {}  # {backend_url: last_activity_datetime}


class ThreadListWidget(QListWidget):
    """スレッド一覧ウィジェット（旧版・ピン留めエリア用に残す）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QListWidget {
                background-color: #2a2a2a;
                border: none;
                color: white;
            }
            QListWidget::item {
                padding: 10px;
                border-radius: 5px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #3399ff;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
        """)
        
        # ドラッグ&ドロップを有効化
        self.setDragDropMode(QListWidget.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        
        # 右クリックメニューを有効化
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
        # ドロップ完了時のシグナル
        self.model().rowsMoved.connect(self.on_rows_moved)
    
    def on_rows_moved(self, parent, start, end, destination, row):
        """ドラッグ&ドロップで順序変更されたとき"""
        # ChatWindowインスタンスを取得
        main_window = self.window()
        if hasattr(main_window, 'save_thread_order'):
            main_window.save_thread_order(self)
    
    def show_context_menu(self, pos):
        """右クリックメニューを表示"""
        item = self.itemAt(pos)
        if item is None:
            return
        
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        
        # 現在のピン留め状態を確認
        thread_id = item.data(Qt.UserRole)
        main_window = self.window()
        is_pinned = False
        
        if hasattr(main_window, 'get_thread_pinned_status'):
            is_pinned = main_window.get_thread_pinned_status(thread_id)
        
        rename_action = menu.addAction("リネーム")
        settings_action = menu.addAction("設定")
        menu.addSeparator()
        
        # ピン留め状態に応じてメニュー変更
        if is_pinned:
            pin_action = menu.addAction("ピン留め解除")
        else:
            pin_action = menu.addAction("ピン留めする")
        
        # 移動メニュー
        current_row = self.row(item)
        move_up_action = menu.addAction("▲ 上へ移動")
        move_down_action = menu.addAction("▼ 下へ移動")
        
        # 最上位または最下位の場合は無効化
        if current_row == 0:
            move_up_action.setEnabled(False)
        if current_row == self.count() - 1:
            move_down_action.setEnabled(False)
        
        menu.addSeparator()
        delete_action = menu.addAction("削除")
        
        action = menu.exec_(self.mapToGlobal(pos))
        
        if action == rename_action:
            self.rename_thread(item)
        elif action == settings_action:
            self.edit_thread_settings(item)
        elif action == pin_action:
            self.toggle_pin(item)
        elif action == move_up_action:
            self.move_item_up(item)
        elif action == move_down_action:
            self.move_item_down(item)
        elif action == delete_action:
            self.delete_thread(item)
    
    def rename_thread(self, item):
        """スレッドをリネーム"""
        thread_id = item.data(Qt.UserRole)
        current_name = item.text()
        
        # ChatWindowインスタンスを取得
        main_window = self.window()
        if hasattr(main_window, 'rename_thread_dialog'):
            main_window.rename_thread_dialog(thread_id, current_name)
    
    def edit_thread_settings(self, item):
        """スレッド設定を編集"""
        thread_id = item.data(Qt.UserRole)
        
        # ChatWindowインスタンスを取得
        main_window = self.window()
        if hasattr(main_window, 'edit_thread_settings_dialog'):
            main_window.edit_thread_settings_dialog(thread_id)
    
    def toggle_pin(self, item):
        """ピン留めを切り替え"""
        thread_id = item.data(Qt.UserRole)
        
        # ChatWindowインスタンスを取得
        main_window = self.window()
        if hasattr(main_window, 'toggle_thread_pin'):
            main_window.toggle_thread_pin(thread_id)
    
    def move_item_up(self, item):
        """アイテムを上へ移動"""
        current_row = self.row(item)
        if current_row > 0:
            self.insertItem(current_row - 1, self.takeItem(current_row))
            self.setCurrentRow(current_row - 1)
            
            # 順序を保存
            main_window = self.window()
            if hasattr(main_window, 'save_thread_order'):
                main_window.save_thread_order(self)
    
    def move_item_down(self, item):
        """アイテムを下へ移動"""
        current_row = self.row(item)
        if current_row < self.count() - 1:
            self.insertItem(current_row + 1, self.takeItem(current_row))
            self.setCurrentRow(current_row + 1)
            
            # 順序を保存
            main_window = self.window()
            if hasattr(main_window, 'save_thread_order'):
                main_window.save_thread_order(self)
    
    def delete_thread(self, item):
        """スレッドを削除"""
        thread_id = item.data(Qt.UserRole)
        thread_name = item.text()
        
        # ChatWindowインスタンスを取得
        main_window = self.window()
        if hasattr(main_window, 'delete_thread_dialog'):
            main_window.delete_thread_dialog(thread_id, thread_name)


class ThreadTreeWidget(QTreeWidget):
    """スレッドツリーウィジェット（グループ対応）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # verbose設定（親ウィンドウから取得、なければfalse）
        self.verbose = False
        
        self.setHeaderHidden(True)
        self.setStyleSheet("""
            QTreeWidget {
                background-color: #2a2a2a;
                border: none;
                color: white;
            }
            QTreeWidget::item {
                padding: 5px;
                border-radius: 5px;
                margin: 2px;
            }
            QTreeWidget::item:selected {
                background-color: #3399ff;
            }
            QTreeWidget::item:hover {
                background-color: #3a3a3a;
            }
        """)
        
        # ドラッグ&ドロップを有効化
        self.setDragDropMode(QTreeWidget.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        
        # 右クリックメニューを有効化
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
        # クリック時のシグナル
        self.itemClicked.connect(self.on_item_clicked)
    
    def dropEvent(self, event):
        """ドロップ時の処理（グループ移動 or 並び順変更）"""
        # デフォルトのドロップ動作を防止
        event.setDropAction(Qt.IgnoreAction)
        
        # ドロップ先のアイテムを取得
        drop_item = self.itemAt(event.pos())
        
        # ドラッグ中のアイテムを取得
        dragged_items = self.selectedItems()
        if not dragged_items:
            event.ignore()
            return
        
        dragged_item = dragged_items[0]
        thread_id = dragged_item.data(0, Qt.UserRole)
        
        # スレッドアイテム以外はドロップ不可
        if not thread_id:
            event.ignore()
            return
        
        # 元のグループ名を取得
        old_group_item = dragged_item.parent()
        old_group_name = old_group_item.text(0).replace("▼ ", "").replace("▶ ", "") if old_group_item else '未分類'
        
        # ドロップ先がグループアイテムの場合
        new_group_item = None
        drop_target_thread = None
        
        if drop_item:
            # スレッドにドロップした場合
            if drop_item.data(0, Qt.UserRole):
                new_group_item = drop_item.parent()
                drop_target_thread = drop_item
            # グループにドロップした場合
            else:
                new_group_item = drop_item
        
        if new_group_item:
            new_group_name = new_group_item.text(0).replace("▼ ", "").replace("▶ ", "")
            
            # 同じグループ内での並び替え
            if old_group_name == new_group_name and drop_target_thread:
                if self.verbose:
                    print(f"Reordering thread {thread_id} within group {old_group_name}")
                
                # ドロップ位置を取得
                old_index = old_group_item.indexOfChild(dragged_item)
                new_index = new_group_item.indexOfChild(drop_target_thread)
                
                if old_index != new_index:
                    # アイテムを移動
                    old_group_item.takeChild(old_index)
                    new_group_item.insertChild(new_index, dragged_item)
                    self.setCurrentItem(dragged_item)
                    
                    # 並び順を保存
                    main_window = self.window()
                    if hasattr(main_window, 'save_thread_order_in_group'):
                        main_window.save_thread_order_in_group(new_group_item, new_group_name)
                
                event.accept()
                return
            
            # 別グループへの移動
            if old_group_name != new_group_name:
                if self.verbose:
                    print(f"Moving thread {thread_id}: {old_group_name} -> {new_group_name}")
                
                # config.yamlを更新
                try:
                    config_path = Path("threads") / thread_id / "config.yaml"
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                    
                    config['group'] = new_group_name
                    
                    with open(config_path, 'w', encoding='utf-8') as f:
                        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
                    
                    if self.verbose:
                        print(f"Updated config successfully")
                    
                    # リロード
                    main_window = self.window()
                    if hasattr(main_window, 'load_thread_list'):
                        main_window.load_thread_list()
                except Exception as e:
                    print(f"Error moving thread to group: {e}")
                    import traceback
                    traceback.print_exc()
        
        event.accept()
    
    def on_item_clicked(self, item, column):
        """アイテムクリック時の処理"""
        # スレッドアイテムのみ処理（グループは無視）
        thread_id = item.data(0, Qt.UserRole)
        if thread_id:
            # ChatWindowの on_thread_selected を呼ぶ
            main_window = self.window()
            if hasattr(main_window, 'on_thread_selected_from_tree'):
                main_window.on_thread_selected_from_tree(item)
    
    def show_context_menu(self, pos):
        """右クリックメニューを表示"""
        item = self.itemAt(pos)
        
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        
        # 空白部分をクリックした場合
        if item is None:
            create_group_action = menu.addAction("新規グループ作成")
            action = menu.exec_(self.mapToGlobal(pos))
            
            if action == create_group_action:
                self.create_new_group()
            return
        
        thread_id = item.data(0, Qt.UserRole)
        
        # グループアイテムの場合
        if not thread_id:
            rename_group_action = menu.addAction("グループ名変更")
            delete_group_action = menu.addAction("グループ削除")
            
            action = menu.exec_(self.mapToGlobal(pos))
            
            if action == rename_group_action:
                self.rename_group(item)
            elif action == delete_group_action:
                self.delete_group(item)
            return
        
        # スレッドアイテムの場合
        main_window = self.window()
        is_pinned = False
        
        if hasattr(main_window, 'get_thread_pinned_status'):
            is_pinned = main_window.get_thread_pinned_status(thread_id)
        
        rename_action = menu.addAction("リネーム")
        settings_action = menu.addAction("設定")
        menu.addSeparator()
        
        # ピン留め状態に応じてメニュー変更
        if is_pinned:
            pin_action = menu.addAction("ピン留め解除")
        else:
            pin_action = menu.addAction("ピン留めする")
        
        menu.addSeparator()
        
        # 並び順変更メニュー
        move_up_action = menu.addAction("▲ 上へ移動")
        move_down_action = menu.addAction("▼ 下へ移動")
        
        menu.addSeparator()
        delete_action = menu.addAction("削除")
        
        action = menu.exec_(self.mapToGlobal(pos))
        
        if action == rename_action:
            self.rename_thread(item)
        elif action == settings_action:
            self.edit_thread_settings(item)
        elif action == pin_action:
            self.toggle_pin(item)
        elif action == move_up_action:
            self.move_thread_up(item)
        elif action == move_down_action:
            self.move_thread_down(item)
        elif action == delete_action:
            self.delete_thread(item)
    
    def rename_group(self, item):
        """グループ名変更"""
        current_name = item.text(0).replace("▼ ", "").replace("▶ ", "")
        main_window = self.window()
        if hasattr(main_window, 'rename_group_dialog'):
            main_window.rename_group_dialog(current_name, item)
    
    def delete_group(self, item):
        """グループ削除"""
        group_name = item.text(0).replace("▼ ", "").replace("▶ ", "")
        main_window = self.window()
        if hasattr(main_window, 'delete_group_dialog'):
            main_window.delete_group_dialog(group_name, item)
    
    def create_new_group(self):
        """新規グループ作成"""
        main_window = self.window()
        if hasattr(main_window, 'create_new_group_dialog'):
            main_window.create_new_group_dialog()
    
    def rename_thread(self, item):
        """スレッドをリネーム"""
        thread_id = item.data(0, Qt.UserRole)
        current_name = item.text(0).replace("● ", "").replace("○ ", "")
        
        main_window = self.window()
        if hasattr(main_window, 'rename_thread_dialog'):
            main_window.rename_thread_dialog(thread_id, current_name)
    
    def edit_thread_settings(self, item):
        """スレッド設定を編集"""
        thread_id = item.data(0, Qt.UserRole)
        
        main_window = self.window()
        if hasattr(main_window, 'edit_thread_settings_dialog'):
            main_window.edit_thread_settings_dialog(thread_id)
    
    def toggle_pin(self, item):
        """ピン留めを切り替え"""
        thread_id = item.data(0, Qt.UserRole)
        
        main_window = self.window()
        if hasattr(main_window, 'toggle_thread_pin'):
            main_window.toggle_thread_pin(thread_id)
    
    def move_thread_up(self, item):
        """スレッドを上へ移動"""
        parent = item.parent()
        if not parent:
            return
        
        index = parent.indexOfChild(item)
        if index > 0:
            parent.takeChild(index)
            parent.insertChild(index - 1, item)
            self.setCurrentItem(item)
            
            # 並び順を保存
            main_window = self.window()
            if hasattr(main_window, 'save_thread_order_in_group'):
                group_name = parent.text(0).replace("▼ ", "").replace("▶ ", "")
                main_window.save_thread_order_in_group(parent, group_name)
    
    def move_thread_down(self, item):
        """スレッドを下へ移動"""
        parent = item.parent()
        if not parent:
            return
        
        index = parent.indexOfChild(item)
        if index < parent.childCount() - 1:
            parent.takeChild(index)
            parent.insertChild(index + 1, item)
            self.setCurrentItem(item)
            
            # 並び順を保存
            main_window = self.window()
            if hasattr(main_window, 'save_thread_order_in_group'):
                group_name = parent.text(0).replace("▼ ", "").replace("▶ ", "")
                main_window.save_thread_order_in_group(parent, group_name)
    
    def delete_thread(self, item):
        """スレッドを削除"""
        thread_id = item.data(0, Qt.UserRole)
        thread_name = item.text(0).replace("● ", "").replace("○ ", "")
        
        main_window = self.window()
        if hasattr(main_window, 'delete_thread_dialog'):
            main_window.delete_thread_dialog(thread_id, thread_name)


class ChatWindow(QMainWindow):
    """メインウィンドウ"""
    
    def __init__(self):
        super().__init__()
        
        # UI状態管理
        self.ui_state = UIStateManager()
        
        # HTTPクライアント
        self.client = httpx.Client(timeout=300.0)
        
        # 現在のスレッドIDを決定
        self.current_thread_id = self.get_initial_thread_id()
        
        # バックエンドURL（スレッドごとに変わる）
        self.backend_url = None
        
        # キャラ画像（初期値なし）
        self.original_pixmap = None
        
        # サイドバーの状態（ui_state.yamlから復元、初回はTrue）
        self.sidebar_visible = self.ui_state.state.get('sidebar_visible', True)
        
        # バックエンド状態のキャッシュ（状態変化検出用）
        self.last_backend_alive = None
        
        # バックエンド自動停止タイマー
        self.backend_idle_timer = QTimer()
        self.backend_idle_timer.timeout.connect(self.check_backend_idle)
        self.backend_idle_timer.start(60000)  # 1分ごと
        
        # スレッドリスト更新タイマー（バックエンド状態表示用）
        self.thread_list_update_timer = QTimer()
        self.thread_list_update_timer.timeout.connect(self.update_thread_list_status)
        self.thread_list_update_timer.start(5000)  # 5秒ごとにチェック
        
        # アプリ終了時にバックエンド停止
        atexit.register(self.stop_all_backends)
        
        # verbose設定を取得
        self.verbose = self.ui_state.get_ui_config('verbose', False)
        
        # フォント設定を適用
        font_family = self.ui_state.get_ui_config('font_family', 'Noto Sans CJK JP')
        font_size = self.ui_state.get_ui_config('font_size', 12)
        app_font = QFont(font_family, font_size)
        self.setFont(app_font)
        
        # UIの初期化
        self.init_ui()
        
        # スレッド一覧をロード
        self.load_thread_list()
        
        # スレッドがない場合は新規作成ダイアログを表示
        if self.current_thread_id is None:
            QTimer.singleShot(100, self.show_initial_thread_dialog)
        else:
            # バックエンドURLを読み込む
            self.load_backend_url()
            
            # ローカルバックエンドなら起動チェック
            if self.is_local_backend(self.backend_url):
                if not self.is_backend_alive():
                    if self.verbose:
                        print("Backend not running on startup, starting...")
                    # プログレスダイアログを表示しながら起動
                    self.start_backend_with_dialog()
                else:
                    # すでに起動済み
                    self.load_initial_content()
            else:
                # リモートバックエンド
                self.load_initial_content()
    
    def on_html_loaded(self, ok):
        """HTML読み込み完了時"""
        if ok:
            if self.verbose:
                print("HTML loaded successfully")
            self.html_loaded = True
            # 保留中の履歴読み込みがあれば実行
            if self.pending_history_load:
                self.pending_history_load = False
                if self.verbose:
                    print("Loading pending history...")
                self.load_history()
        else:
            if self.verbose:
                print("HTML load failed")
    
    def load_initial_content(self):
        """初期コンテンツ読み込み（画像・履歴）"""
        if self.verbose:
            print("=== load_initial_content called ===")
        # キャラ画像をロード
        self.load_character_image()
        # 履歴読み込み（HTML読み込み済みなら即実行、未完了なら保留）
        if self.html_loaded:
            if self.verbose:
                print("HTML already loaded, calling load_history...")
            self.load_history()
        else:
            if self.verbose:
                print("HTML not loaded yet, marking as pending...")
            self.pending_history_load = True
        if self.verbose:
            print("=== load_initial_content finished ===")
    
    def load_history_after_html_ready(self):
        """HTML読み込み完了後に履歴読み込み"""
        if self.verbose:
            print("Calling load_history...")
        self.load_history()
        if self.verbose:
            print("=== load_initial_content finished ===")
    
    def start_backend_with_dialog(self):
        """プログレスダイアログを表示しながらバックエンド起動"""
        from PyQt5.QtWidgets import QProgressDialog
        
        progress = QProgressDialog("LLM起動中...", None, 0, 0, self)
        progress.setWindowTitle("起動中")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)  # キャンセル不可
        progress.show()
        QApplication.processEvents()
        
        # バックエンド起動
        success = self.start_backend()
        
        progress.close()
        
        if success:
            # 起動成功したらコンテンツ読み込み
            self.load_initial_content()
        else:
            QMessageBox.warning(self, "エラー", "バックエンドの起動に失敗しました")
    
    def show_input_context_menu(self, pos):
        """入力エリアの右クリックメニュー（コピー・ペーストのみ）"""
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        
        # 選択されているかチェック
        cursor = self.input_text.textCursor()
        has_selection = cursor.hasSelection()
        
        copy_action = menu.addAction("コピー")
        copy_action.setEnabled(has_selection)
        
        paste_action = menu.addAction("ペースト")
        
        action = menu.exec_(self.input_text.mapToGlobal(pos))
        
        if action == copy_action:
            self.input_text.copy()
        elif action == paste_action:
            self.input_text.paste()
    
    def show_search_dialog(self):
        """RAG検索ダイアログを表示"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QTextEdit, QDialogButtonBox
        
        # 現在のグループを取得
        if not self.current_thread_id:
            QMessageBox.warning(self, '警告', 'スレッドが選択されていません')
            return
        
        config_path = Path("threads") / self.current_thread_id / "config.yaml"
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            group_name = config.get('group', '未分類')
        except:
            group_name = '未分類'
        
        # ダイアログ作成
        dialog = QDialog(self)
        dialog.setWindowTitle(f'RAG検索 - グループ: {group_name}')
        dialog.setMinimumWidth(600)
        dialog.setMinimumHeight(500)
        
        layout = QVBoxLayout(dialog)
        
        # 検索クエリ入力
        query_label = QLabel('検索クエリ:')
        layout.addWidget(query_label)
        
        query_input = QLineEdit()
        query_input.setPlaceholderText('検索したい内容を入力...')
        layout.addWidget(query_input)
        
        # 検索結果表示
        results_label = QLabel('検索結果:')
        layout.addWidget(results_label)
        
        results_display = QTextEdit()
        results_display.setReadOnly(True)
        layout.addWidget(results_display)
        
        # ボタン
        button_box = QDialogButtonBox()
        search_btn = button_box.addButton('検索', QDialogButtonBox.ActionRole)
        close_btn = button_box.addButton('閉じる', QDialogButtonBox.RejectRole)
        
        layout.addWidget(button_box)
        
        # 検索結果を保持
        search_results = []
        
        def do_search():
            query = query_input.text().strip()
            if not query:
                results_display.setText('検索クエリを入力してください')
                return
            
            try:
                # バックエンドに検索リクエスト
                response = self.client.post(
                    f"{self.backend_url}/search",
                    params={
                        "group_name": group_name,
                        "query": query,
                        "top_k": 5
                    }
                )
                response.raise_for_status()
                data = response.json()
                
                nonlocal search_results
                search_results = data.get('results', [])
                
                if not search_results:
                    results_display.setText('検索結果が見つかりませんでした')
                    return
                
                # 結果を整形して表示
                display_text = []
                for i, result in enumerate(search_results, 1):
                    display_text.append(f"=== 結果 {i} (類似度: {result.get('distance', 'N/A'):.3f}) ===")
                    display_text.append(f"スレッド: {result.get('thread_id', 'N/A')}")
                    display_text.append(f"タイムスタンプ: {result.get('timestamp', 'N/A')}")
                    display_text.append("")
                    
                    messages = result.get('messages', [])
                    for msg in messages:
                        role = msg.get('role', 'unknown')
                        content = msg.get('content', '')
                        display_text.append(f"{role}: {content}")
                    
                    display_text.append("")
                
                results_display.setText('\n'.join(display_text))
                
            except Exception as e:
                results_display.setText(f'検索エラー: {e}')
        
        search_btn.clicked.connect(do_search)
        close_btn.clicked.connect(dialog.reject)
        
        dialog.exec_()
    
    def show_webview_context_menu(self, pos):
        """WebViewの右クリックメニュー（コピー＋検索）"""
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        
        copy_action = menu.addAction("コピー")
        menu.addSeparator()
        search_action = menu.addAction("🔍 RAG検索")
        
        action = menu.exec_(self.message_view.mapToGlobal(pos))
        
        if action == copy_action:
            # JavaScriptで選択されたテキストをコピー
            self.message_view.page().runJavaScript(
                "window.getSelection().toString();",
                lambda text: self.copy_to_clipboard(text)
            )
        elif action == search_action:
            self.show_search_dialog()
    
    def copy_to_clipboard(self, text):
        """クリップボードにコピー"""
        if text:
            from PyQt5.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            if self.verbose:
                print(f"Copied to clipboard: {text[:50]}...")
    
    def get_initial_thread_id(self):
        """初期スレッドIDを取得"""
        # 最後に使ったスレッドを取得
        last_thread = self.ui_state.get_last_thread_id()
        
        if last_thread:
            # 最後のスレッドが存在するか確認
            thread_path = Path("threads") / last_thread / "config.yaml"
            if thread_path.exists():
                return last_thread
        
        # 既存のスレッドを取得（ファイルシステムから直接）
        try:
            threads_dir = Path("threads")
            if threads_dir.exists():
                threads = [
                    item.name for item in threads_dir.iterdir()
                    if item.is_dir() and (item / "config.yaml").exists()
                ]
                if threads:
                    return sorted(threads)[0]
        except Exception as e:
            print(f"Error getting initial thread: {e}")
        
        # スレッドが1つもない場合
        return None
    
    def save_last_thread(self, thread_id):
        """最後に使ったスレッドを保存"""
        self.ui_state.set_last_thread_id(thread_id)
    
    def show_initial_thread_dialog(self):
        """初回起動時のスレッド作成ダイアログ"""
        # 新規スレッド作成ダイアログを表示
        self.create_new_thread()
    
    def init_ui(self):
        """UIを初期化"""
        self.setWindowTitle('AI Assistant')
        
        # config.yamlからウィンドウサイズを取得
        width, height = self.ui_state.get_window_size()
        self.setGeometry(100, 100, width, height)
        
        # ダークテーマを設定（固定値）
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QTextEdit {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 5px;
                padding: 10px;
                color: #ffffff;
            }
            QPushButton {
                background-color: #3399ff;
                border: none;
                border-radius: 5px;
                padding: 10px 20px;
                font-size: 14px;
                color: white;
            }
            QPushButton:hover {
                background-color: #2277dd;
            }
            QPushButton:pressed {
                background-color: #1155bb;
            }
        """)
        
        # メインウィジェット
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # メインレイアウト
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # サイドバー
        self.sidebar = self.create_sidebar()
        self.sidebar.setVisible(self.sidebar_visible)  # 保存された状態を反映
        main_layout.addWidget(self.sidebar)
        
        # メインコンテンツエリア
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(10)
        
        # ハンバーガーメニューボタン（常時表示）
        hamburger_layout = QHBoxLayout()
        self.hamburger_btn = QPushButton("≡")
        self.hamburger_btn.setStyleSheet("""
            QPushButton {
                font-size: 24px;
                background: transparent;
                border: none;
                color: #ffffff;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-radius: 5px;
            }
        """)
        self.hamburger_btn.setFixedSize(40, 40)
        self.hamburger_btn.clicked.connect(self.toggle_sidebar)
        hamburger_layout.addWidget(self.hamburger_btn)
        hamburger_layout.addStretch()
        content_layout.addLayout(hamburger_layout)
        
        # 上部: キャラ画像とメッセージエリア（QSplitter使用）
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)  # 完全に折りたたまれないように
        
        # 左側: キャラクター画像
        char_widget = QWidget()
        char_widget.setStyleSheet("background-color: #2a2a2a; border-radius: 10px;")
        # 最小幅を設定しない（0まで縮められるように）
        char_layout = QVBoxLayout(char_widget)
        
        self.char_label = QLabel()
        self.char_label.setAlignment(Qt.AlignCenter)
        self.char_label.setScaledContents(False)
        self.char_label.setText('画像なし')  # 初期状態
        
        self.char_widget = char_widget
        char_layout.addWidget(self.char_label)
        
        # 右側: メッセージエリア（WebView）
        self.message_view = QWebEngineView()
        self.message_view.setStyleSheet("background-color: #2a2a2a; border-radius: 10px;")
        self.message_view.setMinimumWidth(300)
        
        # 右クリックメニューをカスタマイズ（コピーのみ）
        self.message_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.message_view.customContextMenuRequested.connect(self.show_webview_context_menu)
        
        # HTML読み込み完了時のコールバック
        self.html_loaded = False
        self.pending_history_load = False
        self.message_view.loadFinished.connect(self.on_html_loaded)
        
        # HTMLファイルを読み込む
        html_path = Path(__file__).parent / 'message_view.html'
        # キャッシュ回避のためタイムスタンプ付きURLで読み込み
        from datetime import datetime
        timestamp = int(datetime.now().timestamp())
        url = QUrl.fromLocalFile(str(html_path.absolute()))
        url.setQuery(f"t={timestamp}")
        self.message_view.setUrl(url)
        
        # Splitterにウィジェットを追加
        self.main_splitter.addWidget(char_widget)
        self.main_splitter.addWidget(self.message_view)
        
        # 比率を設定
        self.apply_splitter_ratio()
        
        # 比率変更を検知
        self.main_splitter.splitterMoved.connect(self.on_splitter_moved)
        
        content_layout.addWidget(self.main_splitter, stretch=8)
        
        # 下部: 入力エリア
        input_layout = QHBoxLayout()
        
        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText('メッセージを入力...')
        self.input_text.setMaximumHeight(100)
        self.input_text.installEventFilter(self)
        
        # 入力欄のフォントサイズを設定
        input_font_size = self.ui_state.get_ui_config('input_font_size', 14)
        input_font = QFont(self.font().family(), input_font_size)
        self.input_text.setFont(input_font)
        
        # 右クリックメニューをカスタマイズ（コピー・ペーストのみ）
        self.input_text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.input_text.customContextMenuRequested.connect(self.show_input_context_menu)
        
        self.send_button = QPushButton('送信')
        self.send_button.clicked.connect(self.send_message)
        self.send_button.setFixedWidth(100)
        
        input_layout.addWidget(self.input_text, stretch=9)
        input_layout.addWidget(self.send_button, stretch=1)
        
        content_layout.addLayout(input_layout, stretch=1)
        
        main_layout.addWidget(content_widget, stretch=1)
    
    def create_sidebar(self):
        """サイドバーを作成"""
        sidebar = QFrame()
        sidebar.setFixedWidth(250)
        sidebar.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border-right: 1px solid #3a3a3a;
            }
        """)
        
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # ヘッダー（タイトルボタン + 新規ボタン）
        header_layout = QHBoxLayout()
        
        # タイトルボタン（クリックでサイドバー開閉）
        title_btn = QPushButton("≡ スレッド")
        title_btn.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                background: transparent;
                border: none;
                text-align: left;
                padding: 5px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
            }
        """)
        title_btn.clicked.connect(self.toggle_sidebar)
        header_layout.addWidget(title_btn)
        
        header_layout.addStretch()
        
        # 新規スレッドボタン
        new_thread_btn = QPushButton("+")
        new_thread_btn.setFixedSize(30, 30)
        new_thread_btn.clicked.connect(self.create_new_thread)
        header_layout.addWidget(new_thread_btn)
        
        layout.addLayout(header_layout)
        
        # ピン留めスレッド
        pinned_label = QLabel("■ ピン留め")
        pinned_label.setStyleSheet("color: #999; font-size: 12px;")
        layout.addWidget(pinned_label)
        
        self.pinned_thread_list = ThreadListWidget()
        self.pinned_thread_list.itemClicked.connect(self.on_thread_selected)
        layout.addWidget(self.pinned_thread_list)
        
        # 通常スレッド
        threads_label = QLabel("▼ すべてのスレッド")
        threads_label.setStyleSheet("color: #999; font-size: 12px; margin-top: 5px;")
        layout.addWidget(threads_label)
        
        self.thread_tree = ThreadTreeWidget()
        layout.addWidget(self.thread_tree)
        
        return sidebar
    
    def create_menu_bar(self):
        """メニューバーを作成"""
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenuBar {
                background-color: #2a2a2a;
                color: white;
            }
            QMenuBar::item:selected {
                background-color: #3a3a3a;
            }
            QMenu {
                background-color: #2a2a2a;
                color: white;
            }
            QMenu::item:selected {
                background-color: #3399ff;
            }
        """)
        
        # ファイルメニュー
        file_menu = menubar.addMenu('ファイル')
        
        new_thread_action = QAction('新しいスレッド', self)
        new_thread_action.triggered.connect(self.create_new_thread)
        file_menu.addAction(new_thread_action)
        
        # 表示メニュー
        view_menu = menubar.addMenu('表示')
        
        toggle_sidebar_action = QAction('サイドバーを切り替え', self)
        toggle_sidebar_action.triggered.connect(self.toggle_sidebar)
        view_menu.addAction(toggle_sidebar_action)
    
    def toggle_sidebar(self):
        """サイドバーの表示/非表示を切り替え"""
        self.sidebar_visible = not self.sidebar_visible
        self.sidebar.setVisible(self.sidebar_visible)
        
        # 状態を保存
        self.ui_state.state['sidebar_visible'] = self.sidebar_visible
        self.ui_state.save_state()
    
    def get_thread_backend_url(self, thread_id):
        """スレッドのバックエンドURLを取得"""
        try:
            config_path = Path("threads") / thread_id / "config.yaml"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                return config.get('backend', {}).get('url', 'http://127.0.0.1:8000')
        except:
            return 'http://127.0.0.1:8000'
    
    def load_thread_list(self):
        """スレッド一覧を読み込む（ツリー構造）"""
        try:
            # ファイルシステムから直接スレッドIDを取得
            threads_dir = Path("threads")
            thread_data = []
            empty_groups = set()  # 空グループのセット
            
            if threads_dir.exists():
                for item in threads_dir.iterdir():
                    if item.is_dir():
                        # ダミーディレクトリの検出
                        if item.name.startswith("_empty_"):
                            group_name = item.name[7:]  # "_empty_"を除去
                            empty_groups.add(group_name)
                            continue
                        
                        # 通常のスレッド
                        if (item / "config.yaml").exists():
                            thread_id = item.name
                            try:
                                config_path = item / "config.yaml"
                                with open(config_path, 'r', encoding='utf-8') as f:
                                    config = yaml.safe_load(f)
                                
                                thread_data.append({
                                    'thread_id': thread_id,
                                    'thread_name': config.get('thread_name', thread_id),
                                    'group': config.get('group', '未分類'),
                                    'is_pinned': config.get('pinned', False),
                                    'display_order': config.get('display_order', 9999)
                                })
                            except:
                                thread_data.append({
                                    'thread_id': thread_id,
                                    'thread_name': thread_id,
                                    'group': '未分類',
                                    'is_pinned': False,
                                    'display_order': 9999
                                })
            
            # display_order順にソート
            thread_data.sort(key=lambda x: x['display_order'])
            
            # 一覧をクリア
            self.pinned_thread_list.clear()
            self.thread_tree.clear()
            
            # グループごとに整理
            groups = {}
            pinned_groups = {}
            
            for data in thread_data:
                group_name = data['group']
                
                if data['is_pinned']:
                    # ピン留めグループ
                    if group_name not in pinned_groups:
                        pinned_groups[group_name] = []
                    pinned_groups[group_name].append(data)
                else:
                    # 通常グループ
                    if group_name not in groups:
                        groups[group_name] = []
                    groups[group_name].append(data)
                
                # スレッドがあるグループは空グループから除外
                if group_name in empty_groups:
                    empty_groups.discard(group_name)
                    # ダミーディレクトリを削除
                    dummy_dir = Path("threads") / f"_empty_{group_name}"
                    if dummy_dir.exists():
                        import shutil
                        shutil.rmtree(dummy_dir)
            
            # 空グループをgroupsに追加
            for group_name in empty_groups:
                groups[group_name] = []
            
            # ピン留めエリアにグループ表示（フラット）
            for group_name in sorted(pinned_groups.keys()):
                # グループヘッダー（クリック不可）
                group_header = QListWidgetItem(f"{group_name}")
                group_header.setFlags(group_header.flags() & ~Qt.ItemIsSelectable)  # 選択不可
                self.pinned_thread_list.addItem(group_header)
                
                for data in pinned_groups[group_name]:
                    backend_url = self.get_thread_backend_url(data['thread_id'])
                    if self.is_local_backend(backend_url):
                        status_icon = "● " if self.is_backend_alive(backend_url) else "○ "
                    else:
                        status_icon = ""
                    
                    thread_item = QListWidgetItem(f"  {status_icon}{data['thread_name']}")  # インデント
                    thread_item.setData(Qt.UserRole, data['thread_id'])
                    self.pinned_thread_list.addItem(thread_item)
                    
                    if data['thread_id'] == self.current_thread_id:
                        self.pinned_thread_list.setCurrentItem(thread_item)
            
            # 通常エリアにツリー表示
            for group_name in sorted(groups.keys()):
                group_item = QTreeWidgetItem(self.thread_tree, [f"{group_name}"])
                group_item.setExpanded(True)  # デフォルトで展開
                
                for data in groups[group_name]:
                    backend_url = self.get_thread_backend_url(data['thread_id'])
                    if self.is_local_backend(backend_url):
                        status_icon = "● " if self.is_backend_alive(backend_url) else "○ "
                    else:
                        status_icon = ""
                    
                    thread_item = QTreeWidgetItem(group_item, [f"{status_icon}{data['thread_name']}"])
                    thread_item.setData(0, Qt.UserRole, data['thread_id'])
                    
                    if data['thread_id'] == self.current_thread_id:
                        self.thread_tree.setCurrentItem(thread_item)
            
            # ピン留めリストの高さを中身に合わせて調整
            pinned_count = self.pinned_thread_list.count()
            if pinned_count > 0:
                # アイテムがある場合：アイテム数分の高さ
                item_height = self.pinned_thread_list.sizeHintForRow(0)
                self.pinned_thread_list.setMaximumHeight(item_height * pinned_count + 10)
            else:
                # アイテムがない場合：最小の高さ
                self.pinned_thread_list.setMaximumHeight(5)
        
        except Exception as e:
            print(f"Thread list load error: {e}")
    
    def on_thread_selected(self, item):
        """スレッドが選択されたとき（ピン留めリスト用）"""
        thread_id = item.data(Qt.UserRole)  # 保存したthread_idを取得
        
        if thread_id and thread_id != self.current_thread_id:
            self.current_thread_id = thread_id
            self.save_last_thread(thread_id)  # 保存
            self.load_backend_url()  # バックエンドURLを更新
            self.load_character_image()  # キャラ画像を更新
            self.apply_splitter_ratio()  # 比率を再適用
            self.load_history()
    
    def on_thread_selected_from_tree(self, item):
        """スレッドが選択されたとき（ツリー用）"""
        thread_id = item.data(0, Qt.UserRole)  # TreeWidgetItemはdata(column, role)
        
        if thread_id and thread_id != self.current_thread_id:
            self.current_thread_id = thread_id
            self.save_last_thread(thread_id)  # 保存
            self.load_backend_url()  # バックエンドURLを更新
            self.load_character_image()  # キャラ画像を更新
            self.apply_splitter_ratio()  # 比率を再適用
            self.load_history()
    
    def rename_group_dialog(self, old_name, group_item):
        """グループ名変更ダイアログ"""
        new_name, ok = QInputDialog.getText(
            self, 'グループ名変更', 
            f'新しいグループ名を入力してください:',
            text=old_name
        )
        
        if ok and new_name and new_name != old_name:
            # グループ内の全スレッドのgroupを更新
            for i in range(group_item.childCount()):
                child = group_item.child(i)
                thread_id = child.data(0, Qt.UserRole)
                if thread_id:
                    try:
                        config_path = Path("threads") / thread_id / "config.yaml"
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config = yaml.safe_load(f)
                        config['group'] = new_name
                        with open(config_path, 'w', encoding='utf-8') as f:
                            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
                    except Exception as e:
                        print(f"Error updating group: {e}")
            
            # バックエンドのベクトルDBもリネーム
            try:
                response = self.client.post(
                    f"{self.backend_url}/rename_group",
                    params={"old_name": old_name, "new_name": new_name}
                )
                response.raise_for_status()
                if self.verbose:
                    print(f"Vector DB renamed: {old_name} -> {new_name}")
            except Exception as e:
                print(f"Error renaming vector DB: {e}")
            
            # リロード
            self.load_thread_list()
    
    def delete_group_dialog(self, group_name, group_item):
        """グループ削除ダイアログ"""
        reply = QMessageBox.question(
            self, '確認',
            f'グループ「{group_name}」を削除しますか？\n（スレッドは「未分類」に移動します）',
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # グループ内の全スレッドを「未分類」に移動
            child_count = group_item.childCount()
            for i in range(child_count):
                child = group_item.child(i)
                thread_id = child.data(0, Qt.UserRole)
                if thread_id:
                    try:
                        config_path = Path("threads") / thread_id / "config.yaml"
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config = yaml.safe_load(f)
                        config['group'] = '未分類'
                        with open(config_path, 'w', encoding='utf-8') as f:
                            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
                    except Exception as e:
                        print(f"Error moving thread: {e}")
            
            # ダミーディレクトリも削除
            dummy_dir = Path("threads") / f"_empty_{group_name}"
            if dummy_dir.exists():
                import shutil
                shutil.rmtree(dummy_dir)
                print(f"Deleted dummy directory: {dummy_dir}")
            
            # バックエンドのベクトルDBも削除
            try:
                response = self.client.post(
                    f"{self.backend_url}/delete_group",
                    params={"group_name": group_name}
                )
                response.raise_for_status()
                if self.verbose:
                    print(f"Vector DB deleted: {group_name}")
            except Exception as e:
                print(f"Error deleting vector DB: {e}")
            
            # リロード
            self.load_thread_list()
    
    def create_new_group_dialog(self):
        """新規グループ作成ダイアログ"""
        group_name, ok = QInputDialog.getText(
            self, '新規グループ作成', 
            '新しいグループ名を入力してください:'
        )
        
        if ok and group_name:
            # ダミーディレクトリを作成
            dummy_dir = Path("threads") / f"_empty_{group_name}"
            dummy_dir.mkdir(parents=True, exist_ok=True)
            
            # リロードして表示
            self.load_thread_list()
            
            QMessageBox.information(
                self, '確認',
                f'グループ「{group_name}」を作成しました。'
            )
    
    def create_new_thread(self):
        """新しいスレッドを作成"""
        # 新規スレッド作成ダイアログを表示
        dialog = NewThreadDialog(self)
        
        if dialog.exec_() == NewThreadDialog.Accepted:
            config = dialog.get_config()
            
            if config:
                # 新しいスレッドIDを生成
                thread_id = str(uuid.uuid4().hex)[:8]
                
                # AI自動命名が必要かフラグを保存
                needs_auto_naming = not config['thread_name']
                
                # バックエンドにスレッド作成リクエスト
                try:
                    # まずバックエンドURLをデフォルト値で仮設定
                    temp_backend_url = config.get('backend_url', 'http://127.0.0.1:8000')
                    
                    # ローカルバックエンドなら起動チェック
                    if self.is_local_backend(temp_backend_url):
                        # バックエンドURLを一時的に設定
                        self.backend_url = temp_backend_url
                        
                        if not self.is_backend_alive():
                            if self.verbose:
                                print(f"Backend not running, starting on {temp_backend_url}...")
                            
                            # プログレスダイアログを表示しながらバックエンド起動
                            from PyQt5.QtWidgets import QProgressDialog
                            
                            progress = QProgressDialog("LLM起動中...", None, 0, 0, self)
                            progress.setWindowTitle("起動中")
                            progress.setWindowModality(Qt.WindowModal)
                            progress.setCancelButton(None)  # キャンセル不可
                            progress.show()
                            QApplication.processEvents()
                            
                            success = self.start_backend()
                            
                            progress.close()
                            
                            if not success:
                                QMessageBox.warning(self, "エラー", "バックエンドの起動に失敗しました")
                                return
                    
                    # 画像はまだコピーせず、パスだけ保持
                    source_image_path = config.get('image_path')
                    
                    response = self.client.post(
                        f"{temp_backend_url}/create_thread",
                        json={
                            "thread_id": thread_id,
                            "thread_name": config['thread_name'],
                            "user_name": config.get('user_name', ''),  # ユーザー名を追加
                            "group": config.get('group', '未分類'),  # グループ名を追加
                            "description": config['description'],
                            "system_prompt": config['system_prompt'],
                            "backend_url": config['backend_url'],
                            "pinned": config['pinned'],
                            "needs_auto_naming": needs_auto_naming,
                            "character_image_path": ""  # 後で更新するので一旦空
                        }
                    )
                    response.raise_for_status()
                    
                    if self.verbose:
                        print(f"Thread created successfully: {thread_id}")
                    
                    # バックエンドでスレッド作成完了後、画像をコピー
                    if source_image_path:
                        import shutil
                        images_dir = Path("threads") / thread_id / "images"
                        images_dir.mkdir(parents=True, exist_ok=True)
                        
                        image_ext = Path(source_image_path).suffix
                        dest_path = images_dir / f"character{image_ext}"
                        shutil.copy(source_image_path, dest_path)
                        
                        # config.yamlの画像パスを更新
                        config_path = Path("threads") / thread_id / "config.yaml"
                        if config_path.exists():
                            with open(config_path, 'r', encoding='utf-8') as f:
                                thread_config = yaml.safe_load(f)
                            thread_config['character'] = {'image': str(dest_path)}
                            with open(config_path, 'w', encoding='utf-8') as f:
                                yaml.dump(thread_config, f, allow_unicode=True, default_flow_style=False)
                    
                    # 現在のスレッドを切り替え
                    self.current_thread_id = thread_id
                    
                    # UI更新（バックエンドから応答が来たので確実に完了している）
                    self.load_thread_list()
                    self.load_backend_url()
                    self.load_character_image()
                    self.message_view.page().runJavaScript("clearMessages();")
                    
                except Exception as e:
                    print(f"Thread creation error: {e}")
                    # エラーでも一応UI更新
                    self.current_thread_id = thread_id
                    self.load_thread_list()
                    self.load_backend_url()
                    self.load_character_image()
    
    def eventFilter(self, obj, event):
        """イベントフィルター"""
        # Enterキーで送信
        if hasattr(self, 'input_text') and obj == self.input_text and event.type() == event.KeyPress:
            if event.key() == Qt.Key_Return and not event.modifiers() & Qt.ShiftModifier:
                self.send_message()
                return True
        
        # キャラ画像エリアのリサイズ
        if hasattr(self, 'char_widget') and obj == self.char_widget and event.type() == event.Resize:
            self.update_char_image()
        
        return super().eventFilter(obj, event)
    
    def send_message(self):
        """メッセージを送信"""
        message = self.input_text.toPlainText().strip()
        if not message:
            return
        
        if self.verbose:
            print(f"Sending message, backend_url: {self.backend_url}")
        
        # バックエンドがローカルの場合、起動チェック
        if self.is_local_backend(self.backend_url):
            if not self.is_backend_alive():
                if self.verbose:
                    print("Backend not running, starting...")
                if not self.start_backend():
                    QMessageBox.warning(self, "エラー", "バックエンドの起動に失敗しました")
                    return
        
        # アクティビティ時刻を更新
        self.update_backend_activity()
        
        # 入力欄をクリア
        self.input_text.clear()
        
        # ユーザーメッセージを表示
        self.add_message_to_view('user', message)
        
        # 最後のスレッドとして保存
        self.save_last_thread(self.current_thread_id)
        
        # バックエンドに送信
        try:
            response = self.client.post(
                f"{self.backend_url}/chat",
                json={
                    "user_message": message,
                    "thread_id": self.current_thread_id
                }
            )
            response.raise_for_status()
            data = response.json()
            ai_response = data['response']
            
            # AI応答を表示
            self.add_message_to_view('assistant', ai_response)
            
            # AI自動命名チェック
            self.check_and_auto_name_thread(message, ai_response)
            
        except Exception as e:
            print(f"Error: {e}")
            self.add_message_to_view('assistant', f'エラーが発生しました: {str(e)}')
    
    def add_message_to_view(self, role, content):
        """メッセージをWebViewに追加"""
        content_escaped = content.replace('\\', '\\\\').replace('`', '\\`').replace("'", "\\'")
        js_code = f"addMessage('{role}', `{content_escaped}`);"
        self.message_view.page().runJavaScript(js_code)
    
    def check_and_auto_name_thread(self, user_message, ai_response):
        """AI自動命名が必要かチェックして実行"""
        try:
            config_path = Path("threads") / self.current_thread_id / "config.yaml"
            if not config_path.exists():
                return
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            # 自動命名が必要かチェック
            if not config.get('_needs_auto_naming', False):
                return
            
            # 履歴を取得してメッセージ数をカウント
            history = self.load_history_for_count()
            message_count = len(history)
            
            # 3往復（6メッセージ）で強制命名
            if message_count >= 6:
                if self.verbose:
                    print("Auto-naming: 3往復達成、強制命名")
                title = self.generate_thread_title_forced(history)
                self.update_thread_name(title)
                return
            
            # 2メッセージ以上あれば命名を試みる
            if message_count >= 2:
                title = self.generate_thread_title(user_message, ai_response)
                if title and title != "SKIP":
                    if self.verbose:
                        print(f"Auto-naming: タイトル生成成功 -> {title}")
                    self.update_thread_name(title)
                else:
                    if self.verbose:
                        print("Auto-naming: SKIP、次のメッセージまで待機")
        
        except Exception as e:
            print(f"Auto-naming error: {e}")
    
    def generate_thread_title(self, user_message, ai_response):
        """LLMにスレッドタイトルを生成させる"""
        try:
            # タイトル生成用のプロンプト
            naming_prompt = f"""以下の会話を3-10文字で要約してください。

ユーザー: {user_message}
AI: {ai_response}

【重要】
- 内容が挨拶のみ、または話題が明確でない場合は、必ず「SKIP」とだけ返答してください
- 具体的な話題がある場合のみ、3-10文字の要約を返してください
- 例: 挨拶のみ → SKIP、質問がある → その質問の内容

要約:"""
            
            # バックエンドに送信（通常の会話とは別）
            response = self.client.post(
                f"{self.backend_url}/chat",
                json={
                    "user_message": naming_prompt,
                    "thread_id": "_naming_temp"  # 一時的なスレッド
                }
            )
            response.raise_for_status()
            data = response.json()
            title = data['response'].strip()
            
            # 一時スレッドを削除
            self.cleanup_temp_thread()
            
            return title
        
        except Exception as e:
            print(f"Title generation error: {e}")
            self.cleanup_temp_thread()
            return None
    
    def generate_thread_title_forced(self, history):
        """履歴全体から強制的にタイトルを生成"""
        try:
            # 履歴をまとめる
            conversation = "\n".join([
                f"{entry['role']}: {entry['content']}" 
                for entry in history[:6]  # 最初の6メッセージ
            ])
            
            naming_prompt = f"""以下の会話を3-10文字で要約してください。

{conversation}

3-10文字の要約:"""
            
            response = self.client.post(
                f"{self.backend_url}/chat",
                json={
                    "user_message": naming_prompt,
                    "thread_id": "_naming_temp"
                }
            )
            response.raise_for_status()
            data = response.json()
            title = data['response'].strip()
            
            # 一時スレッドを削除
            self.cleanup_temp_thread()
            
            return title
        
        except Exception as e:
            print(f"Forced title generation error: {e}")
            self.cleanup_temp_thread()
            return self.current_thread_id  # 失敗したらthread_idをそのまま使う
    
    def cleanup_temp_thread(self):
        """一時スレッドを削除"""
        try:
            import shutil
            temp_thread_path = Path("threads") / "_naming_temp"
            if temp_thread_path.exists():
                shutil.rmtree(temp_thread_path)
                print("Cleaned up temporary naming thread")
        except Exception as e:
            print(f"Cleanup temp thread error: {e}")
    
    def update_thread_name(self, title):
        """スレッド名を更新"""
        try:
            config_path = Path("threads") / self.current_thread_id / "config.yaml"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                config['thread_name'] = title
                
                # _needs_auto_namingフラグを削除
                if '_needs_auto_naming' in config:
                    del config['_needs_auto_naming']
                
                with open(config_path, 'w', encoding='utf-8') as f:
                    yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
                
                # スレッド一覧を更新
                self.load_thread_list()
                
                if self.verbose:
                    print(f"Thread renamed: {self.current_thread_id} -> {title}")
        
        except Exception as e:
            print(f"Update thread name error: {e}")
    
    def rename_thread_dialog(self, thread_id, current_name):
        """スレッドリネームダイアログ"""
        new_name, ok = QInputDialog.getText(
            self,
            "スレッドをリネーム",
            "新しいスレッド名:",
            text=current_name
        )
        
        if ok and new_name.strip():
            try:
                config_path = Path("threads") / thread_id / "config.yaml"
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                    
                    config['thread_name'] = new_name.strip()
                    
                    with open(config_path, 'w', encoding='utf-8') as f:
                        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
                    
                    # スレッド一覧を更新
                    self.load_thread_list()
                    
                    if self.verbose:
                        print(f"Thread renamed: {thread_id} -> {new_name}")
            except Exception as e:
                print(f"Rename error: {e}")
                QMessageBox.warning(self, "エラー", f"リネームに失敗しました: {e}")
    
    def get_thread_pinned_status(self, thread_id):
        """スレッドのピン留め状態を取得"""
        try:
            config_path = Path("threads") / thread_id / "config.yaml"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                return config.get('pinned', False)
        except:
            return False
    
    def toggle_thread_pin(self, thread_id):
        """スレッドのピン留めを切り替え"""
        try:
            config_path = Path("threads") / thread_id / "config.yaml"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                # ピン留め状態を反転
                current_pinned = config.get('pinned', False)
                config['pinned'] = not current_pinned
                
                with open(config_path, 'w', encoding='utf-8') as f:
                    yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
                
                # スレッド一覧を更新
                self.load_thread_list()
                
                if self.verbose:
                    status = "ピン留めしました" if config['pinned'] else "ピン留めを解除しました"
                    print(f"{status}: {thread_id}")
        except Exception as e:
            print(f"Toggle pin error: {e}")
    
    def save_thread_order(self, list_widget):
        """スレッドの表示順序を保存"""
        try:
            # リストの順序を取得
            for index in range(list_widget.count()):
                item = list_widget.item(index)
                thread_id = item.data(Qt.UserRole)
                
                # config.yamlにdisplay_orderを保存
                config_path = Path("threads") / thread_id / "config.yaml"
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                    
                    config['display_order'] = index
                    
                    with open(config_path, 'w', encoding='utf-8') as f:
                        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            
            if self.verbose:
                print(f"Thread order saved")
        except Exception as e:
            print(f"Save thread order error: {e}")
    
    def save_thread_order_in_group(self, group_item, group_name):
        """グループ内のスレッド表示順序を保存"""
        try:
            # グループ内の子アイテム（スレッド）の順序を保存
            for index in range(group_item.childCount()):
                child_item = group_item.child(index)
                thread_id = child_item.data(0, Qt.UserRole)
                
                if not thread_id:
                    continue
                
                # config.yamlにdisplay_orderを保存
                config_path = Path("threads") / thread_id / "config.yaml"
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                    
                    config['display_order'] = index
                    
                    with open(config_path, 'w', encoding='utf-8') as f:
                        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            
            if self.verbose:
                print(f"Thread order saved in group: {group_name}")
        except Exception as e:
            print(f"Save thread order in group error: {e}")
    
    def edit_thread_settings_dialog(self, thread_id):
        """スレッド設定ダイアログ"""
        dialog = NewThreadDialog(self, edit_mode=True, thread_id=thread_id)
        
        if dialog.exec_() == NewThreadDialog.Accepted:
            config = dialog.get_config()
            
            if config:
                try:
                    config_path = Path("threads") / thread_id / "config.yaml"
                    
                    # 既存設定を読み込む
                    with open(config_path, 'r', encoding='utf-8') as f:
                        existing_config = yaml.safe_load(f)
                    
                    # 更新
                    existing_config['thread_name'] = config['thread_name']
                    existing_config['user_name'] = config.get('user_name', '')  # ユーザー名を追加
                    existing_config['group'] = config.get('group', '未分類')  # グループ名を追加
                    existing_config['description'] = config['description']
                    existing_config['system_prompt'] = config['system_prompt']
                    existing_config['pinned'] = config['pinned']
                    
                    # バックエンドURL
                    existing_config['backend'] = {
                        'url': config['backend_url'],
                        'timeout': 300
                    }
                    
                    # 画像を更新
                    images_dir = Path("threads") / thread_id / "images"
                    existing_image = existing_config.get('character', {}).get('image', '')
                    
                    if config.get('image_path'):
                        # 新しい画像が指定された場合
                        new_image_path = config['image_path']
                        
                        # 既存画像と同じパスかチェック
                        if str(new_image_path) != str(existing_image):
                            import shutil
                            images_dir.mkdir(parents=True, exist_ok=True)
                            
                            # 古い画像を削除
                            if existing_image and Path(existing_image).exists():
                                try:
                                    Path(existing_image).unlink()
                                    print(f"Deleted old image: {existing_image}")
                                except Exception as e:
                                    print(f"Failed to delete old image: {e}")
                            
                            # 新しい画像をコピー
                            image_ext = Path(new_image_path).suffix
                            dest_path = images_dir / f"character{image_ext}"
                            shutil.copy(new_image_path, dest_path)
                            
                            existing_config['character'] = {'image': str(dest_path)}
                            print(f"Updated image: {dest_path}")
                        # else: 同じ画像なので何もしない
                    else:
                        # 画像なしに変更
                        # 古い画像を削除
                        if existing_image and Path(existing_image).exists():
                            try:
                                Path(existing_image).unlink()
                                print(f"Deleted image: {existing_image}")
                            except Exception as e:
                                print(f"Failed to delete image: {e}")
                        
                        existing_config['character'] = {'image': ''}
                    
                    # 保存
                    with open(config_path, 'w', encoding='utf-8') as f:
                        yaml.dump(existing_config, f, allow_unicode=True, default_flow_style=False)
                    
                    # 現在のスレッドなら再読み込み
                    if thread_id == self.current_thread_id:
                        self.load_backend_url()
                        self.load_character_image()
                        self.apply_splitter_ratio()
                    
                    # スレッド一覧を更新
                    self.load_thread_list()
                    
                    print(f"Thread settings updated: {thread_id}")
                except Exception as e:
                    print(f"Settings update error: {e}")
                    QMessageBox.warning(self, "エラー", f"設定の保存に失敗しました: {e}")
    
    def delete_thread_dialog(self, thread_id, thread_name):
        """スレッド削除ダイアログ"""
        reply = QMessageBox.question(
            self,
            "スレッドを削除",
            f"「{thread_name}」を削除しますか?\n\nこの操作は取り消せません。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                import shutil
                thread_dir = Path("threads") / thread_id
                
                if thread_dir.exists():
                    shutil.rmtree(thread_dir)
                    print(f"Thread deleted: {thread_id}")
                    
                    # 削除したスレッドが現在のスレッドの場合
                    if thread_id == self.current_thread_id:
                        # 別のスレッドに切り替え
                        threads_dir = Path("threads")
                        remaining_threads = [
                            item.name for item in threads_dir.iterdir()
                            if item.is_dir() and (item / "config.yaml").exists()
                        ]
                        
                        if remaining_threads:
                            # 最初のスレッドに切り替え
                            self.current_thread_id = sorted(remaining_threads)[0]
                            self.load_backend_url()
                            self.load_character_image()
                            self.apply_splitter_ratio()
                            self.load_history()
                        else:
                            # スレッドがなくなった場合
                            self.current_thread_id = None
                            self.message_view.page().runJavaScript("clearMessages();")
                    
                    # スレッド一覧を更新
                    self.load_thread_list()
            except Exception as e:
                print(f"Delete error: {e}")
                QMessageBox.warning(self, "エラー", f"削除に失敗しました: {e}")
    
    def load_history_for_count(self):
        """メッセージ数カウント用に履歴を読み込む"""
        try:
            response = self.client.get(f"{self.backend_url}/history/{self.current_thread_id}")
            response.raise_for_status()
            data = response.json()
            return data.get('history', [])
        except:
            return []
    
    def load_character_image(self):
        """現在のスレッドのキャラ画像を読み込む"""
        try:
            import time
            start = time.time()
            
            config_path = Path("threads") / self.current_thread_id / "config.yaml"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                image_path = config.get('character', {}).get('image', '')
                
                if image_path and Path(image_path).exists():
                    # EXIF回転対応の画像読み込み
                    if PILLOW_AVAILABLE:
                        try:
                            t1 = time.time()
                            pil_image = Image.open(image_path)
                            original_format = pil_image.format  # 元のフォーマットを保存
                            if self.verbose:
                                print(f"Image.open: {time.time() - t1:.3f}s")
                            
                            t2 = time.time()
                            # EXIF情報を読んで自動回転
                            pil_image = ImageOps.exif_transpose(pil_image)
                            if self.verbose:
                                print(f"exif_transpose: {time.time() - t2:.3f}s")
                            
                            t3 = time.time()
                            # メモリ上で元のフォーマットのまま保存（JPGならJPG）
                            buffer = BytesIO()
                            save_format = original_format if original_format else 'PNG'
                            pil_image.save(buffer, format=save_format)
                            buffer.seek(0)
                            if self.verbose:
                                print(f"save to buffer ({save_format}): {time.time() - t3:.3f}s")
                            
                            t4 = time.time()
                            # QPixmapに変換
                            self.original_pixmap = QPixmap()
                            self.original_pixmap.loadFromData(buffer.read())
                            if self.verbose:
                                print(f"loadFromData: {time.time() - t4:.3f}s")
                        except Exception as e:
                            print(f"EXIF rotation failed, using fallback: {e}")
                            self.original_pixmap = QPixmap(image_path)
                    else:
                        self.original_pixmap = QPixmap(image_path)
                    
                    self.update_char_image()
                else:
                    # 画像なしの場合
                    self.char_label.clear()
                    self.char_label.setText('画像なし')
                    self.original_pixmap = None
                
                # 画像の有無に応じて比率を再適用
                QTimer.singleShot(100, self.apply_splitter_ratio)
            
            if self.verbose:
                print(f"Total load_character_image: {time.time() - start:.3f}s")
        except Exception as e:
            print(f"Load character image error: {e}")
            self.char_label.clear()
            self.char_label.setText('画像なし')
            self.original_pixmap = None
    
    def load_backend_url(self):
        """現在のスレッドのバックエンドURLを読み込む"""
        try:
            if self.verbose:
                print(f"Loading backend URL for thread: {self.current_thread_id}")
            config_path = Path("threads") / self.current_thread_id / "config.yaml"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                self.backend_url = config.get('backend', {}).get('url', 'http://127.0.0.1:8000')
                if self.verbose:
                    print(f"Backend URL loaded: {self.backend_url}")
            else:
                if self.verbose:
                    print(f"Config not found: {config_path}")
                self.backend_url = 'http://127.0.0.1:8000'
        except Exception as e:
            print(f"Load backend URL error: {e}")
            self.backend_url = 'http://127.0.0.1:8000'
    
    def apply_splitter_ratio(self):
        """スプリッター比率を適用"""
        # 画像があるか確認
        has_image = self.original_pixmap is not None
        
        if has_image:
            # グローバル比率を使用
            char_ratio, message_ratio = self.ui_state.get_splitter_ratio()
            # スライダーを表示
            self.main_splitter.setHandleWidth(5)
            # キャラウィジェットを表示
            self.char_widget.setVisible(True)
        else:
            # 画像なし → 0:1（画像エリアを非表示）
            char_ratio, message_ratio = (0, 1.0)
            # スライダーを非表示（いじれなくする）
            self.main_splitter.setHandleWidth(0)
            # キャラウィジェットを非表示
            self.char_widget.setVisible(False)
        
        # QSplitterのサイズを設定
        total_width = self.main_splitter.width()
        if total_width > 0:
            char_width = int(total_width * char_ratio)
            message_width = int(total_width * message_ratio)
            self.main_splitter.setSizes([char_width, message_width])
            
            # 画像をリサイズ
            QTimer.singleShot(50, self.update_char_image)
    
    def on_splitter_moved(self, pos, index):
        """スプリッターが動かされたとき"""
        # 画像がない場合は保存しない（自動で0:1に戻るべき）
        if self.original_pixmap is None:
            return
        
        sizes = self.main_splitter.sizes()
        total = sum(sizes)
        
        if total > 0:
            char_ratio = sizes[0] / total
            message_ratio = sizes[1] / total
            
            # 保存
            self.ui_state.set_splitter_ratio(char_ratio, message_ratio)
            print(f"Splitter ratio saved: {char_ratio:.2f}:{message_ratio:.2f}")
            
            # 画像をリサイズ
            QTimer.singleShot(10, self.update_char_image)
    
    def load_history(self):
        """履歴を読み込む"""
        try:
            response = self.client.get(f"{self.backend_url}/history/{self.current_thread_id}")
            response.raise_for_status()
            data = response.json()
            history = data.get('history', [])
            
            if history:
                history_json = json.dumps(history, ensure_ascii=False)
                js_code = f"loadHistory({history_json});"
                self.message_view.page().runJavaScript(js_code)
            else:
                # 履歴が空の場合はクリア
                self.message_view.page().runJavaScript("clearMessages();")
        
        except Exception as e:
            print(f"History load error: {e}")
    
    def resizeEvent(self, event):
        """ウィンドウリサイズ時"""
        super().resizeEvent(event)
        QTimer.singleShot(10, self.update_char_image)
    
    def closeEvent(self, event):
        """ウィンドウを閉じるときの処理"""
        if self.current_thread_id:
            self.save_last_thread(self.current_thread_id)
        
        # ウィンドウサイズを保存
        self.ui_state.set_window_size(self.width(), self.height())
        
        # バックエンドを停止
        self.stop_backend()
        event.accept()
    
    def is_backend_alive(self, backend_url=None):
        """バックエンドが生存しているかチェック（プロセス監視）"""
        global backend_processes
        
        # URL指定なしなら現在のスレッドのURL
        if backend_url is None:
            backend_url = self.backend_url
        
        if not backend_url or backend_url not in backend_processes:
            return False
        
        process = backend_processes[backend_url]
        
        # プロセスが終了していないかチェック
        return process.poll() is None
    
    def is_local_backend(self, backend_url):
        """バックエンドがローカルかどうか判定"""
        if not backend_url:
            return False
        return "127.0.0.1" in backend_url or "localhost" in backend_url
    
    def check_backend_health(self, backend_url):
        """バックエンドのヘルスチェック"""
        try:
            response = httpx.get(f"{backend_url}/health", timeout=1.0)
            return response.status_code == 200
        except:
            return False
    
    def start_backend(self):
        """バックエンドを起動"""
        global backend_processes, backend_activities
        
        # 既にこのURLのバックエンドが起動中かチェック
        if self.backend_url in backend_processes:
            process = backend_processes[self.backend_url]
            if process.poll() is None:  # プロセスが生きている
                if self.verbose:
                    print(f"Backend already running on {self.backend_url}")
                return True
            else:
                # プロセスが死んでいたら削除
                del backend_processes[self.backend_url]
        
        # backend_urlからポート番号を抽出
        port = "8000"  # デフォルト
        if self.backend_url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(self.backend_url)
                if parsed.port:
                    port = str(parsed.port)
            except:
                pass
        
        try:
            # 既存フラグを削除（前回の残骸対策）
            flag_file = Path("backend_ready.flag")
            flag_file.unlink(missing_ok=True)
            
            if self.verbose:
                print(f"Starting backend on port {port}")
            
            # uvicornのログレベルを設定（verbose: false なら warning 以上のみ）
            log_level = "info" if self.verbose else "warning"
            
            # 標準出力・エラー出力を継承してリアルタイム表示
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", port, "--log-level", log_level],
                cwd=str(Path(__file__).parent)
            )
            
            # プロセスを辞書に保存
            backend_processes[self.backend_url] = process
            
            # アクティビティ記録（URL単位）
            backend_activities[self.backend_url] = datetime.now()
            
            # フラグファイルを待つ（最大60秒）
            if self.verbose:
                print("Waiting for backend to be ready...")
            max_wait = 60
            for i in range(max_wait):
                QApplication.processEvents()  # UIを固まらせない
                
                # プロセスが死んでないかチェック
                if process.poll() is not None:
                    print(f"Backend process died with exit code: {process.poll()}")
                    if self.backend_url in backend_processes:
                        del backend_processes[self.backend_url]
                    return False
                
                if flag_file.exists():
                    if self.verbose:
                        print(f"Backend started successfully (took {i+1}s)")
                    flag_file.unlink(missing_ok=True)  # すぐ削除
                    return True
                import time
                time.sleep(1)
            
            print("Backend started but ready flag not found")
            return False
        except Exception as e:
            print(f"Failed to start backend: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def stop_backend(self):
        """現在のバックエンドを停止"""
        global backend_processes
        
        if not self.backend_url or self.backend_url not in backend_processes:
            return
        
        process = backend_processes[self.backend_url]
        
        try:
            print(f"Stopping backend on {self.backend_url}...")
            process.terminate()
            process.wait(timeout=5)
            print("Backend stopped")
        except:
            print("Force killing backend...")
            process.kill()
        finally:
            del backend_processes[self.backend_url]
            # フラグファイルを削除
            Path("backend_ready.flag").unlink(missing_ok=True)
    
    def stop_all_backends(self):
        """全てのバックエンドを停止（終了時用）"""
        global backend_processes
        
        for url, process in list(backend_processes.items()):
            try:
                print(f"Stopping backend on {url}...")
                process.terminate()
                process.wait(timeout=5)
            except:
                print(f"Force killing backend on {url}...")
                process.kill()
        
        backend_processes.clear()
        Path("backend_ready.flag").unlink(missing_ok=True)
    
    def check_backend_idle(self):
        """バックエンドのアイドル時間をチェック（URL単位）"""
        global backend_activities, backend_processes
        
        if self.verbose:
            print(f"[DEBUG] check_backend_idle called")
            print(f"  backend_processes: {list(backend_processes.keys())}")
            print(f"  self.backend_url: {self.backend_url}")
            print(f"  backend_activities: {list(backend_activities.keys())}")
        
        if not backend_processes:
            return
        
        # 現在アクティブなバックエンドURLを取得
        if not self.backend_url or self.backend_url not in backend_activities:
            if self.verbose:
                print(f"  -> Skipped (URL not in activities)")
            return
        
        # このバックエンドURLを使用している全スレッドの最長タイムアウトを取得
        threads_dir = Path("threads")
        max_timeout_seconds = 0  # デフォルト0（タイムアウト無効）
        
        if threads_dir.exists():
            for thread_dir in threads_dir.iterdir():
                if thread_dir.is_dir() and not thread_dir.name.startswith('_'):
                    config_path = thread_dir / "config.yaml"
                    if config_path.exists():
                        try:
                            with open(config_path, 'r', encoding='utf-8') as f:
                                config = yaml.safe_load(f)
                            
                            # このスレッドが同じバックエンドURLを使っているか確認
                            thread_backend_url = config.get('backend', {}).get('url', 'http://127.0.0.1:8000')
                            if thread_backend_url == self.backend_url:
                                # タイムアウト設定を取得（0 = 無効）
                                thread_timeout_seconds = config.get('backend', {}).get('timeout', 0)
                                if self.verbose:
                                    print(f"    Thread {thread_dir.name}: timeout={thread_timeout_seconds}s")
                                max_timeout_seconds = max(max_timeout_seconds, thread_timeout_seconds)
                        except:
                            pass
        
        # タイムアウト0の場合は無効
        if max_timeout_seconds == 0:
            if self.verbose:
                print(f"  -> Timeout disabled")
            return
        
        # アイドル時間チェック
        last_activity = backend_activities.get(self.backend_url)
        if last_activity is None:
            if self.verbose:
                print(f"  -> No activity recorded yet")
            return
        
        elapsed = (datetime.now() - last_activity).total_seconds()
        
        if self.verbose:
            print(f"  Elapsed: {elapsed:.1f}s / Timeout: {max_timeout_seconds}s")
        
        if elapsed > max_timeout_seconds:
            if self.verbose:
                print(f"Backend idle for {elapsed:.1f}s (timeout: {max_timeout_seconds}s), stopping...")
            self.stop_backend()
    
    def update_thread_list_status(self):
        """スレッドリストのバックエンド状態表示を更新"""
        # 現在の状態を取得
        current_state = self.is_backend_alive()
        
        # 状態が変わった時だけリロード
        if current_state != self.last_backend_alive:
            if self.verbose:
                print(f"Backend state changed: {self.last_backend_alive} -> {current_state}")
            self.last_backend_alive = current_state
            self.load_thread_list()
    
    def update_backend_activity(self):
        """バックエンドの最終アクティビティ時刻を更新"""
        global backend_activities
        if self.backend_url:
            backend_activities[self.backend_url] = datetime.now()
    
    def update_char_image(self):
        """キャラ画像をウィンドウサイズに合わせてリサイズ"""
        if not hasattr(self, 'original_pixmap') or self.original_pixmap is None:
            return
        
        if hasattr(self, 'char_label') and hasattr(self, 'char_widget'):
            available_width = self.char_widget.width() - 20
            available_height = self.char_widget.height() - 20
            
            if available_width > 0 and available_height > 0:
                scaled_pixmap = self.original_pixmap.scaled(
                    available_width,
                    available_height,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.char_label.setPixmap(scaled_pixmap)


def main():
    """メイン関数"""
    app = QApplication(sys.argv)
    
    # フォント設定
    font = QFont("Noto Sans JP", 10)
    app.setFont(font)
    
    window = ChatWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
