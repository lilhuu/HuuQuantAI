# AI Agent 系统性学习路线

> 目标：从零基础到能够独立设计、开发和部署 AI Agent 系统。
> 预计周期：3-6 个月（每天 1-2 小时投入）。

---

## 一、路线总览

```
Phase 1 ─── 基础储备（2-4 周）
  ├─ Python 编程基础
  ├─ LLM 原理与 API 使用
  └─ 提示词工程

Phase 2 ─── Agent 核心概念（2-3 周）
  ├─ Agent 架构与类型
  ├─ 工具调用（Function Calling）
  ├─ 记忆系统
  └─ 规划与推理

Phase 3 ─── 框架实战（3-5 周）
  ├─ 主流框架上手
  ├─ 单 Agent 系统构建
  ├─ 多 Agent 协作
  └─ MCP 协议

Phase 4 ─── 进阶与生产化（3-4 周）
  ├─ RAG + Agent
  ├─ 可观测性与调试
  ├─ 安全与对齐
  └─ 部署方案

Phase 5 ─── 项目实战（持续）
  ├─ 从简单到复杂逐步迭代
  └─ 开源贡献
```

---

## 二、Phase 1：基础储备（第 1-4 周）

### 2.1 Python 编程基础

> 时间：1-2 周 | 目标：能熟练编写脚本、处理数据、调用 API

| 知识点 | 说明 | 推荐资源 |
|--------|------|----------|
| Python 语法基础 | 变量、控制流、函数、类 | Python 官方教程 |
| 异步编程 | `async/await`、`asyncio` 事件循环 | Real Python: Async IO |
| HTTP 请求 | `requests`、`httpx`、`aiohttp` | 官方文档 + 实战 |
| 数据处理 | `json`、`pandas` 基础 | 官方文档 |
| 包管理 | `pip`、`venv`、`poetry` | 官方文档 |
| 版本控制 | Git 基础操作 | Pro Git 书籍 |

**检验项目**：写一个异步爬虫，并发获取 10 个 API 的数据并合并保存。

### 2.2 大语言模型（LLM）原理与 API

> 时间：1 周 | 目标：理解 LLM 的基本原理，能熟练调用主流 API

**理论知识**：
- Transformer 架构概览（注意力机制、编码器-解码器）
- 预训练 → 微调 → 对齐（RLHF/DPO）的基本流程
- Tokenization、上下文窗口、温度等关键概念
- 模型间的差异：GPT、Claude、Gemini、开源模型

**实践技能**：
- 调用 OpenAI / Anthropic API：文本生成、流式输出
- 理解 system prompt、user message、assistant message 的角色
- 掌握常用参数：`temperature`、`max_tokens`、`top_p`、`stop`

**检验项目**：通过 API 用 Chain of Thought 提示词解决一个数学推理问题。

### 2.3 提示词工程（Prompt Engineering）

> 时间：1 周 | 目标：掌握结构化提示词编写技巧，能系统性地调试 Prompt

**核心技法**：
- 角色设定（System Prompt）
- 少样本学习（Few-shot）
- 思维链（Chain-of-Thought, CoT）
- 思维树（Tree-of-Thought, ToT）
- 分解任务（Task Decomposition）
- 格式约束（JSON Output、Markdown）

**推荐阅读**：
- OpenAI Prompt Engineering Guide
- Anthropic Prompt Engineering Guide

**检验项目**：用提示词让模型从非结构化文本中提取结构化数据（JSON），覆盖各种边界情况。

---

## 三、Phase 2：Agent 核心概念（第 5-7 周）

### 3.1 理解 AI Agent

> 时间：3-5 天

**什么是 AI Agent？**
一个 AI Agent 是一个能自主感知环境、制定计划、使用工具并执行行动来完成目标的系统。不同于单纯的 LLM 问答，Agent 具有：

- **自主性**：无需逐条指令即可推进任务
- **工具使用**：调用外部 API、数据库、浏览器等
- **记忆**：记住对话历史和关键信息
- **规划**：将复杂目标分解为子步骤
- **反思**：根据执行结果调整策略

**经典架构**（以 Anthropic 的定义为例）：

```
用户输入 → 规划（思考需要做什么）
            ↓
         工具调用（执行具体操作）
            ↓
         观察结果（工具返回的信息）
            ↓
         推理与调整（判断是否需要下一步）
            ↓
         最终输出（向用户返回结果）
```

**Agent 类型对比**：

| 类型 | 描述 | 适用场景 |
|------|------|----------|
| ReAct Agent | 思考-行动-观察循环 | 通用任务 |
| Plan-and-Execute Agent | 先规划再逐步执行 | 复杂多步骤任务 |
| Reflection Agent | 执行后自我反思改进 | 写作、代码生成 |
| Multi-Agent | 多个 Agent 协作 | 复杂工作流 |

### 3.2 工具调用（Function Calling / Tool Use）

> 时间：1 周

**核心概念**：
- Tool 的定义：名称、描述、参数 Schema（JSON Schema）
- LLM 如何决定调用哪个工具
- 工具执行结果如何反馈给 LLM 进行下一步推理
- 并行工具调用（Parallel Tool Calling）

**实战技能**：
- 定义搜索、计算、文件读写等工具
- 实现工具的自动注册和分发
- 处理工具调用失败和重试逻辑

```python
# 伪代码示例：工具定义
tools = [
    {
        "name": "search_web",
        "description": "搜索网络获取最新信息",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"}
            },
            "required": ["query"]
        }
    }
]
```

**检验项目**：构建一个能搜索网络、读取网页内容并总结的 Agent。

### 3.3 记忆系统（Memory）

> 时间：3-5 天

Agent 的记忆分为多个层次：

| 记忆类型 | 存储内容 | 实现方式 | 生命周期 |
|----------|----------|----------|----------|
| 短期记忆 | 当前对话上下文 | LLM 上下文窗口 | 一次对话 |
| 长期记忆 | 用户偏好、历史事实 | 向量数据库 / 文件 | 跨对话 |
| 工作记忆 | 当前任务进度 | 临时变量 / 文件 | 任务期间 |

**关键实现**：
- 对话历史管理（滑动窗口、摘要压缩）
- 向量数据库检索（ChromaDB、Pinecone、Milvus）
- 关键信息提取与结构化存储
- 记忆的优先级与遗忘机制

**检验项目**：给 Agent 添加长期记忆，使其能记住用户的偏好并在后续对话中使用。

### 3.4 规划与推理（Planning & Reasoning）

> 时间：5-7 天

**关键技术**：
- **ReAct**：交替进行推理（Thought）和行动（Action）
- **Plan-and-Solve**：先制定完整计划，再逐步执行
- **Self-Reflection**：执行后评估结果、修正错误
- **Repeated Reflection**：多次反思改进输出质量

**实现方式**：
- 利用 LLM 的 Chain-of-Thought 能力
- 显式的规划步骤（Plan 写入文件或变量）
- 子任务分解与依赖管理
- 循环执行直到任务完成或达到最大轮次

**检验项目**：构建一个能自动研究一个话题的 Agent（搜索 → 阅读 → 总结 → 生成报告）。

---

## 四、Phase 3：框架实战（第 8-11 周）

### 4.1 主流框架概览与选择

| 框架 | 语言 | 特点 | 适合场景 |
|------|------|------|----------|
| **LangChain / LangGraph** | Python/JS | 生态最丰富、灵活度高 | 通用 Agent 开发 |
| **AutoGen (Microsoft)** | Python | 多 Agent 对话 | 多 Agent 协作 |
| **CrewAI** | Python | 简洁易用、角色化 | 快速原型 |
| **Semantic Kernel** | C#/Python | 企业级、Azure 集成 | .NET 生态 |
| **Anthropic SDK** | Python/JS | 原生 MCP 支持、简洁 | Claude 专用 |
| **OpenAI SDK** | Python/JS | 原生 Function Calling | GPT 专用 |
| **Smolagents (HuggingFace)** | Python | 轻量级、代码优先 | 实验与教学 |
| **Agno** | Python | 极简设计、生产级 | 轻量 Agent |

**推荐学习路径**：先从 **LangChain / LangGraph** 入手（生态最丰富），再根据项目需要学习其他框架。

### 4.2 LangChain 入门

> 时间：1 周

**学习步骤**：
1. 理解 LangChain 核心概念：Model I/O、Retrieval、Chain、Agent、Tool
2. 掌握 ChatModel 的调用
3. 学习 Prompt Template 管理
4. 构建简单的 Chain
5. 集成 Tool 和 Agent Executor

**关键知识点**：
- `ChatOpenAI` / `ChatAnthropic`
- `PromptTemplate` / `ChatPromptTemplate`
- `StrOutputParser` / `PydanticOutputParser`
- `Tool` 的定义与注册
- `AgentExecutor` 的运行机制

**检验项目**：用 LangChain 构建一个具备搜索和计算功能的客服 Agent。

### 4.3 LangGraph：状态化 Agent

> 时间：1-2 周

LangGraph 是 LangChain 的进阶框架，支持有状态、循环的工作流，是实现复杂 Agent 的核心工具。

**学习要点**：
- StateGraph：定义状态和图结构
- Node：每个处理步骤
- Edge：步骤之间的跳转逻辑
- Conditional Edge：条件分支
- 循环与终止条件

```python
# 伪代码：LangGraph 的基本结构
graph = StateGraph(AgentState)
graph.add_node("agent", call_agent)
graph.add_node("tools", call_tools)
graph.add_edge("agent", "tools")
graph.add_conditional_edges("tools", should_continue)
graph.set_entry_point("agent")
app = graph.compile()
```

**检验项目**：用 LangGraph 构建一个 ReAct Agent，支持多轮工具调用和错误恢复。

### 4.4 多 Agent 系统

> 时间：1 周

**架构模式**：
- **Supervisor Agent**：一个主 Agent 协调多个子 Agent
- **Debate / Discussion**：多个 Agent 讨论协作
- **Pipeline**：Agent 链式传递结果
- **Hierarchical**：层级化管理

**实现方式**：
- LangGraph 的 `Send` API 实现并行 Agent
- AutoGen 的对话式多 Agent
- CrewAI 的角色化多 Agent

**检验项目**：构建一个 Supervisor + 两个 Specialist 的多 Agent 系统（如：一个研究 Agent + 一个写作 Agent，由 Supervisor 协调）。

### 4.5 MCP 协议（Model Context Protocol）

> 时间：3-5 天

MCP 是 Anthropic 推出的开放协议，用于标准化 LLM 与外部工具/数据源的连接方式。

**核心概念**：
- MCP Server：提供工具和资源
- MCP Client：连接 Server 并使用工具
- 标准化接口：无需为每个工具写适配代码
- 资源（Resources）：文件、数据库等数据源
- 工具（Tools）：可调用的功能

**学习内容**：
- 搭建 MCP Server
- 使用现成的 MCP Server（文件系统、数据库、Slack、GitHub 等）
- 理解 MCP 与传统 Function Calling 的区别

**检验项目**：创建一个本地的 MCP Server，提供天气查询或文件读写功能，然后用 Agent 连接使用。

---

## 五、Phase 4：进阶与生产化（第 12-15 周）

### 5.1 RAG + Agent

> 时间：1 周

RAG（检索增强生成）让 Agent 能访问私有知识库。

**学习要点**：
- 文档分块（Chunking）策略
- Embedding 模型选择
- 向量数据库（ChromaDB、Pgvector、Pinecone）
- 检索策略（相似度搜索、MMR、HyDE）
- 将 RAG 作为 Agent 的工具

**典型架构**：
```
文档 → 分块 → Embedding → 向量数据库
                                    ↓
用户问题 → Agent → 检索工具 → 向量检索 → 上下文 → LLM → 回答
```

**检验项目**：给 Agent 添加一个"查询企业内部文档"的 RAG 工具。

### 5.2 可观测性与调试

> 时间：3-5 天

**关键工具**：
- LangSmith（LangChain 官方）：Trace、Debug、评估
- LangFuse：开源的 LLM 可观测性平台
- Weights & Biases Prompts：Prompt 管理与追踪
- 自建的日志系统（记录每次 LLM 调用、工具调用、Agent 决策）

**监控指标**：
- 每次 LLM 调用的延迟和 Token 消耗
- 工具调用成功率
- Agent 完成任务的轮次数量
- 最终结果质量评估

### 5.3 安全与对齐

> 时间：3-5 天

**核心安全问题**：
- **提示注入**（Prompt Injection）：用户输入尝试绕过限制
- **工具越权**：Agent 使用了不应使用的工具
- **数据泄露**：Agent 在输出中泄露了敏感信息
- **无限循环**：Agent 陷入重复调用

**防护措施**：
- 输入验证与净化
- 工具权限最小化
- 人工审核（Human-in-the-Loop）
- 最大轮次限制和超时
- 敏感内容过滤
- 独立的 Guardrails 层（如 Nvidia NeMo Guardrails）

### 5.4 部署方案

> 时间：1 周

| 部署方式 | 适用场景 | 推荐工具 |
|----------|----------|----------|
| API 服务 | 提供 Agent API | FastAPI + Uvicorn |
| 流式响应 | 实时对话 | WebSocket / SSE |
| 任务队列 | 后台长任务 | Celery / Redis Queue |
| 容器化 | 标准化部署 | Docker + Docker Compose |
| 无服务器 | 弹性扩缩 | AWS Lambda / Vercel |

**生产注意事项**：
- 请求限流（Rate Limiting）
- 并发控制
- 错误重试与退避策略
- 监控告警
- 版本管理与回滚

---

## 六、Phase 5：项目实战

从简单到复杂，逐步构建实际项目。

### 项目 1：个人助手 Agent（1 周）

**功能**：
- 联网搜索并总结
- 读取本地文件并回答
- 天气查询
- 日历管理

**技术栈**：单一 Agent + 3-5 个工具 + 短期记忆

### 项目 2：自动化研究报告 Agent（1-2 周）

**功能**：
- 接受一个主题
- 自动搜索多个来源
- 阅读并提取关键信息
- 生成结构化报告（Markdown/PDF）

**技术栈**：Plan-and-Execute Agent + 搜索/网页读取工具 + 文件输出

### 项目 3：客服工单处理系统（2 周）

**功能**：
- 接收用户问题
- 检索知识库（RAG）
- 自动回复常见问题
- 复杂问题转人工

**技术栈**：ReAct Agent + RAG + Human-in-the-Loop

### 项目 4：多 Agent 编程助手（2-3 周）

**功能**：
- 架构 Agent：分析需求、设计方案
- 编码 Agent：编写代码
- 测试 Agent：编写和运行测试
- 审核 Agent：Code Review

**技术栈**：LangGraph Multi-Agent + 文件系统/Shell 工具

---

## 七、推荐学习资源

### 课程与教程

| 资源 | 链接 | 说明 |
|------|------|------|
| DeepLearning.AI - Building Systems with AI Agents | 官网 | 入门首选，免费 |
| DeepLearning.AI - LangChain for LLM Apps | 官网 | LangChain 入门 |
| DeepLearning.AI - Multi AI Agent Systems (CrewAI) | 官网 | 多 Agent 实践 |
| Anthropic - Build with Claude (官方教程) | docs.anthropic.com | Claude Agent 开发 |
| OpenAI - Function Calling 官方文档 | platform.openai.com | 基础概念 |
| LangChain 官方教程 | python.langchain.com | 文档完善 |

### 必读论文

| 论文 | 核心贡献 |
|------|----------|
| **ReAct: Synergizing Reasoning and Acting in LLMs** | Agent 的基础范式 |
| **Chain-of-Thought Prompting Elicits Reasoning in LLMs** | 推理增强 |
| **Tree of Thoughts: Deliberate Problem Solving** | 高级推理 |
| **Toolformer: Language Models Can Teach Themselves to Use Tools** | 工具学习的理论 |
| **Reflexion: Language Agents with Verbal Reinforcement Learning** | 自我反思 |

### 开源项目参考

| 项目 | GitHub | 学习价值 |
|------|--------|----------|
| LangChain | langchain-ai/langchain | 生态最全 |
| AutoGen | microsoft/autogen | 多 Agent 对话 |
| CrewAI | crewAIInc/crewAI | 简洁的多 Agent |
| smolagents | huggingface/smolagents | 轻量级教学 |
| open-interpreter | open-interpreter/open-interpreter | 生产级 Agent |

---

## 八、快速起步路线（1 个月速成版）

如果您时间有限，想尽快上手做出可用项目：

```
第 1 周：Python 异步 + LLM API 调用 + 提示词工程
第 2 周：Function Calling + ReAct 循环 + 简单工具
第 3 周：LangChain/LangGraph 上手 + 记忆系统
第 4 周：构建一个完整的单 Agent 项目（搜索 + 阅读 + 总结）
```

之后边做项目边补充进阶知识。

---

## 九、常见误区与建议

- **不要过早陷入框架细节**：先理解 Agent 的核心循环（思考→行动→观察），再学框架
- **重视提示词工程**：即使使用框架，好的提示词仍是 Agent 表现的关键
- **先做单 Agent，再做多 Agent**：多 Agent 的复杂度翻倍，先打好基础
- **关注 Token 成本**：Agent 循环会消耗大量 Token，设计时要注意效率
- **注重可观测性**：Agent 的调试远比传统程序困难，日志和追踪是必须的
- **从小处着手**：用最简单的 Python 脚本实现 ReAct 循环，比直接上框架更能加深理解

---

> **记住**：AI Agent 领域发展极快，框架和最佳实践在持续更新。保持学习、关注官方文档和社区动态，比死记硬背某个框架更重要。
