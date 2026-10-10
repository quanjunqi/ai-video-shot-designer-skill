# Changelog

本文件记录 AI Video Shot Designer 的显著变更，格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.2.1] - 2026-09-13

### Changed
- 强化 H3 校验器：兼容完整/简写主体定义，识别未知字段、空字段、重复或未定义标签、非法标签间距、镜头编号倒序以及不平衡的 `<d>` 台词标签。
- 压测样例补齐局部首时码并拆分单行多标签定义，三组回归样例均达到 `ERROR=0 / WARNING=0`。

### Added
- 新增 10 项零依赖回归测试，覆盖历史基线跳过、定义语法、镜头编号、标签和台词闭合等边界。

## [0.2.0] - 2026-09-13

### Added
- `references/platform-spec.md`：平台硬约束与经验默认值的单一事实源，区分【平台】/【默认】，附平台升级核对清单。
- `references/worked-example.md`：端到端黄金样例（资产/故事板 Prompt ＋ 对白单元 ＋ 道具交接跨段单元）。
- `scripts/validate_h3_prompt.py`：零依赖 H3 分段 Prompt 机械校验器，覆盖六字段顺序、标签先定义后使用、前缀、枚举、时间码、台词标签与禁用字段，ERROR 时非零退出。
- `references/pre-delivery-checklist.md`：机械项＋语义项两层交付自检。
- `references/batch-ledger-schema.md`：跨批次项目台账、用户回传清单、素材命名约定与跨会话恢复。
- `references/terminology-map.md`：内部英文字段 ↔ 中文显示名 ↔ 是否进入六字段的权威对照。
- `references/script-parsing-schema.md`：剧本解析的标准中间表示。
- 新增 README、MIT LICENSE、本 CHANGELOG。

### Changed
- 将散落在 SKILL 与多个 reference 的时长区间、词量、批次、重叠/尾帧秒数、参考图张数统一改为引用 `platform-spec.md`，消除“8—15 秒”与“13.5—15 / 8—12 秒”并存的口径冲突。
- 写实 `agents/openai.yaml` 的展示描述。
- 全部新规范从 SKILL.md 主入口建立导航，形成渐进式文档结构。

### Removed
- 移除与本 Skill 无关的 `student.md` 草稿文件。

## [0.1.0]

### Added
- 初始能力：剧本到 MiniMax H3 六字段分段 Prompt 的转换、≤15 秒分段与跨段首尾帧一致性。
- 导演级连续性（景别递进、轴线、镜头交接）、资产/故事板/参考图选择规则、站位地图与分段状态 schema。
- 中文生成设置与英文六字段的双区交付，官方标签与台词标签规范。

[0.2.1]: /commits
[0.2.0]: /commits
[0.1.0]: /commits
