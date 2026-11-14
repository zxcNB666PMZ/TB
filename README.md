# 💼 财务 AI 智能分析与台账助手 (Financial AI Assistant)

> 一个基于大语言模型 (LLM)、RAG 检索增强生成与云端数据库构建的企业级全栈财务应用。

## 📖 项目简介 (Introduction)
传统财务工作中，长篇幅财报的阅读效率极低，且海量发票的手动录入极易出错。本项目旨在打造一个**“AI 财务中台”**，通过接入智谱 GLM 大模型，实现财报文档的精准问答、发票信息的自动化提取与结构化沉淀，并利用 BI 看板提供商业数据洞察。

🔗 **在线体验 (Live Demo):** [https://mengzhan.streamlit.app](https://mengzhan.streamlit.app)

---

## ✨ 核心功能 (Key Features)

### 1. 💬 财报文档智能问答 (基于 RAG)
- 上传动辄上百页的财务 PDF，系统通过 `pdfplumber` 精准提取文本。
- 利用 LangChain 进行文本切片，结合 HuggingFace 中文向量模型 (`bge-small-zh`) 构建本地知识库 (ChromaDB)。
- 严格限制 AI 基于检索到的上下文回答，有效解决大模型在财务领域的“幻觉”问题。

### 2. 🧾 批量发票识别与台账 (基于 AI 抽取)
- 支持一键批量上传电子发票 PDF。
- 借助 Prompt Engineering，强制大模型以严格的 JSON 格式输出发票号码、日期、金额等关键字段。
- 彻底解放财务人员的双手，替代传统低效的手动录入。

### 3. 🗄️ 历史数据查询与商业 BI 看板
- 数据无缝接入 **Supabase (PostgreSQL) 云端数据库**，实现多端数据永久同步。
- 使用 `Pandas` 进行数据清洗，结合 `Plotly` 动态绘制供应商支出占比环形图与开票趋势柱状图。
- **AI 财务总监诊断报告**：将表格数据再次喂给大模型，一键生成高情商的“财务降本增效建议”。

### 4. 📈 银行/微信/支付宝流水智能分类
- 上传杂乱无章的流水 Excel。
- 利用 AI 对“交易备注”进行语义理解，自动打上（餐饮、交通、办公等）分类标签。
- 使用原生 SQL 与 `Pandas` 处理数据，直观展示个人/企业消费结构。<img width="1280" height="691" alt="bec4aa6b0fd31cd5de5da3a95288aaea" src="https://github.com/user-attachments/assets/b9cf642b-d610-468b-bd19-7d8ca86b2413" />


---

## 🏗️ 系统架构图 (Architecture)

```mermaid
graph TD
    A[用户 (Web/Mobile)] -->|上传财报/发票| B(Streamlit 前端)
    B -->|提取文本| C{PDF解析引擎 pdfplumber}
    C -->|纯文本| D(RAG / Prompt 工程)
    D -->|API 调用| E[智谱 GLM-4-Flash 大模型]
    E -->|结构化数据提取| F[Pandas 数据清洗]
    F -->|持久化存储| G[(Supabase PostgreSQL 云数据库)]
    F -->|数据聚合| H[Plotly 交互式 BI 图表]
    G -->|SQL 查询| H
    H -->|展示| B
🤖 核心亮点：AI Agent 架构
项目不仅实现了基础的 RAG 问答，更基于 ReAct (Reasoning and Acting) 模式 实现了 AI Agent。大模型能够自主拆解任务，根据用户提问动态调用 query_invoice_db（云端数据库查询）和 calculator（计算器）工具，实现了从“静态问答”到“动态智能体”的跨越。
“高阶架构：数据层实现了 MCP (Model Context Protocol) 服务化。将数据库查询能力封装为独立的 MCP Server。Agent 通过 SSE 协议与工具服务进行远程通信，实现了真正的工具即服务 (Tool-as-a-Service)。
