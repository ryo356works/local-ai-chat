#!/bin/bash

# 色付き出力
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   AI Assistant セットアップ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# OS判定
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    IS_LINUX=true
else
    IS_LINUX=false
fi

# Linuxの場合、PyQt5のシステムパッケージをインストール
if [ "$IS_LINUX" = true ]; then
    echo -e "${BLUE}[1/6] システムパッケージを確認中...${NC}"
    if ! dpkg -l | grep -q python3-pyqt5; then
        echo -e "${YELLOW}PyQt5をインストール中...${NC}"
        sudo apt update
        sudo apt install -y python3-pyqt5 python3-pyqt5.qtwebengine
        echo -e "${GREEN}✓ PyQt5をインストールしました${NC}"
    else
        echo -e "${GREEN}✓ PyQt5は既にインストールされています${NC}"
    fi
    echo ""
fi

# Pythonバージョン確認
echo -e "${BLUE}[2/6] Pythonバージョンを確認中...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}エラー: Python3がインストールされていません${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo -e "${GREEN}✓ Python ${PYTHON_VERSION} が見つかりました${NC}"
echo ""

# 仮想環境の作成
echo -e "${BLUE}[3/6] 仮想環境を作成中...${NC}"
if [ -d "venv" ]; then
    echo -e "${YELLOW}既存の仮想環境が見つかりました。スキップします。${NC}"
else
    if [ "$IS_LINUX" = true ]; then
        # Linuxは--system-site-packages付きで作成（PyQt5用）
        python3 -m venv --system-site-packages venv
    else
        python3 -m venv venv
    fi
    echo -e "${GREEN}✓ 仮想環境を作成しました${NC}"
fi
echo ""

# 仮想環境のアクティベート
echo -e "${BLUE}[4/6] 仮想環境をアクティベート中...${NC}"
source venv/bin/activate
echo -e "${GREEN}✓ 仮想環境をアクティベートしました${NC}"
echo ""

# pipのアップグレード
echo -e "${BLUE}[5/6] pipをアップグレード中...${NC}"
pip install --upgrade pip -q
echo -e "${GREEN}✓ pipをアップグレードしました${NC}"
echo ""

# 依存関係のインストール
echo -e "${BLUE}[6/6] 依存関係をインストール中...${NC}"
echo -e "${YELLOW}これには数分かかる場合があります...${NC}"
pip install -r requirements.txt
echo -e "${GREEN}✓ 依存関係をインストールしました${NC}"
echo ""

# GPU対応の確認（オプション）
echo -e "${BLUE}GPU対応について:${NC}"
echo -e "GPU（NVIDIA）を使用する場合は、以下のコマンドを実行してください:"
echo -e "${YELLOW}./install_cuda.sh${NC}"
echo ""
echo -e "手動でインストールする場合は、必ず仮想環境内で以下のコマンドを実行してください:"
echo -e "${YELLOW}CMAKE_ARGS=\"-DLLAMA_CUDA=on\" pip install llama-cpp-python --force-reinstall --no-cache-dir${NC}"
echo ""

# 完了メッセージ
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   セットアップが完了しました！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

deactivate
