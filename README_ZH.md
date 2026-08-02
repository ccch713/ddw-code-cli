# minimax-agent

一个基于 **MiniMax Token Plan** 的 Claude Code 风格 Python CLI 编程助手。

`minimax-agent` 是一个自包含、类单文件的 CLI，把可插拔的模型 Provider
和工具调用 Agent 循环整合在一起。整体代码量约 1k 行，可读、可改、可嵌入
其他产品。

## 特性

- **Agent 循环**：`max_turns=15` 上限、60% 上下文触发 micro-compact、完整流式输出。
- **OpenAI 兼容 Provider**：适配 MiniMax Token Plan（`sk-cp-` 前缀），支持 SSE
  流式、函数调用、429/503 指数退避重试。
- **八个内置工具**：`file_read` / `file_write` / `file_edit` / `bash` / `grep`
  （ripgrep + 纯 Python 兜底）/ `glob` / `web_search`（DuckDuckGo HTML）/ `todo`。
- **四级权限模型**：`allow` / `ask` / `deny` / `force_ask`，危险命令检测
  （`rm -rf /`、`sudo`、`git push --force` ...）和禁止路径守卫
  （`~/.ssh`、`~/.gnupg`、`/etc/shadow` ...）。
- **沙箱模式**：对所有写操作强制确认，适合共享主机使用。
- **项目上下文检测**：自动加载 `AGENTS.md` / `CLAUDE.md` / `README.md`，
  识别项目语言（Python / Node / Go / Rust / Java / Ruby）。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

设置 Token Plan API Key：

```bash
export MINIMAX_API_KEY="sk-cp-..."
```

## 使用

```bash
# 单次模式：执行一次、打印、退出
minimax-agent --print "写一个 hello world Python 脚本"

# 交互模式
minimax-agent

# 管道友好
echo "读 README.md" | minimax-agent --print

# 自动批准所有写操作（CI / 沙箱环境）
minimax-agent --print --auto-approve "重构 foo.py"

# 更严格的权限
minimax-agent --sandbox
```

## 命令行参数

| 参数 | 说明 |
| --- | --- |
| `--print` | 非交互模式：执行一次、打印、退出 |
| `--api-key` | MiniMax API Key（或设置 `MINIMAX_API_KEY`） |
| `--base-url` | 覆盖 API 基础 URL |
| `--model` | 覆盖模型名（默认 `MiniMax-Text-01`） |
| `--max-turns` | 单轮最大工具调用迭代次数（默认 15） |
| `--workspace` | 工作目录（默认当前目录） |
| `--sandbox` | 对写操作强制确认 |
| `--auto-approve` | 跳过所有权限确认 |
| `--verbose`, `-v` | 详细日志输出到 stderr |

## 配置

`minimax-agent` 读取以下环境变量（CLI 参数优先级更高）：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `MINIMAX_API_KEY` | — | **必填。** Token Plan Key（`sk-cp-...`） |
| `MINIMAX_TOKEN` | — | `MINIMAX_API_KEY` 的别名 |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.com/v1` | API 端点 |
| `MINIMAX_MODEL` | `MiniMax-Text-01` | 模型名 |
| `MINIMAX_MAX_TURNS` | `15` | 单轮最大工具迭代次数 |

## 架构

```
minimax_agent/
├── cli.py                 # argparse + 交互式 REPL
├── turn_loop.py           # Agent 循环（async generator）
├── config.py              # env/CLI 配置加载
├── providers/
│   ├── base.py            # ModelProvider ABC
│   └── minimax.py         # MiniMax API 适配器（SSE + 重试）
├── tools/
│   ├── registry.py        # Tool 数据类 + 注册表
│   ├── dispatcher.py      # 权限校验 + schema 校验
│   ├── builder.py         # 一键构造默认注册表
│   ├── file_read.py / file_write.py / file_edit.py
│   ├── bash.py / grep.py / glob.py
│   ├── web_search.py / todo.py
├── compact/
│   ├── micro_compact.py   # 60% 阈值、零 LLM、纯字符串替换
│   └── auto_compact.py    # LLM 摘要兜底（骨架）
├── security/
│   ├── permissions.py     # 四级权限模型
│   └── danger_check.py    # 危险命令 + 禁止路径
└── context/
    └── detector.py        # 语言识别 + AGENTS.md / README.md 加载
```

## 测试

```bash
pip install -e ".[dev]"
pytest
pytest --cov=minimax_agent
```

当前测试套件 **98 个用例**，**86% 行覆盖率**（目标是 30 个用例 / 80% 覆盖率）。

## 端到端冒烟测试

```bash
# 帮助命令
minimax-agent --help

# 缺少 key 时优雅失败，退出码 2
unset MINIMAX_API_KEY
minimax-agent --print "hi" ; echo "exit=$?"

# 有真实 key 时，--print 流式返回
export MINIMAX_API_KEY="sk-cp-..."
minimax-agent --print "写一个 hello world Python 脚本"
minimax-agent --print "读 README.md"
minimax-agent --print "列出当前目录的文件"
```

## 安全机制

默认：

- `file_read` / `grep` / `glob` / `web_search` / `todo` 允许直接执行
- `file_write` / `file_edit` / `bash` 每次会话询问一次，之后记住
- 读取 `~/.ssh` / `~/.gnupg` / `~/.aws/credentials` / `/etc/shadow` 等被直接拒绝
- Shell 命令匹配 `rm -rf /` / `sudo` / `git push --force` / `dd if=... of=/dev/sd*`
  / fork bomb 等十几个模式直接被拒绝

用 `--sandbox` 把所有写操作升级为 `force_ask`（每次都询问）。

## 许可

Apache-2.0，见 `LICENSE`。
