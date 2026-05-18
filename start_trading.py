#!/usr/bin/env python3
"""加密货币量化交易系统快速启动脚本。"""

import os
import sys


def setup_environment() -> bool:
    """设置运行环境。"""
    print("设置交易系统环境...")

    if sys.version_info < (3, 8):
        print("错误: 需要Python 3.8或以上版本")
        return False

    directories = ["config", "core", "strategies", "logs", "data"]
    for dir_name in directories:
        os.makedirs(dir_name, exist_ok=True)
        print(f"已确认目录: {dir_name}")

    try:
        import numpy  # noqa: F401
        import pandas  # noqa: F401
        import yaml  # noqa: F401

        print("核心依赖已安装")
    except ImportError as e:
        print(f"缺少依赖: {e}")
        print("请运行: pip install -r requirements.txt")
        return False

    return True


def create_core_files() -> bool:
    """检查核心文件是否存在（加密货币架构）。"""
    print("\n检查核心文件...")

    required_files = [
        "core/crypto_market_data_provider.py",
        "core/crypto_paper_broker.py",
        "core/desktop_paths.py",
        "core/app_state.py",
        "core/credential_manager.py",
        "core/file_lock.py",
        "api/main.py",
        "api/routers/crypto.py",
        "api/services/crypto_service.py",
        "strategies/base_strategy.py",
        "strategies/dual_ma_strategy.py",
        "strategies/rsi_strategy.py",
        "strategies/bollinger_strategy.py",
        "strategies/momentum_strategy.py",
        "desktop_backend.py",
    ]

    missing_files = [path for path in required_files if not os.path.exists(path)]
    if missing_files:
        print("缺少核心文件:")
        for path in missing_files:
            print(f"  - {path}")
        return False

    print("核心文件就绪")
    return True


def main() -> None:
    """主函数。"""
    print("=" * 60)
    print("加密货币量化交易系统 - 快速启动")
    print("=" * 60)

    if not setup_environment():
        sys.exit(1)

    if not create_core_files():
        sys.exit(1)

    config_path = "config/config.yaml"
    if not os.path.exists(config_path):
        print(f"\n配置文件不存在: {config_path}")
        print("请运行桌面应用或手动创建配置后启动。")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("环境准备完成")
    print("\n运行命令:")
    print("  python desktop_backend.py     # 启动桌面后端 API")
    print("  python -m pytest tests/       # 运行测试")
    print("=" * 60)


if __name__ == "__main__":
    main()
