# 镜头规划合同

本文件统一定义场景导演意图、覆盖计划、设计模式、策略选择和 `shot_card`。`shot_card` 是镜头级唯一生产事实源；导演总版和 Prompt 都从它派生，不能反向覆盖它。

初步生成单元不是镜头表。镜头方案在场景空间、走位和机位运动获批后建立；每个单元同时提交 `shot_plan` 与 `editorial_plan`，后者明确镜头顺序、切点逻辑、声桥、屏幕文字时机和向下一单元的交付。二者都由用户确认后，才可编译可执行单元。

表演重点属于镜头与表演指导，不属于选角客观条件。演员是否需要完成某类肢体动作可作为角色分析事实，但不得把“疲惫、焦虑、克制”等剧情状态烘焙进中性演员基准。

```text
Script IR + scene_map -> scene direction -> coverage plan -> shot_card -> unit Prompt
```

## 1. 场景导演意图

每场 `scene_direction_briefs[]` 记录：`scene_id`、`dramatic_objective`、`viewpoint_character`、`opening_state`、`turning_point`、`information_release`、`performance_arc`、`spatial_arc`、`camera_principle`、`coverage_principle`、`cutting_principle`、`closing_image`。

这些字段只解释已锁定的 `EV/DLG/LOCK`，不得增加人物、道具、台词、事件或改变结果。没有主观人物时，`viewpoint_character` 写“客观观察”。

## 2. 覆盖计划

每场主动选择一种覆盖模式并记录 `selection_reason`：

- `single-shot`：一个固定或极简镜头足以完成信息与表演。
- `long-take`：连续空间和动作链从不中断观察中获益。
- `multi-camera-coverage`：关系、反应、证据或信息释放需要多个最终视角。
- `action-montage`：高速或大规模动作需要规模、推进、接触和结果分工。

复杂不等于专业。没有触发、信息增益或节奏价值的视角应删除。

`coverage_plans[]` 包含 `scene_id`、`coverage_mode`、`selection_reason`、`visual_beats`、`camera_assignments`、`shot_order`、`coverage_strategies`、`cut_contracts`。覆盖策略从 `config/directing/coverage-strategies.json` 选择，不占逐镜策略名额。

每个 `camera_assignments[]` 至少包含：`camera_id`、主/次职责、位置、方向、景别、主体、可见锚点、禁止内容、进出切点触发和输入/输出动作状态。职责只能取：

```text
scale | relationship | viewpoint | immersive-follow | reaction
action-proof | prop-proof | reveal | transition | result
```

机位位置、方向和可见锚点必须与同场 `scene_map` 完全一致。

每对相邻最终镜头有且只有一个 `cut_contracts[]`：

```json
{
  "from_shot_id": "S1-01",
  "to_shot_id": "S1-02",
  "cut_trigger": "右脚落地",
  "outgoing_motion": "前镜 action_states.end 原文",
  "incoming_motion": "后镜 action_states.start 原文",
  "screen_direction": "人物保持由左向右",
  "prop_state_before": {},
  "prop_state_after": {},
  "cut_reason": "由关系建立切到手部交接证据"
}
```

出入动作状态必须与相邻镜头卡逐字一致，切点不重置人物位置、道具持有、手别、视线或屏幕方向。`long-take` 只能有一个最终镜头，并通过连续空间、可通行路线、单一主动作链、受控主体数量、构图落点和稳定尾态门禁。`action-montage` 至少包含三个不同信息任务并保留结果镜头。

## 3. 设计模式

每个 beat 在写镜头卡前选择 `drama`、`dynamic` 或 `mixed`。模式只改变设计重点，不改变统一合同。

### Drama

用于对话、观察、犹豫、关系变化、信息揭示和情绪反应：

1. 写清观众此刻必须看谁、理解什么、暂时不能看到什么。
2. 把表演写成连续动作链：视线、呼吸、停顿、手部、身体转向和台词落点。
3. 摄影机写成 `start -> follow -> change_trigger -> end_momentum`；保持固定也要说明职责。
4. 只有视角、信息、关系或节奏变化无法由当前镜头完成时才切镜。
5. 用位置、视线、构图重心、声音或情绪速度承接下一镜。

泛情绪必须转成可观察变化。微表演只能细化剧本已有情绪，不能新增哭泣、敌意、亲密等人物态度。普通短镜保留 1 至 4 个 `performance_beats`，每项绑定可见触发、身体/视线/呼吸反应和时段，并通过 `basis + basis_ref + rationale` 引用镜头卡的五类 `performance_provenance`。`script_fact` 的可见反应必须逐字使用剧本已有动作，例如“肩膀微微颤抖”不能改写成流泪；额外表现只能登记为 `director_recommendation` 并随镜头方案由用户确认，未决表演不得进入镜头卡或 Prompt。

熟悉动作也要推演主辅手、前置条件、接触受力、语义结果、工具落点和真人时长。可读纸张、屏幕或地图还要锁定正反面、阅读方向与逐字内容；动作链超出时长时延长镜头或增加单元，不能机械加速。

### Dynamic

用于追逐、打斗、坠落、车辆、复杂交接和多人高速调度。每镜只承担一个主要运动变化，并明确运动目标、空间路线、关键接触、2 至 3 个可见物理反馈和余势。路线必须通过 `scene_map` 的边界、可通行区和禁区检查。

战斗拆成意图、起动、接触、反作用、失衡/位移和恢复；接触关系、身体方向、力的来源和结果必须闭环。摄影机首先让动作可读，再决定沉浸感，不能穿墙、穿人或无因改变轴线。

### Mixed

用于表演触发运动或运动结果转入情绪反应。明确转折触发点，前后分别服从 Drama 与 Dynamic 规则，不在一个短镜中堆叠多个高潮。

## 4. 策略选择

逐镜策略只从 `config/directing/shot-strategies.json` 选择。没有明确问题时使用空数组；非空时恰好一个 `primary`，最多一个不同类别且兼容的 `secondary`。

```json
{
  "strategy_id": "BLK-DEPTH",
  "role": "primary",
  "goal": "让前景与后景人物关系可读",
  "prerequisites_met": ["scene map 已有前后景锚点"],
  "h3_translation": "具体到主体、方向和时机的执行句",
  "contraindications_checked": ["不与既定动作轴冲突"]
}
```

策略必须落实到 `staging/composition/movement/performance_beats/action_chain`。Prompt 不输出 `COV-* / CAM-* / BLK-* / CMP-* / PERF-* / CBT-*` 等内部 ID；可保留 `master shot`、`reaction close-up`、`eyeline match`、`match on action`、`rack focus`、`dolly in` 等标准电影术语，但要同时写明主体、触发、方向、路径、时机和尾态。

## 5. Shot Card

每张镜头卡至少回答：拍什么、人物和道具在哪里、摄影机如何观察、动作怎样发生、为何切镜、向下一镜交付什么状态。

```json
{
  "design_mode": "drama | dynamic | mixed",
  "purpose": "本镜唯一叙事职责",
  "visual_task": "观众必须看清或暂时不知道的内容",
  "strategy_selection": [],
  "staging": {
    "actors": {},
    "props": {},
    "occlusion": "关键遮挡关系"
  },
  "camera": {
    "position": {"x": 0, "y": 0},
    "axis_side": "动作轴侧别",
    "viewpoint": "客观/主观/过肩等",
    "angle": "角度",
    "shot_size": "景别",
    "lens": {"mm": 50, "perspective": "透视效果", "narrative_use": "叙事用途"}
  },
  "focus": {"subject": "焦点", "depth_of_field": "景深", "rack_focus": "触发或无"},
  "composition": {
    "foreground": "前景",
    "middle_ground": "中景",
    "background": ["固定锚点"],
    "leading_lines": "引导线",
    "negative_space": "留白",
    "occlusion": "遮挡边界"
  },
  "movement": {
    "type": "固定/推/拉/摇/移/跟/升降/手持",
    "direction": "世界或画面方向",
    "amplitude": "幅度",
    "speed": "速度",
    "easing": "加减速",
    "stability": "稳定方式",
    "stop_position": "结束机位或构图"
  },
  "timing": {
    "start": "单元局部时间码",
    "duration": "持续时间",
    "internal_beats": [],
    "cut_motivation": "切入/切出原因",
    "emotional_velocity": "情绪速度"
  },
  "action_chain": [],
  "performance_beats": [],
  "action_states": {"start": "首态", "process": "过程与接触", "end": "尾态"},
  "prop_states": {},
  "camera_plan": {
    "start": "初态",
    "follow": "响应方式",
    "change_trigger": "可见触发",
    "end_momentum": "结束动势"
  },
  "cut_necessity": "保留、合并或切镜理由",
  "next_shot_momentum": "下一镜继承或有意打断的动势",
  "continuity": {"in": "镜头首态", "out": "镜头尾态"},
  "lighting": {"anchor": "光源", "subject_side": "受光面", "shadow": "阴影", "exposure": "曝光"},
  "effects": [],
  "sound": {"dialogue": [], "environment": "环境声", "music": "配乐或N/A"},
  "constraints": {"forbidden_drift": [], "do_not_reveal": []}
}
```

空字段不能用“电影感”“高级感”“镜头跟随”等抽象词占位。无移动时仍写明锁定方式和停止构图。含可见表演的 `drama/mixed` 镜头必须有 1 至 4 个 `performance_beats`；纯环境或不可表演道具插入镜可为空，并由 `visual_task` 说明。

`dynamic/mixed` 还必须包含 `motion_objective`、`spatial_route`、`key_contacts`、`primary_motion_change`、`physical_feedbacks` 和 `residual_motion`。

特效必须绑定剧本已登记的道具、光源或环境事件，记录 `source/trigger/timing/intensity/affected_area/environment_interaction/end_state/visibility_limits`。瞬时效果不能烘焙进 canonical；持续效果要进入后续镜头和单元 continuity。

## 6. 跨层门禁

- 外层稳定 `shot_id/scene_id/unit_id/beat_ids/camera_id` 连接剧本、空间、单元和 Prompt；`camera_id` 必须由 coverage plan 批准。
- `staging`、机位、轴侧、背景锚点和空间路线必须与同场 `scene_map` 一致。
- `continuity.in/out` 必须与单元 continuity ledger 一致；道具易手同时在动作三态与 `prop_states` 闭环。
- 前镜发生的持有、手别、伤势、开关或位置变化必须由后镜继承，直到剧本中的下一次变化。切镜不重置状态。
- `sound.dialogue` 只能逐字引用 `DLG`；动作和视觉事实只能来自 `EV/LOCK`。v3 不允许通过 `authorized_changes` 增加内容。
- 镜头时间必须落在所属单元内，总时长不能超过目标 Adapter 的单元时长。
- 每镜的 `h3_execution_facts` 至少有 `start_state/end_state`；涉及方向、手别、持有、唯一数量或物件朝向时增加对应事实和字面证据。
- 小型连续性关键物必须在单元尾镜保持可辨；其他未进入尾帧的空间状态继续由结构化事实与用户确认的视频承担。

镜头卡变更后重新派生受影响的单元计划、资产选择和 Prompt。不得直接修改 Prompt 的镜头数量、顺序、时长、构图或动作来绕过事实层与台账审核。
