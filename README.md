# 墨舟 小说写作 Agent

基于 Python、NiceGUI、Pydantic 和本地 Markdown/JSON 快照的小说写作工作台。支持多项目、设定与三级大纲、章节草稿与定稿、选中段落改写、长期记忆和 Markdown 导出。

## 启动

需要 Python 3.12 或更高版本，以及 uv。Windows 上若默认 python 是旧版，请通过 `py -3.12` 创建虚拟环境。

```powershell
# 已安装 uv 时
uv sync --locked
Copy-Item .env.example .env
uv run python -m app.main
```

若尚未安装 uv，可采用项目内安装方式：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install uv
.\.venv\Scripts\uv.exe sync --locked --python .venv/Scripts/python.exe
Copy-Item .env.example .env
.\.venv\Scripts\uv.exe run python -m app.main
```

打开 [本地工作台](http://127.0.0.1:8080)。应用只监听本机地址，同一数据目录只能启动一个实例。停止运行可在终端按 Ctrl+C。

也可用 `python -m pip install -r requirements.txt` 安装运行依赖；测试依赖由 uv 的开发依赖组管理。

## 模型配置

编辑 `.env`：

```dotenv
NOVEL_MODE=openai
OPENAI_API_KEY=填写自己的密钥
OPENAI_MODEL=填写账户可用且支持Responses与结构化输出的模型名称
OPENAI_BASE_URL=https://api.openai.com/v1
```

当前适配器采用 OpenAI 官方 Python SDK 的 Responses API，正文用 create，设定与记忆用 parse。自定义 API 地址必须支持这些接口，只有 Chat Completions 兼容接口的服务不能直接使用。本项目不预设账户可用模型；需要自行配置并验证。[官方 Python SDK](https://developers.openai.com/api/reference/python)、[结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)

未配置密钥时，可将 `NOVEL_MODE=demo` 后启动。界面会明确显示离线演示标识，所有生成内容是固定示例，仅用来体验流程，不能作为真实创作质量的判断依据。实际创作前建议另建项目。

可选环境变量：

| 配置 | 默认值 | 用途 |
|---|---|---|
| NOVEL_DATA_DIR | projects | 小说数据目录 |
| NOVEL_PORT | 8080 | 本机服务端口 |
| NOVEL_TIMEOUT | 120 | 单次模型请求超时秒数 |
| NOVEL_CONTEXT_TOKENS | 24000 | 总上下文预算，需适配所选模型 |
| NOVEL_OUTPUT_TOKENS | 6000 | 输出预留与请求输出上限 |

上下文使用 cl100k_base 的 token 数乘以余量系数估算，不能替代各厂商的精确计数。首次使用 tiktoken 可能需要联网下载编码资源。程序优先保留正式设定、当前大纲、人物和未回收伏笔，历史摘要及检索片段按剩余空间加入。目标字数与 token 上限是两个不同约束，实际字数显示在编辑器下方。

## 使用流程

1. 创建小说项目，在“项目管理”填写题材、简介、目标读者、叙事视角、风格和字数，保存。
2. 在“设定与大纲”生成基础设定，审阅 JSON 内容后点击“确认生效”。也可自行填写合法 JSON。characters 的 relationships 填人物 ID，势力和人物 ID 应保持稳定。
3. 依次生成并确认全书大纲、分卷大纲。切换文档类型后，卷号字段用于选择分卷。
4. 在“章节创作”选择章节编号并点击“加载章节”，填写章节名称和所属分卷，先保存章节信息。
5. 回到“设定与大纲”，选择章节大纲及对应章节号，生成、编辑并确认。
6. 在“章节创作”设置本章目标字数及额外要求，点击“AI 创作 / 整章重写”。生成结果作为草稿保存，正式正文不被覆盖。
7. 可以直接编辑正文；在正文框选中一段文字，填写修改要求，点击“修改选中段落”，审阅后应用。应用建议后需要保存草稿。正文变化会使旧的修改建议失效。
8. 点击“确认定稿并更新记忆”，在确认窗口确认。正文先可靠保存，再提取记忆。前章未定稿时不允许生成或定稿后章。
9. 查看“小说记忆”的同步状态、逐章来源和 JSON 数据。可以手工修订摘要、人物状态、关系、时间线及伏笔，或按关键词检索正式章节全文。
10. 继续下一章；在“项目管理”导出全部正式章节的 Markdown。

AI 生成只读取正式设定和大纲；候选保存不代表生效。切换文档、章节或项目之前请保存编辑内容。浏览器断开时只有已保存内容保证恢复。

## 记忆冲突与恢复

记忆同步失败不会撤销或删除已保存的正文。界面显示失败原因，点击“重试 / 恢复记忆同步”继续处理；重启后也可以执行该操作。未同步前阻止新的章节 AI 生成，仍可查看与编辑。

如果模型发现设定冲突，候选记忆会保留在“小说记忆”中。对照正式设定与正文处理问题，编辑候选 JSON，并清空已解决的 conflicts，确认候选修订后重试同步。不要只清除错误提示而忽略实际矛盾。程序不会自动覆盖世界规则。

修改并重新定稿历史章节后，程序从该章开始依次重建记忆，保留后续正文并提示复核。修改正式设定也会触发记忆重建；修改较早章节的正式记忆则从后章重建。程序不自动重写已有后续正文。

## 文件与备份

```text
projects/<project_id>/
  CURRENT                     当前完整快照的版本 ID
  .write.lock                 写入互斥锁
  revisions/<version>/
    state.json                完整状态及 schema_version
    project.json              项目基本信息
    settings/                 正式设定、人物与势力
    outline/                  正式大纲、章节元数据
    drafts/                   候选设定、大纲和章节草稿
    chapters/                 正式章节完整 Markdown
    memory/                   逐章来源、摘要、人物、时间线和伏笔
    operations/current.json   定稿操作 ID 与同步进度
```

每次保存生成不可变修订，完成全部文件写入后才替换 CURRENT。应用只从 CURRENT 对应的 state.json 读取，避免混用新旧文件。目录中的其他 Markdown/JSON 是该修订的可读导出，不应直接编辑；在界面中编辑会生成新的完整修订。

备份时停止应用，复制整个数据目录，包括 CURRENT 和 revisions。历史修订不自动清理，数据量随保存次数增长。需要人工回滚时先备份，在停机状态下将 CURRENT 改为一个已完成且含有效 state.json 的历史修订 ID。中断时留下的未发布目录不作为正式数据读取。

本方案的原子替换主要防止进程中断造成半次保存，不能保证硬件损坏、磁盘故障或所有文件系统的断电行为；重要作品请另做备份。

## 验证与开发

```powershell
uv sync --locked
# 无本机 Edge 的环境先安装测试浏览器
uv run playwright install chromium
uv run pytest -q
Get-ChildItem tests/Verify-*.ps1 | ForEach-Object { & $_.FullName }
```

pytest 包含独立存储目录下的工作流测试和真实浏览器测试。Windows 优先用已安装的 Edge，其他环境使用 Playwright Chromium。浏览器测试会启动自己的随机本地端口，所有数据写到测试临时目录，不调用付费 API。

自动化五章测试采用演示模型，检查流程、上下文、来源和重启恢复。真实模型的中文创作质量、长篇一致性、字数达标率及至少五章人工审阅，需要在配置真实密钥后验收；它们不由固定示例测试代替。

设计依据：[产品设计](docs/MVP设计文档.md)、[技术方案](docs/MVP技术方案.md)。
