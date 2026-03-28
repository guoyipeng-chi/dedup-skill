---
name: dedup-skill
description: "在当前代码仓识别并处理重复代码组：展示重复组、让用户选择组、按工具定位代码并执行合并重构。USE FOR: duplicate code, dedup, code clone, CPD duplication.xml, 重复代码, 合并重复逻辑, 提取公共函数, line-ops."
---

# Dedup Skill（重复代码组交互式合并）

该 skill 用于在当前仓库中完成一条闭环：
1) 发现并展示重复代码组；
2) 询问用户选择要处理的组；
3) 基于工具定位到具体文件与行范围；
4) 执行最小且可验证的合并重构。

并且 **必须优先调用 `scripts` 目录中的脚本** 完成扫描与分组数据准备。

## 适用场景

当用户意图包含以下内容时启用：
- “重复代码”“代码克隆”“duplication.xml”“CPD 报告”
- “列出重复组并让我选”“按组选组重构”
- “把重复段抽公共实现/公共函数/公共模块”

不适用：
- 仅做代码格式化
- 无重复证据且用户不希望扫描

## 参考设计（来自 CPD + LLM 流程）

此 skill 吸收以下设计思想：
- 以“重复组”为中心（group id、tokens、lines、occurrences）
- 先让用户选组，再做修改（默认一次处理 1 组）
- 按坐标定位（文件 + 行号范围），减少误改
- 优先抽公共实现，差异点参数化，避免复制出新重复
- 结构化计划优先（可类比 line-ops：`cut_paste`/`delete`/`insert`）

## 脚本入口（必须使用）

本 skill 的扫描与分组阶段，优先使用以下脚本：
- `scripts/scan_duplication.py`：调用 PMD CPD 扫描，生成 `duplication.xml`
- `scripts/list_dup_groups.py`：解析 XML 并输出重复组列表（含 score 排序）
- `scripts/build_group_payload.py`：按用户选中的组导出包含行号与上下文的 payload

### PMD 自动安装

脚本默认开启 **PMD 自动安装**（首次运行时自动下载到 `.tools` 目录）：
- 若 PMD 未找到，脚本会从 GitHub 官方发行版自动下载并安装
- 后续运行不再下载，直接复用已安装版本
- 用户无需预先配置 PMD，开箱即用

处理选项：
- `--no-auto-install-pmd`：禁用自动安装，找不到 PMD 时报错
- `--pmd <path>`：手动指定 PMD 路径
- `SET PMD_BIN=<path>`：设置环境变量

**例子**

```bash
# 正常：首次自动安装，后续复用
python scripts/scan_duplication.py <repo> --out-dir artifacts --min-tokens 40

# 指定 PMD 路径
python scripts/scan_duplication.py <repo> --pmd C:/path/to/pmd.bat

# 关闭自动安装
python scripts/scan_duplication.py <repo> --no-auto-install-pmd
```

标准命令（Windows PowerShell）：
- `python scripts/scan_duplication.py <repo_path> --out-dir artifacts --min-tokens 40`
- `python scripts/list_dup_groups.py artifacts/duplication.xml`
- `python scripts/build_group_payload.py artifacts/duplication.xml --repo <repo_path> --groups 1 --out artifacts/selected_groups_payload.json`

约束：
- 运行脚本统一用 `run_in_terminal`
- 非必要不跳过脚本阶段手写解析

## 强制执行流程

> 必须按顺序执行；禁止跳过“用户选组”直接改代码。

### Step 1 - 发现重复组数据源

优先顺序：
1. 若用户已提供 XML 报告路径：直接进入 Step 2
2. 否则执行 `scripts/scan_duplication.py` 生成报告
3. 若扫描失败，再向用户确认 PMD 路径或报告路径

工具约束：
- 代码库探索必须先用 `search_subagent`
- 结构/路径补充可用 `file_search`、`list_dir`
- 触发扫描必须调用 `run_in_terminal` 执行脚本

### Step 2 - 解析并汇总重复组

必须通过 `scripts/list_dup_groups.py` 获取分组汇总，再展示给用户。

为每个组提取并展示：
- 组 ID
- 重复行数（lines）
- token 数（tokens）
- occurrence 数量
- 涉及文件列表（简要）

输出给用户时默认按“影响度”排序：
- 推荐分数 = occurrence_count × lines

### Step 2.5 - 显示模式选择

在展示重复组前，询问用户显示与处理的方式。必须调用 `ask_questions` 收集：
- 显示模式（单选）：
  - `exact-only`：仅显示完全雷同的重复组（代码片段逐字节相同）
  - `all`：显示所有扫描出的重复组（默认）
  - `table-only`：仅打印重复组表格，然后终止 skill 执行（不进行后续合并）

根据用户选择，调用 `scripts/list_dup_groups.py`：
- 若选 `exact-only`：加 `--exact-only` 参数
- 若选 `table-only`：加 `--table-only` 参数（脚本会自动停止）
- 若选 `all`：正常调用（无额外参数）

### Step 3 - 询问用户选择处理组

**注意**：仅当 Step 2.5 未选 `table-only` 时执行本步。

必须调用 `ask_questions`，至少收集：
- 要处理的 group id（支持单选或多选）

默认策略：
- 未明确要求批量时，一次处理 1 组

用户选组后，必须执行：
- `scripts/build_group_payload.py` 生成 `artifacts/selected_groups_payload.json`
- 后续定位与改动计划基于该 payload，而不是临时猜测行号

### Step 4 - 定位代码并构建改动计划

对选中组逐个 occurrence 执行：
- 读取目标文件与行号附近上下文（`read_file`）
- 确定 canonical 片段（通常取第一处或最完整处）
- 形成“最小可行合并计划”

计划应包含：
- 抽取目标（函数/方法/公共模块）
- 每个 occurrence 的替换策略
- 受影响文件列表
- 风险点（行为差异、边界条件、宏/条件编译差异）

### Step 5 - 应用修改

仅可使用 `apply_patch` 落盘，且遵循：
- 仅修改选中重复组涉及文件（除新增公共文件外）
- 最小改动，不做无关重构
- 保持原有风格与 API 稳定

### Step 6 - 验证与回报

至少执行：
- `get_errors` 检查改动后错误

如仓库存在测试/构建入口，优先做与改动最相关的验证（可用 `run_in_terminal`）。

向用户汇报：
- 处理了哪些组
- 修改了哪些文件
- 验证结果
- 是否继续下一个组

## 行为约束（必须遵守）

- 未经用户选择组，不得直接改代码。
- 不得一次性“全仓大重构”，除非用户明确要求。
- 不得捏造重复组数据；解析失败时必须显式说明并给备选方案。
- 若报告行号与文件不一致：先提示并重新定位，必要时请求用户确认后再改。
- 优先保持行为不变；若存在行为变化风险，先告知用户并给两种方案。

## 推荐工具调用模板

1) 探索与发现
- `search_subagent`：定位重复报告、去重脚本、已有重构入口
- `file_search` / `list_dir`：补充路径信息
- `run_in_terminal`：调用 `scripts/scan_duplication.py`

2) 第一个用户交互 (Step 2.5 - 显示模式选择)
- `ask_questions`：询问用户 exact-only / all / table-only
- 根据选择，调用 `scripts/list_dup_groups.py`：
  - exact-only: `python scripts/list_dup_groups.py artifacts/duplication.xml --exact-only --repo <repo_path>`
  - all (default): `python scripts/list_dup_groups.py artifacts/duplication.xml --repo <repo_path>`
  - table-only: `python scripts/list_dup_groups.py artifacts/duplication.xml --table-only --repo <repo_path>` (agent会自动停止，不培进后续 Step 3)

3) 第二个用户交互 (Step 3 - 选择处理组)
- 仅当 table-only 未被选中时执行
- `ask_questions`：选择 group id
- `run_in_terminal`：调用 `scripts/build_group_payload.py artifacts/duplication.xml --repo <repo_path> --groups <id> --out artifacts/selected_groups_payload.json`

4) 定位与修改
- `read_file`：读取 occurrence 与上下文
- `multi_replace_string_in_file` 或 `replace_string_in_file`：应用合并修改

5) 验证
- `get_errors`：检查改动后错误
- `run_in_terminal`（可选）：执行最小相关测试/构建

## 输出风格建议

每轮处理保持短闭环：
1. 先展示候选组（含推荐）
2. 等用户选择
3. 执行并验证
4. 简要汇总并询问是否继续