@echo off
chcp 65001 > nul
title llama-cpp-python CUDA対応版インストール

echo ========================================
echo    llama-cpp-python CUDA対応版
echo ========================================
echo.

REM 仮想環境の確認
if not exist "venv" (
    echo エラー: 仮想環境が見つかりません
    echo 先に setup.bat を実行してください
    pause
    exit /b 1
)

REM CUDAの確認
echo CUDAを確認中...
nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo 警告: nvidia-smi が見つかりません
    echo CUDA Toolkitがインストールされているか確認してください
    echo.
    set /p confirm="続行しますか？ (y/N): "
    if /i not "%confirm%"=="y" exit /b 1
) else (
    echo ✓ CUDA が見つかりました
    nvidia-smi --query-gpu=name --format=csv,noheader
    echo.
)

REM 仮想環境をアクティベート
echo 仮想環境をアクティベート中...
call venv\Scripts\activate.bat
echo ✓ 仮想環境をアクティベートしました
echo.

REM llama-cpp-pythonをCUDA対応でインストール
echo llama-cpp-python (CUDA対応版) をインストール中...
echo これには数分かかる場合があります...
set CMAKE_ARGS=-DLLAMA_CUDA=on
pip install llama-cpp-python --force-reinstall --no-cache-dir

if errorlevel 1 (
    echo.
    echo ========================================
    echo    インストールに失敗しました
    echo ========================================
    echo.
    echo トラブルシューティング:
    echo - CUDA Toolkit がインストールされているか確認
    echo - Visual Studio Build Tools がインストールされているか確認
    pause
    exit /b 1
)

echo.
echo ========================================
echo    インストールが完了しました！
echo ========================================
echo.
pause
