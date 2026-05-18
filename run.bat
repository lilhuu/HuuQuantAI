@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo 启动HTTP轮询行情系统...
echo 当前目录: %cd%

REM 检查虚拟环境
if not exist ".venv" (
    echo 创建虚拟环境...
    python -m venv .venv
)

REM 激活虚拟环境
call .venv\Scripts\activate.bat

REM 安装依赖
echo 安装依赖...
pip install -r requirements.txt > nul 2>&1

REM 创建必要目录
if not exist "config" mkdir config
if not exist "core" mkdir core
if not exist "logs" mkdir logs
if not exist "data" mkdir data

REM 检查配置文件
if not exist "config\config.yaml" (
    echo 创建示例配置文件...
    python -c "import sys; sys.path.append('.'); from main import create_sample_config; create_sample_config()"
)

REM 运行主程序
echo 启动主程序...
python main.py

pause
