# 锁定剧本与覆盖合同

本合同同时定义 Script IR、源文件锁和生成单元覆盖。下游只引用锁定事实，不改写剧情。

## 导演解读与制作分析

剧本锁定后，AI 必须先提交两份可审核产物，不向用户重复询问“想拍什么故事”：

- `director_analysis:PROJECT`：只依据 `EV/DLG/LOCK` 分析戏剧推进、情绪曲线、人物关系、视觉叙事重点、连续性风险和不确定项。它用于决定表演、声音、镜头节奏与 Prompt 的情绪密度，但不得新增主题、事件或台词。
- `media_implementation_plan:PROJECT`：识别实拍空间、屏幕画面、游戏内画面、字幕/聊天文字、特效、声音和技术风险，说明如何忠实转译为可生成影像。每个 `scene_strategies[]` 必须绑定 `scene_id + script_refs + source_medium + representation_mode + rationale`。游戏内段落必须显式选择 `screen_insert`、`direct_gameplay` 或 `characterized_performance`；选择角色化演绎时写 `approval_required: true`，不能因“游戏内”自动让真人演员进入游戏空间。

导演解读不改变剧本事实，却直接影响后续镜头职责、表演节拍、光线、声音和剪辑，因此必须有；它不是让用户重新解释已经交付的故事。

Script IR 是**内部规划产物和下游事实源**：不直接投喂模型、不默认输出给用户；复杂剧本或需要复核时按此结构整理，用户明确要求时才展示。只记录剧本已有信息，信息不足用最小必要假设并在 `open_questions` 标注，不创造剧情事实。解析完成后必须建立 `EV/DLG/LOCK`，使每个可观察事件、台词原文和不可改写约束都能被镜头卡与真实 H3 定位。

## 1. 标准结构（空白模板）

```text
project:
- title:
- target_language / output_language:        # 剧本语言；六字段结构英文、台词保原语言
- aspect_ratio:                              # 画幅，剧本未给则留待确认/最小假设
- visual_genre_style:                        # 类型与视觉基调
- duration_budget:                           # 详见 ../production/units.md
  - target_seconds / target_source:
  - faithful_min_seconds / final_planned_seconds:
  - breakdown: dialogue / action / pause_reaction / movement_camera
  - resolution / authorized_change_ids:
- estimated_unit_count:                      # 依据忠实时长、台词密度/动作复杂度估算

script_manifest:
- events:                                    # EV：剧本允许发生的可观察事件
  - event_id / beat_id / fact:
- dialogues:                                 # DLG：逐字锁定的对白
  - dialogue_id / beat_id / speaker_id / text / language:
- locks:                                     # LOCK：因果、结果、身份、时空等不可改写项
  - lock_id / target / rule:
- authorized_changes: []                     # v2 兼容字段；v3 永远为空
  - change_id / targets / change / reason / approved_by:

scenes:
- scene_id:
  location / interior_exterior / time:
  weather / ambient_light / key_light_dir:   # 天气、环境光、主光方向
  characters_present: []
  props_present: []

characters:
- character_id:
  name / age_band / identity_anchors:        # 面部识别点、体型
  costume / hairstyle / accessories / injury:# 跨段必须锁定的外观
  voice_language / trait:                    # 声线、所说语言

props:
- prop_id:
  name / material_color_size:
  initial_holder_and_hand / initial_position:
  state_changes: []                          # 仅记录剧本真实发生的易手/开合/损坏

beats:                                        # 按时间排列的动作与事件
- beat_id / scene_id:
  action:                                    # 可观察动作，注明起止与方向
  dialogue:                                  # speaker_id、原文、语言、画内/画外(VO)
  on_screen_text:                            # text_id / text / category / treatment / asset bindings
  flashback:                                 # 是/否；若是记主时间线锚点与回切点
  vfx_special:                               # effect_id / source / trigger / observable_result / persistence

timeline_plan:
- proposed_shots: []                         # 初步景别/机位意向，供导演规划细化
- proposed_units: []                         # 初步分段与切点（切点避开不可恢复关键动作）

open_questions:                              # 信息缺口与最小假设
- <缺失项>：<采用的最小假设 or 需用户确认的问题>
```

## 2. 填写规则

- **只抽取不创作**：外观、时间、道具状态、动作方向必须来自剧本；推断项标注“估算/假设”，并与用户明确指定区分。
- **台词逐字**：`dialogue` 保留原文、原语言与标点，不翻译不改写；画外音标 VO，供后续包成 `<d>[Language]…</d>`。
- **可见文字单列并分类**：物件固有剧情文字用 `object_intrinsic + asset_locked + asset_id`；签名/填写/盖章等状态变化用 `dynamic_state + same_source_states + state_asset_ids`；字幕/片名/编辑型 UI 用 `editorial + post_production`；不承载叙事且明确不可读的显示面用 `non_narrative_unreadable + abstract_layout`。不混进对白，也不把所有屏幕文字一律推给后期。
- **闪回显式标记**：在解析阶段就标出闪回与其主时间线锚点，避免后续时间码覆盖主时间线。
- **特效不是资产外观**：火、烟、火花、闪烁、自发光和环境染色写入 `vfx_special`，至少登记稳定 `effect_id`、来源、触发、可观察结果和是否持续；道具 canonical 只锁本体，镜头卡 `effects` 再负责时间、强度、范围和结束状态。
- **时长估算可追溯**：`duration_budget` 区分用户目标、忠实呈现下限、分项依据和最终计划；目标不足时必须延长。v3 不接受 `authorized_changes`，用户改变内容时提交新的完整剧本版本。具体规则见 [生成单元](../production/units.md)，平台上限读取目标 Adapter 配置。
- **为连续性埋点**：每个道具的初始持有者、每次人物移动与易手都要在 beats 中出现，供 `scene_map` 与 continuity ledger 接续。
- **事件可定位**：每个有可观察动作或状态变化的 beat 至少对应一个 `EV`；一个 EV 可以被多个镜头覆盖，但镜头不能创造不存在的 EV。
- **对白单一来源**：每句对白单独登记 `DLG`，保留说话人、语言、原文和标点。下游只引用 `dialogue_id`，不得从故事板、总版或 H3 反向抄回 Script IR。
- **锁定不可变事实**：关键因果、动作结果、人物身份、时空关系和明确禁止项登记为 `LOCK`。推断的摄影选择不是剧本锁。
- **版本边界明确**：v3 的 `authorized_changes` 只为兼容 v2 Schema 而保留，必须为空。任何内容变化都要求用户提交新的完整剧本版本，并重新锁定源文件与下游覆盖。v2 旧项目继续按其 Manifest 记录历史授权变化。

## 3. 极简结构示例

```text
project:
- title: 信(The Letter)；output_language: 结构英文/台词中文；aspect_ratio: 16:9
- visual_genre_style: 写实、年代夜景、暖黄油灯主光
- duration_budget: target=24s/estimated；faithful_min=24s；final=24s；breakdown=对白9s+动作6s+停顿反应5s+移动摄影4s；resolution=fits；estimated_unit_count: 2
script_manifest:
- events: EV001/B1/陈默从左后景门走向右侧柜台；EV002/B3/信封由陈默右手交至林岚双手
- dialogues: DLG001/B2/C2/“林掌柜，有人让我把这个，亲手交给你。”/Chinese；DLG002/B3/C1/“……他，还说了什么？”/Chinese
- locks: LOCK001/EV002/信封交接结果不得改变；LOCK002/DLG001,DLG002/对白逐字保留
- authorized_changes: []
scenes:
- S1 旧式茶馆内 / interior / night；主光 camera-right 油灯；characters: C1林岚,C2陈默；props: P1信封
characters:
- C1 林岚 女约30 藏青斜襟布衫 低髻 腰挂黄铜钥匙；语言中文
- C2 陈默 男三十余 深色长衫 左肩雨痕；语言中文
props:
- P1 牛皮纸信封 无字；initial: C2右手；state_changes: 单元2 由C2右手交至C1双手
beats:
- B1 C2自左后景门走向右侧柜台
- B2 C2(S1)台词“林掌柜，有人让我把这个，亲手交给你。”
- B3 信封交接 C2右手→C1双手；C1(S2)台词“……他，还说了什么？”
open_questions:
- 剧本未给画幅：按 16:9 最小假设，可按用户要求改
```

## 4. 源文件、覆盖与下游

锁定源文件使用案例内相对路径和 SHA-256。文件变化必须建立新版本；`authorized_changes` 在 v3 必须为空。

`script_manifest.sequence` 按原文顺序列出全部 `EV/DLG`。每个单元的 `script_refs` 必须是其中一个连续区间；按 `unit_order` 拼接后与 `sequence` 完全相等，因此不能遗漏、重复、重排或加入未知内容。

用户可读《单元拍摄稿》由工具确定性渲染：动作逐字读取 `events[].fact`，对白逐字读取 `dialogues[].text`。手工修改拍摄稿或替换文件会因内容与哈希不一致而失效。

```bash
python3 scripts/check_unit_coverage.py unit-plan.json --render-dir units/
python3 scripts/check_unit_coverage.py unit-plan.json --artifact-root project-root/
```

Script IR 完成后，按 [视觉开发](visual-development.md) 建立演员、定妆和场景母版，按 [空间与调度](../planning/spatial.md) 建立空间事实，按 [镜头规划](../planning/shots.md) 建立镜头事实，按 [生成单元](../production/units.md) 维护覆盖与连续性，再按 [资产合同](../production/assets.md) 选择最小输入集并由目标 Adapter 转译 Prompt。默认链路不包含分镜位图。
