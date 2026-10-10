# Director Workflow Manifest v2

该 manifest 是跨层一致性清单，不是另一个创作层。它用稳定 ID 和真实文件哈希证明 Script IR、scene map、shot card、unit continuity、资产、H3、用户验收记录与实际尾帧引用的是同一事实。

## 1. 顶层结构

```json
{
  "schema_version": "2.2",
  "planning_mode": "shot-card-first",
  "workflow_id": "project-batch-v2",
  "workflow_state": "PROMPTS_VALIDATED",
  "active_unit_id": "U01",
  "execution_target": {
    "delivery_method": "model",
    "target_model": "minimax-h3",
    "api_platform": null,
    "adapter_id": null,
    "prompt_contract": "minimax-h3-direct-v1",
    "confirmation": {"statement": "直接交给 MiniMax H3", "confirmed_by": "user", "confirmed_at": "..."},
    "contract_source": "references/adapters/minimax-h3.md#direct",
    "contract_verified_at": "2026-09-16"
  },
  "project_style_lock": "只含媒介与图像质感的完整英文锁原文",
  "script_ir": {},
  "scene_maps": [],
  "spatial_reviews": [],
  "scene_direction_briefs": [],
  "coverage_plans": [],
  "coverage": {"included_beat_ids": [], "deferred_beat_ids": []},
  "shots": [],
  "units": [],
  "assets": [],
  "delivery": {"mode": "prompt-only", "scope": "full", "emitted": ["h3", "assets"]},
  "visual_review": [],
  "artifacts": {}
}
```

v2 中每个 `shots[]` 无条件携带 [镜头规划合同](../planning/shots.md) 的完整 `shot_card`。v2.1 及 v2.2 还要求每张镜头卡包含 `strategy_selection`；无需逐镜策略时写空数组。v2.2 新增逐场 `scene_direction_briefs` 与 `coverage_plans`。`storyboards`、`storyboard_candidates` 和 `storyboard_source` 不属于 v2 契约；即使工作目录保留历史图片，也不能绕过镜头卡。

`script_ir.project.duration_budget` 与每个 `units[]` 的剧情容量字段按 [生成单元合同](units.md) 登记。它们证明单元边界来自忠实呈现时长、剧情结果和模型容量，而不是故事板格数。

v2.2 每个连续空间分两阶段登记同源投影，避免在 coverage 尚未设计时让用户确认机位。第一份只确认布局、边界、路线和落点：

```json
{
  "review_id": "spatial-review-S1-v1",
  "review_type": "layout",
  "scene_id": "S1",
  "map_version": "v1",
  "source_scene_map_signature": "sha256:...",
  "text_map": {"path": "reviews/S1-v1.md", "sha256": "sha256:..."},
  "covered_state_ids": ["S0", "S1", "S2"],
  "confirmation_status": "用户确认",
  "confirmed_scope": ["layout", "routes", "boundaries", "end_states"],
  "change_class": "initial",
  "confirmed_by": "user",
  "confirmed_at": "2026-09-16T01:00:00+08:00"
}
```

布局确认后才能进入 coverage。coverage plan 写回同一 scene map 的 camera 后，再生成 `review_type: "camera_plan"`，其 `confirmed_scope` 固定为 `["camera_positions", "camera_targets"]`。进入 `SPACE_READY` 及其后必须确认布局投影；进入 `SHOTS_LOCKED` 及其后还必须确认机位投影。两类签名独立，改焦距或曝光不会让布局确认失效，机位位置、方向或目标变化只使机位确认失效。

## 2. 状态与 Gate

状态顺序、合法迁移和各 Gate 的累积必需字段以 `config/workflow/states.json` 为机器事实源；schema 版本能力以 `config/workflow/versions.json` 为机器事实源。本节解释这些规则，不维护第二份运行时枚举。

`workflow_state` 只能是：

```text
SOURCE_READY
SCRIPT_LOCKED
SPACE_READY
SHOTS_LOCKED
UNITS_READY
ASSETS_READY
PROMPTS_VALIDATED
IN_PRODUCTION
USER_REVIEW_PENDING
USER_ACCEPTED
USER_REJECTED
DELIVERED
```

状态表示 `active_unit_id` 指向单元已通过的最高 Gate。`delivery.mode` 只能是 `prompt-only` 或 `generated-video`。`PROMPTS_VALIDATED/IN_PRODUCTION` 要求活动单元为 `PROMPT_READY`；`USER_REVIEW_PENDING` 要求 `GENERATED_AWAITING_USER`；接受/拒绝状态必须同名一致。`DELIVERED + prompt-only` 要求 `PROMPT_READY`，`DELIVERED + generated-video` 要求 `USER_ACCEPTED` 且 `emitted` 包含 `video`。因此 API 成功不能伪装为交付完成。

manifest 按 Gate 渐进增长，不要求早期状态伪造尚未产生的下游层：`SOURCE_READY` 只需来源、基础 delivery 和 workflow 身份；`SCRIPT_LOCKED` 完成 Script IR；`SPACE_READY` 增加 scene maps、空间确认及其文件证据；`SHOTS_LOCKED` 增加导演意图、coverage 和 shots；`UNITS_READY` 增加 units 与 beat coverage；`ASSETS_READY` 增加资产和经用户确认的 `execution_target`；`PROMPTS_VALIDATED` 才强制绑定与目标契约一致的真实交付稿。未确认执行目标时最多进行到 `UNITS_READY`。

`execution_target` 的完整规则见 [执行与交付](execution.md)。当前可放行的组合包括 MiniMax H3 直接模型、AutoDL MiniMax H3 API，以及基于用户提供 Prompt 契约的 Seedance 2.5 直接模型。Seedance API 和其他未知 API 可以登记为 `prompt_contract=unresolved`，但不能进入 `PROMPTS_VALIDATED`。

每个单元的 `input_bindings` 是上传顺序事实源：

```json
{
  "input_bindings": [
    {"order": 1, "media_type": "image", "slot": "<Subject 1>", "asset_id": "character-c1-v1"},
    {"order": 2, "media_type": "image", "slot": "<Subject 2>", "asset_id": "scene-s1-v1"}
  ]
}
```

数组位置必须与连续 `order` 一致。直接模型按“第 N 个素材”交付；AutoDL 图片和音频分别从 `ref_image_0`、`ref_audio_0` 映射。改变顺序会使旧 Prompt 和请求元数据失效。

进入 `IN_PRODUCTION` 必须登记当前真实提交，不能只改状态字符串：

```json
{
  "active_generation": {
    "unit_id": "U01",
    "task_id": "AutoDL task id",
    "request_metadata_path": "metadata/videos/unit-01-submit.json",
    "request_metadata_hash": "sha256:...",
    "submitted_at": "2026-09-16T12:00:00+08:00",
    "status": "submitted"
  }
}
```

`status` 在生产中使用 `submitted/queued/running`，任务完成后改为 `completed` 并推进至 `USER_REVIEW_PENDING`。提交元数据必须含相同 `task_id`、`unit_id` 和请求哈希。

每个实际生成的 `units[]` 还必须登记自己的生产状态，避免顶层状态掩盖多单元差异：

```json
{
  "unit_id": "U01",
  "production_status": "USER_ACCEPTED",
  "video_asset_id": "unit-01-video-v1",
  "user_acceptance": {
    "decision": "accepted",
    "statement": "单元1通过了",
    "decided_by": "user",
    "decided_at": "2026-09-16T12:00:00+08:00",
    "video_asset_id": "unit-01-video-v1",
    "video_asset_sha256": "sha256:..."
  }
}
```

`production_status` 只能是 `PLANNED_BLOCKED`、`PROMPT_READY`、`GENERATED_AWAITING_USER`、`USER_ACCEPTED` 或 `USER_REJECTED`。后续单元在前序单元获用户接受前保持 `PLANNED_BLOCKED`。API 或下载成功只能进入 `GENERATED_AWAITING_USER`；不能自动生成接受记录。用户拒绝时原样记录反馈，修订后新结果使用新 `video_asset_id`，不得覆盖旧决定。

每个生成视频必须登记为不可变资产：

```json
{
  "asset_id": "unit-01-video-v1",
  "tag": "generated-video-U01-01",
  "kind": "generated-video",
  "unit_id": "U01",
  "task_id": "AutoDL task id",
  "result_url": "https://.../result.mp4",
  "local_path": "generated-videos/unit-01-v1.mp4",
  "sha256": "sha256:...",
  "request_metadata_hash": "sha256:...",
  "request_metadata_path": "metadata/videos/unit-01-v1_result.json"
}
```

用户决定同时绑定 `video_asset_id + video_asset_sha256`，不能只绑定可复用字符串。校验器会检查本地文件存在且哈希一致；AutoDL 客户端在下载时直接输出上述可登记对象。

## 3. Script IR 锁

`script_ir.script_manifest` 必须包含：

```json
{
  "events": [{"event_id": "EV001", "beat_id": "B1", "fact": "可观察事件"}],
  "dialogues": [{"dialogue_id": "DLG001", "beat_id": "B1", "speaker_id": "C1", "text": "原文", "language": "Chinese"}],
  "locks": [{"lock_id": "LOCK001", "target": "EV001", "rule": "不得改变事件因果和结果"}],
  "authorized_changes": []
}
```

无事件、对白或额外锁时对应数组可以为空，但四个字段必须存在。任何补充动作、台词改写或事实调整必须在 `authorized_changes` 中记录目标 ID、变更内容、理由和批准来源。

## 4. 场景导演意图与覆盖

v2.2 每个 Script IR 场景必须恰有一份 `scene_direction_briefs[]` 和 `coverage_plans[]`。导演意图解释锁定剧情的目标、视点、信息释放、表演/空间弧和结尾画面；覆盖计划从 `single-shot`、`long-take`、`multi-camera-coverage`、`action-montage` 中主动选择一种，并绑定 scene map 中的机位、最终 `shot_order`、场景级覆盖策略和相邻镜头 `cut_contracts`。

每个 `shots[].camera_id` 必须由同场覆盖计划批准。机位位置、方向、可见锚点与景别必须和 scene map / shot card 一致。切镜合同的动作输出/输入逐项对应相邻 shot card，前镜道具尾态在切镜瞬间不得改变；后镜内的新变化由该镜自身闭环。没有触发、信息增益或节奏价值的切镜不得保留。H3 按最终顺序逐镜输出，不将多机位描述为同时拍摄或分屏。

## 5. 可选导演总版

用户明确需要人工视觉审阅时，可登记：

```json
{
  "director_review_artifact": {
    "path": "reviews/director-overview.png",
    "sha256": "sha256:...",
    "covered_shot_ids": ["shot_01"],
    "coverage_status": "complete",
    "review_status": "用户确认",
    "shot_reviews": [
      {
        "shot_id": "shot_01",
        "script_coverage": "match",
        "staging_match": "match",
        "camera_match": "match",
        "action_match": "match",
        "prompt_match": "match",
        "issues": [],
        "decision": "accept"
      }
    ]
  }
}
```

总版只能证明“人看过这个投影并记录了判断”。`prompt_match` 必须通过总版、shot card 与真实 H3 文本并排核对，不能由图片像素自动推断。删除整个 `director_review_artifact` 后，`shots`、`units`、`assets`、H3 文件及 `video_inputs` 必须字节级不变。

## 6. 构图参考与尾帧

按需构图参考图：

```json
{
  "tag": "<Picture 1>",
  "kind": "composition-reference",
  "asset_id": "composition-shot-01-v1",
  "shot_id": "shot_01",
  "visual_state": "用户确认",
  "composition_source": {
    "type": "shot_card",
    "shot_id": "shot_01",
    "scene_id": "S1",
    "basis": ["shot_card", "scene_map", "canonical-assets"],
    "canonical_asset_ids": ["character-c1-v1", "scene-s1-v1"]
  }
}
```

用户接受视频后登记的实际尾帧：

```json
{
  "tag": "<Picture 2>",
  "kind": "tailframe",
  "asset_id": "unit-01-tail-v1",
  "visual_state": "用户确认",
  "tailframe_source": {
    "source_unit_id": "unit_01",
    "source_video_asset_id": "unit-01-video-v1",
    "timestamp": "00:11.900",
    "frame_hash": "sha256:..."
  }
}
```

构图参考图不能充当尾帧；尾帧必须能追溯到已登记且对应单元已获用户接受的视频资产。用户接受视频与尾帧可用是两个事实：连续单元缺尾帧时，视频仍可保持 `USER_ACCEPTED`，但下一单元只能是不可提交规划稿。

## 7. 文件证据

`artifacts` 使用当前案例根目录内的相对路径绑定真实交付稿与 scene map 的 SHA-256；绝对路径和 `..` 越界路径一律拒绝。`SPACE_READY` 起必须绑定全部 scene map 文件，`PROMPTS_VALIDATED` 起必须绑定真实交付稿。校验器按 `prompt_contract` 路由：直接模型稿拒绝 AutoDL 字段；AutoDL 稿核对上传顺序、API 字段和 H3 标签；未实现目标不能通过。逐单元放行时，在 `artifacts.delivery_draft.unit_ids` 中按 `unit_order` 列出该文件实际包含的单元。

```json
{
  "artifacts": {
    "delivery_draft": {
      "path": "deliverables/unit-01.md",
      "sha256": "sha256:...",
      "unit_ids": ["U01"]
    },
    "scene_maps": []
  }
}
```

v2 中，每个含动作 EV 的镜头还必须逐事件登记真实 H3 的字面证据：

```json
{
  "shot_id": "shot_01",
  "beat_ids": ["B1", "B2"],
  "h3_evidence_by_event": {
    "EV001": ["walks in from the rear-left door"],
    "EV002": ["stops beside the counter while still holding the envelope"]
  }
}
```

每个绑定到该镜头的动作 EV 都必须有自己的非空证据数组，且片段必须真实存在于对应 `[Shot N]` 段落。`h3_evidence` 只保留给 v1 兼容，不能用于新的 v2 真实交付。

每镜还必须有 `h3_execution_facts` 对象。`start_state/end_state` 每镜必填；存在空间路线或画面方位时还需 `screen_direction`；镜头卡出现手别、持有者、唯一数量或物件朝向风险时，分别强制 `hand/holder/unique_count/prop_orientation`。每项包含 `value`、`required_literals` 和 `forbidden_literals`。空对象不能替代适用事实，校验器会核对真实 `[Shot N]` 字面证据与冲突。

## 8. 兼容策略

缺少 `schema_version` 或显式写 `1.x` 的清单按 legacy v1 只读校验，并产生迁移警告。v1 可以保留 `storyboards/storyboard_source`，但它们不获得新的生产能力。`2.0/2.1` 继续兼容既有项目；新项目和任何实质修改使用 `2.2`。

运行：

```bash
python3 scripts/check_director_workflow.py director-workflow.json
python3 scripts/check_director_workflow.py --json director-workflow.json
```
