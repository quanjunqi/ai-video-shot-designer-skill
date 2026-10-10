# MiniMax H3 输出与投递规范

本规范只适用于已确认目标模型为 MiniMax H3 的项目。先按 [执行目标](../production/execution.md) 区分直接模型和 API；不能默认使用 AutoDL。每个生成单元输出人类可读设置与一个六字段核心块，但外围上传清单和块内绑定写法随投递路径改变。

## 0. 投递路由

### Direct

`prompt_contract=minimax-h3-direct-v1`：用户直接把素材和 Prompt 交给 MiniMax H3 模型界面。生成设置顶部必须列出严格上传顺序：

```text
执行目标：直接模型 / MiniMax H3
素材上传顺序：
1. <Subject 1> / character-fang-v1 / 角色身份与服装
2. <Subject 2> / scene-control-room-v1 / 场景结构与光线
```

六字段中使用标签指代素材，但不得出现 `ref_image_N`、`ref_audio_N`、AutoDL 名称、工作流 ID、API 分辨率枚举或 10000 字符适配器限制。

### AutoDL API

`prompt_contract=autodl-minimax-h3-v1`：使用 AutoDL Art `minimax_h3_zm_u24`。生成设置顶部同时列出稳定上传顺序和 API 映射：

```text
执行目标：API / AutoDL Art / MiniMax H3 / minimax_h3_zm_u24
素材上传顺序：
1. ref_image_0 -> <Subject 1> / character-fang-v1 / 角色身份与服装
2. ref_image_1 -> <Subject 2> / scene-control-room-v1 / 场景结构与光线
```

数组中的第一个图片资产映射 `ref_image_0`，第二个映射 `ref_image_1`；音频在自己的序列中从 `ref_audio_0` 开始。映射必须与 manifest `input_bindings`、API payload 和 `subject_definitions` 完全一致。

Seedance 2.5 直接模型使用独立的 [Seedance 2.5 Prompt 契约](seedance-2.5-direct.md)，不使用本规范。Seedance API 与其他未知 API 尚未实现，只能输出规划稿。

## 1. 中文生成设置

```text
生成单元：<unit_id>
全片时间线：<起止>
本段时间线：<起止，不超过15秒>
镜头卡：<shot_id列表>
连续性输入：<结构化首态或上一段实际尾帧>
连续性输出：<计划稳定尾态；生成后才可登记实际尾帧>
光影锚点（机器校验）：<主光位/色温/光质/受光面/阴影落点/曝光>
生成素材：<本段实际使用的canonical资产、按需构图图、实际尾帧和视频参考>
参考图选择：
必选：<标签与唯一用途；无则写无>
可选：<标签与增强用途；无则写无>
禁止混用：<标签与冲突原因；无则写无>
```

复杂动作按 [生成单元合同](../production/units.md) 增加机器可读状态锚点。镜头卡可投影为导演可读文字摘要，但结构化 `shot_card` 才是事实源。

## 2. 六字段代码块

字段名与顺序固定：

```text
subject_definitions:
...

summary:
[reference generation] ...

retention_analysis:
...

detailed_description:
...

overall_soundscape:
...

non_diegetic_music:
...
```

### subject_definitions

只定义本单元实际使用和追踪的 `<Subject N>`、`<Picture N>`、`<Video N>`、`<Audio N>`。canonical 角色/场景/道具资产按真实用途绑定；`<Picture N>` 只用于按需构图参考或实际尾帧。导演总版、故事板、俯视规划图不得定义为标签。

`subject_definitions` 中的 `approved` 是资产状态声明，不是修辞。只有已登记且由用户明确确认的资产可以称为 approved。尚未由用户确认资产的规划测试必须同时提供对应资产图片 Prompt，将标签明确写成 `planned placeholder`，并在文件和定义中声明 `do not submit`；不得让干运行稿看起来像已经具备真实参考图的可提交 Prompt。

通过 AutoDL Art 上传参考图或音频时，绑定必须出现在实际发送的六字段内部：每个 `ref_image_N` / `ref_audio_N` 在一个且仅一个 H3 标签定义中出现。直接模型路径只写标签与资产含义，不写这些 API 字段。canonical 资产使用 `<Subject N>`，actual tailframe 和按需构图图使用 `<Picture N>`，音频使用 `<Audio N>`。

### summary

以与实际输入匹配的适配任务前缀开头，写明全片时间范围、本单元范围、叙事任务与相邻单元关系。只引用已定义标签，不把估算时长写成用户明确要求。

### retention_analysis

逐项列出引用标签出现在哪些镜头及其保留关系。可见内容使用 `fully_preserved`、`partially_preserved`、`attribute_transfer`、`weak_reference`；音频使用 `fully_copy`、`partially_copy`、`reference`、`weak_reference`。

### detailed_description

使用英文，按播放顺序将每张 shot card 转译为一个独立 `[Shot N]` 自然段。每镜必须包含：

先按以下优先级分配 Prompt 字符，不以接近任何平台上限为目标；只有 AutoDL 路径受其适配器字符合同约束：

1. **本镜主任务与结果**：本镜必须让观众看清什么，以及镜尾达到什么可见状态。
2. **动作因果与时间**：动作主体、手别、接触顺序、道具状态变化、接收关系和真实完成时间。
3. **连续性与空间**：人物位置、方向、轴线、唯一性和上一镜已发生且仍生效的后态。
4. **摄影执行**：景别、机位、焦点、必要运镜及有叙事作用的切点。
5. **全局视觉与异常防护**：只保留本镜确有漂移风险的控制项。

同一事实只在最合适的层级定义一次：身份与永久外观放 `subject_definitions`，全片风格和共同画面规则放 `summary`，逐镜变化放 `detailed_description`，声音放 `overall_soundscape`。逐镜不得重复完整角色穿着、完整房间清单、完整风格串或与本镜无关的禁物枚举。连续性后态按下述要求重申，但应写成紧邻动作的正向结果，不把过去失败案例逐条拼进每个镜头。若字符接近适配器上限，先删修辞、同义重复、无叙事作用的材质/镜头参数和已在上层锁定的静态事实；不得压缩关键动作链、可读文字、台词、空间关系、切点或稳定尾态。

语言库的专业能力必须在最终执行语言中可见：若镜头卡选择了有公认名称的电影手法，H3 应保留对应标准英文术语，并在同句或紧邻句展开具体执行。内部策略 ID 不输出。不能把 `reaction close-up`、`eyeline match`、`match on action`、`rack focus`、`dolly in` 等有效术语全部抹平成泛化的 `camera shows`，也不能只堆术语而缺少人物、触发、方向、路径、停止点和尾态。

- 单元内递增的 `At MM:SS.mmm`。
- 视觉任务、景别、视角、角度、机位、焦距透视和构图。每个 `[Shot N]` 使用明确的英文标准景别短语，如 `wide shot`、`medium shot`、`medium close-up shot`、`close-up shot` 或 `insert shot`，并显式写出 `camera` 的固定或运动状态；不要只用 `view/frame/insert` 等上下文隐含景别和机位。
- 人物/道具起点、连续动作链、关键接触和终点状态。
- 状态变化后的每个后续 `[Shot N]` 都要重申仍然生效的持有者、手别、数量、接触边界或位置后态；不能只在状态变化发生的镜头写一次。
- 最后一镜必须把下一单元需要作为视觉输入的关键状态保持在可辨尺度直到生成结束。小道具特写后不得再切到道具不可辨的远景来充当“验证镜头”。
- 摄影机起始、跟随、触发变化、完整动力学和结束动势。
- 对焦、景深、光影、可见空间锚点与禁止揭示内容。
- 台词、同步物理声及进入下一镜的切点。
- v2.2 每个 `[Shot N]` 使用 coverage plan 批准的唯一 `camera_id` 所对应机位事实；按 `shot_order` 顺序写最终视角。切镜必须兑现 cut contract 的触发、前镜输出动势、后镜进入动势和屏幕方向。不要把多机位写成同时拍摄、分屏或画内出现摄影机。
- 禁止内容优先改写为目标正态和允许集合，例如“墙面严格保持 canonical 参考中的空白状态”“只出现已定义五项主体”。不要在正向 Prompt 中反复枚举颜色鲜明、形态具体的禁用物体；若模型生成了被枚举的禁物，先按负向概念泄漏处理，删除具体名称并强化目标正态。声音事件若不应产生画面响应，明确写为 `audible-only` 并只在声音层描述。
- 没有获授权画内文字时，正向定义“干净摄影母版”：对白只改变音轨，每一帧只呈现摄影机拍到的场景、人物和道具，画面边缘及下部安全区保持场景本身。不要靠枚举具体文字污染类型来控制。
- 显示面按 canonical 的材质、自发光、亮度、颜色和反射状态锁定；“不可读”不能替代暗屏或指定界面状态。
- 没有授权灯光变化时，逐镜继承同一手动曝光、白平衡、灯具输出、黑位、对比度、tone mapping 与全片调色；尾部稳定区不得自动改变。
- 硬切必须描述切前末帧与切后首帧的可辨构图差异，并明确离散画面替换；不能让连续推拉或变焦冒充切镜。
- 角色外观使用封闭允许集合，除脸、发型和服装颜色外，还要锁定衣面已有的接缝、口袋、反光条、徽章、文字、色块和配饰；未获授权的附加标记不得出现。

不得加入 `Visual:`、`Action:`、`Camera:` 等自定义字段，不得补写 Script IR 中没有且未授权的事件。动态镜头必须兑现运动目标、空间路线、一个主要运动变化、2 至 3 个物理反馈和余势。

台词按 Script IR 的 `DLG` 原文写成 `<d>[Language]原文</d>`，不翻译、不改写。画面文字按 `object_intrinsic / dynamic_state / editorial / non_narrative_unreadable` 分类执行，不包装成对白。闪回必须写主时间线锚点、单元局部时间码、声音桥和回切点。

### overall_soundscape

用 1 至 4 句英文概括环境声、物理动作声和非语言人声，不重复对白。无环境声写 `N/A`。

### non_diegetic_music

用 1 至 3 句英文描述角色听不到的配乐。无配乐写 `N/A`；画内音乐放在 `detailed_description`。

## 3. 事实与投影

- H3 内容必须能回溯到 shot card、EV/DLG/LOCK、scene map 和 continuity。
- H3 发现遗漏时回改转译；若镜头事实本身不足，先回改 shot card，再重新派生 H3。
- 导演总版可以和 H3 并排人工审阅，但不能从图片自动恢复或修补 Prompt。
- 生成视频前的尾态只能称为计划状态。实际尾帧必须从生成视频截取并登记来源。
- H3 修改了镜头数量、顺序、时长、构图或动作时，必须先同步 shot card、unit plan 与 manifest，再重新运行校验；聊天中的临时 Prompt 不得绕过事实链直接送入生成。

## 4. 最终交付

每个单元只交付与已确认目标一致的一套稿件：生成设置、有序素材清单、导演语言落点和唯一六字段 Prompt。未通过当前版本资产、空间、镜头和 Prompt 审核时，标记为不可提交，不提供看似可直接生成的混合稿。

## 5. Adapter 边界

机器执行值以 `config/adapters/minimax-h3-direct.json` 与 `config/adapters/autodl-minimax-h3.json` 为权威。当前项目合同：单元时长为 1-15 秒；AutoDL 另有 1-10000 字符、分辨率枚举和媒体数量限制。10000 字符不是已核实的 MiniMax 官方上下文上限，不得外推到直接模型。

Direct 路径显示“第 N 个素材”并禁止 `ref_image_N/ref_audio_N`、工作流 ID 和 AutoDL 分辨率。AutoDL 路径按 `input_bindings.order` 分别映射图片和音频的零基字段，并在实际 `subject_definitions` 中唯一绑定。所有限制和能力从 Adapter 配置读取，不从本文硬编码。

内部状态、scene map 坐标、策略 ID、审核台账和 API 元数据不进入六字段。摄影、构图、调度、剪辑与表演术语可以进入，但必须展开为可观察的主体、触发、方向、路径、时机和尾态。

v3 共同创作流程可在上游需求已批准且图片 API 已配置时生成演员、定妆、融合角色和场景候选；每批候选仍须用户选择。v2 资产路径默认先交付 canonical/状态资产 Prompt、用途、来源和用户核对清单。资产确认后，再交付镜头卡摘要、执行目标、严格素材顺序、生成设置和独立 H3 Prompt。H3 前附紧凑的“导演语言落点”，逐镜列出最终使用的标准专业术语及叙事作用。Direct 与 AutoDL 只能输出用户选定的一套格式。导演总版仅在用户要求人工视觉审阅时附加；默认没有分镜位图。
