# HuuQuantAI

HuuQuantAI 是一个本地运行的加密货币量化交易工作台，包含 FastAPI 后端、Vue 前端、Binance 公共行情、WebSocket 实时行情、本地模拟交易、策略验证、回测、风控、审计和桌面一体化打包。

当前版本默认只做模拟交易。真实交易与 Binance mainnet 下单保持关闭。

## 桌面一体化应用

目标形态是 Windows 桌面版 `HUU Auto Trade Console.exe`：Electron 负责窗口和进程生命周期，PyInstaller 后端 exe 负责 FastAPI、WebSocket、策略、行情和数据服务。

构建桌面版：

```powershell
cd D:\auto_trader
.\.venv\Scripts\python.exe scripts\build_desktop.py
```

构建完成后输出：

```text
release\HUU Auto Trade Console.exe
```

桌面版运行数据目录：

```text
%APPDATA%\AutoTrader
```

其中包含：

- `config\`：用户配置
- `data\`：SQLite 数据库、运行覆盖配置和本地缓存
- `logs\`：桌面壳和后端日志

## 配置

本地真实配置文件是 `config/config.yaml`，不会提交到 Git。首次部署可以从示例文件复制：

```powershell
Copy-Item config\config.example.yaml config\config.yaml
```

敏感配置请使用环境变量，例如：

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`
- `FRED_API_KEY`
- `AUTO_TRADER_POSTGRES_URL`

## 本地 Web 一体化启动

如果不打包桌面版，也可以继续用浏览器访问本地一体化服务：

```powershell
cd D:\auto_trader
.\.venv\Scripts\python.exe scripts\start_local_app.py
```

启动后打开：

```text
http://127.0.0.1:8000
```

常用地址：

- 前端工作台：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/healthz`

## 开发模式

前端单独开发：

```powershell
cd D:\auto_trader\frontend
npm.cmd run dev
```

后端单独启动：

```powershell
cd D:\auto_trader
.\.venv\Scripts\python.exe scripts\start_api.py
```

Electron 壳开发启动：

```powershell
cd D:\auto_trader\desktop
npm.cmd install
npm.cmd run dev
```

## 项目结构

- `api/`：FastAPI 后端、REST 接口、WebSocket、服务层
- `frontend/`：Vue + Pinia 前端工作台
- `desktop/`：Electron 桌面壳
- `config/`：示例配置、API 配置和配置加载器
- `core/`：行情、策略、回测、风控、审计、执行和数据缓存核心模块
- `strategies/`：策略实现
- `scripts/`：本地启动和桌面构建脚本
- `tests/`：测试用例

## 安全说明

- 默认交易模式是 `crypto_paper`。
- `real_trading_enabled` 默认必须为 `false`。
- Binance mainnet 真实交易尚未接入。
- Testnet 执行器默认 dry-run；启用前需要单独确认流程。
- 本地数据库、日志、打包产物、密钥和真实配置都不进入 Git。
