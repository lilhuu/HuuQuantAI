#!/bin/bash
# 自动交易系统启动脚本

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "启动HTTP轮询行情系统..."
echo "当前目录: $(pwd)"

# 检查虚拟环境
if [ ! -d ".venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv .venv
fi

# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
echo "安装依赖..."
pip install -r requirements.txt > /dev/null 2>&1

# 创建必要目录
mkdir -p config core logs data

# 检查配置文件
if [ ! -f "config/config.yaml" ]; then
    echo "创建示例配置文件..."
    python -c "
import sys
sys.path.append('.')
from main import create_sample_config
create_sample_config()
"
fi

# 运行主程序
echo "启动主程序..."
python main.py
