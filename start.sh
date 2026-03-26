#!/bin/bash

# 色付き出力
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   AI Assistant 起動スクリプト${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 仮想環境の存在確認
if [ ! -d "venv" ]; then
    echo -e "${RED}エラー: 仮想環境が見つかりません${NC}"
    echo -e "${YELLOW}セットアップスクリプトを先に実行してください:${NC}"
    echo -e "${YELLOW}  ./setup.sh${NC}"
    exit 1
fi

# 仮想環境をアクティベート
echo -e "${YELLOW}仮想環境をアクティベート中...${NC}"
source venv/bin/activate

# モデルパスの確認
MODEL_PATH=$(grep "model_path:" config.yaml | awk '{print $2}' | tr -d '"')
if [ ! -f "$MODEL_PATH" ]; then
    echo -e "${RED}警告: モデルファイルが見つかりません: ${MODEL_PATH}${NC}"
    echo -e "${YELLOW}config.yaml の model_path を確認してください${NC}"
    deactivate
    exit
    echo ""
fi

# アプリケーション起動
echo -e "${GREEN}アプリケーションを起動します...${NC}"
echo ""
python3 chat.py

# 終了処理
echo ""
echo -e "${GREEN}アプリケーションが終了しました${NC}"
deactivate
