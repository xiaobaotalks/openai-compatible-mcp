# 【学习工作赛道】openai-compatible-mcp — 一行 pip install 接入任意 LLM 到 4 大 IDE

> 一句话定位：**MCP 协议实现只用 Python 标准库(零三方依赖),一行 `pip install` 即可把任意 OpenAI 兼容 API 接入 Claude Desktop / Cursor / Claude Code / Codex CLI**,并附带 Codex 协议翻译代理、Claude Code 跳过登录、合并式配置文件写入,把所有"MCP 模板项目的边界情况"全部在包内处理掉。

## 🏷 参赛信息

| 项 | 内容 |
|---|---|
| 作品名 | openai-compatible-mcp |
| 赛道 | **学习工作赛道** |
| 作者 | xiaobaotalks (单人参赛) |
| 版本 | v0.2.11 |
| 创意提案 | [点这里打开单页提案(暗色、可独立体验)](https://xiaobaotalks.github.io/openai-compatible-mcp/contest/proposal.html) |
| 落地页 | https://xiaobaotalks.github.io/openai-compatible-mcp/ |
| PyPI | https://pypi.org/project/openai-compatible-mcp/ |
| GitHub | https://github.com/xiaobaotalks/openai-compatible-mcp |

---

## 🎯 我解决的真实问题

我自己在 Claude / Cursor / Codex 之间反复切。每次想把 DeepSeek 接到这些 IDE,都会撞上 4 道关卡:

1. **4 份配置文件** — Claude Desktop 用 `mcpServers`、Cursor 用 `mcp_servers`、Codex 用 `config.toml`、Claude Code 用 `~/.claude.json`。字段名 / 嵌套层级 / env 写法各不相同。
2. **Codex 协议不兼容** — Codex CLI 走 `/v1/responses`(OpenAI 较新的 Responses API),DeepSeek 只支持 `/v1/chat/completions`。要么自己写翻译层,要么 Codex 就用不了 DeepSeek。
3. **Claude Code 强制登录** — 改了 `ANTHROPIC_BASE_URL` 之后,Claude Code 仍要求登录 Anthropic 账号。多数用 DeepSeek 的用户根本就没账号,卡在登录界面走不下去。
4. **MCP 模板要装一堆依赖** — 现有 MCP server 模板都基于官方 SDK,动辄十几个包,Windows 上还要配 venv、SSL、端口冲突。

我做的工具就是把这 4 道关卡**全部打掉**:装一个包、点 4 下向导,4 个 IDE 立即能用 DeepSeek。

---

## 🚀 5 分钟跑完整个流程

```powershell
# 1) 装包(零三方依赖,Windows / macOS / Linux 通用)
pip install openai-compatible-mcp

# 2) 写 Key(命令行一行,免开浏览器)
openai-compatible-mcp --api-key sk-你的DeepSeekKey

# 3) 起向导(浏览器自动开 127.0.0.1:8989)
openai-compatible-mcp

# 4) 勾选 Claude Desktop / Cursor / Claude Code / Codex CLI,点"写配置"
# 5) 重启 IDE → 立即能用
```

如果用 Codex CLI,再多 2 步:

```powershell
# 4.5) 启 Codex 翻译代理(本地 127.0.0.1:7878,Flask 协议翻译层)
openai-compatible-mcp --proxy

# 5) 直接 codex,免登免配
codex
```

---

## 🛠 技术亮点(评审关心的)

- **MCP 协议 stdio JSON-RPC 2.0 自实现** — `__main__.py` + `server.py` 共 ~300 行纯标准库代码,无 SDK、无 fastapi、无 pydantic。Windows / macOS / Linux 通吃。
- **Codex 翻译代理** — `proxy_server.py` 用 Flask + httpx 桥接 Codex 的 `/v1/responses` 与 DeepSeek 的 `/v1/chat/completions`,流式响应 / 函数调用 / 上下文压缩 全部透明翻译。
- **Claude Code 跳过登录** — 同时写 `~/.claude.json` 和 `~/.claude/settings.json`,设 `hasCompletedOnboarding=true`,注入 `ANTHROPIC_BASE_URL` 指向 DeepSeek 的 Anthropic 兼容端点。配套 `claude-launch.cmd` / `claude-launch.sh` 包装成一个命令。
- **配置合并式写入** — 写 mcpServers / mcp_servers 走"读 → 合并 → 写"流程,只新增本包条目,你原有的 MCP server 全部保留。卸载时(`pip uninstall`)也会从配置里把对应条目一并清掉,不留垃圾。
- **6+ 提供商 + 任意兼容端点** — DeepSeek / OpenAI / 千问(DashScope) / MinMax / mimo(小米) / 自定义。llama.cpp、vLLM、Ollama 走 OpenAI 兼容模式一行接上。
- **7878 端口防冲突** — Codex 代理启动前先扫描 127.0.0.1:7878 端口是否被占用,已有一个实例在跑就直接复用,不会重复拉起。
- **内嵌 Web UI** — 0.2.11 起 `127.0.0.1:7878` 不再是冷冰冰的 JSON,变成可点击的暗色控制台:改 Key / 改 Base URL / 改默认模型 / 测试连接,免重启。

---

## 📂 可点击的 Demo(评审 5 分钟内能看完)

| 链接 | 看点 |
|---|---|
| [📄 创意提案单页](https://xiaobaotalks.github.io/openai-compatible-mcp/contest/proposal.html) | 9 大板块,本帖的"宣传册"版本,暗色设计可独立打开 |
| [🌐 完整产品落地页](https://xiaobaotalks.github.io/openai-compatible-mcp/) | 同一份产品主页,所有功能介绍、客户端兼容、架构图 |
| [📦 PyPI 包](https://pypi.org/project/openai-compatible-mcp/) | 已发到 PyPI,0.2.11 版本,审核通过的发布管道 |
| [💻 GitHub 源码](https://github.com/xiaobaotalks/openai-compatible-mcp) | 完整源码 + 18 个 commit 历史 + GitHub Actions 自动 Pages 部署 |

---

## 📊 真实迭代轨迹(不是写在 PPT 上的"未来规划")

| 版本 | 状态 | 干了什么 |
|---|---|---|
| v0.1.x | ✅ 已发 | MCP 桥接核心 + 基础向导 |
| v0.2.0 ~ v0.2.7 | ✅ 已发 | Claude Code 跳过登录 + 3 种启动方式 + claude-launch 包装 |
| v0.2.8 ~ v0.2.10 | ✅ 已发 | Codex 翻译代理 + 命令行 `--api-key` 写 Key + 7878 端口防冲突 |
| v0.2.11 | ✅ 已发 | 内嵌 Web UI,改 Key / 模型 / 上游免重启 |
| v0.2.12+ | 🚧 路线图 | 多代理实例共享 Key、Windows 服务化、Linux systemd unit,让云电脑场景零配置 |

---

## 🤔 这个项目跟"又一个 MCP 模板"区别在哪

| ✓ openai-compatible-mcp | × 自己手搓 MCP server |
|---|---|
| 图形化向导,鼠标点完事 | 读 MCP 协议规范,手写 JSON-RPC 帧解析 |
| 6+ 提供商 + 自定义,默认 DeepSeek | 每个客户端改不同位置的 JSON |
| stdio JSON-RPC 2.0 自实现,零三方依赖 | 重命名模型字段、写流式 SSE 解析 |
| Codex / Claude Code 适配已写好,免登录 | Codex 的 Responses API 不兼容要写翻译层 |
| 配置合并写入,不动你其他 MCP server | Claude Code env 注入要双写两个文件 |
| 代理 / launcher / 向导都打进包 | 手动测试每个客户端的认证流程 |

---

## ❓ 为什么我投「学习工作赛道」

这个工具的目标用户是**在多个 AI 编码 IDE 之间切换的开发者**——核心场景是**"把工作流串起来"**而不是"做一个消费品"。它解决的问题(配置分散、协议不兼容、模型不对齐)都是开发者每天在 IDE 里碰到的真实摩擦。提效感非常强,装上 5 分钟内就能用上 DeepSeek 跑 Claude/Cursor/Codex,而不需要折腾一晚上。

---

**参赛作品完成。点击上面的"创意提案"链接可以打开本作品的独立宣传页,落地页和 PyPI 都是活的。**
