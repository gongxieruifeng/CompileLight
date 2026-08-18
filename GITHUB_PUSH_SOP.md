# 项目推送 GitHub 标准 SOP

> **用途**：将本 SOP 传递给 Agent，Agent 按此规范完成任意项目的 GitHub 推送、文档编写与公开仓库维护。  
> **版本**：v1.0 · 2026-08-17  
> **基于**：CompileLight 项目推送实践

---

## 前置条件（用户提供）

Agent 开始前需确认以下信息：

| 参数 | 说明 | 示例 |
|------|------|------|
| `项目根目录` | 本地项目绝对路径 | `/Users/xxx/Desktop/MyProject` |
| `GitHub 用户名` | 用户的 GitHub 账号 | `gongxieruifeng` |
| `GitHub 邮箱` | Git commit 用邮箱 | `xxx@stu.scu.edu.cn` |
| `GitHub PAT` | Classic Token，需 `repo` 权限 | `ghp_xxxxxxxxxxxx` |
| `项目名（GitHub）` | 仓库显示名称（PascalCase） | `CompileLight` |
| `可见性` | `public` 或 `private` | `public` |
| `简历描述（可选）` | 用户简历中对该项目的描述文本 | 见用户输入 |

---

## 阶段 1：文件筛选与清理

### 1.1 扫描项目结构

```
1. LS 项目根目录，了解整体结构
2. 识别以下分类：
   - ✅ 保留：源码 / 配置 / 迁移脚本 / 文档 / 资产模板 / 运维脚本
   - ❌ 排除：测试数据 / 运行时数据库 / 中间结果 / 缓存 / 环境目录 / 凭据
```

### 1.2 排除清单（写入 .gitignore）

以下文件/目录 **必须排除**，不随仓库上传：

```gitignore
# 环境与配置
.env
.conda/
__pycache__/
*.pyc
*.egg-info/

# 运行时数据
data/db/*.sqlite3
data/traces/
data/reports/
data/artifacts/runtime/

# 中间结果与缓存
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage

# 项目内部文档（如不需要公开设计过程）
/docs/

# IDE
.vscode/
.idea/
*.swp
.DS_Store
```

### 1.3 保留决策原则

| 类别 | 保留 | 排除 |
|------|------|------|
| 源码 | `src/` 全部保留 | — |
| 脚本 | `scripts/` 保留 | — |
| 配置 | `pyproject.toml` / `environment.yml` / `.env.example` 保留 | `.env` 排除 |
| 迁移 | `migrations/` 保留 | — |
| 文档 | `README.md` 保留；`docs/` 按用户要求决定 | 设计过程文档默认排除 |
| 图片 | 架构图放 `assets/` 保留 | 设计素材图片排除 |
| 测试 | 用户明确要求才保留 `tests/` | 默认不保留测试文件 |
| 数据 | 资产模板种子 JSON 保留 | 运行时 SQLite / Trace / 报告排除 |

---

## 阶段 2：文档编写

### 2.1 README.md（开发者向，仓库主文档）

**结构模板**：

```markdown
<div align="center">

# {项目名}

**{副标题}**

[技术栈 Badge 图片]

**{一句话核心理念}**

</div>

---

## 📌 项目简介
{痛点 + 解决方案 + 核心理念引用块}

## ✨ 核心特性
{分编号子章节，每节含代码块/表格/关键指标}

## 📊 量化结果
{表格：指标 | 数值 | 对比基线}

## 🏗️ 整体架构
{ASCII 架构图}

## 📁 项目结构
{目录树}

## 🚀 快速开始
{环境要求表格 + 分步骤命令}

## 🧪 代码质量检查
{ruff / mypy / pytest 命令}

## 🔑 设计不变量
{编号列表，底线约束}

## 🛠️ 技术栈
{层级 | 选型 | 说明 表格}

## 📚 架构图
{图片引用表格}

## 📝 License
{MIT License}

<div align="center">
Made with ❤️ at {公司} · {职位} · {时间}
</div>
```

**编写规则**：
- 面向开源社区开发者，含完整快速开始指南
- 不含中间实验结果或项目进度数据
- 所有链接使用相对路径（`assets/xxx.png` 而非绝对 URL）
- Git Clone URL 用 HTTPS 格式
- 不引用仓库中不存在的目录（如 `docs/`、`tests/`）

### 2.2 {项目名}.md（面试官向，项目详细介绍）

**结构模板**：

```markdown
# {项目名} — {副标题}

> **职位**：{公司} · {职位} · {时间}
> **GitHub**：{仓库 URL}

---

## 项目概述
{一段式电梯演讲，痛点 + 解决方案}

## 核心亮点
### {emoji} {亮点标题}
{2-3 句说明}

## 量化成果
{表格：指标 | 数值 | 对比基线}

## 架构设计
{ASCII 架构图}

## 技术栈
{精简表格}

## 项目亮点总结
{4 条面试导向归纳}

---

**GitHub 仓库**：{URL}
```

**编写规则**：
- 面向面试官和非技术读者，强调业务价值和工程决策
- 量化数据来自用户简历或用户提供的数据
- 不含安装步骤、代码片段或开发者操作指令
- 突出架构创新、工程落地、可审计性、量化验证

### 2.3 PROJECT_HOMEPAGE.md（主页构建模板）

**结构模板**：

```markdown
# {项目名} 项目主页模板

## 项目基本信息
{表格：字段 | 值}

## 主页卡片展示内容
{一段式简介 + 三大链接}

## 核心标签
{技术标签列表}

## 量化亮点
{指标表格}

## 核心亮点
{分章节说明}

## 架构图引用
{GitHub Raw 链接表格}

## 技术栈表格
{精简表格}

## 主页模板 HTML 参考
{可直接渲染的 HTML 卡片}

## 链接汇总
{三个核心链接汇总}
```

---

## 阶段 3：Git 初始化与配置

### 3.1 初始化本地仓库

```bash
cd {项目根目录}
git init
git config user.name "{GitHub 用户名}"
git config user.email "{GitHub 邮箱}"
```

### 3.2 暂存与首次提交

```bash
git add -A
git commit -m "feat: initial release of {项目名}"
```

### 3.3 创建 GitHub 仓库

```bash
# 通过 GitHub API 创建仓库
curl -s -X POST \
  -H "Authorization: token {PAT}" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/user/repos \
  -d '{
    "name": "{项目名}",
    "description": "{一句话描述}",
    "private": {true/false},
    "has_issues": true,
    "has_wiki": false
  }'
```

### 3.4 添加远程并推送

```bash
git remote add origin https://{用户名}:{PAT}@github.com/{用户名}/{项目名}.git
git branch -M main
git push -u origin main
```

---

## 阶段 4：仓库公开（如需 public）

```bash
# 通过 GitHub API 切换可见性
curl -s -X PATCH \
  -H "Authorization: token {PAT}" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/{用户名}/{项目名} \
  -d '{"private": false, "visibility": "public"}'

# 验证匿名可访问
curl -s -o /dev/null -w "%{http_code}" \
  https://api.github.com/repos/{用户名}/{项目名}
# 期望返回 200
```

---

## 阶段 5：后续维护操作

### 5.1 删除远程文件（保留本地）

```bash
git rm -r --cached {目录/文件}
git commit -m "chore: remove {说明}"
git push origin main
```

### 5.2 追加新文件并推送

```bash
git add {文件}
git commit -m "docs: add {说明}"
git push origin main
```

### 5.3 修改 README 后推送

```bash
git add README.md
git commit -m "docs: {变更说明}"
git push origin main
```

### 5.4 安全提醒

推送完成后告知用户：

> 当前 `origin` remote URL 中内嵌了 PAT。如需更安全，可切换：
> ```bash
> # 切换为无 Token 的 HTTPS
> git remote set-url origin https://github.com/{用户名}/{项目名}.git
> # 或切换为 SSH
> git remote set-url origin git@github.com:{用户名}/{项目名}.git
> ```

---

## 质量检查清单

推送完成后逐项确认：

- [ ] `README.md` 面向开发者，含完整快速开始指南
- [ ] `{项目名}.md` 面向面试官，含量化成果和亮点
- [ ] `PROJECT_HOMEPAGE.md` 含 HTML 模板和链接汇总
- [ ] `.gitignore` 已排除所有中间结果、测试数据、环境文件
- [ ] 仓库中不存在 `.env`、`*.sqlite3`、`__pycache__/`
- [ ] 仓库中不存在 `docs/` 内部设计文档（除非用户要求保留）
- [ ] README 中无指向已排除目录的破损链接
- [ ] Git Clone URL 使用 HTTPS 格式
- [ ] 仓库可见性符合用户要求（public/private）
- [ ] 匿名访问验证通过（如为 public）
- [ ] Git commit 信息简洁且符合规范
- [ ] 已提醒用户 PAT 安全风险并提供切换方案

---

## Agent 执行流程总结

```
用户输入（项目路径 + GitHub 凭据 + 简历描述）
  │
  ├── 阶段 1：扫描项目 → 写 .gitignore → 筛选文件
  ├── 阶段 2：写 README.md + {项目名}.md + PROJECT_HOMEPAGE.md
  ├── 阶段 3：git init → commit → GitHub API 建仓 → push
  ├── 阶段 4：如需 public → API 切换 → 匿名验证
  └── 阶段 5：安全提醒 → 输出最终总结
```
