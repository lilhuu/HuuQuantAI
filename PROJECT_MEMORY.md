# HUU Auto Trade Console 项目记忆

更新时间：2026-04-29
项目路径：D:\auto_trader
桌面应用：C:\Users\Administrator\Desktop\HUU Auto Trade Console.exe

## 当前定位

这是一个本地桌面一体化自助股票交易平台，后端为 FastAPI，前端为 Vue，桌面壳为 Electron，后端交易内核由 PyInstaller 打包进桌面应用。

默认行情源仍保留为 HTTP 轮询，后续可以按需切换到 WebSocket 或券商 QMT/xtquant 行情。

## 当前主要模块

- 后端 API：api/
- 交易核心：main.py、core/
- 策略：strategies/
- 模型：models/
- 前端：frontend/
- 桌面壳：desktop/
- 构建脚本：scripts/build_desktop.py
- 配置：config/config.yaml、config/api_config.yaml
- 数据：data/
- 测试：tests/

## 已完成的重要能力

- FastAPI 后端骨架
- 登录和本地用户体系
- Vue 前端交易工作台
- Electron 桌面一体化应用
- FastAPI 托管前端 build
- 手动下单接口
- 账户接口
- 行情接口
- 订单接口和订单事件时间线
- 风控接口
- 策略接口
- WebSocket：market、orders、system
- EventBus 持久化与最近事件缓存
- 业务错误码体系
- SQLite 并发优化
- K 线聚合接口
- RSI 策略接入
- 双均线策略接入
- 模拟交易执行器统一到 UnifiedTrader
- QMT/xtquant 券商和行情适配器骨架

## 最近完成的修复

- RSI 策略从孤立文件接入主系统和 API。
- 风控每日统计跨日自动重置，不再只依赖交易信号触发。
- WebSocket 行情源从空壳改为可连接、可认证、可订阅、可缓存、可重连的通用适配器。
- 环境变量占位符支持 `${VAR}`、嵌入式字符串、`${VAR:-default}`。
- 新增 K 线聚合能力：1m、5m、15m、30m、60m、day、week、month。
- SQLite 从每次新建连接改为线程本地连接复用、写锁、重试、WAL。
- 修复 `core/unified_trader.py` 中订单拒绝消息乱码。
- 桌面应用多次重建并覆盖到桌面。

## 最近测试状态

最后一次全量测试结果：96 passed

常用测试命令：

```powershell
.\.venv\Scripts\python.exe -m pytest .\tests -q
```

## 常用构建命令

```powershell
.\.venv\Scripts\python.exe scripts\build_desktop.py
```

覆盖桌面 EXE：

```powershell
$src = 'D:\auto_trader\release\HUU Auto Trade Console.exe'
$dst = Join-Path ([Environment]::GetFolderPath('Desktop')) 'HUU Auto Trade Console.exe'
Copy-Item -Path $src -Destination $dst -Force
```

## 当前注意事项

- 项目当前不是 Git 仓库。
- 默认行情源仍是 `http_poller`。
- 真实交易必须显式关闭 dry_run 并配置真实券商 SDK，默认不会实盘下单。
- 不建议保存明文券商密码到配置文件。
- 桌面运行数据建议继续保存在 `%APPDATA%\AutoTrader`。

## 下一步建议

1. 初始化 Git 仓库，建立版本历史。
2. 给项目加正式备份脚本。
3. 前端接入 K 线图表。
4. 做策略回测模块。
5. 完善真实券商 SDK 的实盘接入说明和安全开关。
6. 增加项目设置页，允许在 UI 中切换行情源和策略参数。
