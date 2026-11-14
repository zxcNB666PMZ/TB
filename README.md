# 💼 财务 AI 智能分析与台账助手 (Full-Stack AI Agent)

> 一个基于大语言模型 (LLM)、RAG 检索增强生成、ReAct Agent 架构与 MCP 微服务协议构建的企业级全栈财务应用。

## 📖 项目简介 (Introduction)
传统财务工作中，长篇幅财报的阅读效率极低，且海量发票的手动录入极易出错。本项目旨在打造一个**“全自动 AI 财务中台”**，通过接入智谱 GLM 大模型，实现财报文档的精准问答、发票信息的自动化提取、结构化沉淀，以及**具备自主规划能力的 Agent 智能体**。

🔗 **在线体验 (Live Demo):** [https://mengzhan.streamlit.app](https://mengzhan.streamlit.app)
*(测试账号：`admin` / 密码：`123456` 或 `finance` / `888888`)*

---

## ✨ 核心功能与高阶架构 (Key Features & Architecture)

### 1. 🤖 基于 ReAct 架构的 AI Agent 智能体
- **自主任务拆解**：大模型不仅会聊天，还能根据用户提问（如“帮我查滴滴发票并算算还能报多少”），自主拆解为“查库”与“计算”两步。
- **Function Calling (工具调用)**：手搓 ReAct 循环。AI 能动态调用 `query_invoice_db`（云库查询）和 `calculator`（计算器）工具，并整合结果输出。
- **多轮对话记忆**：基于 Streamlit Session State 维护上下文。

### 2. 🔌 MCP (Model Context Protocol) 微服务解耦
- **Tool-as-a-Service**：将数据库查询能力封装为独立的 `mcp_server.py` 服务。
- **SSE 网络通信**：前端 Agent 通过 Server-Sent Events 协议与 MCP 工具服务进行异步通信，实现了工具与业务逻辑的彻底解耦。
- **多环境自适应降级**：通过环境变量控制，本地开发环境走 MCP 网络调用（展示微服务架构）；云端 Serverless 环境自动降级为直连数据库，保证云端 100% 稳定。

### 3. 🔒 企业级多用户鉴权与数据隔离
- **云端鉴权**：抛弃本地环境变量，全面接入 **Supabase PostgreSQL** 进行动态多用户账号密码校验。
- **角色管理**：支持不同角色（超级管理员、财务总监）登录，并在侧边栏动态展示当前身份。
- **安全防护**：前端拦截器强制拦截未登录请求，防止大模型 API 被恶意消耗。

### 4. 💬 RAG 财报文档智能问答
- 上传动辄上百页的财务 PDF，系统通过 `pdfplumber` 精准提取文本。
- 利用 LangChain 切片，结合 HuggingFace 中文向量模型 (`bge-small-zh`) 构建本地知识库 (ChromaDB)。
- 严格限制 AI 基于检索到的上下文回答，有效解决财务领域的“幻觉”问题。

### 5. 🧾 批量发票识别与台账
- 借助 Prompt Engineering，强制大模型以严格的 JSON 格式输出发票字段。
- 彻底解放财务人员的双手，替代传统低效的手动录入。

### 6. 📊 商业 BI 看板与智能诊断
- 数据无缝接入 Supabase 云数据库，使用 `Pandas` 清洗，`Plotly` 动态绘制供应商支出环形图与开票趋势柱状图。
- **AI 财务总监诊断报告**：将汇总数据喂给大模型，一键生成“降本增效”的高管级建议。

### 7. 📈 流水智能分类
- 上传流水 Excel，利用 AI 对“交易备注”进行语义理解，自动打上分类标签，生成消费结构饼图。

---

## 🏗️ 系统架构图 (Architecture)

```mermaid
graph TD
    A["用户 (Web/Mobile)"] -->|"登录/上传/提问"| B["Streamlit 前端 & 鉴权拦截器"]
    B -->|"发送对话"| C["智谱 GLM-4 (Agent大脑)"]
    C -->|"决定调用工具"| D["ReAct 循环控制器"]
    
    D -->|"本地环境 (SSE 协议)"| E["MCP Server 微服务 (Port 8000)"]
    D -->|"云端环境 (降级直连)"| F[("Supabase PostgreSQL 云数据库")]
    E -->|"SQL 查询"| F
    
    F -->|"返回结构化数据"| D
    D -->|"工具结果注入"| C
    C -->|"最终回答"| B
    
    B -->|"PDF解析"| G["pdfplumber + ChromaDB (RAG)"]
    B -->|"数据可视化"| H["Pandas + Plotly BI 看板"]
