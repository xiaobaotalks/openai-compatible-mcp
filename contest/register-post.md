# 【学习工作赛道】一行 pip install — 把任意 LLM 接到 Claude / Cursor / Codex / Claude Code

**【标签】** `学习工作`

---

## 1. 创意名称 + 创意介绍

**创意名称**:openai-compatible-mcp

**想解决什么问题**:Anthropic 把 MCP 协议开源后,所有 IDE 都在抢着接,但开发者想用 DeepSeek / 千问 / mimo 等国产 LLM 跑 Claude Desktop / Cursor / Claude Code / Codex CLI 时,会撞上 **4 道关卡** —— 4 份字段名各异的配置文件、Codex 的 Responses 协议与 DeepSeek 不兼容、Claude Code 强制登录 Anthropic 账号、MCP 模板项目要装一堆三方依赖。

**为什么会想到做这个**:我自己就天天在 Claude / Cursor / Codex 之间切换,每次换 DeepSeek 都要重新写 JSON、查协议、解决登录弹窗,折腾一晚上。**于是做了一个把这 4 道关卡全部打掉的工具**:一行 `pip install` + 浏览器向导点 4 下,4 个 IDE 立即能用任意 OpenAI 兼容 API。

**大概是什么产品**:**Python 命令行包(已发 PyPI v0.2.11)** + 内嵌 Web 向导(`127.0.0.1:8989`)+ Codex 协议翻译代理(`127.0.0.1:7878`)+ GitHub Pages 落地页 = 一套让开发者 5 分钟内把任意 LLM 接入 4 个主流 AI 编码 IDE 的完整工具链。

---

## 2. 目标用户及痛点

**面向哪些用户**:在国内使用 DeepSeek / 千问 / mimo 等国产 LLM 编码的开发者(单人 / 团队都适用),特别是同时在 **Claude Desktop、Cursor、Claude Code、Codex CLI** 之间切换的全栈 / 后端 / 工具链工程师。

**在什么场景下使用**:
- ① 主力 IDE 是 Cursor / Claude Desktop,想用 DeepSeek 节省成本时
- ② 用 Codex CLI,但 Codex 的 `/v1/responses` 协议不兼容国产 LLM 时
- ③ 用 Claude Code,但没有 / 不愿注册 Anthropic 账号时
- ④ 自己搭 Ollama / vLLM / llama.cpp 本地服务,想接进 IDE 时
- ⑤ 给团队成员配环境,不想每个人手写 4 份 JSON 时

**当前痛点**:
- ① 4 份配置文件 4 个字段名,改完 Claude 改 Cursor,改完 Cursor 改 Codex,改完 Codex 改 Claude Code,半小时没了
- ② Codex CLI 走 `/v1/responses` 协议,DeepSeek 只支持 `/v1/chat/completions`,要么自己写翻译层,要么 Codex 就用不了国产 LLM
- ③ Claude Code 改了 `ANTHROPIC_BASE_URL` 后仍要求登录 Anthropic,没账号的人直接卡在登录页走不下去
- ④ 现有 MCP server 模板都基于官方 SDK,装一堆包 + 配 venv + 解 SSL 冲突,光是装环境就劝退一半人

---

## 3. 价值与意义

**效率提升**:装包 30 秒 + 写 Key 5 秒 + 浏览器点 4 下 1 分钟,**总耗时 5 分钟内跑通 4 个 IDE 接任意 LLM**,比"自己手搓 MCP server + 写协议翻译层"快 2–3 个晚上。**已有真实可用的 v0.2.11 PyPI 包 + 18 个 commit 历史 + 4 个真实接入 demo**,不是 PPT 上的"未来规划"。

**社会价值**:把"配置分散、协议不兼容、模型不对齐"这些 IDE 厂商之间留出的空缺补上,**降低国产 LLM 在开发场景的接入门槛**,让不会写协议翻译的开发者也能享受模型选择自由,直接为"国产 LLM 落地 IDE"做基础工具贡献。

---

## 4. 附件

**TRAE Work 生成的创意产物 HTML(已上传社区)**:

📄  **创意提案单页**:[xiaobaotalks.github.io/openai-compatible-mcp/contest/proposal.html](https://xiaobaotalks.github.io/openai-compatible-mcp/contest/proposal.html)

> 暗色设计,9 大板块,可独立打开:核心指标 / 4 大痛点 / 4 步流程 / 6 个差异化亮点 / 4 个可点击 Demo / 技术栈 / 真实迭代路线图 / CTA。

📦  **PyPI 包(已发版)**:[pypi.org/project/openai-compatible-mcp](https://pypi.org/project/openai-compatible-mcp/) — `pip install openai-compatible-mcp` 即可

💻  **GitHub 源码**:[github.com/xiaobaotalks/openai-compatible-mcp](https://github.com/xiaobaotalks/openai-compatible-mcp) — 18 个 commit,4 个真实接入 demo

🌐  **落地页**:[xiaobaotalks.github.io/openai-compatible-mcp](https://xiaobaotalks.github.io/openai-compatible-mcp/)

---

**参赛者**:xiaobaotalks(单人参赛)
**赛道**:学习工作
**版本**:v0.2.11
