---
name: ai-video-shot-designer
description: 以人机共同导演方式将用户确认的中文或英文短剧剧本转换为导演解读、演员、状态化定妆、场景、调度、镜头、可执行生成单元和目标模型 Prompt，并逐阶段等待用户明确确认。适用于忠实拍摄完整短剧或明确剧本片段；不用于 MV、广告、纪录片等其他视频类型。
---

# AI Video Shot Designer

把已确认剧本忠实转换为可追溯的视频生成计划。默认使用 `co-direct`：AI 先分析并提出专业方案，用户确认具体版本后才进入下游。用户表达“不清楚、先继续”时只能暂定推进准备工作，不能登记为批准。只加载当前任务需要的 reference，不要预读全部资料。

新 v3 项目先读取 [共同创作流程](references/core/workflow.md)，其中包含阶段、审核、项目台账、依赖失效与生产不变量。既有 v2.2 项目继续按原 Manifest 工作，不为迁移复制权威事实。

节点执行时先按 [上下文包合同](references/core/context-packets.md) 编译当前节点所需的最小已确认输入。相同输入哈希可以复用派生上下文和 Prompt 前置结果；缓存只减少重复读取和重算，不代表用户批准，也不能绕过版本、哈希和人工审核。

## 事实源

- `script_ir` 与 `EV/DLG/LOCK`：剧情、动作和台词事实。
- `scene_map`：空间、路线、锚点和机位事实。
- `shot_card`：镜头级生产事实。
- continuity ledger：跨镜和跨单元状态事实。
- execution target：交付方式、模型和 API 平台事实。
- Prompt：面向目标模型的派生执行稿，不得反向定义事实。

导演总版仅是可选的人工审阅投影，不是构图来源、真实尾帧或视频输入。默认不生成分镜位图、单格状态图和拼接分镜板。

## 工作方式

1. 先判断请求属于规划、资产、Prompt、生成还是复核；一次请求可跨越相邻阶段。
2. 仅读取下方对应的 reference。跨阶段工作或改变 Gate 时，再读取 [完整工作流](references/core/workflow.md)。
3. 以 [生产 Manifest](references/production/manifest-v2.md) 记录视频生产状态和证据；按当前 Gate 渐进补全，不伪造尚未产生的对象。
4. 使用现有脚本做机械校验和执行，不把脚本中的实现细节复制进 Prompt。
5. 涉及真实生成、资产上传或交付前，复核 [共同创作流程](references/core/workflow.md) 的生产不变量。

## 按需路由

- **剧本**：读取 [锁定剧本与覆盖](references/contracts/script.md)。
- **角色、选角、演员基准、状态化定妆、角色四视图与场景母版**：读取 [视觉开发](references/contracts/visual-development.md)。旧项目若出现 `actor_identity_set`，按该文档的兼容规则处理，不把它当作新项目的必经阶段。
- **空间与调度**：读取 [空间与调度](references/planning/spatial.md)。
- **覆盖与镜头**：读取 [镜头规划](references/planning/shots.md)。
- **单元与连续性**：读取 [生成单元](references/production/units.md)。
- **资产**：读取 [资产合同与生产](references/production/assets.md)。
- **Prompt 转译**：先读取 [执行目标](references/production/execution.md)，再按目标读取 [MiniMax H3](references/adapters/minimax-h3.md) 或 [Seedance 2.5](references/adapters/seedance-2.5-direct.md)。
- **生成、验收与交付**：读取 [Prompt、视频与交付](references/production/execution.md) 和 Manifest 契约；运行对应校验器。不得把 API 成功或下载成功视为用户接受。

不要为普通任务加载历史兼容说明、未涉及平台的 Adapter 或不相关领域合同。

## Gate

v3 人机共同创作阶段：

```text
SOURCE_READY -> SCRIPT_LOCKED -> DIRECTION_READY -> SPEC_READY -> COVERAGE_READY
-> CAST_READY -> LOOKS_READY -> SCENES_READY -> SPACE_READY -> BLOCKING_READY
-> SHOTS_READY -> UNITS_READY -> PROMPTS_READY -> IN_PRODUCTION -> DELIVERED
```

每次推进由 `project-ledger.json` 检查所有已登记角色、场景和单元的当前产物是否获得用户确认。详细生产证据继续使用 v2.2 Manifest 的状态：

```text
SOURCE_READY -> SCRIPT_LOCKED -> SPACE_READY -> SHOTS_LOCKED
-> UNITS_READY -> ASSETS_READY -> PROMPTS_VALIDATED
-> IN_PRODUCTION -> USER_REVIEW_PENDING
-> USER_ACCEPTED -> DELIVERED
                   \-> USER_REJECTED -> PROMPTS_VALIDATED
```

Prompt-only 可从 `PROMPTS_VALIDATED` 交付。真实生成必须经过 `USER_REVIEW_PENDING`，只有用户明确接受才能进入 `USER_ACCEPTED`。v3.1 项目台账使用 `schema_version: "3.1"`；其底层视频生产 Manifest 继续使用 `2.2/shot-card-first`，不复制视频任务和验收事实。

## 核心边界

- 用户确认的剧本不可删除、改写、重排或补写；模型容量不足时增加生成单元。每个事件与对白必须完整映射到用户可读的单元拍摄稿。
- AI 必须主动完成导演解读、媒介实现和内部角色分析，并向用户提交可行动的选角建议、定妆状态和场景功能方案；“剧本未指定”应进入有依据的导演建议或待确认项，不能成为停止分析的借口。
- 角色分析是内部、可校验的导演推理，不作为独立用户审批项，也不进入 `pending_reviews`；它只用于派生选角简报、定妆状态和后续表演设计。用户首先确认的是只包含稳定身份与身体条件的选角简报。演员保持中性；定妆按场景状态建立，医生上班/下班、舞台演员素颜/舞台妆不能混成单一外观。
- 所有导演推断都必须保留来源边界：剧本事实、连续性约束、导演建议、未决项和用户决定分开登记，并由具体设计项用 `basis_ref` 精确引用。地点、时间、职业、情绪或行为不能自动推出具体服装、发型、妆容、鞋子、配饰、道具、特殊效果、表演动作或场景外观；`prop` 属于场景/镜头资产，不走角色组件生产且不进入角色融合。未决项不能进入 Prompt，导演建议只有在对应审核产物获用户确认后才能进入生产。
- 新项目的角色资产顺序固定为：演员基准图 -> 造型状态方案 -> 组件需求确认 -> 独立生成并选择服装/面料/无身份穿着效果、发型和配饰 -> 基于演员图应用妆容 -> 角色定妆融合 -> 四视图确认。演员基准图不是角色，四视图也不是分镜或构图参考。
- 演员候选、造型状态、定妆需求、定妆组件、融合角色、四视图、场景母版、空间骨架、调度、镜头、Prompt 和视频都必须绑定具体版本供用户确认；AI 和 API 不能代替用户批准。
- 图片 API 不是流程前置条件。若用户未指定 API 路线或本地未配置图片服务，只输出可复制的单图 Prompt，不指导用户生成多少张、如何筛选或如何编号，也不要求用户先配置 API。默认用户会自行筛选；当用户附图并明确表示“这是选好的/就用这张”时，直接校验文件、登记 SHA-256 并记录为用户选定结果，不再要求候选编号或二次确认。未明确表达选定时才进入待选择状态。Prompt 本身不是审批项，也不能代替真实图片或用户选择。
- 初步生成单元只定义完整覆盖、容量边界和计划首尾态，不是分镜。镜头与剪辑方案确认后才编译 `EXECUTABLE` 单元；已接受视频的 actual tailframe 优先于计划尾态驱动下一单元。
- 场景母版是视觉事实，`scene_map` 是空间事实；走位与机位图只能从 `scene_map` 确定性派生。
- v3 不接受 `authorized_changes`；用户需要改变剧情时提交新的完整剧本版本。历史 v2 项目的授权变化仍按原 Manifest 记录。
- 每个 v2 shot 都必须有完整 `shot_card`；故事板或导演总版不能替代它。
- 新案例不得复用其他案例的图片、视频、Prompt、API 响应或 actual tailframe。
- 未确认执行目标时最多推进到 `UNITS_READY`；不得伪造可提交格式。
- v3 选角及后续明确设计的候选生成阶段可在用户已确认上游需求、图片 API 已配置时调用图片模型；API 成功不等于用户批准。既有 v2 流程仍默认只交付资产 Prompt。
- 只有用户确认 API 路径后才能调用对应 API；凭证只从本地环境读取。
- 当前已实现目标包括 MiniMax H3 直接模型、AutoDL + MiniMax H3 API，以及基于用户提供 Prompt 契约的 Seedance 2.5 直接模型；其他目标保持 `unresolved`。
