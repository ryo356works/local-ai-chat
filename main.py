from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yaml
import os
from datetime import datetime, timezone
import json
from typing import Optional
from llama_cpp import Llama
from thread_manager import ThreadManager
from embedding_manager import EmbeddingManager

app = FastAPI()

@app.get("/health")
async def health_check():
    """ヘルスチェックエンドポイント"""
    return {"status": "ok", "message": "Backend is running"}

# --- スレッド管理 ---
thread_manager = ThreadManager("threads")

# --- Embedding管理 ---
embedding_manager = EmbeddingManager("config.yaml")

# --- 設定ファイルパス ---
SETTINGS_YAML_PATH = "config.yaml"

# --- グローバル変数 ---
llm_model = None  # Llamaモデルインスタンスを保持
LLM_CONFIG = {}  # 設定を保持
last_thread_id = None  # 前回のスレッドID（バッファフラッシュ用）
VERBOSE = False  # ログ出力制御

def load_settings_from_yaml(file_path: str) -> dict:
    """YAMLファイルから設定を読み込み"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"設定ファイルが見つかりません: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        settings = yaml.safe_load(f)
    
    if not isinstance(settings, dict):
        raise ValueError(f"設定ファイル '{file_path}' の形式が不正です。")
    
    return settings

@app.on_event("startup")
async def startup_event():
    """
    アプリケーション起動時の処理
    llama.cppモデルをロード
    """
    global llm_model, LLM_CONFIG, VERBOSE

    print("アプリケーション起動中：設定とLLMモデルをロードしています...")

    # 設定ファイルの読み込み
    try:
        LLM_CONFIG = load_settings_from_yaml(SETTINGS_YAML_PATH)
        
        # verbose設定を取得（ui:から）
        VERBOSE = LLM_CONFIG.get('ui', {}).get('verbose', False)

        # llm設定を取得
        llm_config = LLM_CONFIG.get('llm', {})
        
        model_path = llm_config.get('model_path')
        if not model_path:
            raise ValueError(f"設定ファイルに 'llm.model_path' が指定されていません。")
        
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"モデルファイルが見つかりません: {model_path}")

    except (FileNotFoundError, ValueError) as e:
        print(f"エラー: 設定ファイルの読み込みに失敗: {e}")
        raise SystemExit(f"起動失敗: {e}")
    
    # llama.cppモデルのロード
    try:
        if VERBOSE:
            print(f"LLMモデル '{model_path}' をロード中...")
        
        # GPU層の数（-1で全層GPU、0で全層CPU）
        n_gpu_layers = llm_config.get('n_gpu_layers', -1)
        
        # コンテキストサイズ
        n_ctx = llm_config.get('n_ctx', 4096)
        
        # バッチサイズ
        n_batch = llm_config.get('n_batch', 512)
        
        # スレッド数（CPUコア数に応じて調整）
        n_threads = llm_config.get('n_threads', None)
        
        llm_model = Llama(
            model_path=model_path,
            n_gpu_layers=n_gpu_layers,  # GPU使用層数
            n_ctx=n_ctx,                # コンテキストウィンドウ
            n_batch=n_batch,            # バッチサイズ
            n_threads=n_threads,        # CPUスレッド数
            verbose=VERBOSE             # ロード時の詳細情報を表示
        )
        
        print(f"LLMモデルのロードが完了しました")
        if VERBOSE:
            print(f"  - GPU層: {n_gpu_layers}")
            print(f"  - コンテキストサイズ: {n_ctx}")

    except Exception as e:
        print(f"モデルロード中にエラーが発生: {e}")
        llm_model = None
        raise SystemExit(f"起動失敗: {e}")
    
    # Embeddingモデルのロード（有効な場合）
    try:
        if embedding_manager.is_enabled():
            if VERBOSE:
                print("Embeddingモデルをロード中...")
            embedding_manager.load_model()
            print("Embeddingモデルのロードが完了しました")
        elif VERBOSE:
            print("Embedding機能は無効です")
    except Exception as e:
        print(f"Embeddingモデルロード中にエラーが発生: {e}")
        print("Embedding機能なしで続行します")
    
    # 起動完了フラグを作成
    from pathlib import Path
    Path("backend_ready.flag").touch()
    if VERBOSE:
        print("Backend ready flag created")

@app.on_event("shutdown")
async def shutdown_event():
    """アプリケーション終了時の処理"""
    if VERBOSE:
        print("Shutting down: flushing all embedding buffers...")
    if embedding_manager.is_enabled():
        try:
            embedding_manager.flush_all_buffers()
            if VERBOSE:
                print("All buffers flushed successfully")
        except Exception as e:
            print(f"Error flushing buffers on shutdown: {e}")

# --- リクエスト/レスポンスモデル ---
class MessageRequest(BaseModel):
    """ユーザーからのメッセージを含むリクエストボディ"""
    user_message: str
    thread_id: Optional[str] = "default"

class ChatResponse(BaseModel):
    """LLMからの応答を含むレスポンスボディ"""
    response: str

class HistoryEntry(BaseModel):
    role: str
    content: str
    created_at: str

class HistoryResponse(BaseModel):
    history: list[HistoryEntry]

# --- FastAPIエンドポイント ---
@app.post("/chat", response_model=ChatResponse)
async def chat_with_llm(req: MessageRequest):
    """LLMとチャットするエンドポイント"""
    global last_thread_id
    
    if llm_model is None:
        raise HTTPException(status_code=503, detail="LLMモデルがロードされていません")
    
    thread_id = req.thread_id or "default"
    
    # スレッドが切り替わった場合、前回スレッドのバッファをフラッシュ
    if last_thread_id and last_thread_id != thread_id and embedding_manager.is_enabled():
        try:
            # 前回スレッドのグループを取得
            prev_config = thread_manager.get_thread_config(last_thread_id)
            prev_group = prev_config.get('group', '未分類')
            embedding_manager.flush_buffer(prev_group, last_thread_id)
        except Exception as e:
            print(f"Error flushing buffer for previous thread: {e}")
    
    last_thread_id = thread_id
    
    # スレッドが存在しない場合は作成
    if thread_id not in thread_manager.get_all_threads():
        thread_manager.create_thread(thread_id, thread_name=thread_id)
    
    # スレッドの設定を取得
    thread_config = thread_manager.get_thread_config(thread_id)
    system_prompt = thread_config.get('system_prompt', "あなたは親切なAIアシスタントです。")
    
    # ユーザー名があればシステムプロンプトに追記
    user_name = thread_config.get('user_name', '')
    if user_name:
        system_prompt += f"\n\nユーザーの名前は「{user_name}」です。"
    
    # RAG検索（embeddingが有効な場合）
    if embedding_manager.is_enabled():
        try:
            group_name = thread_config.get('group', '未分類')
            search_results = embedding_manager.search(
                group_name=group_name,
                query=req.user_message,
                top_k=3,  # 上位3件
                thread_id=None  # グループ全体から検索
            )
            
            if search_results:
                # 参考情報をシステムプロンプトに追加
                reference_text = "\n\n【参考情報】過去の関連する会話:\n"
                for i, result in enumerate(search_results, 1):
                    reference_text += f"\n--- 参考 {i} (類似度: {result.get('distance', 0):.3f}) ---\n"
                    messages_list = result.get('messages', [])
                    for msg in messages_list:
                        role = msg.get('role', 'unknown')
                        content = msg.get('content', '')
                        reference_text += f"{role}: {content}\n"
                
                system_prompt += reference_text
                if VERBOSE:
                    print(f"RAG: Found {len(search_results)} relevant chunks")
        except Exception as e:
            if VERBOSE:
                print(f"RAG search error: {e}")
            # RAGエラーは無視して続行
    
    # LLMパラメータを取得（スレッド設定 or グローバル設定）
    llm_params = thread_config.get('llm_parameters', {})
    max_tokens = llm_params.get('max_tokens', LLM_CONFIG.get('max_new_tokens', 512))
    temperature = llm_params.get('temperature', LLM_CONFIG.get('temperature', 0.7))
    top_p = llm_params.get('top_p', LLM_CONFIG.get('top_p', 0.9))
    repeat_penalty = llm_params.get('repeat_penalty', LLM_CONFIG.get('repeat_penalty', 1.1))
    
    # 過去の履歴を読み込む
    history_from_file = thread_manager.load_history(thread_id, limit=10)
    
    # メッセージリストを構築
    messages = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    
    for entry in history_from_file:
        messages.append({"role": entry["role"], "content": entry["content"]})
    
    messages.append({"role": "user", "content": req.user_message})
    
    if VERBOSE:
        print(f"Thread: {thread_id}, メッセージ履歴: {len(messages)}件")
    
    try:
        # llama.cppで推論実行
        response = llm_model.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
            stop=["User:", "ユーザー:", "\nUser:", "\nユーザー:"],  # 停止トークン
        )
        
        # 応答の抽出
        if response and 'choices' in response and len(response['choices']) > 0:
            ai_response = response['choices'][0]['message']['content'].strip()
            
            # 履歴に保存
            thread_manager.append_to_history(thread_id, "user", req.user_message)
            thread_manager.append_to_history(thread_id, "assistant", ai_response)
            
            # Embeddingに追加（有効な場合）
            if embedding_manager.is_enabled():
                try:
                    # グループ名を取得
                    group_name = thread_config.get('group', '未分類')
                    
                    # ユーザーメッセージを追加
                    user_msg_id = f"{thread_id}_user_{datetime.now().timestamp()}"
                    embedding_manager.add_message(group_name, user_msg_id, "user", req.user_message, thread_id)
                    
                    # AIレスポンスを追加
                    ai_msg_id = f"{thread_id}_assistant_{datetime.now().timestamp()}"
                    embedding_manager.add_message(group_name, ai_msg_id, "assistant", ai_response, thread_id)
                except Exception as e:
                    if VERBOSE:
                        print(f"Embedding追加中にエラー: {e}")
                    # Embeddingのエラーは無視して続行
            
            if VERBOSE:
                print(f"LLM応答: {ai_response[:100]}...")
            return ChatResponse(response=ai_response)
        else:
            raise HTTPException(status_code=500, detail="LLMからの応答が不正です")
    
    except Exception as e:
        print(f"LLM推論中にエラー: {e}")
        raise HTTPException(status_code=500, detail=f"推論エラー: {e}")

@app.get("/history/{thread_id}", response_model=HistoryResponse)
async def get_history(thread_id: str):
    """指定されたスレッドの会話履歴を返す"""
    history = thread_manager.load_history(thread_id, limit=50)
    return HistoryResponse(history=history)

@app.get("/threads")
async def get_threads():
    """既存のスレッドID一覧を返す"""
    return thread_manager.get_all_threads()

@app.post("/rename_group")
async def rename_group(old_name: str, new_name: str):
    """グループ名を変更"""
    try:
        # ベクトルDBをリネーム
        if embedding_manager.is_enabled():
            embedding_manager.rename_group_vector_db(old_name, new_name)
        
        return {"status": "success", "message": f"Group renamed: {old_name} -> {new_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rename group: {e}")

@app.post("/delete_group")
async def delete_group(group_name: str):
    """グループを削除"""
    try:
        # ベクトルDBを削除
        if embedding_manager.is_enabled():
            embedding_manager.delete_group_vector_db(group_name)
        
        return {"status": "success", "message": f"Group deleted: {group_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete group: {e}")

@app.post("/search")
async def search_messages(group_name: str, query: str, top_k: int = 5, thread_id: Optional[str] = None):
    """ベクトル検索でメッセージを検索"""
    try:
        if not embedding_manager.is_enabled():
            return {"results": [], "message": "Embedding is disabled"}
        
        results = embedding_manager.search(group_name, query, top_k=top_k, thread_id=thread_id)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")

class CreateThreadRequest(BaseModel):
    """スレッド作成リクエスト"""
    thread_id: str
    thread_name: str = ""
    user_name: str = ""  # ユーザー名（任意）
    group: str = "未分類"  # グループ名
    description: str = ""
    system_prompt: str = ""
    backend_url: str = "http://127.0.0.1:8000"
    pinned: bool = False
    needs_auto_naming: bool = False
    character_image_path: Optional[str] = None

@app.post("/create_thread")
async def create_thread_endpoint(req: CreateThreadRequest):
    """新しいスレッドを作成"""
    try:
        if VERBOSE:
            print(f"=== Creating thread: {req.thread_id} ===")
            print(f"Thread name: {req.thread_name}")
            print(f"Backend URL: {req.backend_url}")
        
        # スレッド作成
        success = thread_manager.create_thread(req.thread_id, thread_name=req.thread_name or req.thread_id)
        if VERBOSE:
            print(f"Thread creation success: {success}")
        
        if not success:
            raise HTTPException(status_code=400, detail="スレッドが既に存在します")
        
        # config.yamlを更新
        config = thread_manager.get_thread_config(req.thread_id)
        if VERBOSE:
            print(f"Config loaded: {config is not None}")
        
        if config is None:
            raise HTTPException(status_code=500, detail="スレッド作成後にconfigが見つかりません")
        
        if req.thread_name:
            config['thread_name'] = req.thread_name
        
        config['user_name'] = req.user_name  # ユーザー名を保存
        config['group'] = req.group  # グループ名を保存
        config['description'] = req.description
        config['system_prompt'] = req.system_prompt
        config['pinned'] = req.pinned
        
        # バックエンドURL
        config['backend'] = {
            'url': req.backend_url,
            'timeout': 300
        }
        
        # 自動命名フラグ
        if req.needs_auto_naming:
            config['_needs_auto_naming'] = True
        
        # キャラ画像
        if req.character_image_path:
            config['character'] = {'image': req.character_image_path}
        else:
            config['character'] = {'image': ''}
        
        thread_manager.save_thread_config(req.thread_id, config)
        
        if VERBOSE:
            print(f"Thread created via API: {req.thread_id}")
        
        return {"status": "ok", "thread_id": req.thread_id}
    
    except Exception as e:
        print(f"Create thread error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"スレッド作成エラー: {e}")

