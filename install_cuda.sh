#!/bin/bash

# 色付き出力
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   llama-cpp-python CUDA対応版${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 仮想環境の確認
if [ ! -d "venv" ]; then
    echo -e "${RED}エラー: 仮想環境が見つかりません${NC}"
    echo -e "${YELLOW}先に setup.sh を実行してください${NC}"
    exit 1
fi

# CUDAの確認
echo -e "${BLUE}CUDAを確認中...${NC}"
if ! command -v nvidia-smi &> /dev/null; then
    echo -e "${RED}警告: nvidia-smi が見つかりません${NC}"
    echo -e "${YELLOW}CUDA Toolkitがインストールされているか確認してください${NC}"
    read -p "続行しますか？ (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "${GREEN}✓ CUDA が見つかりました${NC}"
    nvidia-smi --query-gpu=name --format=csv,noheader
    echo ""
fi

# 仮想環境をアクティベート
echo -e "${BLUE}仮想環境をアクティベート中...${NC}"
source venv/bin/activate
echo -e "${GREEN}✓ 仮想環境をアクティベートしました${NC}"
echo ""

# llama-cpp-pythonをCUDA対応でインストール
echo -e "${BLUE}llama-cpp-python (CUDA対応版) をインストール中...${NC}"
echo -e "${YELLOW}これには数分かかる場合があります...${NC}"
CMAKE_ARGS="-DLLAMA_CUDA=on" pip install llama-cpp-python --force-reinstall --no-cache-dir

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}   インストールが完了しました！${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
else
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}   インストールに失敗しました${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo -e "トラブルシューティング:"
    echo -e "- CUDA Toolkit がインストールされているか確認"
    echo -e "- gcc/g++ がインストールされているか確認: sudo apt install build-essential"
    exit 1
fi

deactivate
