# AI 短剧导演共同创作流程

本文件是 v3 `co-direct` 的流程、审核、台账和生产边界的唯一入口。用户确认的完整剧本是内容事实源；AI 负责拆解、候选生成和导演执行，用户逐阶段确认具体版本。v2.2 Manifest 只承担底层视频生产证据，不定义另一条创作流程。

## 1. 主流程

```text
锁定剧本
-> AI 导演解读与媒介实现分析
-> 确认视觉风格和技术制作规格
-> 展示完整覆盖与初步生成单元（PLANNED）
-> AI 内部角色分析 -> 提交并由用户确认选角简报
-> 生成并选择中性演员 -> 登记演员基准图
-> AI 分析角色定妆状态及场次映射 -> 用户确认状态方案
-> 逐项确认组件需求 -> 逐项生成并选择服装/面料/穿着效果、发型、妆容和配饰
-> 融合并确认每个状态定妆 -> 生成并确认角色四视图
-> 确认场景功能稿 -> 确认场景母版与同源视图
-> 确认空间骨架 -> 确认人物走位与机位运动
-> 确认镜头、表演、声音、屏幕文字与剪辑方案
-> 编译并确认可执行生成单元（EXECUTABLE）
-> 确认单元资产与 Prompt -> 逐单元生成视频并确认
-> 已接受视频的真实尾帧驱动下一单元 -> 后期与最终验收
```

粗粒度阶段由 `config/workflow/co-direct-stages.json` 定义。阶段只能顺序推进，并核验项目快照、依赖版本和追加式审核日志。初步单元只做完整覆盖与容量规划，不含已锁定分镜；未确认执行目标时不得把初步单元编译为 `EXECUTABLE`。

## 2. 事实与版本边界

- 剧本只能标注、拆分和引用。v3 不接受 `authorized_changes`；用户要改变内容时提交新的完整剧本版本。
- 每个 `EV/DLG` 按原顺序恰好进入一个生成单元。容量不足时增加单元，不压缩、删减、重排或补写剧情。
- `scene_map`、`shot_card` 和 continuity ledger 分别是空间、镜头和状态事实源；Prompt 只是目标模型转译。
- 场景母版锁视觉外观，`scene_map` 锁物理空间。故事板、导演总版、状态格和俯视图都是审阅投影，不得冒充事实源或视频输入。
- actual tailframe 必须来自对应的已接受视频，并保留来源单元、视频、时间码和哈希。它证明实际可见状态，但不覆盖 canonical 身份。
- 新案例不得复用其他案例的图片、视频、Prompt、API 响应或 actual tailframe。所有路径必须位于当前案例根内。

## 3. 人工审核

每次提交一个边界清楚的对象，说明版本、相对上一版的变化、需要用户决定的事项和确认后的下一步。决定固定为：

```text
approve | request_changes | reject | regenerate | select_candidate | defer | continue_provisionally
```

有效批准绑定 `artifact_id + version + sha256 + user_statement`。只有 `approve/select_candidate` 且用户原话明确表达通过或选择时才能产生 `USER_APPROVED`。`defer/continue_provisionally` 始终保持 `AWAITING_USER`；“现在不清楚，先进行下一步”属于后者。演员、定妆需求与组件、融合角色、场景母版、补充视图、空间、调度、镜头、资产、Prompt 和视频均遵守同一规则。API 成功、下载成功、AI 判断和用户未回复都不构成批准。

内部推理与用户决策必须分层。`character_role_profile` 用于整理剧本事实、戏剧功能、场次状态、表演任务和定妆线索，由校验器检查但不进入 `pending_reviews`，也不要求用户理解或批准。用户只审核会改变下游选择的可行动对象；角色阶段的首个审核对象是 `casting_brief`。只有内部分析发现会改变角色数量、剧本事实或关键状态划分的实质歧义时，才把具体问题提给用户，不能把整份内部分析当作审批表。

导演建议必须保持来源边界：地点、时间、职业、情绪和行为可以触发建议，但不能直接变成服化道、场景外观或表演事实。所有状态规划、场景功能稿和表演规划都必须把 `script_facts`、`continuity_constraints`、`director_recommendations`、`unresolved`、`user_decisions` 分开登记，并由每个具体结论通过 `basis_ref` 引用其中一项。`script_facts` 还必须用 `script_fact_domains` 标明事实领域；只有同领域的直接可见事实可以进入具体设计结论，跨领域语境只能触发导演建议。未决项不能进入 Prompt，推荐项在对应审核产物获用户确认前不能进入生产资产；`user_confirmed` 必须带 `decision_ref`。角色道具属于场景/镜头资产，不能走角色组件生产或混入角色定妆融合。

## 4. v3 项目台账

`project-ledger.json` 是小型当前快照，不承载领域文件的完整内容：

```json
{
  "schema_version": "3.1",
  "project_id": "drama-001",
  "workflow_mode": "co-direct",
  "current_stage": "SOURCE_READY",
  "current_versions": {},
  "artifacts": {},
  "derived_cache": {},
  "pending_reviews": [],
  "blocked_by": []
}
```

产物以 `<artifact_type>:<scope_id>` 作为当前版本键，作用域为 `PROJECT`、角色 ID、`角色ID:定妆状态ID`、场景 ID 或单元 ID。项目登记 `characters/look_states/scenes/units` 四类作用域。状态固定为：

```text
DRAFT | AWAITING_USER | USER_APPROVED | USER_REJECTED | STALE | SUPERSEDED
```

新产物只能注册为 `DRAFT` 或 `AWAITING_USER`。`USER_APPROVED` 只能由绑定当前产物 ID、版本和哈希的用户审核事件产生。

`review-ledger.jsonl` 只追加、不覆盖，每行保存审核 ID、产物身份、版本、哈希、用户决定、用户原话和时间。AI 整理的字段不能替代用户原话。

依赖类型由 `config/workflow/dependencies.json` 定义，审核规则由 `config/workflow/review-policy.json` 定义。上游产生新版本时，类型/作用域规则与产物自身的 `depends_on` 共同把当前下游标记为 `STALE`；历史文件、审核和已接受视频不删除。下一单元 Prompt 对 actual tailframe 使用显式依赖，避免形成类型级循环。

### 派生上下文与缓存

所有节点统一通过 `prepare_context(...)` 或 `project_ledger.py context build/inspect` 编译自己的最小上下文包，映射由 `config/workflow/context-packets.json` 驱动。上下文由已批准 artifact 的文件内容、版本和 SHA-256 组成，经过规范化 JSON 后生成稳定的 `context_hash`。节点复用规则如下：

```text
相同 context_hash + 缓存输出哈希仍匹配 -> 复用派生结果
输入 artifact 版本、内容或批准状态变化 -> 删除受影响缓存并重算
无关 artifact 变化 -> 当前节点缓存继续有效
```

`derived_cache` 只保存上下文类型、输入键、输入哈希、输出相对路径和输出哈希，不复制剧本、分析或图片内容；它不是第三套事实台账。缓存命中也不能把 `DRAFT/AWAITING_USER` 变成 `USER_APPROVED`，用户审核仍绑定当前 artifact 的 `artifact_id + version + sha256`。

blocking、shot、prompt 等固定节点复用配置驱动的依赖；跨角色、跨场景或跨单元的节点使用显式 `artifact_keys`。其中视频上下文必须显式列出本单元实际使用的全部角色四视图、造型状态、场景母版、执行资产和上一已接受单元的真实 `actual_tailframe`。第一单元没有真实尾帧时不得用计划尾态伪造。reference 文件只是一份经过哈希校验的上下文收据，视频适配器会再次核验其路径、作用域、哈希和输入键。

内部检查或批处理可以使用：

```bash
python3 scripts/project_ledger.py --path runs/example/project-ledger.json context inspect project PROJECT --project-root runs/example
python3 scripts/project_ledger.py --path runs/example/project-ledger.json context build project PROJECT --project-root runs/example --output derived/contexts/project.json
```

`context build` 只允许把输出写在项目根目录内；老台账没有 `derived_cache` 时按空缓存兼容，不影响既有项目恢复。视频等动态上下文还可以用 `--reference-output` 落盘引用；`context inspect` 始终只读。缓存仅复用派生数据，不改变人工审核顺序，也不跳过候选生成、用户选择或视频验收。

```bash
python3 scripts/project_ledger.py --path runs/example/project-ledger.json init drama-001 "短剧名称"
python3 scripts/project_ledger.py --path runs/example/project-ledger.json register style-v1 visual_style PROJECT 1 sha256:<hex> style/style-v1.json
python3 scripts/project_ledger.py --path runs/example/project-ledger.json --reviews runs/example/reviews/review-ledger.jsonl review review-style-v1 visual_style PROJECT approve "风格通过"
python3 scripts/project_ledger.py --path runs/example/project-ledger.json set-scopes characters C01 C02
python3 scripts/project_ledger.py --path runs/example/project-ledger.json --reviews runs/example/reviews/review-ledger.jsonl advance SCRIPT_LOCKED
```

## 5. 两层台账

- v3 `project-ledger.json`：共同创作阶段、当前产物版本、依赖快照和待审核项。
- v2.2 Director Workflow Manifest：视频任务、请求元数据、下载文件、用户视频决定和 actual tailframe。
- 图片资产台账：图片谱系、用途、文件哈希和用户图片决定。

三者以稳定角色、场景、单元和资产 ID 连接，不复制彼此权威事实。底层视频生产字段见 [v2.2 Manifest](../production/manifest-v2.md)。跨会话恢复必须同时读取项目快照、审核日志、领域产物、图片资产台账和 Manifest，不能凭聊天记忆补状态。

## 6. 生产不变量

- 每个可用资产必须有机器可读合同，并绑定用户决定和当前文件哈希；失败根资产的后代全部失效。
- 参考输入使用最小不冲突集合，每张输入只有一个用途。`lineage-final-only` 状态图与 canonical 根默认不同时上传。
- `asset_id` 是项目身份，模型标签是单次输入槽位；`input_bindings` 必须按真实上传顺序连续编号。
- v3 的演员、定妆、融合角色和场景阶段可在上游需求已批准且图片 API 已配置时调用图片模型；API 结果仍须用户选择。v2 资产流程默认只交付 Prompt。
- 凭证只从本地环境读取，不得写入 Prompt、台账、Manifest、请求元数据或日志。
- 未确认 API 路径时不得调用 API。未知模型或平台保持 `unresolved`，不得借用其他 Adapter 格式。
- generated-video 必须有真实任务、请求元数据、下载文件与哈希证据，并进入用户验收；Prompt-only 可从 `PROMPTS_VALIDATED` 交付。
- 默认一次正式交付一个生成单元。当前单元由用户接受后才解锁下一单元；提前规划不等于可提交。接受后提取绑定该视频版本与哈希的 actual tailframe，连续下一单元以真实尾帧为首要承接证据；没有已接受真实尾帧时才使用计划尾态。

## 7. 返工原则

用户拒绝后，根据反馈定位最小责任层：视觉候选问题回到对应视觉产物；空间不可行回到 `scene_map`；镜头职责或动作链问题回到 `shot_card`；仅格式或模型表达问题回到 Prompt。不得用 Prompt 补丁掩盖事实层缺陷，也不得借返工修改锁定剧本。
