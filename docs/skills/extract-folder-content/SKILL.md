---
name: extract-folder-content
description: 自动提取指定文件夹内的完整目录树结构及各类纯文本、代码、配置文件的内容，并整合成结构化的 Markdown 报告。
---

# Extract Folder Content Skill

本 Skill 用于对任意指定的本地文件夹进行全量或定向内容提取，输出完整的**目录树**和**文件内容汇总报告**（Markdown 格式），适用于代码走查、项目内容打包汇报、喂给大模型分析等场景。

## 核心功能

1. **目录结构可视化**：以 ASCII 树形结构展示文件夹层级。
2. **多编码兼容读取**：自动尝试 UTF-8、UTF-8 BOM、GBK、GB18030、CP936 等编码，避免中文乱码。
3. **安全过滤与保护**：
   - 自动跳过 `.git`、`node_modules`、`__pycache__` 等开发缓存与庞大依赖目录。
   - 自动识别并跳过图片、音视频、压缩包、可执行文件等二进制格式（仅保留文件路径占位说明）。
   - 单文件体积保护（默认上限 512KB，可自定义），防止提取巨型文件撑爆上下文或内存。
4. **灵活筛选**：支持指定提取特定后缀（如 `--ext .py .js .md`）。

---

## 快速使用

### 1. 使用 Python 执行（跨平台，推荐）

```bash
# 基本用法：提取目标文件夹并输出为 Markdown
python extract_folder.py ./my_folder -o output.md

# 仅提取 Python 和 Markdown 文件
python extract_folder.py C:/path/to/project -o project_summary.md --ext .py .md

# 调整单文件大小上限为 1024 KB (1MB)
python extract_folder.py ./my_folder -o summary.md --max-size 1024

# 忽略特定文件夹
python extract_folder.py ./project -o summary.md --ignore-dirs temp logs
```

### 2. 使用 PowerShell 原生脚本执行（Windows 环境免安装依赖）

如果当前系统或终端处于 Windows PowerShell 环境，可直接调用：

```powershell
# 基本用法
.\Extract-Folder.ps1 -Folder "./my_folder" -Output "output.md"

# 仅提取特定类型文件
.\Extract-Folder.ps1 -Folder "D:\Projects\MyApp" -Output "report.md" -Ext ".js", ".json"
```

### 3. 在 Python 代码中作为模块直接调用

```python
from extract_folder import extract_folder

# 直接获取提取后的 Markdown 字符串
markdown_report = extract_folder(
    folder_path="./src",
    output_path="report.md",       # 可选，若为 None 则只返回字符串
    max_file_size_kb=512,         # 可选
    include_tree=True,            # 是否包含目录树
    extensions={".py", ".json"}   # 可选，过滤指定后缀
)
```

---

## 参数说明

| 参数 | 类型 / 选项 | 默认值 | 作用说明 |
| :--- | :--- | :--- | :--- |
| `folder` | 必填位置参数 | - | 目标文件夹路径（支持相对路径与绝对路径） |
| `-o`, `--output` | 可选字符串 | None | 输出的 Markdown 报告路径；未指定时输出到控制台 |
| `--max-size` | 可选整数 | 512 | 单个文本文件最大读取上限（单位：KB） |
| `--no-tree` | 可选标志 | False | 报告中是否关闭目录结构树生成 |
| `--ext` | 列表（多个值） | None | 仅提取指定后缀，例如 `--ext .ts .vue .json` |
| `--ignore-dirs` | 列表（多个值） | None | 额外指定需要忽略的文件夹名 |

---

## 默认规则

- **忽略的目录**：`.git`, `.svn`, `.hg`, `__pycache__`, `node_modules`, `.venv`, `venv`, `.idea`, `.vscode`, `dist`, `build`, `.next`, `.nuxt`, `bin`, `obj`, `.dsh-acl-report`, `_acl-recovery` 等。
- **二进制识别**：`.exe`, `.dll`, `.zip`, `.png`, `.jpg`, `.mp4`, `.pdf`, `.docx` 等常见二进制类型不读取正文，仅在报告中标注占位。
