# 空间连续性合同

这是所有场面调度对象共用的空间模型。车辆、房间、楼梯、门、家具、武器和其他道具都使用同一套字段；对象类型只增加自己的附加字段。目标是让每个镜头的画面都能从场景布局、对象状态和摄影机位置推导出来。

## 1. 场景模型

每个有调度风险的场景先确认场景功能稿、场景母版和同源视图，再建立一份 `scene_map`。空间系统负责校验已登记几何关系，不宣称从一张透视图自动恢复“完美空间”；无法证明的尺寸、遮挡或连通关系必须显式待确认。先登记固定事实，再登记会移动或改变状态的对象：

```text
scene_id: <稳定连续空间标签>
continuous_space_id: <与 Script IR scenes[].continuous_space_id 一致>
scene_ids: <共享该空间的一个或多个 Script IR 剧情场次 ID>
space_boundary: <真实连续空间边界 polygon 与 boundary_type>
fixed_anchors: <门、柱、窗、出口等及其相对位置>
primary_axis: <主要动作轴>
walkable_zones: <角色和摄影机可通行区域>
objects: <object_id、object_type、position、orientation、state、relations>
camera: <position、side、orientation、visible_anchors>
movement_routes: <人物在相邻 blocking state 之间的可通行折线路径>
persistent_landmarks: <动态场景持续存在的地标、尺寸、可通行性和可见规则>
occupancy_zones: <允许区/禁入区多边形、适用人物与理由>
scale_anchors: <稳定真实尺寸或对象间比例>
```

位置不能只写“画面左/右”。最终 Prompt 可以使用 `camera left/right` 和 `foreground/background`，但内部必须先绑定到固定锚点、对象或动作轴。

`scene_map` 按连续空间建立，不按剧本场次机械复制。同一房间在场次 1-1 和 1-3 再次出现时，两场通过 `scene_ids` 绑定同一个 `continuous_space_id` 和同一份地图；导演意图、coverage plan 与镜头卡仍按各自剧情场次建立。一个剧情场次不能同时绑定两份连续空间图。

`space_boundary` 不能由人物、家具或锚点的坐标外接框推测。`walkable_zones` 每项必须包含稳定 `zone_id + polygon` 并落在真实边界内。当前简洁文字俯视图只渲染矩形连续空间；非矩形空间必须拆成可确认的相邻连续空间，不能用外接矩形冒充真实墙体。

## 2. 对象与关系

所有可辨对象必须先判定身份：

- `story-object`：参与剧情、被角色使用、移动、遮挡或改变状态。
- `fixed-anchor-object`：位置固定，承担空间、路线、遮挡或透视锚点。
- `incidental-object`：仅为不可辨背景细节，不得在后续镜头中被当作可交互对象。

对象至少需要 `object_id`、`object_type`、`position`、`orientation`、`state` 和 `relations`。关系要写清谁使用或接触它、它阻挡什么、它与哪些锚点相邻，以及从哪些机位可见。

对象类型的专用字段只在类型出现时启用：

```text
vehicle: parking_slot, front_direction, driver_side, seats
room: entrances, exits, levels, connected_spaces
door: hinge_side, open_state, passage_direction
stair: bottom_anchor, top_anchor, climb_direction
furniture: usable_sides, blocking_extent
weapon_or_prop: holder, hand, contact_state, facing_surface
```

这些字段是同一合同的扩展，不为每个新对象另写一套连续性规则。

### 动态地标、占用区与比例

`dynamic/mixed` 场景必须额外登记：

```json
{
  "persistent_landmarks": [{
    "anchor_id": "platform_edge",
    "dimensions": {"length_m": 20.0, "height_m": 0.3},
    "traversability": "solid | surface | passable",
    "visibility_policy": "persistent | may_leave_frame",
    "environment_cover_limit": "轮廓与高度始终可辨"
  }],
  "occupancy_zones": [{
    "zone_id": "track_forbidden",
    "polygon": [[-8, 0], [8, 0], [8, 4], [-8, 4]],
    "access": "forbidden",
    "applies_to": ["C1", "C2"],
    "reason": "剧本要求人物留在站台"
  }],
  "scale_anchors": [{
    "anchor_id": "platform_edge",
    "real_size_m": 0.3,
    "comparison": "人物身高约为站台高度的5至6倍"
  }]
}
```

持续地标必须引用已登记的固定锚点或对象。`occupancy_zones` 使用 scene map 同一坐标系；逐镜 blocking state 中适用人物落入禁入区时必须报错。环境效果可以覆盖表面，但不能删除地标、改变其结构或掩盖到无法辨认。尺度锚点只锁真实比例，不要求每个镜头都把地标拍进画面。

## 3. 镜头状态与因果

每个场景把移动对象的逐镜坐标登记在 `blocking_states`，每个机位用 `blocking_state_id` 绑定当前真实调度快照；不能让多个镜头共享一套“代表性人物坐标”。每个镜头同时登记 `start_state`、`beat_states` 和 `end_state`。状态至少包含人物位置、朝向、层次、对象位置和状态、持有者或接触者、摄影机侧、主光方向以及可见固定锚点。

```json
{
  "blocking_states": {
    "dialogue_position": {"objects": {
      "actor_A": {"position": {"x": -2, "y": 3}},
      "actor_B": {"position": {"x": 2, "y": 3}}
    }}
  },
  "camera": {"shot_02": {
    "blocking_state_id": "dialogue_position",
    "screen_positions": {"actor_A": "left", "actor_B": "right"}
  }}
}
```

下一镜头的 `start_state` 必须能从上一镜头的 `end_state` 推导。无法直接推导时，补交代镜头、登记剧本明确的时空切换，或将镜头标记为阻塞并补充空间资料。不能让图片模型自行决定中间发生了什么。

`user_review.state_sequence` 中相邻状态只要人物坐标改变，就必须有对应 `movement_routes[]`，包含 `route_id/object_id/from_state_id/to_state_id/points`。路线首尾必须等于两个状态坐标，整条折线必须位于 `space_boundary` 和可通行区内，且不能穿过适用于该人物的禁入区。

推导链固定为：

```text
固定锚点 → 对象位置/朝向 → 人物与对象关系 → 摄影机位置/观察方向
→ 可见锚点与画面左右 → 动作和遮挡 → 下一镜头状态
```

## 4. 摄影机可达性与视线

摄影机必须登记 `placement=inside/outside/attached`。inside 机位必须同时位于真实边界和可通行区，outside 机位必须位于边界外；attached 机位必须在该机位对象上填写 `attached_to`，并引用 scene map 中已知角色、车辆、道具或固定锚点。机位、角度、景别和焦距必须与场景模型相容：机位不能穿过不可通行对象；镜头看到的固定锚点必须是该位置真实可见的锚点；越轴或换侧时必须登记过渡方式和新的轴线；角色走位不能经过未声明的障碍物或瞬移到下一状态。

“对象右侧”“驾驶室右边”“画面右边”必须标明参照坐标：对象坐标、摄影机坐标或画面坐标。含义未消歧时，相关镜头只能待确认。

## 5. 类型示例

车辆使用通用对象字段，并补充 `parking_slot`、`front_direction`、`driver_side` 和 `seats`。房间补充入口出口，门补充铰链侧和开合状态，楼梯补充上下锚点和攀爬方向，家具补充可用侧和阻挡范围，道具补充持有者、手别和接触状态。新对象沿用同一模型。

如果车辆是角色乘坐的 `story-object`，还必须记录角色座位、方向盘位置、车门和车窗外可见锚点。场景图中的车辆没有这些信息时，不能自动认定为角色车辆，依赖该车的车内镜头必须阻塞。

## 6. 资产与交付门禁

scene map 是空间关系的唯一事实源；canonical 场景空镜只锁空间外观，shot card 负责镜头顺序、调度与构图决定，按需单镜构图图只提供目标模型要求的单帧条件，实际尾帧负责已经生成的真实状态。导演总版若存在，只是从 shot cards 派生的审阅投影，不承担空间或调度事实。

任何对象的身份、位置、朝向、状态、人物关系、摄影机位置或可见锚点无法证明时，相关派生图只能标记为“待视觉确认”或“失败”，不得进入视频模型。

## 7. 用户场景空间确认稿

每个连续空间从同一 `scene_map` 依次派生两份面向用户的确认稿。先确认布局与走位，此时 `user_review.review_phase` 写 `layout`，`camera` 可以是空对象，不得为通过校验而伪造机位：

```bash
python3 scripts/render_blocking_map_text.py scene_map.json reviews/scene-map-text.md
```

布局确认后完成 coverage plan，把 `review_phase` 改为 `camera_plan`，将获批机位写回同一 `scene_map.camera`，再派生覆盖机位确认稿；此时 camera 不得为空：

```bash
python3 scripts/render_blocking_map_text.py scene_map.json reviews/camera-plan-text.md --review-type camera_plan
```

两份确认稿都必须直接从同一 `scene_map` 生成，不允许手写第二套空间。布局稿包含空间骨架、人物与关键物件、走位变化、无机位俯视图和必须保持项；机位稿在同一骨架上加入 `C1↑/C2↙`、位置、方向和拍摄目标。俯视图必须画出真实边界和门，外部机位必须位于边界外。不得展示坐标、内部 shot ID、签名、状态编号或路线表。

确认粒度固定为“连续空间版本”，不是每镜或每生成单元：

- 首次解析后，一次汇总所有连续空间地图给用户确认。
- 同一空间内的镜头和单元只引用 blocking state ID，不重复确认。
- 新房间、楼层、车辆内部或独立区域建立新的空间地图。
- 布局、门/墙/障碍导致的通行边界、人物/道具路线、交接位置或最终落点变化，标记 `change_class=material`，必须生成新版本并重新由用户确认。
- 用户可见机位的位置、朝向或拍摄目标变化只使 `camera_plan` 确认失效，不要求重新确认未变化的布局。布局、路线、边界或落点变化会同时使两类下游确认失效。

多人调度按可辨职责分级：

- 2-4 名主要人物：逐人记录起点、每阶段位置、朝向、路线、交互和尾态。
- 5-8 名可辨人物：主要人物逐人记录；次要人物按稳定小组和 occupancy zone 记录。
- 大规模群众：只逐人跟踪剧情角色，群众按区域、密度、总体流向和禁入边界管理。
- 每阶段明确当前行动者、交互双方和必须原地保持者；多人路线交叉时拆成连续状态，不把并发箭头挤在一张图里。

v2.2 manifest 用 `spatial_reviews.review_type` 区分 `layout` 与 `camera_plan`。布局签名只覆盖边界、锚点、对象、路线和落点；机位签名由布局签名加 camera facts 构成。进入 `SPACE_READY` 及其后必须确认布局；进入 `SHOTS_LOCKED` 及其后还必须确认覆盖机位。

## 8. 空间因果几何层与新场景接入（与具体场景无关，可复用）

`scripts/check_spatial_contract.py` 在结构层之上提供确定性几何推导，换任何剧本/场景都适用，不绑定车库。

- **统一字段（唯一口径）**：坐标一律用 `position`，取值 `{x,y}` 或 `[x,y]`；车头/机位/人物朝向一律用数值 `orientation`（罗盘方位角，0=N,90=E,180=S,270=W）。旧字段 `pos`、`orientation_bearing`、`front_bearing` 仍兼容但新场景不必再写。道具等没有罗盘朝向的对象，`orientation` 可写文字。
- **坐标系**：x=东+、y=北+，方位角自正北顺时针。先摆固定锚点坐标，再摆对象与每个机位，几何结果由坐标推出，不靠文字描述。
- **推导内容**：在机位绑定的 `blocking_state_id` 快照上计算每个“可见锚点”的方位角，判断是否落在 `fov_half` 视锥内；再把方位投影到画面坐标，核对 `screen_positions` 的 `left/center/right`。车内镜头只有在外部锚点显式写 `through_window` 时，才按车头朝向判定窗户，不把车内人物和门误标为“经由挡风玻璃”。
- **错误码**：
  - `spatial-anchor-out-of-view`：锚点相对机位超出视锥，不可能入镜；
  - `spatial-window-mismatch`：按车头朝向应从 A 窗看到，却声明从 B 窗；
  - `spatial-anchor-should-be-hidden`：声明“禁见”的锚点落入视锥；
  - `spatial-vehicle-heading-missing`：机位在车内但车辆缺数值车头朝向；
  - `spatial-camera-geometry-missing`：**场景已给坐标、机位又引用了锚点，却缺数值坐标/朝向**——此时不再静默跳过，必须补齐，或在该机位显式写 `"spatial":"skipped"`。全场景无任何坐标时才向后兼容地跳过几何层。
  - `spatial-blocking-state-missing/unknown`：动态场景机位未绑定逐镜调度快照，或引用了不存在的快照；
  - `spatial-screen-side-mismatch`：对象虽在视锥内，但坐标投影的画面左右与声明不一致。
- **新场景接入流程**：复制 `assets/templates/scene-map.json` → 摆锚点/对象/机位坐标与朝向 → `python3 scripts/check_spatial_contract.py <file>` 校验 → `--constraints <file>` 自动生成每镜“可含/禁见、经由哪扇窗”的约束文本，直接抄进图像 prompt，避免手工翻译几何出错。
- **能力边界**：几何层已建模真实空间边界、人物可通行路线、逐镜静态调度快照、机位内外、方位、视锥、画面左右与显式车窗扇区；仍不自动推导墙体遮挡和连续运动摄影机轨迹。未登记的角色位移会阻塞，不再以静态快照之间“可能可达”假通过。它校验调度计划自洽，不读取生成像素。
- **动态风险层**：动态/混合镜头还要检查持续地标、占用/禁入多边形和尺度锚点。当前可机械判断逐镜坐标是否落入禁区；连续路径穿越墙体、镜头运动碰撞和真实像素比例仍需后续几何扩展与人工复核。
