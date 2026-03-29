"""
新規スレッド作成ダイアログ
"""
import yaml
import shutil
from pathlib import Path
from io import BytesIO
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QTextEdit, QPushButton, QCheckBox, QGroupBox, QFileDialog, QComboBox, QSpinBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap

try:
    from PIL import Image, ImageOps
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("Warning: Pillow not installed. EXIF rotation will not work.")


class NewThreadDialog(QDialog):
    """新規スレッド作成/編集ダイアログ"""
    
    def __init__(self, parent=None, edit_mode=False, thread_id=None):
        super().__init__(parent)
        
        self.edit_mode = edit_mode
        self.thread_id = thread_id
        
        if edit_mode:
            self.setWindowTitle('スレッド設定')
        else:
            self.setWindowTitle('新しいスレッド作成')
        
        self.setMinimumWidth(500)
        self.setMinimumHeight(700)
        
        # 戻り値
        self.thread_config = None
        
        # 選択された画像パス
        self.selected_image_path = None
        
        # LLMパラメータ（デフォルト値）
        self.llm_params = {
            'max_tokens': 512,
            'temperature': 0.7,
            'top_p': 0.9,
            'repeat_penalty': 1.1,
        }
        
        self.init_ui()
        
        # 編集モードなら既存設定を読み込む
        if edit_mode and thread_id:
            self.load_existing_config()
        else:
            self.load_template()
    
    def get_existing_groups(self):
        """既存のグループ名一覧を取得"""
        groups = set(['未分類'])  # デフォルトグループ
        
        threads_dir = Path("threads")
        if threads_dir.exists():
            for item in threads_dir.iterdir():
                if item.is_dir() and (item / "thread.yaml").exists():
                    try:
                        with open(item / "thread.yaml", 'r', encoding='utf-8') as f:
                            config = yaml.safe_load(f)
                        group = config.get('group', '未分類')
                        groups.add(group)
                    except:
                        pass
        
        return sorted(list(groups))
    
    def init_ui(self):
        """UIを初期化"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # スレッド名
        name_group = QGroupBox("スレッド名")
        name_layout = QVBoxLayout(name_group)
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText('空白の場合、AIが自動で命名します')
        name_layout.addWidget(self.name_input)
        
        # 編集モードの時はスレッドIDを表示
        if self.edit_mode and self.thread_id:
            thread_id_label = QLabel(f"スレッドID: {self.thread_id}")
            thread_id_label.setStyleSheet("color: #888; font-size: 11px;")
            name_layout.addWidget(thread_id_label)
        
        layout.addWidget(name_group)
        
        # ユーザー名
        user_name_group = QGroupBox("ユーザー名（任意）")
        user_name_layout = QVBoxLayout(user_name_group)
        
        self.user_name_input = QLineEdit()
        self.user_name_input.setPlaceholderText('空白の場合、システムプロンプトに追記されません')
        user_name_layout.addWidget(self.user_name_input)
        
        layout.addWidget(user_name_group)
        
        # グループ
        group_group = QGroupBox("グループ")
        group_layout = QVBoxLayout(group_group)
        
        self.group_input = QComboBox()
        self.group_input.setEditable(True)  # 新規グループ名も入力可能
        # プレースホルダーは空白（ドロップダウンで選択が基本）
        self.group_input.addItems(self.get_existing_groups())
        
        # 編集可能QComboBoxの内部QLineEditに直接スタイル適用
        line_edit = self.group_input.lineEdit()
        if line_edit:
            line_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #3a3a3a;
                    border: none;
                    color: white;
                    padding: 4px;
                }
            """)
        
        group_layout.addWidget(self.group_input)
        
        layout.addWidget(group_group)
        
        # 説明/メモ
        desc_group = QGroupBox("説明/メモ（任意）")
        desc_layout = QVBoxLayout(desc_group)
        
        self.desc_input = QTextEdit()
        self.desc_input.setPlaceholderText('スレッドの目的や内容を簡単に記載')
        self.desc_input.setMaximumHeight(60)
        desc_layout.addWidget(self.desc_input)
        
        layout.addWidget(desc_group)
        
        # バックエンドURL
        backend_group = QGroupBox("バックエンドURL")
        backend_layout = QVBoxLayout(backend_group)
        
        self.backend_input = QLineEdit()
        self.backend_input.setPlaceholderText('http://127.0.0.1:8000')
        backend_layout.addWidget(self.backend_input)
        
        # タイムアウト
        timeout_layout = QHBoxLayout()
        timeout_label = QLabel("タイムアウト:")
        timeout_label.setStyleSheet("font-weight: normal;")
        timeout_layout.addWidget(timeout_label)
        
        self.timeout_input = QSpinBox()
        self.timeout_input.setRange(0, 86400)  # 0〜24時間
        self.timeout_input.setValue(0)
        self.timeout_input.setFixedWidth(80)
        self.timeout_input.setSuffix(" 秒")
        timeout_layout.addWidget(self.timeout_input)
        
        note_label = QLabel("(0 = 無効)")
        note_label.setStyleSheet("color: #888; font-size: 11px; font-weight: normal;")
        timeout_layout.addWidget(note_label)
        timeout_layout.addStretch()
        backend_layout.addLayout(timeout_layout)
        
        layout.addWidget(backend_group)
        
        # キャラクター画像
        char_group = QGroupBox("キャラクター画像")
        char_layout = QVBoxLayout(char_group)
        
        # ボタン
        btn_layout = QHBoxLayout()
        
        self.select_image_btn = QPushButton('画像を選択')
        self.select_image_btn.clicked.connect(self.select_image)
        btn_layout.addWidget(self.select_image_btn)
        
        self.clear_image_btn = QPushButton('クリア')
        self.clear_image_btn.clicked.connect(self.clear_image)
        btn_layout.addWidget(self.clear_image_btn)
        
        btn_layout.addStretch()
        char_layout.addLayout(btn_layout)
        
        # プレビュー
        self.image_preview = QLabel()
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setMinimumHeight(150)
        self.image_preview.setMaximumHeight(150)
        self.image_preview.setStyleSheet("""
            QLabel {
                border: 1px solid #555;
                border-radius: 5px;
                background-color: #3a3a3a;
            }
        """)
        self.image_preview.setText('画像なし')
        char_layout.addWidget(self.image_preview)
        
        layout.addWidget(char_group)
        
        # システムプロンプト
        prompt_group = QGroupBox("システムプロンプト")
        prompt_layout = QVBoxLayout(prompt_group)
        
        # テンプレート読込ボタン
        self.prompt_input = QTextEdit()
        self.prompt_input.setMinimumHeight(150)
        prompt_layout.addWidget(self.prompt_input)
        
        layout.addWidget(prompt_group)
        
        # オプション
        options_layout = QHBoxLayout()
        self.pinned_checkbox = QCheckBox('ピン留めする')
        options_layout.addWidget(self.pinned_checkbox)
        layout.addLayout(options_layout)
        
        # ボタン行（テンプレート再読込 / LLM設定 / キャンセル / 作成）
        button_layout = QHBoxLayout()
        
        self.load_template_btn = QPushButton('テンプレートを再読込')
        self.load_template_btn.clicked.connect(self.load_template)
        button_layout.addWidget(self.load_template_btn)
        
        button_layout.addStretch()
        
        llm_settings_btn = QPushButton('LLM設定')
        llm_settings_btn.clicked.connect(self.open_llm_settings)
        button_layout.addWidget(llm_settings_btn)
        
        cancel_btn = QPushButton('キャンセル')
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        ok_label = '更新' if self.edit_mode else '作成'
        create_btn = QPushButton(ok_label)
        create_btn.clicked.connect(self.accept_dialog)
        create_btn.setDefault(True)
        button_layout.addWidget(create_btn)
        
        layout.addLayout(button_layout)
        
        # スタイル
        self.setStyleSheet("""
            QDialog {
                background-color: #2a2a2a;
                color: white;
            }
            QGroupBox {
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
                color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: white;
            }
            QLineEdit, QTextEdit {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 5px;
                padding: 8px;
                color: white;
            }
            QLineEdit::placeholder, QTextEdit::placeholder {
                color: #888;
            }
            QComboBox {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 5px;
                padding: 8px;
                padding-right: 25px;
                color: white;
            }
            QComboBox:editable {
                background-color: #3a3a3a;
            }
            QComboBox:!editable, QComboBox::drop-down:editable {
                background-color: #3a3a3a;
            }
            QComboBox:on {
                border-color: #3399ff;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid white;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #3a3a3a;
                color: white;
                selection-background-color: #3399ff;
                border: 1px solid #555;
            }
            QPushButton {
                background-color: #3399ff;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                color: white;
            }
            QPushButton:hover {
                background-color: #2277dd;
            }
            QCheckBox {
                color: white;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #555;
                border-radius: 3px;
                background-color: #3a3a3a;
            }
            QCheckBox::indicator:checked {
                background-color: #3399ff;
                border-color: #3399ff;
            }
            QCheckBox::indicator:checked::after {
                content: "✓";
                color: white;
            }
        """)
    
    def open_llm_settings(self):
        """LLM設定ダイアログを開く"""
        dlg = LLMSettingsDialog(self, llm_params=self.llm_params)
        if dlg.exec_() == LLMSettingsDialog.Accepted:
            self.llm_params = dlg.get_params()
    
    def select_image(self):
        """画像を選択"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            '画像を選択',
            '',
            'Images (*.png *.PNG *.jpg *.JPG *.jpeg *.JPEG *.bmp *.BMP *.gif *.GIF *.webp *.WEBP)'
        )
        
        if file_path:
            self.selected_image_path = file_path
            self.update_image_preview(file_path)
    
    def clear_image(self):
        """画像をクリア"""
        self.selected_image_path = None
        self.image_preview.clear()
        self.image_preview.setText('画像なし')
    
    def update_image_preview(self, image_path):
        """プレビューを更新"""
        if PILLOW_AVAILABLE:
            # Pillowで画像を開いてEXIF回転を適用
            try:
                pil_image = Image.open(image_path)
                original_format = pil_image.format  # 元のフォーマットを保存
                # EXIF情報を読んで自動回転
                pil_image = ImageOps.exif_transpose(pil_image)
                
                # メモリ上で元のフォーマットのまま保存
                buffer = BytesIO()
                save_format = original_format if original_format else 'PNG'
                pil_image.save(buffer, format=save_format)
                buffer.seek(0)
                
                # QPixmapに変換
                pixmap = QPixmap()
                pixmap.loadFromData(buffer.read())
            except Exception as e:
                print(f"EXIF rotation failed, using fallback: {e}")
                pixmap = QPixmap(image_path)
        else:
            # Pillowがない場合は通常読み込み
            pixmap = QPixmap(image_path)
        
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                140, 140,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_preview.setPixmap(scaled_pixmap)
    
    def load_template(self):
        """テンプレートを読み込む"""
        try:
            template_path = Path("template_thread.yaml")
            if template_path.exists():
                with open(template_path, 'r', encoding='utf-8') as f:
                    template = yaml.safe_load(f)
                
                # システムプロンプトを設定
                self.prompt_input.setPlainText(
                    template.get('system_prompt', 'あなたは親切なAIアシスタントです。')
                )
                
                # バックエンドURLを設定
                backend_url = template.get('backend', {}).get('url', 'http://127.0.0.1:8000')
                self.backend_input.setText(backend_url)
                
                # タイムアウトを設定
                timeout = template.get('backend', {}).get('timeout', 0)
                self.timeout_input.setValue(int(timeout) if timeout else 0)
                
                # デフォルト画像を読み込む
                default_image = template.get('character', {}).get('image', '')
                if default_image and Path(default_image).exists():
                    self.selected_image_path = default_image
                    self.update_image_preview(default_image)
                
                # LLMパラメータを読み込む
                llm_params = template.get('llm_parameters', {})
                if llm_params:
                    self.llm_params.update(llm_params)
        except Exception as e:
            print(f"Template load error: {e}")
    
    def load_existing_config(self):
        """既存のスレッド設定を読み込む（編集モード）"""
        try:
            config_path = Path("threads") / self.thread_id / "thread.yaml"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                # スレッド名
                self.name_input.setText(config.get('thread_name', ''))
                
                # ユーザー名
                self.user_name_input.setText(config.get('user_name', ''))
                
                # グループ
                group = config.get('group', '未分類')
                index = self.group_input.findText(group)
                if index >= 0:
                    self.group_input.setCurrentIndex(index)
                else:
                    self.group_input.setCurrentText(group)
                
                # 説明
                self.desc_input.setPlainText(config.get('description', ''))
                
                # バックエンドURL
                backend_url = config.get('backend', {}).get('url', 'http://127.0.0.1:8000')
                self.backend_input.setText(backend_url)
                
                # タイムアウト
                timeout = config.get('backend', {}).get('timeout', 0)
                self.timeout_input.setValue(int(timeout) if timeout else 0)
                
                # システムプロンプト
                self.prompt_input.setPlainText(
                    config.get('system_prompt', 'あなたは親切なAIアシスタントです。')
                )
                
                # ピン留め
                self.pinned_checkbox.setChecked(config.get('pinned', False))
                
                # LLMパラメータ
                llm_params = config.get('llm_parameters', {})
                if llm_params:
                    self.llm_params.update(llm_params)
                
                # キャラクター画像
                image_path = config.get('character', {}).get('image', '')
                if image_path and Path(image_path).exists():
                    self.selected_image_path = image_path
                    self.update_image_preview(image_path)
        except Exception as e:
            print(f"Load existing config error: {e}")
    
    def accept_dialog(self):
        """ダイアログを受け入れる"""
        # 設定を作成
        self.thread_config = {
            'thread_name': self.name_input.text().strip() or '',
            'user_name': self.user_name_input.text().strip(),
            'group': self.group_input.currentText().strip() or '未分類',
            'description': self.desc_input.toPlainText().strip(),
            'backend_url': self.backend_input.text().strip() or 'http://127.0.0.1:8000',
            'backend_timeout': self.timeout_input.value(),
            'system_prompt': self.prompt_input.toPlainText().strip(),
            'pinned': self.pinned_checkbox.isChecked(),
            'image_path': self.selected_image_path,
            'llm_parameters': self.llm_params,
        }
        
        self.accept()
    
    def get_config(self):
        """設定を取得"""
        return self.thread_config


class LLMSettingsDialog(QDialog):
    """LLMパラメータ設定ダイアログ"""

    def __init__(self, parent=None, llm_params=None):
        super().__init__(parent)
        self.setWindowTitle('LLM設定')
        self.setMinimumWidth(350)
        self.setStyleSheet("""
            QDialog { background-color: #2a2a2a; color: white; }
            QGroupBox {
                border: 1px solid #3a3a3a; border-radius: 5px;
                margin-top: 10px; padding-top: 10px;
                font-weight: bold; color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px;
                padding: 0 5px; color: white;
            }
            QLabel { color: white; }
            QLineEdit {
                background-color: #3a3a3a; border: 1px solid #555;
                border-radius: 5px; padding: 8px; color: white;
            }
            QPushButton {
                background-color: #3399ff; border: none;
                border-radius: 5px; padding: 8px 16px; color: white;
            }
            QPushButton:hover { background-color: #2277dd; }
        """)

        params = llm_params or {}
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        group = QGroupBox("パラメータ")
        form = QVBoxLayout(group)

        def make_row(label_text, default):
            row = QHBoxLayout()
            label = QLabel(label_text)
            label.setFixedWidth(130)
            inp = QLineEdit(str(default))
            inp.setFixedWidth(100)
            row.addWidget(label)
            row.addWidget(inp)
            row.addStretch()
            form.addLayout(row)
            return inp

        self.max_tokens_input    = make_row("max_tokens",     params.get('max_tokens', 512))
        self.temperature_input   = make_row("temperature",    params.get('temperature', 0.7))
        self.top_p_input         = make_row("top_p",          params.get('top_p', 0.9))
        self.repeat_penalty_input= make_row("repeat_penalty", params.get('repeat_penalty', 1.1))

        layout.addWidget(group)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton('キャンセル')
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        ok_btn = QPushButton('OK')
        ok_btn.clicked.connect(self.accept)
        ok_btn.setDefault(True)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

    def get_params(self):
        """入力値を取得"""
        def to_float(s, default):
            try: return float(s)
            except: return default
        def to_int(s, default):
            try: return int(s)
            except: return default

        return {
            'max_tokens':     to_int(self.max_tokens_input.text(), 512),
            'temperature':    to_float(self.temperature_input.text(), 0.7),
            'top_p':          to_float(self.top_p_input.text(), 0.9),
            'repeat_penalty': to_float(self.repeat_penalty_input.text(), 1.1),
        }
