# Lean 4 AI Prover Assistant

[![Lean 4](https://img.shields.io/badge/Lean-4-orange)](https://leanprover.github.io/)
[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

一个将大型语言模型（LLM）集成到 Lean 4 环境中的AI辅助证明工具。它通过提供智能策略建议、自动修复错误和生成证明框架，旨在显著提升定理证明的效率和流畅度。

## ✨ 功能特性

- **智能策略建议 (`llm_next`)**: 根据当前的证明目标，动态建议最高效的下一步策略。
- **证明框架生成 (`llm_framework`)**: 为复杂的证明目标一键生成高级的证明框架（如 `induction`, `cases`），并用 `sorry` 填充待证明的子目标。
- **关键引理补全 (`llm_type`)**: 为复杂的证明目标生成一个引理，并用 `sorry` 填充证明项。
- **已有代码修复 (`llm_revise`)**: 修复可能错误的证明，沿用原有的 `sorry`。
- **自动错误诊断与修复**: 当一个策略执行失败时，系统会自动分析错误信息，向LLM请求诊断，并尝试生成修复后的代码。
- **上下文感知**: 所有请求都会包含完整的定理声明、当前的证明状态和用户提示，确保LLM能给出最相关的建议。
- **本地库搜索**: 在诊断阶段，能够根据错误智能生成关键词，搜索本地 Lean 环境中可能相关的定理。
- **高度可定制**: 系统的所有行为都由易于编辑的文本 Prompt 文件驱动，方便用户根据自己的需求调整AI的风格和逻辑。

## 🏛️ 系统架构

本项目采用一个解耦的架构，Lean 4 作为前端，通过标准的输入/输出（Stdio）与一个独立的 Python 服务进行通信。

**工作流程如下:**

1.  **Lean 端 (Tactic)**:
    - 用户在 Lean 文件中调用 `llm_next` 或 `llm_framework` 等策略。
    - `Tactic.lean` 中的Elab Tactic被触发，收集当前的证明上下文（目标状态、定理声明、用户提示等）。
    - 它将这些信息序列化为一个 JSON 对象。

2.  **启动 Python 服务**:
    - Lean 进程启动 `llm_service.py` 脚本作为一个子进程。
    - JSON 请求通过 `stdin` 发送给 Python 脚本。

3.  **Python 端 (LLM Service)**:
    - `llm_service.py` 接收并解析 JSON 请求。
    - `PromptManager` 根据请求类型（例如 `init_next`, `diagnose`）加载并渲染对应的 Prompt 模板。
    - `CustomOpenAIProvider` 将渲染好的 Prompt 发送给配置好的 LLM API（如 OpenAI）。
    - 脚本接收 LLM 的原始响应，并根据请求类型解析出关键信息（例如，要执行的策略代码、要搜索的关键词等）。
    - 最终处理结果被格式化为 JSON 并通过 `stdout` 返回。

4.  **返回 Lean 端**:
    - Lean 进程捕获 Python 脚本的输出，并将其解码为 `LlmResponse` 结构。
    - 根据响应：
        - 如果是策略代码，使用 `TryThis` 小部件在 VS Code 中显示为可接受的建议。
        - 如果是诊断请求，则触发新一轮的搜索和修复流程。
        - 如果发生错误，会在 InfoView 中显示错误信息。

## 📦 安装与配置

请遵循以下步骤来安装和配置项目。

### 1. 先决条件

- **Lean 4**: 确保你已经通过 `elan` 安装了 Lean 4 工具链。
- **Python**: 版本 >= 3.9。

### 2. 下载项目

将此项目克隆到你的本地机器。

### 3. 配置 Python 环境

建议使用虚拟环境。

```sh
# 创建一个虚拟环境
python3 -m venv .venv

# 激活虚拟环境
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
# .venv\Scripts\activate

# 安装依赖
pip install openai requests beautifulsoup4 lxml
```

### 4. 设置环境变量

AI 服务需要 API 密钥和其他配置才能运行。你需要创建以下环境变量, 请参考不同系统上设置环境变量的方法。

```sh

# 你的 LLM API 密钥 (必需)
LLM_API_KEY="sk-..."

# 你的 LLM 服务地址 (可选, 默认为 OpenAI)
LLM_BASE_URL="https://api.example.com/v1"

# 你的 LLM 模型名称 (可选, 默认为 gpt-4o)
LLM_MODEL="gpt-4o-mini"

# 指向你虚拟环境中 python 解释器的路径 (重要)
# On macOS/Linux, run `which python` after activating venv
LEAN_LLM_PYTHON="/path/to/your/project/.venv/bin/python"
# On Windows, it might be C:\path\to\your\project\.venv\Scripts\python.exe

# 你希望使用的定理搜索服务提供者 (可选, 默认为 local: 执行本地搜索; leansearch.net 暂不可用)
LEAN_LLM_SEARCH_PROVIDER=""
```
**重要**: 确保 `LEAN_LLM_PYTHON` 指向的是你刚刚创建的虚拟环境中的 Python 解释器，否则 Lean 将无法找到已安装的 `openai` 库。

### 5. 集成到你的 Lean 项目

要在一个已有的 Lean 4 项目中使用此工具，你需要将其添加为 `lakefile.lean` 中的一个本地依赖。

假设你的项目结构如下：
```
MyLeanProject/
├── lakefile.lean
├── MyLeanProject.lean
└── lean-toolchain
LLMTools/  <-- 这个AI工具的文件夹
├── Core.lean
├── Search.lean
├── Tactic.lean
├── llm_service.py
└── ...
```

在 `MyLeanProject/lakefile.lean` 中添加：
```lean
import Lake
open Lake DSL

package «my-lean-project» where
  -- ... other settings

require «llm-tools» from "../LLMTools" -- [!code focus]

@[default_target]
lean_lib «MyLeanProject» where
  -- ...
```
现在，在你的 Lean 文件中，你可以导入并使用这些AI策略了。

## 🚀 使用方法

在你想要使用 AI 辅助的 Lean 文件顶部导入模块：
```lean
import LLMTools.Tactic
```

### 示例: `llm_next`

```lean
import LLMTools.Tactic
import Mathlib.Tactic

theorem add_comm (a b : Nat) : a + b = b + a := by
  -- 将光标放在这里然后输入 llm_next
  llm_next
  -- AI 可能会建议:
  -- Try this: induction a
```

**带参数使用:**
- **`fuel` (重试次数)**: `llm_next 5` (设置最大重试次数为5次，默认为6)
- **`hint` (用户提示)**: `llm_next "try using induction on b"`

## 🔧 自定义 Prompts

本工具的核心驱动力在于 `prompts/` 目录下的文本文件。你可以通过修改这些文件来定制AI的行为。

- `system.txt`: 定义AI作为 Lean 专家的核心角色和基本指令。
- `init_next.txt`: 用于生成下一步策略的初始请求。
- `init_framework.txt`: 用于生成证明框架的初始请求。
- `diagnose.txt`: 当策略失败时，用于分析错误原因的请求。
- `fix_next.txt`: 基于诊断和搜索结果，生成修复后代码的请求。
- ... 等等。

修改这些文件后，无需重启 Lean 即可立即生效。

## 🤝 贡献

欢迎提交 PRs 和 Issues！如果你有任何改进建议或发现了 Bug，请随时提出。

## 📄 许可证

本项目采用 [MIT License](LICENSE)。
