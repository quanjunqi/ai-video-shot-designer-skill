# 资产合同与生产规则

本文件是角色、场景、道具、状态图、构图参考、actual tailframe 和音频资产的唯一规则入口。资产只锁定身份、外观、结构、状态或声音，不替代 `scene_map`、`shot_card` 和 continuity ledger。

## 1. 通用资产合同

每项资产建立机器可读 `asset_contract`：

```json
{
  "contract_version": "1.0",
  "asset_id": "a08",
  "asset_type": "directional_prop",
  "label": "phone-front-canonical",
  "purpose": "锁定手机正面材质与屏幕区域",
  "prompt_operation": "canonical_create | reference_edit | composition_create",
  "style_application": "project-texture-lock | inherit-source",
  "identity_invariants": [],
  "required_views": [],
  "required_elements": [],
  "forbidden_elements": [],
  "topology": {"object_count": 1, "visible_surfaces": [], "mutually_exclusive_surfaces": []},
  "text_lock": {"expected_text": null, "forbidden_extra_text": true, "user_review_status": "pending"},
  "state_lock": {},
  "variable_regions": [],
  "usage_scope": [],
  "upload_policy": {"mode": "lineage-final-only", "justification": ""},
  "provenance": {"lineage_root_asset_id": "a08", "derived_from": []},
  "review_contract": {
    "file_check": "pending",
    "physical_structure": "pending_user",
    "visible_surface": "pending_user",
    "ocr": {"status": "not_requested", "evidence": []},
    "user_confirmation": {"status": "pending", "statement": null, "file_sha256": null}
  }
}
```

`canonical_create` 使用 `project-texture-lock`；`reference_edit` 使用 `inherit-source`；`composition_create` 根据实际生成方式选择其一。`required_elements` 与 `forbidden_elements` 不得相交。单张非拼贴图不能同时锁定互斥表面；需要正反面时建立两个用途明确的派生视图，或建立不进入视频输入的多视图身份板。

`usage_scope` 说明内部用途，`upload_policy` 说明能否成为视频输入。内部 canonical、状态派生图和实际上传集合是三件不同的事。`lineage-final-only` 表示同一单元默认只上传当前最终状态图，不再同时上传其 canonical 根或同谱系其他状态。

## 2. 类型专用字段

- `character`：身份不变量、服装封闭集合、人体拓扑、真实提供视角、中性表情基线、环境与道具排除项。角色身份应按演员基准、造型状态组件、角色定妆状态、角色四视图身份资产和按需原子身份视图建立；已确认的四视图身份资产可以作为视频中的人物身份与服装参考，但不能冒充分镜或构图参考。
- `scene`：世界方向、空间边界、固定锚点、家具名称/数量/位置/朝向、可通行区、禁区、门窗状态、光源锚点、占用状态和摄影方向。
- `directional_prop`：必须/禁止可见面、交互面、朝向、阅读方向、数量和允许状态转换。
- `screen_text`：载体资产、显示区、精确允许文字、额外文字禁止项和同设备谱系；除显示区外不得变化。
- `environment_state`：绑定场景 canonical，只允许天气、时间、灯具、损坏或陈设中的获准变量变化。
- `appearance_state`：绑定角色 canonical，只允许指定衣物、污损、妆容或伤势区域变化，不得重画身份。
- `game_ip`：游戏机位、地图方向、UI 区域、UI/世界分离、角色状态、事件顺序和胜负结果。
- `vfx_state`：特效实体、触发、来源、强度、范围、环境反光和结束状态；瞬时特效不烘焙进 canonical。
- `composition_reference`：绑定 shot card、scene map 和 canonical 资产；单帧非拼贴，只服务当前镜头构图。
- `actual_tailframe`：绑定已接受视频、单元、时间码、帧哈希和文件哈希，不覆盖 canonical 身份。
- `audio`：说话者/声源、语言、内容、时长、声道和允许用途；声纹、对白、环境声和音乐职责分开。

## 3. Canonical 与派生资产

Canonical 资产锁定角色身份、场景结构、道具形态或可读文字，不包含剧情动作、运镜、临时特效和不必要环境状态。

- 主角色：先建立中性演员基准；服装结构、面料、无身份穿着效果、发型和配饰独立设计，只有妆容应用阶段读取演员图，最后再把演员与全部获批组件融合为角色定妆基准。通过后生成一张四视图身份资产作为默认人物参考。四视图应包含正面全身、90 度侧面全身、背面全身和正面胸部以上脸部特写；侧面、背面或其他独立原子视图仅在四视图不足以支撑当前镜头时派生。
- 场景：先确认无人母版，再以同一母版参考编辑补充方向视图；不把人物走位或机位运动画进场景图。
- 方向道具：为实际镜头生成可见面；相反表面由独立派生视图承担。
- 可读文字：`text_lock` 保存 `expected_text`、用户逐字确认和额外文字禁止项。动态前后态必须共享可回溯的真实 canonical 根，不能只填写相同根 ID。
- 状态图：从已批准根资产派生，只修改合同中的 `variable_regions`。失败根资产使全部后代失效。

只有目标视频模型明确需要单帧条件，且 `shot_card + scene_map + approved canonical assets` 仍不足时，才派生构图参考：

```text
shot_card + scene_map + approved canonical assets -> composition reference
```

构图参考不得经过故事板、状态格或导演总版，必须绑定 `shot_id`、`scene_id`、来源资产、用途、模型和 `STYLE-01`。

## 4. Prompt 操作

- `canonical_create`：主体/空间、所需视图、资产背景与照明、比例、限制和一次纯净项目质感锁。不得加入成片表演、运镜或环境剧情。
- `reference_edit`：声明已确认源图，列出必须保持项，只修改 `variable_regions`；默认继承源图的质感、光线、视角、构图、材质、阴影和背景。
- `composition_create`：只使用当前镜头卡、场景地图和 canonical 来源支持的构图、摄影与光线事实。

`STYLE-01` 只包含媒介、真实度、纹理、材质响应、颗粒、锐度、总体调色和风格禁止项；不得混入画幅、焦段、景深、机位、构图、表演、场景物件、天气或具体光源。

`no text` 只用于不需要文字的资产。文字资产改用精确允许集和额外文字禁止项。单帧构图图要求 `single frame, no split-screen, no collage`。使用 `scripts/check_asset_prompt.py` 检查操作与风格应用是否冲突。

## 5. 生成、选择与台账

v3 在演员、定妆、融合角色和场景阶段，可于上游需求已批准且图片 API 已配置后调用图片模型。v2 资产流程默认只交付 Prompt。两者都按以下原则放行：

1. API 成功只产生候选，不产生批准。
2. 程序检查只证明文件存在、可解码、尺寸非空和来源可追溯，不判断身份、拓扑、数量、文字或审美。
3. AI 不自动 OCR、不自动评价或重抽。OCR 只有用户明确要求时才作为辅助转录，不能替用户裁决。
4. 用户决定必须绑定当前文件 SHA-256；文件替换、上游变化、失败祖先或用户拒绝使下游失效。
5. 每张实际视频输入有唯一用途和稳定 `asset_id`。导演总版、场景平面图和历史故事板不得上传。

图片资产台账记录 `canonical/derived`、`derived_from`、用途、生成方、模型标签、案例内相对路径和 SHA-256。它不记录视频任务、视频状态、用户视频决定或 actual tailframe 的生产权威；这些由 Director Workflow Manifest 管理。

```bash
python3 scripts/check_image_quality.py output.png --kind asset
python3 scripts/asset_ledger.py register-user-file --help
python3 scripts/asset_ledger.py validate --path runs/current-project/asset-ledger.json
```

只有台账校验无错误且用户明确确认的资产，才能进入 `input_bindings`。同谱系最终状态图已包含身份与当前状态时，默认不再同时上传 canonical 根。
