# HuuQuantAI

HuuQuantAI 是本地运行的加密货币量化交易工作台，包含 FastAPI 后端、Vue 前端、Binance 公共行情、本地模拟交易、策略验证、回测、风控、审计、AI 信号分析、AI 对话助手和 Windows 桌面打包。

当前版本面向 Binance 公共行情和本地 Paper Trading。真实交易默认关闭，Binance mainnet 不接入；Testnet 执行器默认 dry-run，不会发送真实交易。

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

## AI 助手

项目包含两类 AI 功能：

- `AI 信号` 页面：生成结构化 BUY/SELL/HOLD 建议，必须经过本地风控审批，不能自动下单。
- `AI 对话` 抽屉：全局右侧助手，可回答行情、K 线、账户、持仓、策略、风控、回测和复盘问题。

AI 对话接口：

```text
POST   /api/v1/crypto/ai/chat
GET    /api/v1/crypto/ai/chat/sessions
GET    /api/v1/crypto/ai/chat/sessions/{session_id}
DELETE /api/v1/crypto/ai/chat/sessions/{session_id}
```

聊天记录会保存到当前 SQLite 运行库中：

```text
ai_chat_sessions
ai_chat_messages
```

安全边界：

- AI 只能给建议和解释，不能真实下单。
- AI 不能调用 PaperBroker、Testnet 或 mainnet 下单接口。
- 用户要求“帮我下单”时，助手只能提示风险并引导用户手动操作模拟交易控件。
- API Key 只从环境变量读取，不写入前端、不落入聊天记录。

## 数据库

当前运行库使用 SQLite：

```yaml
database:
  engine: sqlite
  sqlite_path: data/trading.db
```

`data/trading.db` 保存本地模拟订单、持仓、权益曲线、行情缓存、审计轨迹、影子交易状态、AI 信号和 AI 对话记录。PostgreSQL 迁移仍是后续路线，当前版本不启用外部 PostgreSQL。

## 配置

本地配置文件是 `config/config.yaml`。首次部署可以从示例复制：

```powershell
Copy-Item config\config.example.yaml config\config.yaml
```

敏感配置请使用环境变量：

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`
- `FRED_API_KEY`
- `OPENAI_API_KEY`

AI 默认配置示例：

```yaml
ai:
  enabled: false
  provider: openai
  model: gpt-5.2
  fallback_model: gpt-5-mini
  api_key_env: OPENAI_API_KEY
  mode: advisory
  manual_confirm_required: true
  auto_paper_order_enabled: false
```

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

- `api/`: FastAPI 后端、REST 接口、WebSocket 和服务层。
- `core/`: 行情、策略、回测、风控、审计、AI、执行器和数据缓存核心模块。
- `frontend/`: Vue + Pinia 前端工作台。
- `desktop/`: Electron 桌面壳。
- `config/`: 示例配置、API 配置和配置加载器。
- `scripts/`: 本地启动和桌面构建脚本。
- `tests/`: 后端测试用例。

## 验证命令

```powershell
cd D:\auto_trader
.\.venv\Scripts\python.exe -m pytest

cd D:\auto_trader\frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

## 安全说明

- 默认交易模式是 `crypto_paper`。
- `real_trading_enabled` 默认并且必须保持为 `false`。
- Binance mainnet 真实交易未接入。
- Testnet 交易在当前构建中仍以 dry-run 为默认保护。
- 本地数据库、日志、打包产物、密钥和真实配置不进入 Git。
- 主网交易前必须另行实现签名下单、订单状态同步、撤单、余额同步、交易所精度校验和更强密钥保护。
