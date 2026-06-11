"""Advisory-only AI chat assistant for the crypto workspace."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.ai_signal_advisor import AiAdvisorConfig, safe_json, utc_now
from core.sqlite_utils import configure_sqlite_connection


CHAT_SYSTEM_PROMPT = (
    "You are HuuQuantAI's project copilot, product guide, and advisory-only crypto quant assistant. "
    "Answer in Chinese unless the user asks otherwise. You can have normal conversations, explain how "
    "the HuuQuantAI app works, guide the user through modules and workflows, and answer crypto quant, "
    "strategy, risk, backtest, portfolio, paper-trading, and operations questions. Use the supplied "
    "project module knowledge, workspace state, market, K-line, account, position, order, and risk "
    "context when relevant. Do not promise profits. Do not recommend leverage, short selling, mainnet "
    "trading, or bypassing risk checks. You cannot place orders, cannot call paper/testnet/mainnet "
    "trading endpoints, and cannot change trading configuration. If the user asks you to trade, explain "
    "the risk and tell them to use the manual simulated trading controls themselves. Keep answers concise, "
    "practical, and clearly marked as research, product guidance, or simulated-trading advice. When "
    "guide_mode is true, or the user asks how to do something, where to click, how to backtest, or why "
    "auto trading did not place an order, prefer a step-by-step manual guide with: current judgment, "
    "operation steps, checkpoints, common failure causes, and a safety reminder. Steps must be manual "
    "user actions only; never imply that you can click, submit, place orders, cancel orders, or modify "
    "configuration for the user."
)


PROJECT_MODULES: list[dict[str, Any]] = [
    {
        "id": "dashboard",
        "name": "仪表盘",
        "route": "/",
        "purpose": "总览行情、AI 建议、风控审批、模拟订单和账户状态。",
        "key_actions": ["刷新总览", "查看 AI 建议", "检查风险步骤", "查看最近订单"],
        "common_questions": ["现在系统整体是否正常？", "当前最重要的风险是什么？"],
        "closed_loop_role": "把市场、AI、风控和模拟交易串成一个总控视角。",
    },
    {
        "id": "market",
        "name": "市场行情",
        "route": "/market",
        "purpose": "查看交易对行情、K 线、盘口深度和量价状态。",
        "key_actions": ["选择交易对", "切换周期", "加载 K 线", "查看盘口和报价列表"],
        "common_questions": ["这段行情趋势是否健康？", "成交量有没有确认突破？"],
        "closed_loop_role": "为 AI、策略和风控提供市场上下文。",
    },
    {
        "id": "manual_trade",
        "name": "手动交易",
        "route": "/trade",
        "purpose": "手动创建模拟订单，查看订单状态和模拟账户影响。",
        "key_actions": ["填写交易对", "选择 BUY/SELL", "输入小数数量", "提交模拟订单"],
        "common_questions": ["这笔模拟单会不会超出限额？", "卖出会不会超过持仓？"],
        "closed_loop_role": "承接人工确认后的 PaperBroker 模拟执行。",
    },
    {
        "id": "auto_trade",
        "name": "自动交易",
        "route": "/auto",
        "purpose": "配置策略扫描、交易对、周期、仓位限制和自动模拟执行开关。",
        "key_actions": ["保存扫描配置", "立即扫描", "启动或暂停自动循环", "查看决策记录"],
        "common_questions": ["为什么自动交易没有下单？", "哪一步被风控挡住了？"],
        "closed_loop_role": "把策略信号送入宏观门控、风控审批和模拟执行。",
    },
    {
        "id": "ai_assistant",
        "name": "AI 助手",
        "route": "/ai",
        "purpose": "进行结构化 AI 分析和自然语言项目问答。",
        "key_actions": ["选择模型", "触发 AI 分析", "查看建议理由", "手动确认生成模拟订单"],
        "common_questions": ["AI 为什么建议 HOLD？", "这个模块应该怎么用？"],
        "closed_loop_role": "提供建议、解释和操作引导，但不直接下单。",
    },
    {
        "id": "strategy",
        "name": "策略中心",
        "route": "/strategy",
        "purpose": "运行策略模板、查看信号、执行回测和比较策略表现。",
        "key_actions": ["加载策略模板", "运行策略", "执行回测", "查看信号和结果"],
        "common_questions": ["RSI 策略适合当前行情吗？", "哪个策略回撤更低？"],
        "closed_loop_role": "生成候选信号并提供可验证的策略依据。",
    },
    {
        "id": "backtest",
        "name": "回测中心",
        "route": "/backtest",
        "purpose": "验证策略历史表现、收益曲线、回撤和参数稳定性。",
        "key_actions": ["选择策略", "设置周期", "运行回测", "查看收益和回撤"],
        "common_questions": ["这个策略有没有过拟合？", "最大回撤是否可接受？"],
        "closed_loop_role": "在进入模拟执行前验证策略质量。",
    },
    {
        "id": "portfolio",
        "name": "投资组合",
        "route": "/portfolio",
        "purpose": "查看模拟组合收益、权益曲线、持仓敞口和分组归因。",
        "key_actions": ["切换时间范围", "查看权益曲线", "按交易对或策略归因"],
        "common_questions": ["组合风险集中在哪个币？", "资金曲线是否进入回撤？"],
        "closed_loop_role": "复盘模拟交易结果和 AI/策略建议效果。",
    },
    {
        "id": "account",
        "name": "账户状态",
        "route": "/account",
        "purpose": "查看 USDT 现金、持仓、资金曲线和 PaperBroker 日志。",
        "key_actions": ["查看现金", "查看持仓", "查看模拟日志", "检查账户权益"],
        "common_questions": ["当前可用资金是多少？", "哪些持仓风险最大？"],
        "closed_loop_role": "提供模拟盘资产和执行状态的事实依据。",
    },
    {
        "id": "risk",
        "name": "风控中心",
        "route": "/risk",
        "purpose": "检查最大单笔、最大持仓、禁止做空、禁止杠杆和真实交易关闭状态。",
        "key_actions": ["查看风控规则", "查看阻断原因", "检查 Kill Switch 状态"],
        "common_questions": ["这条信号为什么被拒绝？", "当前是否允许生成模拟订单？"],
        "closed_loop_role": "所有 AI 和策略信号进入模拟执行前的本地审批闸门。",
    },
    {
        "id": "audit",
        "name": "审计日志",
        "route": "/audit",
        "purpose": "追踪 AI 建议、风控审批、模拟订单、撤单和异常事件。",
        "key_actions": ["查看订单生命周期", "查看拒单记录", "复盘模拟日志"],
        "common_questions": ["哪条建议生成了订单？", "最近有哪些异常？"],
        "closed_loop_role": "保留可追溯证据链，方便复盘和排错。",
    },
    {
        "id": "diagnostics",
        "name": "诊断中心",
        "route": "/diagnostics",
        "purpose": "检查行情连接、自动循环、策略状态、缓存和执行质量。",
        "key_actions": ["查看健康雷达", "检查策略状态", "定位异常线索"],
        "common_questions": ["哪个模块不健康？", "为什么数据没有刷新？"],
        "closed_loop_role": "帮助判断系统问题在行情、策略、风控还是执行层。",
    },
    {
        "id": "settings",
        "name": "系统设置",
        "route": "/settings",
        "purpose": "查看模型、提醒音效、连接状态和真实交易安全边界。",
        "key_actions": ["切换 Flash/Pro", "查看连接状态", "确认真实交易关闭"],
        "common_questions": ["现在用的是哪个模型？", "真实交易是否关闭？"],
        "closed_loop_role": "管理工作台偏好和安全默认值。",
    },
]

MODULE_ALIASES = {
    "dashboard": "dashboard",
    "market": "market",
    "trade": "manual_trade",
    "manual_trade": "manual_trade",
    "auto": "auto_trade",
    "auto_trade": "auto_trade",
    "ai": "ai_assistant",
    "ai_assistant": "ai_assistant",
    "strategy": "strategy",
    "backtest": "backtest",
    "portfolio": "portfolio",
    "account": "account",
    "risk": "risk",
    "audit": "audit",
    "diagnostics": "diagnostics",
    "settings": "settings",
}

ROUTE_MODULE_MAP = {
    "/": "dashboard",
    "/market": "market",
    "/trade": "manual_trade",
    "/auto": "auto_trade",
    "/ai": "ai_assistant",
    "/strategy": "strategy",
    "/backtest": "backtest",
    "/portfolio": "portfolio",
    "/account": "account",
    "/risk": "risk",
    "/audit": "audit",
    "/diagnostics": "diagnostics",
    "/settings": "settings",
}

ROUTE_SUGGESTED_QUESTIONS = {
    "dashboard": ["帮我总结当前系统状态", "当前最重要的风险是什么？", "下一步应该检查哪个模块？"],
    "market": ["帮我解释当前 K 线走势", "成交量有没有确认趋势？", "当前行情适合观察哪些风险？"],
    "manual_trade": ["这笔模拟单提交前要检查什么", "卖出会不会超过持仓？", "这笔订单可能被哪些风控挡住？"],
    "auto_trade": ["为什么自动交易没有下单", "最近一次扫描卡在哪一步？", "自动交易配置应该先看哪里？"],
    "ai_assistant": ["AI 为什么给这个建议？", "这个建议能不能生成模拟订单？", "AI 的风险提示该怎么看？"],
    "strategy": ["当前策略结果怎么看", "哪个策略信号更可靠？", "策略冲突时应该看哪些字段？"],
    "backtest": ["这次回测结果该看哪些指标", "最大回撤是否可接受？", "这组参数有没有过拟合风险？"],
    "portfolio": ["帮我分析当前组合风险", "组合收益主要来自哪里？", "仓位是否过于集中？"],
    "account": ["帮我解释当前模拟账户状态", "当前可用资金够不够？", "哪些持仓需要重点关注？"],
    "risk": ["这个风控阻断是什么意思", "当前是否允许生成模拟订单？", "怎样理解最大单笔和持仓限制？"],
    "audit": ["帮我复盘最近订单生命周期", "最近有哪些拒单或异常？", "哪条 AI 建议关联了模拟订单？"],
    "diagnostics": ["当前系统哪里可能不健康", "为什么数据没有刷新？", "策略或行情连接是否异常？"],
    "settings": ["当前 AI 和交易安全配置是否正常", "现在使用的是 Flash 还是 Pro？", "真实交易是否保持关闭？"],
}

DEFAULT_SUGGESTED_QUESTIONS = [
    "这个项目怎么用？",
    "自动交易为什么没有下单？",
    "风控中心这些指标是什么意思？",
    "策略中心和回测中心有什么区别？",
]


ALLOWED_USER_ACTIONS = [
    "manual_click",
    "manual_input",
    "manual_confirm",
    "page_navigation",
    "read_only_review",
]

FORBIDDEN_AI_ACTIONS = [
    "place_order",
    "cancel_order",
    "enable_real_trading",
    "change_config",
    "click_ui",
    "call_trade_api",
]

OPERATION_GUIDES: list[dict[str, Any]] = [
    {
        "id": "system_overview",
        "module": "dashboard",
        "title": "查看系统状态",
        "goal": "确认行情、账户、风控、AI 和自动交易是否正常",
        "keywords": ["系统状态", "仪表盘", "总览", "健康", "状态"],
        "steps": [
            "进入仪表盘，先看顶部连接状态和当前交易对。",
            "检查市场概览、AI 建议、风控审批和模拟账户卡片是否有异常提示。",
            "如果有红色错误或连接断开，再进入诊断中心查看具体模块。",
        ],
        "check_points": ["行情连接", "AI 配置", "真实交易关闭", "模拟账户余额", "最近订单状态"],
        "common_failures": ["行情源不可用", "AI API Key 未配置", "自动交易处于暂停", "风控触发阻断"],
        "safety_notice": "这里只做状态查看，不会触发任何交易。",
    },
    {
        "id": "market_kline_analysis",
        "module": "market",
        "title": "分析行情和 K 线",
        "goal": "查看交易对趋势、成交量和关键价格区间",
        "keywords": ["行情", "K线", "K 线", "趋势", "价格", "成交量"],
        "steps": [
            "进入市场行情页面，选择交易对和周期。",
            "加载 K 线后观察均线、最新价、最高点、成交量和最近波动。",
            "再让 AI 总结趋势，但把结论当作研究建议，不直接作为下单依据。",
        ],
        "check_points": ["K 线数量", "最新收盘价", "成交量变化", "数据源状态", "周期是否匹配"],
        "common_failures": ["交易对格式错误", "行情源超时", "缓存数据过旧", "周期选择过短导致噪音大"],
        "safety_notice": "行情分析不等于交易信号，仍需经过策略和风控确认。",
    },
    {
        "id": "manual_paper_order",
        "module": "manual_trade",
        "title": "创建手动模拟订单",
        "goal": "手动提交一笔 PaperBroker 模拟买入或卖出",
        "keywords": ["手动", "模拟订单", "买入", "卖出", "下单", "订单"],
        "steps": [
            "进入手动交易页面，确认页面显示的是模拟交易。",
            "选择交易对、BUY 或 SELL，并填写小数数量和价格。",
            "提交前检查可用现金、当前持仓、单笔金额和风控提示。",
            "手动点击提交后，在订单列表和账户状态里复核成交结果。",
        ],
        "check_points": ["可用 USDT", "持仓数量", "价格", "数量", "手续费和滑点", "风控限制"],
        "common_failures": ["现金不足", "卖出超过持仓", "单笔金额超过限制", "价格或数量为 0"],
        "safety_notice": "AI 只能解释流程，不能替你点击提交或生成订单。",
    },
    {
        "id": "auto_no_order_diagnostics",
        "module": "auto_trade",
        "title": "排查自动交易为什么没下单",
        "goal": "定位自动交易停在行情、策略、宏观门控、风控还是提交阶段",
        "keywords": ["没下单", "沒有下单", "没有下单", "未下单", "为什么", "排查", "自动交易"],
        "steps": [
            "进入自动交易页面，先确认自动交易状态是运行中，且模式仍是 paper。",
            "检查交易对、周期、扫描间隔、置信度阈值、最大持仓和单笔金额配置。",
            "点击或等待一次扫描后查看最近决策流水，确认哪一步是 pass、fail 或 skip。",
            "如果信号通过但没有订单，继续到风控中心看阻断原因，再到审计日志看提交记录。",
        ],
        "check_points": ["自动交易状态", "策略信号", "置信度", "宏观门控", "风控审批", "可用现金", "持仓上限"],
        "common_failures": ["自动交易未启动", "策略信号为 HOLD", "置信度低于阈值", "宏观门控降低信号", "风控拒绝", "现金不足"],
        "safety_notice": "自动交易仍只允许模拟盘，AI 不会替你启动、暂停或提交订单。",
    },
    {
        "id": "strategy_signal_run",
        "module": "strategy",
        "title": "运行策略信号",
        "goal": "用当前策略模板生成可复核的候选信号",
        "keywords": ["策略信号", "运行策略", "信号", "策略"],
        "steps": [
            "进入策略中心，确认交易对、周期和策略模板。",
            "运行策略后查看每个策略的 action、confidence、reason 和冲突处理结果。",
            "只把通过本地规则和风控的信号作为候选，不直接进入真实交易。",
        ],
        "check_points": ["策略启用状态", "参数", "信号方向", "置信度", "冲突结果", "风控状态"],
        "common_failures": ["K 线不足", "策略参数不合理", "多个策略方向冲突", "置信度过低"],
        "safety_notice": "策略信号只是候选，需要风控审批和人工确认。",
    },
    {
        "id": "strategy_backtest",
        "module": "strategy",
        "title": "跑一次策略回测",
        "goal": "验证策略在历史 K 线上的收益、回撤和稳定性",
        "keywords": ["回测", "策略回测", "backtest", "跑一次", "历史表现"],
        "steps": [
            "进入策略中心或回测中心，选择交易对、周期、K 线数量和策略模板。",
            "确认初始资金、手续费、滑点和仓位参数后，手动点击运行回测。",
            "重点查看总收益、最大回撤、胜率、交易次数和权益曲线，而不是只看收益。",
            "如果结果异常，调整参数后再跑一次，并和原结果对比稳定性。",
        ],
        "check_points": ["样本长度", "手续费", "滑点", "最大回撤", "收益曲线", "交易次数", "参数稳定性"],
        "common_failures": ["K 线不足", "参数过拟合", "只在单一周期有效", "收益高但回撤不可接受"],
        "safety_notice": "回测不代表未来收益，不能绕过模拟交易和风控验证。",
    },
    {
        "id": "portfolio_risk_review",
        "module": "portfolio",
        "title": "查看组合风险",
        "goal": "判断模拟组合是否过度集中或进入明显回撤",
        "keywords": ["组合", "投资组合", "风险", "资金曲线", "回撤"],
        "steps": [
            "进入投资组合页面，选择观察时间范围。",
            "查看权益曲线、回撤、持仓分布和收益归因。",
            "如果某个币种或策略贡献过度集中，回到风控中心检查仓位限制。",
        ],
        "check_points": ["权益曲线", "最大回撤", "持仓集中度", "收益来源", "近期亏损次数"],
        "common_failures": ["样本太短", "持仓过度集中", "单个策略贡献异常", "缓存数据未刷新"],
        "safety_notice": "组合复盘只用于降低风险，不承诺收益最大化。",
    },
    {
        "id": "account_check",
        "module": "account",
        "title": "检查模拟账户",
        "goal": "确认 USDT 现金、持仓、订单和资金曲线是否一致",
        "keywords": ["账户", "现金", "持仓", "资金", "余额"],
        "steps": [
            "进入账户状态页面，查看 USDT 现金、可用资金和总权益。",
            "检查持仓列表的数量、成本、浮动盈亏和市值。",
            "对照最近订单和模拟日志，确认账户变化来源。",
        ],
        "check_points": ["现金", "可用资金", "总权益", "持仓数量", "最近成交", "模拟日志"],
        "common_failures": ["缓存未刷新", "部分成交导致数量不一致", "撤单后状态未同步"],
        "safety_notice": "账户页展示的是模拟账户，不代表真实资产。",
    },
    {
        "id": "risk_block_explanation",
        "module": "risk",
        "title": "查看风控阻断原因",
        "goal": "理解某条信号或订单为什么被本地风控拒绝",
        "keywords": ["风控", "阻断", "拒绝", "审批", "限制", "kill switch"],
        "steps": [
            "进入风控中心，先确认真实交易关闭、禁止做空和禁止杠杆仍然生效。",
            "查看最大单笔金额、最大持仓、总仓位、冷却期和 Kill Switch 状态。",
            "对照自动交易决策或 AI 建议的金额、方向、持仓和置信度，定位被拒原因。",
            "需要调整时只在系统设置或自动交易配置里手动修改，AI 不能替你改配置。",
        ],
        "check_points": ["真实交易关闭", "最大单笔金额", "最大持仓", "现金余额", "持仓数量", "冷却期", "Kill Switch"],
        "common_failures": ["超过单笔上限", "超过持仓上限", "卖出超过持仓", "连续亏损触发冷却", "真实交易安全门关闭"],
        "safety_notice": "风控阻断优先级高于 AI 和策略建议，不能绕过。",
    },
    {
        "id": "audit_order_review",
        "module": "audit",
        "title": "复盘订单审计日志",
        "goal": "追踪 AI 建议、风控审批、订单提交和成交结果",
        "keywords": ["审计", "日志", "复盘", "订单生命周期", "拒单"],
        "steps": [
            "进入审计日志页面，按时间查看 AI 建议、审批、订单和撤单事件。",
            "找到目标订单或信号后，对照状态、原因和关联订单 ID。",
            "如果状态异常，再进入诊断中心检查连接和数据刷新。",
        ],
        "check_points": ["signal_id", "order_id", "approval_status", "reject_reason", "created_at"],
        "common_failures": ["日志被过滤", "信号没有生成订单", "风控拒单", "成交状态延迟刷新"],
        "safety_notice": "审计用于复盘和追责，不会执行交易动作。",
    },
    {
        "id": "diagnostics_health_check",
        "module": "diagnostics",
        "title": "排查系统诊断问题",
        "goal": "定位行情、策略、缓存、自动循环或 AI 配置异常",
        "keywords": ["诊断", "异常", "不健康", "连接", "刷新", "不可用"],
        "steps": [
            "进入诊断中心，先看连接、行情、策略、缓存和 AI 的健康状态。",
            "根据异常模块跳转到对应页面复核，例如行情页、策略中心或系统设置。",
            "如果 AI 不可用，检查模型配置和环境变量是否存在。",
        ],
        "check_points": ["WebSocket", "行情源", "缓存新鲜度", "策略状态", "AI provider", "错误日志"],
        "common_failures": ["网络不可用", "交易所行情源限流", "API Key 缺失", "本地缓存过期"],
        "safety_notice": "诊断过程只读，不要用 AI 指令开启真实交易。",
    },
    {
        "id": "settings_safety_check",
        "module": "settings",
        "title": "检查 AI 模型和真实交易安全配置",
        "goal": "确认 Flash/Pro 模型、上下文开关和真实交易关闭状态",
        "keywords": ["设置", "模型", "Flash", "Pro", "真实交易", "安全配置"],
        "steps": [
            "进入系统设置页面，确认 AI provider、模型模式和环境变量状态。",
            "检查真实交易状态必须保持关闭，模拟交易仍由用户手动确认。",
            "需要切换模型时，在 AI 抽屉右下角选择 Flash 或 Pro 后再发送问题。",
        ],
        "check_points": ["AI provider", "模型", "API Key 状态", "真实交易关闭", "模拟盘模式"],
        "common_failures": ["API Key 未设置", "模型名不匹配", "配置示例与运行配置不一致", "误以为 AI 能自动下单"],
        "safety_notice": "AI 不能打开真实交易，也不能修改配置文件。",
    },
]


class ProjectAssistantContextBuilder:
    """Build safe project-copilot context for AI chat."""

    @staticmethod
    def build_base(
        *,
        symbol: str,
        period: str,
        include_market_context: bool,
        ai_config: AiAdvisorConfig,
        current_route: str | None = None,
        current_module: str | None = None,
        current_view_title: str | None = None,
        visible_context: dict[str, Any] | None = None,
        guide_mode: bool = False,
        user_goal: str | None = None,
    ) -> dict[str, Any]:
        context_mode = "project_and_market" if include_market_context else "project_only"
        active_module = ProjectAssistantContextBuilder.find_module(
            current_module=current_module,
            current_route=current_route,
        )
        active_guide = ProjectAssistantContextBuilder.select_operation_guide(
            active_module=active_module,
            current_route=current_route,
            user_goal=user_goal,
        )
        operation_guides = ProjectAssistantContextBuilder.guides_for_module(
            str((active_module or {}).get("id") or active_guide.get("module") or "")
        )
        route_questions = (
            ROUTE_SUGGESTED_QUESTIONS.get(str(active_module.get("id") or ""), [])
            if active_module
            else DEFAULT_SUGGESTED_QUESTIONS
        )
        return {
            "symbol": symbol,
            "period": period,
            "assistant_scope": {
                "role": "HuuQuantAI 项目副驾驶",
                "can_help_with": [
                    "正常聊天",
                    "项目模块使用说明",
                    "加密货币量化概念解释",
                    "策略、风控、回测、组合分析",
                    "模拟交易流程和审计复盘",
                ],
                "answer_style": "中文、简洁、实用、可操作",
            },
            "project_modules": PROJECT_MODULES,
            "current_workspace": {
                "symbol": symbol,
                "period": period,
                "context_mode": context_mode,
                "trading_mode": "paper_trading",
                "real_trading_status": "disabled",
                "current_route": current_route or "",
                "current_module": active_module.get("id") if active_module else (current_module or ""),
                "current_view_title": current_view_title or active_module.get("name", "") if active_module else current_view_title or "",
                "active_module": active_module.get("id") if active_module else "",
                "visible_context": ProjectAssistantContextBuilder.sanitize_visible_context(visible_context or {}),
            },
            "available_capabilities": {
                "normal_chat": True,
                "project_usage_help": True,
                "market_analysis": bool(include_market_context),
                "strategy_explanation": True,
                "risk_explanation": True,
                "backtest_explanation": True,
                "portfolio_review": True,
                "paper_trading": True,
                "testnet_ordering_by_ai": False,
                "real_ordering_by_ai": False,
            },
            "safety_boundaries": {
                "advisory_only": True,
                "can_place_orders": False,
                "can_change_config": False,
                "paper_order_allowed_by_ai": False,
                "testnet_order_allowed_by_ai": False,
                "real_trading_allowed": False,
                "manual_confirm_required": True,
                "forbidden": ["真实下单", "自动模拟下单", "打开真实交易", "绕过风控", "杠杆", "做空"],
            },
            "ai_limits": {
                "mode": ai_config.mode,
                "manual_confirm_required": True,
                "auto_paper_order_enabled": False,
                "real_trading_allowed": False,
            },
            "active_module_guide": active_module or {},
            "guide_mode": bool(guide_mode),
            "operation_guides": operation_guides,
            "active_operation_guide": active_guide if guide_mode else {},
            "allowed_user_actions": ALLOWED_USER_ACTIONS,
            "forbidden_ai_actions": FORBIDDEN_AI_ACTIONS,
            "route_suggested_questions": route_questions,
            "suggested_questions": route_questions
            if active_module
            else [*DEFAULT_SUGGESTED_QUESTIONS, f"帮我解释当前 {symbol} 的模拟账户风险"],
        }

    @staticmethod
    def find_module(*, current_module: str | None = None, current_route: str | None = None) -> dict[str, Any]:
        module_id = ""
        if current_module:
            module_id = MODULE_ALIASES.get(str(current_module).strip().strip("/"), "")
        if not module_id and current_route:
            path = "/" + str(current_route).strip().split("?", 1)[0].strip("/")
            if path == "/":
                module_id = "dashboard"
            else:
                module_id = ROUTE_MODULE_MAP.get(path, "")
        for module in PROJECT_MODULES:
            if module.get("id") == module_id:
                return dict(module)
        return {}

    @staticmethod
    def guides_for_module(module_id: str) -> list[dict[str, Any]]:
        module = str(module_id or "").strip()
        guides = [dict(guide) for guide in OPERATION_GUIDES if guide.get("module") == module]
        return guides or [dict(guide) for guide in OPERATION_GUIDES if guide.get("id") == "system_overview"]

    @staticmethod
    def select_operation_guide(
        *,
        active_module: dict[str, Any] | None = None,
        current_route: str | None = None,
        user_goal: str | None = None,
    ) -> dict[str, Any]:
        module_id = str((active_module or {}).get("id") or "").strip()
        if not module_id and current_route:
            module = ProjectAssistantContextBuilder.find_module(current_route=current_route)
            module_id = str(module.get("id") or "").strip()
        candidates = ProjectAssistantContextBuilder.guides_for_module(module_id)
        all_guides = [dict(guide) for guide in OPERATION_GUIDES]
        text = str(user_goal or "").strip().lower()

        def score(guide: dict[str, Any]) -> int:
            score_value = 0
            if module_id and guide.get("module") == module_id:
                score_value += 3
            haystack = " ".join(
                [
                    str(guide.get("id") or ""),
                    str(guide.get("title") or ""),
                    str(guide.get("goal") or ""),
                    " ".join(str(item) for item in guide.get("keywords", []) or []),
                ]
            ).lower()
            if text:
                for token in [part for part in text.replace("?", " ").replace("？", " ").split() if part]:
                    if token in haystack:
                        score_value += 2
                for keyword in guide.get("keywords", []) or []:
                    if str(keyword).lower() in text:
                        score_value += 5
            return score_value

        best = max(all_guides, key=score) if all_guides else {}
        if best and score(best) > 0:
            return dict(best)
        return dict(candidates[0]) if candidates else {}

    @staticmethod
    def sanitize_visible_context(value: Any, *, depth: int = 0) -> Any:
        if depth >= 4:
            return "[truncated]"
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 24:
                    sanitized["__truncated__"] = True
                    break
                key_text = str(key)[:80]
                if any(token in key_text.lower() for token in ["api_key", "secret", "password", "token"]):
                    sanitized[key_text] = "[redacted]"
                else:
                    sanitized[key_text] = ProjectAssistantContextBuilder.sanitize_visible_context(item, depth=depth + 1)
            return sanitized
        if isinstance(value, list):
            return [ProjectAssistantContextBuilder.sanitize_visible_context(item, depth=depth + 1) for item in value[:12]]
        if isinstance(value, str):
            return value[:500]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)[:500]

    @staticmethod
    def runtime_summary(
        *,
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        recent_orders: list[dict[str, Any]],
        quote: dict[str, Any],
        macro: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "account": {
                "cash": account.get("cash"),
                "available_cash": account.get("available_cash"),
                "equity": account.get("equity") or account.get("total_equity"),
            },
            "positions_count": len(positions or []),
            "recent_orders_count": len(recent_orders or []),
            "quote": {
                "symbol": quote.get("symbol"),
                "price": quote.get("price"),
                "change": quote.get("change"),
                "source": quote.get("source"),
            },
            "macro_state": macro.get("gate", macro) if isinstance(macro, dict) else {},
        }


class AiChatAssistant:
    """Provider-backed natural-language assistant.

    The class only returns text. It does not expose tools and cannot execute
    paper, testnet, or real orders.
    """

    def __init__(self, config: dict[str, Any] | AiAdvisorConfig | None = None) -> None:
        self.config = config if isinstance(config, AiAdvisorConfig) else AiAdvisorConfig.from_dict(config)

    def chat(
        self,
        *,
        message: str,
        context_summary: dict[str, Any],
        recent_messages: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            raise RuntimeError("AI assistant is disabled in config")
        if self.config.provider not in {"openai", "deepseek"}:
            raise RuntimeError(f"unsupported AI provider: {self.config.provider}")
        api_key = os.environ.get(self.config.api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(f"missing {self._provider_label()} API key env: {self.config.api_key_env}")

        payload = {
            "user_message": str(message or "").strip(),
            "context_summary": context_summary,
            "recent_messages": [
                {
                    "role": str(item.get("role") or ""),
                    "content": str(item.get("content") or "")[:2000],
                    "created_at": str(item.get("created_at") or ""),
                }
                for item in (recent_messages or [])[-12:]
            ],
            "safety": {
                "advisory_only": True,
                "real_trading_allowed": False,
                "paper_order_allowed_by_ai": False,
                "testnet_order_allowed_by_ai": False,
                "manual_confirm_required": True,
            },
        }

        last_error: Exception | None = None
        for candidate_model in self._candidate_models(model):
            if not candidate_model:
                continue
            try:
                content = self._call_provider(api_key=api_key, model=candidate_model, payload=payload)
                if not content.strip():
                    raise ValueError(f"{self._provider_label()} chat response was empty")
                return {"model": candidate_model, "content": content.strip()}
            except Exception as exc:  # pragma: no cover - covered by service tests with monkeypatches.
                last_error = exc
                if model or candidate_model == self.config.fallback_model:
                    break
        raise RuntimeError(f"{self._provider_label()} AI chat request failed: {last_error}")

    def _candidate_models(self, selected_model: str | None = None) -> list[str]:
        if selected_model:
            return [str(selected_model).strip()]
        candidates: list[str] = []
        for model in [self.config.model, self.config.fallback_model]:
            model_text = str(model or "").strip()
            if model_text and model_text not in candidates:
                candidates.append(model_text)
        return candidates

    def _provider_label(self) -> str:
        return "DeepSeek" if self.config.provider == "deepseek" else "OpenAI"

    def _call_provider(self, *, api_key: str, model: str, payload: dict[str, Any]) -> str:
        if self.config.provider == "deepseek":
            return self._call_deepseek(api_key=api_key, model=model, payload=payload)
        return self._call_openai(api_key=api_key, model=model, payload=payload)

    def _call_openai(self, *, api_key: str, model: str, payload: dict[str, Any]) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            instructions=CHAT_SYSTEM_PROMPT,
            input=safe_json(payload),
        )
        return getattr(response, "output_text", "") or self._extract_output_text(response)

    def _call_deepseek(self, *, api_key: str, model: str, payload: dict[str, Any]) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=self.config.base_url or "https://api.deepseek.com")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": safe_json(payload)},
            ],
            temperature=0.2,
        )
        choices = getattr(response, "choices", []) or []
        if not choices:
            raise ValueError("DeepSeek chat response did not include choices")
        message = getattr(choices[0], "message", None)
        return str(getattr(message, "content", "") if message else "")

    def _extract_output_text(self, response: Any) -> str:
        parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()


class AiChatStore:
    """SQLite-backed chat session and message store."""

    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(path)
        self._setup()

    def save_exchange(
        self,
        *,
        session_id: str | None,
        title_seed: str,
        user_content: str,
        assistant_content: str,
        model: str,
        context_summary: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            session = self._get_session(conn, session_id) if session_id else None
            if session_id and session is None:
                return {}
            if session is None:
                session_id = self._new_session_id()
                title = self._make_title(title_seed)
                conn.execute(
                    """
                    INSERT INTO ai_chat_sessions(session_id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (session_id, title, now, now),
                )
            user_message = self._insert_message(
                conn,
                session_id=str(session_id),
                role="user",
                content=user_content,
                model="",
                context_summary={},
                created_at=now,
            )
            assistant_message = self._insert_message(
                conn,
                session_id=str(session_id),
                role="assistant",
                content=assistant_content,
                model=model,
                context_summary=context_summary,
                created_at=utc_now(),
            )
            conn.execute(
                """
                UPDATE ai_chat_sessions
                SET updated_at = ?
                WHERE session_id = ?
                """,
                (assistant_message["created_at"], session_id),
            )
            session = self._get_session(conn, str(session_id))
        return {
            "session": session,
            "user_message": user_message,
            "assistant_message": assistant_message,
        }

    def list_sessions(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        safe_limit = max(1, min(int(limit or 50), 200))
        safe_offset = max(0, int(offset or 0))
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM ai_chat_sessions").fetchone()[0]
            rows = conn.execute(
                """
                SELECT s.*,
                       COUNT(m.message_id) AS message_count,
                       (
                         SELECT content
                         FROM ai_chat_messages last_m
                         WHERE last_m.session_id = s.session_id
                         ORDER BY last_m.created_at DESC, last_m.message_id DESC
                         LIMIT 1
                       ) AS last_message
                FROM ai_chat_sessions s
                LEFT JOIN ai_chat_messages m ON m.session_id = s.session_id
                GROUP BY s.session_id
                ORDER BY s.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (safe_limit, safe_offset),
            ).fetchall()
        return {
            "items": [self._session_row_to_record(row) for row in rows],
            "count": len(rows),
            "total": int(total or 0),
            "limit": safe_limit,
            "offset": safe_offset,
        }

    def get_session_detail(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            session = self._get_session(conn, session_id)
            if not session:
                return None
            rows = conn.execute(
                """
                SELECT *
                FROM ai_chat_messages
                WHERE session_id = ?
                ORDER BY created_at ASC, message_id ASC
                """,
                (str(session_id),),
            ).fetchall()
        return {"session": session, "messages": [self._message_row_to_record(row) for row in rows]}

    def list_messages(self, session_id: str, limit: int = 12) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 12), 50))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM ai_chat_messages
                WHERE session_id = ?
                ORDER BY created_at DESC, message_id DESC
                LIMIT ?
                """,
                (str(session_id), safe_limit),
            ).fetchall()
        return list(reversed([self._message_row_to_record(row) for row in rows]))

    def delete_session(self, session_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM ai_chat_sessions WHERE session_id = ?", (str(session_id),))
        return cursor.rowcount > 0

    def _setup(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ai_chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_chat_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT DEFAULT '',
                    context_summary_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES ai_chat_sessions(session_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_ai_chat_sessions_updated
                    ON ai_chat_sessions(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_session_created
                    ON ai_chat_messages(session_id, created_at ASC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        configure_sqlite_connection(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _get_session(self, conn: sqlite3.Connection, session_id: str | None) -> dict[str, Any] | None:
        if not session_id:
            return None
        row = conn.execute(
            """
            SELECT s.*,
                   COUNT(m.message_id) AS message_count,
                   (
                     SELECT content
                     FROM ai_chat_messages last_m
                     WHERE last_m.session_id = s.session_id
                     ORDER BY last_m.created_at DESC, last_m.message_id DESC
                     LIMIT 1
                   ) AS last_message
            FROM ai_chat_sessions s
            LEFT JOIN ai_chat_messages m ON m.session_id = s.session_id
            WHERE s.session_id = ?
            GROUP BY s.session_id
            """,
            (str(session_id),),
        ).fetchone()
        return self._session_row_to_record(row) if row else None

    def _insert_message(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        role: str,
        content: str,
        model: str,
        context_summary: dict[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        message_id = self._new_message_id(role)
        record = {
            "message_id": message_id,
            "session_id": session_id,
            "role": role,
            "content": str(content or ""),
            "model": str(model or ""),
            "context_summary": context_summary,
            "created_at": created_at,
        }
        conn.execute(
            """
            INSERT INTO ai_chat_messages
                (message_id, session_id, role, content, model, context_summary_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["message_id"],
                record["session_id"],
                record["role"],
                record["content"],
                record["model"],
                safe_json(record["context_summary"]),
                record["created_at"],
            ),
        )
        return record

    def _session_row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": int(row["message_count"] or 0) if "message_count" in row.keys() else 0,
            "last_message": str(row["last_message"] or "") if "last_message" in row.keys() else "",
        }

    def _message_row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "message_id": row["message_id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "model": row["model"] or "",
            "context_summary": json.loads(row["context_summary_json"] or "{}"),
            "created_at": row["created_at"],
        }

    def _new_session_id(self) -> str:
        return f"AICHAT_{int(time.time() * 1000)}_{uuid4().hex[:8]}"

    def _new_message_id(self, role: str) -> str:
        return f"AICHATMSG_{role.upper()}_{int(time.time() * 1000)}_{uuid4().hex[:8]}"

    def _make_title(self, seed: str) -> str:
        normalized = " ".join(str(seed or "AI 对话").strip().split())
        return normalized[:36] or "AI 对话"
