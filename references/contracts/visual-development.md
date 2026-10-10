# 视觉开发合同

本文件统一管理 v3.1 的角色分析、选角简报、中性演员基准、状态化定妆、角色四视图、场景功能稿、场景母版和同源视图。`actor_identity_set` 仅用于兼容旧项目，不是新项目角色定妆前的必经资产。所有候选都必须绑定已批准的上游版本和文件哈希；API 返回成功只代表候选生成完成。

## 0. 角色资产分层

角色资产不是一张“万能人物图”，而是按生产顺序、稳定程度和用途分层：

```text
演员基准图
  -> 造型状态表
  -> 独立服装结构/面料/穿着效果、独立发型/配饰、演员妆容应用
  -> 角色定妆状态（绑定具体场次和服化道）
  -> 角色四视图身份资产（可供人审和视频参考）
  -> 原子身份视图（仅在四视图不足时补充）
  -> 镜头级人物参考（只服务当前镜头）
```

- `actor_baseline` 只锁定演员身份、身体比例和中性基础外观，不是剧本角色。
- `character_four_view` 在具体角色定妆通过后生成角色四视图身份资产。它可以作为视频生成中的人物身份与服装参考，但不能被当作分镜板、场景构图图或连续动作图。
- `actor_identity_view` 是旧项目或四视图不足时的独立单帧备用视图，例如正面脸部、四分之三脸部、侧面或背面全身；新项目不预生成原子视图集。
- `canonical_character_look` 是已经绑定具体角色状态的定妆结果，不得反向覆盖演员身份基准。
- `composition_reference` 只解决当前镜头的构图，不能代替身份资产或定妆资产。

角色参考采用“四视图为默认输入 + 镜头触发补充”的规则。四视图固定包含正面全身、90 度侧面全身、背面全身和正面胸部以上脸部特写；只有四视图对具体镜头解析不足时，才从已批准角色状态派生独立原子视图。视图需求由剧本和镜头事实触发，不由“资产完整”主观触发。

## 1. 角色分析、选角与演员

AI 先在内部生成并校验 `character_role_profile`，把剧本事实、戏剧功能、场次状态、表演任务和定妆线索分开。它服务导演判断，不直接进入演员图片 Prompt，不进入 `pending_reviews`，也不作为独立用户审批项。随后向用户提交可直接修改或确认的 `casting_brief`：

```json
{
  "character_id": "C01",
  "script_refs": ["EV001", "DLG001"],
  "visible_age": "25-30",
  "identity_requirements": ["剧本明确为女性"],
  "physical_requirements": [],
  "user_constraints": [],
  "director_recommendations": [{
    "field": "visible_age",
    "value": "25-30",
    "rationale": "与剧本职业阶段相符，作为待用户确认的导演建议"
  }],
  "unknowns": []
}
```

选角简报只描述演员身份和稳定身体条件，不放表演重点、情绪、角色经历、妆发或服装。剧本未指定的项目由 AI 提出带理由的 `director_recommendations`，用户可确认或修改；不能以“未指定”为由放弃专业建议。不得加入候选排名、优劣评估或 CP 感。用户无需审核内部分析，只需判断选角条件是否符合预期。选角简报获用户批准且哈希一致后才能生成候选。

演员候选保持“演员”状态：一张单独的全身基准图，中性背景、中性基础服装、无角色妆发、无职业制服、无剧情道具、无场景和无表演动作。生成时读取当前已批准的 `visual_style:PROJECT`，不得使用游离的风格描述。用户未指定 API 路线或图片服务未配置时，系统只输出 Prompt 供用户在任意图片工具自行生成和筛选，不规定生成数量或编号，不以 API 配置问题阻塞流程，也不额外要求用户审批生成路线。

候选批次记录模型、请求元数据、文件路径和 SHA-256，不保存 Token。用户选择时重新计算候选文件哈希，并把 `select_candidate`、候选身份和用户原话登记为 `actor_baseline:<character_id>`。AI 不对用户选择继续排名或推翻。

选中单张演员后，演员阶段即完成，并登记为 `actor_baseline:<character_id>`。演员基准图不得带入角色服装、职业制服、角色妆容、剧情道具、场景或表演动作。只有具体状态的角色定妆通过后，才生成该状态的 `character_four_view:<character_id>:<look_state_id>` 供用户一次检查，并作为后续视频生成的人物身份与服装参考。四视图中的背面单元应展示后脑、肩颈和服装背面，不得把“背面”误写成面部特写。

旧版身份集支持两种审批模式。它们只适用于迁移旧项目，或在具体镜头确实无法由角色四视图支撑时按需补充，不是新项目的演员阶段：

1. `set`：用户对整组身份参考一次确认。身份集文件记录四视图身份资产和可选的原子视图路径、哈希、来源与输入用途；四视图资产的批准范围继承自该身份集，不要求用户逐张重复点击确认。
2. `per_view`：兼容旧项目，用户逐张确认每个原子视图。新项目默认使用 `set`。

`actor_identity_set:<character_id>` 只有在旧项目身份集整体获用户确认后才可变为 `USER_APPROVED`。新项目不需要创建该对象，也不能因为缺少它阻塞 `look_state_plan`、组件生成、角色定妆或四视图。新项目的 `casting_brief` 不要求 `required_identity_views` 或 `identity_view_policy`；这两个字段仅为旧文件保留的兼容字段。四视图身份资产、原子身份图和角色定妆图不可互相替代；四视图资产必须保持同一演员、同一角色、同一造型状态和四个稳定视图，不得包含分镜框、动作顺序或场景调度。镜头若新增侧面、背面或极端近景需求，优先继续使用四视图资产；只有出现视图解析不足时才增加原子身份视图，不回退或重审未受影响的身份资产。内部角色分析只需通过结构校验，不构成阶段审批门。

## 2. 角色定妆

演员基准图通过后即可进入角色设计，不等待 `actor_identity_set`。AI 先按场次、时间、职业状态、表演场合、伤病和剧情变化生成 `look_state_plan:<character_id>`。同一人物的医生上班/下班、舞台演员素颜/舞台妆等必须成为不同状态，并明确映射到场次；不能默认全剧只有一个造型。

造型状态必须使用来源分层，不能把语境直接写成造型事实。新计划的每个状态必须有 `provenance`，包含 `script_facts`、`continuity_constraints`、`director_recommendations`、`unresolved` 和 `user_decisions` 五个数组，以及为每条剧本事实标注领域的 `script_fact_domains` 对象；每个组件还要标明 `basis`、`basis_ref`、`rationale` 和 `ownership`。`basis_ref` 必须逐字指向对应来源数组中的一项。`script_fact` 只能复述剧本，而且只有 `hair/makeup/costume/shoes/accessories/prop/special_state/performance/scene_appearance/state_boundary` 等匹配领域的直接事实才能定义对应结论；`location/time/occupation/behavior/emotion/lighting/identity` 等语境事实只能触发导演建议，不能跨领域反推。`continuity_constraint` 只锁定跨场次一致或变化，`director_recommendation` 必须带理由并写 `approval_required: true`，`unresolved` 必须明确保持待设计，`user_confirmed` 必须带 `decision_ref`。旧项目的 `script/director_inference/user` 只能用 `check_v3_artifact.py --allow-legacy-design-basis` 做只读兼容校验；该开关不放行图片生产，新 v3 校验和生产路径不接受旧格式。

地点、时间、职业、情绪、人物类型和行为只能触发设计问题或导演建议，不能自动推出服装、发型、妆容、鞋子、配饰、道具或特殊状态。例如“出租屋、夜、内”不等于居家服，“长时间游戏”不等于油腻乱发、黑眼圈、耳机或电竞服，冷蓝屏幕光不能决定蓝黑服装，偏清瘦的演员条件也不能决定宽松版型；这些具体选择都必须另行提出并确认。状态名也只描述已知边界，如“同一晚连续状态”，不得把未确认的造型类别写进名称。每个状态必须用 `label_basis` 把 `label` 逐字绑定到剧本事实、连续性约束或已确认用户决定；导演建议和未决项不能提前进入状态名。

每个状态按需要列出 `hair/makeup/costume/shoes/accessories/prop/special_state`；这里的 `prop` 只登记状态和归属，不代表它是角色造型组件。不需要的组件不生成。用户明确确认某组件不存在时，组件需求必须登记 `production_disposition=confirmed_absent`、`basis=user_confirmed` 和 `decision_ref`，且不得声明 `asset_type` 或下游图片资产；角色融合必须把该需求作为依赖和禁止新增约束，但不得要求或接受该组件图片。以后把“无”改为具体设计时只发布该组件的新需求版本，并使融合定妆及四视图失效，不推翻其他组件资产。角色造型项先提交独立的 `look_component_requirement:<character_id>:<look_state_id>:<type>` 供用户确认。服装需求边界获批后，必须先询问用户是否有服装参考图：有图时登记 `reference_image_status=provided` 并绑定图片；无图时登记 `reference_image_status=not_provided`，由 AI 提出明确标注为导演建议的类别、版型、色彩、面料和层次方案，再由用户选择。两条路径都必须写入 `reference_decision_ref`。用户确认的文字方案可用 `basis=user_confirmed` 和 `resolves_basis_ref` 将状态方案中的原未决项升级为生产事实。完成这一步且规格获批后才能调用图片 API；`basis=unresolved` 的需求即使存在于规划中也不能进入图片 Prompt。用户选中候选后登记对应的已确认组件。服装状态至少可拆为 `costume_structure`（无人物隐形人台的正面、标准 90 度侧面和背面三视图，锁定廓形、裁片和前后关系）、`fabric_detail`（微距材质，锁定纹理和反光）和 `costume_worn_view`（无身份人台或中性人体模特穿着效果，锁定比例、垂坠和层次）；它们可以共同作为 `costume` 的融合来源。导出 `costume_structure` Prompt 前，规格必须包含 `structure_design.status=user_confirmed`、对应 `decision_ref`、服装组合、已确认的版型/配色/面料类别/层次/图案装饰，以及上装与下装的完整结构字段。结构图不得出现人物、人体部位、演员身份、动作、剧情场景、微距纹理、复杂穿着褶皱或图中文字；正、侧、背由固定左中右位置区分，审核标签如有需要由程序后期确定性叠加。服装参考图若包含模特，只提取服装，不继承模特身份、脸部、体型或背景。发型和配饰也使用无身份头模、展示模特或静物展示，不读取演员图；妆容使用 `makeup_batch` 读取演员基准图，只改变演员脸上的妆容状态。最终角色融合才把演员身份与全部已确认角色组件合并。不得先生成再让用户被动接受 AI 自行决定的服装、妆容或发型。

`prop` 的 `ownership` 只能是 `scene_asset` 或 `shot_asset`，不能使用 `look-component` 生成命令，也不能进入角色融合；电脑、手机、饮料罐和外卖等应转交场景或镜头资产流程。`special_state` 必须用 `ownership` 写明它是 `character_asset`、`performance_state` 还是 `shot_asset`。王力案例中的“疲惫的脸”只规定观众应看见疲惫，不直接授权黑眼圈或肤色变化；“肩膀微微颤抖”只授权原动作，不能自动扩写成哭泣、出汗或衣物破损。

融合定妆必须同时绑定已批准的演员基准图、状态方案、该状态每一项 `look_component_requirement` 和对应的全部已批准组件资产；不能通过手工登记组件资产绕过组件需求确认。旧版已批准身份集可作为可选增强参考。第 1 张参考图始终是演员身份基准，其他图片只贡献各自组件，不继承其中人物、姿势或背景。融合结果需要再次由用户选择，登记为 `canonical_character_look:<character_id>:<look_state_id>`；一个状态通过不能放行其他状态。

定妆基准通过后，才能从 `canonical_character_look:<character_id>:<look_state_id>` 生成 `character_four_view:<character_id>:<look_state_id>`。四视图的固定顺序是：正面全身、90 度侧面全身、背面全身、正面胸部以上脸部特写。四个视图必须是同一演员、同一角色、同一造型状态；纯白背景、光色均匀、无分割线、无箭头、无编号、无文字、无水印、无场景和无分镜框。四视图用户一次确认后即可作为默认视频输入，独立原子视图只在具体镜头解析不足时按需派生。

## 3. 场景视觉

```text
scene_functional_brief -> scene_master -> scene_view -> scene_view_set -> scene_map
```

AI 先提交场景功能稿，明确叙事功能、必须支持的动作与走位、连续性锚点、制作限制和由此推导的视觉需求。场景功能稿必须使用同一套五类 `provenance`；每个 `visual_implications[]` 是含 `requirement/basis/basis_ref/rationale` 的对象，导演建议还要写 `approval_required: true`。未决装修档次、整洁程度、色彩或材质只能留在 `unresolved`，不能进入 `visual_implications` 或母版 Prompt。用户确认功能稿后才生成无人场景母版。反向和侧向补充视图必须从已批准母版参考编辑，不得独立文生。用户逐张确认后组成视图组；视图组至少有唯一 `master/reverse/left_or_right`，每项精确绑定当前产物 ID、SHA-256 和同一个母版来源。

`scene_master` 决定场景“看起来怎样”，`scene_map` 决定“物理上怎样成立”。空间骨架必须绑定 `source_view_set_id`；透视图不能替代几何合同，几何合同也不能擅自重画场景外观。空间、走位和机位规则见 [空间与调度](../planning/spatial.md)。

## 4. 生成与确认

图片有两条执行路线，但共用同一个候选批次和用户选择合同：

1. `API`：通过 `ImageGenerationService` 调用，供应商参数来自 `config/adapters/image-generation/openai-compatible.json` 与环境变量。
2. `外部生成`：导出同一个已批准条件构造的单图 Prompt；用户自行筛选后回传。若用户已明确表示该图是选定结果，系统校验格式、最短边和可解码性，复制到项目目录、记录 SHA-256 并直接登记用户选择，不再要求候选编号或二次确认。不得把仅有 URL 的结果登记为资产。

API 环境变量：

```text
IMAGE_API_BASE_URL
IMAGE_API_TOKEN
IMAGE_API_TEXT_MODEL
IMAGE_API_REFERENCE_MODEL
```

每个候选产物先进入 `AWAITING_USER`。替换文件、上游版本变化或用户拒绝都会使对应选择及下游失效。

```bash
python3 scripts/casting_workflow.py validate-casting-brief casting-brief-C01.json unit-plan.json
python3 scripts/casting_workflow.py export-prompt casting-brief-C01.json unit-plan.json project-ledger.json casting/C01/actor-prompt-v1.md --project-root .
python3 scripts/casting_workflow.py import-candidates casting-brief-C01.json unit-plan.json project-ledger.json casting/C01/candidate-batch-v1.json casting/C01/candidates actor-01.png actor-02.png actor-03.png actor-04.png --project-root .
python3 scripts/casting_workflow.py generate casting-brief-C01.json unit-plan.json project-ledger.json casting/casting-C01.json casting/C01 --project-root . --count 4
python3 scripts/casting_workflow.py select casting/casting-C01.json candidate-03 project-ledger.json reviews/review-ledger.jsonl review-actor-C01-v1 "选择第三位演员" --project-root .
python3 scripts/visual_workflow.py generate costume-structure costume.json project-ledger.json batches/costume-structure.json images/costume-structure --project-root .
python3 scripts/visual_workflow.py export-prompt look-component look.json project-ledger.json prompts/look.md --project-root .
python3 scripts/visual_workflow.py import-candidates look-component look.json project-ledger.json batches/look.json images/look look-01.png look-02.png --project-root .
python3 scripts/visual_workflow.py generate character-fusion fusion.json project-ledger.json batches/fusion.json images/fusion --project-root .
python3 scripts/visual_workflow.py generate character-four-view four-view.json project-ledger.json batches/four-view.json images/four-view --project-root .
python3 scripts/visual_workflow.py generate scene-master scene.json project-ledger.json batches/scene.json images/scene --project-root .
```
