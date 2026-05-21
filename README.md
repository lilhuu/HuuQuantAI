# HuuQuantAI

HuuQuantAI 是本地运行的加密货币量化交易工作台，包含 FastAPI 后端、Vue 前端、Binance 公共行情、WebSocket 实时行情、本地模拟交易、策略验证、回测、风控、审计和桌面一体化打包。

当前版本默认只做模拟交易。Binance mainnet 真实下单保持关闭；Testnet 执行器默认 dry-run。

## 桌面应用

Windows 桌面版由 Electron 负责窗口和进程生命周期，PyInstaller 后端负责 FastAPI、WebSocket、策略、行情和数据服务。

```powershell
cd D:\auto_trader
.\.venv\Scripts\python.exe scripts\build_desktop.py
```

构建产物：

```text
release\HUU Auto Trade Console.exe
```

桌面运行数据目录：

```text
%APPDATA%\HuuQuantAI
```

## 数据库路线

当前运行库明确使用 SQLite：

```yaml
database:
  engine: sqlite
  sqlite_path: data/trading.db
```

`data/trading.db` 保存本地模拟订单、持仓、权益曲线、行情缓存、审计轨迹和影子交易状态。PostgreSQL 迁移是后续路线，当前版本不启用外部 PostgreSQL 驱动或迁移框架。

## 配置

本地配置文件是 `config/config.yaml`。首次部署可以从示例复制：

```powershell
Copy-Item config\config.example.yaml config\config.yaml
```

敏感配置请使用环境变量，例如：

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`
- `FRED_API_KEY`

## 本地启动

不打包桌面版时，可以用浏览器访问本地一体化服务：

```powershell
cd D:\auto_trader
.\.venv\Scripts\python.exe scripts\start_local_app.py
```

常用地址：

- 工作台：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/healthz`

## 开发

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

Electron 开发启动：

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
- `scripts/`：本地启动和桌面构建脚本
- `tests/`：测试用例

## 安全说明

- 默认交易模式是 `crypto_paper`。
- `real_trading_enabled` 默认必须为 `false`。
- Binance mainnet 真实交易尚未接入。
- Testnet 启用前需要单独确认短语，默认仍是 dry-run。
- 本地数据库、日志、打包产物、密钥和真实配置不进入 Git。
