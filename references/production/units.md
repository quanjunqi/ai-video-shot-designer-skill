# 剧情容量与生成单元规划

本文件统一负责把锁定剧本先划分为 `PLANNED` 初步生成任务，再在镜头和剪辑方案通过后编译为 `EXECUTABLE` 单元，并维护镜头内、镜头间和跨单元连续性。生成单元不是分镜：一个单元可包含一个或多个镜头；分段由剧情因果、自然表演时长和目标 Adapter 容量共同决定，不由故事板格数、页面排版或图片模型能力决定。

## 0. 两阶段单元

`PLANNED` 阶段面向用户展示每段到底拍摄哪些锁定剧本条目，并登记 `entry_state/exit_state/handoff/boundary_reason`。此时不得声称镜头数量、构图或剪辑已经锁定，用户可明确批准，也可 `continue_provisionally` 让 AI 继续准备；暂定继续不形成 `USER_APPROVED`。

`EXECUTABLE` 阶段只能在每个单元的 `shot_plan` 与 `editorial_plan` 都获批后编译，必须完整保留初步方案中的剧本覆盖和顺序，并增加 `shot_ids/duration_seconds/planned_exit_state`。只有该阶段完成后才能确认资产和模型 Prompt。

叙事结构库只用于诊断，不是改写模板。可以标记钩子、信息释放、静默节拍、升级、倒计时、平行线或情绪方向，帮助确定 beat 边界与镜头职责；不得为了套入类型模板而新增、删除或重排 `EV/DLG/LOCK`。v3 需要改变内容时，由用户提交新的完整剧本版本。

## 1. 先建立时长预算

Script IR 的 `project.duration_budget` 必须区分用户目标、忠实呈现下限和最终计划：

```json
{
  "target_seconds": 24.0,
  "target_source": "user | estimated",
  "faithful_min_seconds": 28.0,
  "final_planned_seconds": 28.0,
  "breakdown": {
    "dialogue": 10.0,
    "action": 7.0,
    "pause_reaction": 6.0,
    "movement_camera": 5.0
  },
  "resolution": "fits | extended_to_faithful",
  "authorized_change_ids": []
}
```

- `dialogue` 使用自然语速并包含台词前后的必要呼吸，不用异常加速压缩。
- `action` 包含起势、关键接触、动作结果和可辨认的稳定落点。
- `pause_reaction` 只保留理解剧情所需的停顿、倾听和反应，不添加新剧情。
- `movement_camera` 包含必要走位、空间建立和摄影机到达可用落点的时间。
- 用户目标低于忠实下限时只能延长最终时长或增加单元；不能静默删台词、删结果或压缩动作因果。用户确需改剧本时，锁定新的完整剧本版本后重新规划。

## 2. 单元边界

优先在以下位置结束单元：

1. 一个局部目标、一轮对话或一条因果已经落地；
2. 道具交接、命中、落地、开门、离场等结果已经形成可验证状态；
3. 情绪方向发生明确转折；
4. 摄影机和主体到达可恢复的稳定落点；
5. 对白、呼吸、环境声或动作尾音可以自然桥接下一单元；
6. 继续塞入内容会超过平台时长或显著提高身份、手部、道具、空间漂移风险。

不得在一句台词中间、关键接触尚未完成、持有者尚未确定或动作结果尚不可验证时切段。高风险动作可以在下一单元开头短暂复现，但不能用重叠掩盖未定义的结束状态。

## 3. 单元结构

每个可执行 unit 必须登记：

```json
{
  "beat_ids": ["B1", "B2"],
  "narrative_range": {
    "start_beat_id": "B1",
    "end_beat_id": "B2",
    "summary": "本单元完成的剧情结果"
  },
  "generation_duration_seconds": 12,
  "shooting_form": "multi_shot | one_take",
  "boundary": {
    "entry_reason": "从何种可验证状态开始",
    "exit_reason": "为何在此结束",
    "exit_state_recoverable": true,
    "unresolved_causality": []
  },
  "capacity": {
    "dialogue_seconds": 4.0,
    "observable_beat_count": 2,
    "beats_per_10_seconds": 1.67,
    "max_simultaneous_action_lanes": 1,
    "key_contact_count": 1,
    "prop_state_change_count": 1,
    "character_position_change_count": 0,
    "cut_count": 1,
    "precision_risks": ["right-hand pen grip", "signature-field placement"],
    "physical_action_density": 1.67,
    "execution_risk": "medium",
    "rationale": "当前镜头数、时长和复杂度为何可生成"
  }
}
```

`generation_duration_seconds` 由已确认目标的 `config/adapters/*.json` 决定。当前 MiniMax H3 为 1—15 整数：AutoDL 路径是已验证的 API 合同，直接模型是项目兼容策略；Seedance 2.5 直接模型为用户提供的 4—30 秒契约，均不冒充未核实的官方模型上限。逐镜内部时间码可以保留小数。`beat_ids` 必须等于本单元镜头实际覆盖 beat 的并集。`beats_per_10_seconds = observable_beat_count * 10 / generation_duration_seconds`；`physical_action_density = (key_contact_count + prop_state_change_count + character_position_change_count) * 10 / generation_duration_seconds`；`cut_count = shot 数量 - 1`。`precision_risks` 单独记录手别、持有者、数量、文字落位、朝向等精度风险，不能用主观“动作密度高”代替。

容量计数不是自由填写的自评值。校验器会从本单元真实 shot cards 推导可证明的下限：`key_contacts` 项数决定 `key_contact_count` 下限；`spatial_route` 的实际位移决定人物位置变化下限；结构化 `prop_states` 首尾差异决定道具状态变化下限；若镜头登记 `action_lanes`，其最大并行数量决定 `max_simultaneous_action_lanes` 下限。填写值可以高于可推导下限以覆盖未结构化但真实存在的动作，不能低于下限来伪装低风险。`observable_beat_count`、`cut_count` 与两项密度公式仍由实际 beat、shot 和计数精确核对。

## 4. 多镜头与一镜到底

- `multi_shot`：每次切镜都必须带来新的信息任务、观察对象、空间关系、动作阶段或情绪主动权；只换景别不构成切镜理由。
- `one_take`：所有 shot card 代表同一路径中的连续阶段，不得暗示硬切、机位瞬移、轴线重置或速度归零。摄影机路径必须位于 scene map 的可达区域。
- 用户指定拍摄形式但与空间或容量冲突时，保留剧本事实，调整拍摄形式或拆单元，并记录理由。

## 5. 容量判断

每个单元同时检查：

- 不超过当前目标 Adapter 的单元时长上限；
- 所有镜头时长可落入单元时间范围，且总和不超过生成时长；
- 每镜只有一个主要视觉任务，但允许一条相互驱动的连续动作链；
- 台词、动作结果、关键反应和声音落点有足够时间；
- 多人、手部、道具交接、快速位移或复杂遮挡达到高风险时主动缩短单元；
- 不使用任何故事板格数作为容量依据。

## 6. 单元状态合同

每个单元记录 `continuity_in/continuity_out/state_diff/handoff_frame/generation_inputs/continuity_mode/generation_duration/overlap_duration/usable_duration/audio_handoff`。面向用户显示中文名称；这些字段属于生成设置，不进入模型 Prompt。

复杂动作或连续性诊断使用强状态锚点：

```text
状态锚点（机器校验）：
首帧：场景=车间；[人物]位置=画面左；[道具]持有者=人物
尾帧：场景=车间；[人物]位置=门边；[道具]持有者=桌面
变化：[人物]位置 画面左->门边；[道具]持有者 人物->桌面
转换类型：none
跨段重置：无
```

受控槽覆盖场景、时间、天气、主光、机位轴、画幅，以及实体的位置、朝向、持有者、手别、可见、服装、伤势、状态、发声方、文字状态和音频状态。首尾差异必须在变化中精确登记；跨段重置只列剧本允许改变的槽。运行 `scripts/check_continuity.py` 做段内三态与段间 diff。

## 7. 镜头衔接

相邻镜头默认最多跨越两个景别层级：

```text
大远景 -> 远景 -> 全景 -> 中全景 -> 中景 -> 中近景 -> 近景 -> 特写 -> 大特写
```

更大跨越需要有明确冲击、惊吓、喜剧或主观动机，或者增加承担空间、反应、道具或运动承接职责的镜头。景别变化不能同时无因改变摄影机侧、视线方向和主光方向。

每镜维护 `subject_screen_side`、`eyeline_direction`、`look_at_target`、`camera_side_of_axis` 和 `perspective`。越轴前必须使用中性正面、环绕或跟随运动完成空间交代。

镜头交接记录：

```text
shot_handoff_in: 构图、位置、视线、透视、光线和动作起点
shot_handoff_out: 构图、位置、视线、透视、光线和动作终点
shot_transition: 摄影机运动、承接方向和下一镜进入方式
```

`shot_transition` 必须描述可执行动作，不得只写“自然过渡”。人物移动、交手、跌倒、起身、转身和道具交接后都要更新交接状态。

## 8. 跨单元连续性

动作交接使用“上一镜终点 -> 下一镜起点 -> 运动方向 -> 速度 -> 道具状态 -> 新落点”。声音单独记录 `audio_handoff`，覆盖对白完整性、呼吸、脚步、冲击声、环境底噪和配乐位置；对白或爆发音不能在切点截断。

连续性优先级：已接受视频的 actual tailframe/actual exit state > 已确认 canonical 资产 > 计划 continuity 状态文字 > 风格形容词。规划尾态不是 actual tailframe；只有从用户接受的视频按时间码提取并绑定视频、文件哈希和帧哈希后，才可成为下一单元输入。生成失败、待审核或被拒绝的视频不能覆盖计划尾态。

连续事件默认要求下一单元 `continuity_in` 与上一单元 `continuity_out` 逐项相等。`flashback/independent_start` 可以独立开始；`continuous_space/hard_location_cut/time_jump` 仍需解释人物和道具如何承接。高速动作可以规划少量重叠，但不能超过目标 Adapter 的单元上限。

失败诊断顺序：actual tailframe -> 角色/场景/道具版本 -> 状态锚点 -> 空间与镜头事实 -> Prompt 表述。不得默认把所有失败都退回 Prompt。

## 9. 用户可读拍摄稿

单元拍摄稿或镜头摘要只回答覆盖范围、单元目标、连续性、每镜主视觉任务、调度、摄影、动作链、切镜原因和参考资产。它由 Script IR 与已锁定 shot cards 派生，不是新的事实源，不进入模型输入，也不能按版面格数反向决定镜头数量。

- 时长估算错误：回到 `SCRIPT_LOCKED`，重新规划受影响 beat 和 unit。
- 分界错误但剧本事实正确：回到 `UNITS_READY` 前，重排受影响 unit、continuity 和 H3。
- 拍摄形式不可实现：保留 EV/DLG/LOCK，重新设计受影响 shot cards 和 unit。
- 生成视频偏差：先判断事实是否充分；事实充分则优化转译或重生成，事实不足才回改对应事实层。
