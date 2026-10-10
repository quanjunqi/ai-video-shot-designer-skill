# Prompt、视频与交付合同

本文件统一管理执行目标、素材顺序、Prompt 路由、视频提交、用户验收和交付门禁。导演事实只有一套；交付格式由用户确认的目标决定。

## 1. 执行目标

生成最终 Prompt 前确认：

1. `delivery_method`：`model` 或 `api`。
2. `target_model`：当前实现 `minimax-h3` 和直接模型方式的 `seedance-2.5`。
3. `api_platform`：仅 API 路径需要；当前只实现 `autodl-art/minimax_h3_zm_u24`。

受支持组合：

| 交付方式 | 模型 | API 平台 | `prompt_contract` | 状态 |
| --- | --- | --- | --- | --- |
| `model` | `minimax-h3` | `null` | `minimax-h3-direct-v1` | 可交付 |
| `api` | `minimax-h3` | `autodl-art` | `autodl-minimax-h3-v1` | 可交付 |
| `model` | `seedance-2.5` | `null` | `seedance-2.5-direct-v1` | 可交付 Prompt |
| `api` | 任意模型 | 其他平台 | `unresolved` | 等待真实契约 |

执行目标确认后才能进入 `ASSETS_READY`；未确认时最多到 `UNITS_READY`。`PROMPTS_VALIDATED` 要求组合已实现且 `prompt_contract` 不为 `unresolved`。

Manifest 中的 `execution_target` 至少保存交付方式、模型、平台、Adapter、Prompt 合同、用户确认原话和合同来源。平台参数与限制以 `config/adapters/` 为机器事实源。

## 2. 素材顺序

每个单元使用有序 `input_bindings`：

```json
{
  "input_bindings": [
    {"order": 1, "media_type": "image", "slot": "<Subject 1>", "asset_id": "character-fang-v1"},
    {"order": 2, "media_type": "image", "slot": "<Subject 2>", "asset_id": "scene-room-v1"}
  ]
}
```

`order` 从 1 连续递增，数组顺序与之相同，`slot` 和 `asset_id` 不重复。改变顺序、资产或槽位后，旧 Prompt 与请求元数据立即失效。

- MiniMax H3 Direct：显示“第 N 个素材”，只用 H3 标签，不出现 API 字段。
- AutoDL：图片按自身顺序映射 `ref_image_0...`，音频映射 `ref_audio_0...`；映射同时进入元数据和实际 `subject_definitions`。
- Seedance 2.5 Direct：图片映射 `@图片1...`；没有素材时完全省略素材说明。
- 其他 API：必须取得该平台真实字段、顺序、限制和版本后新增 Adapter，不得借用 AutoDL 字段。

## 3. Prompt 路由

- `minimax-h3-direct-v1`：使用 H3 六字段核心结构和有序上传清单，禁止 `ref_image_N/ref_audio_N`、AutoDL 工作流 ID、API 分辨率枚举和 10000 字符限制。
- `autodl-minimax-h3-v1`：使用同一六字段语义并增加 AutoDL 绑定；必须运行 H3 校验和槽位校验。1-10000 字符、1-15 秒、媒体数量及分辨率枚举只属于该 Adapter。
- `seedance-2.5-direct-v1`：使用独立 Seedance 契约和校验器；不得套用 H3 六字段、AutoDL 字段或 API 能力。
- `unresolved`：只允许保留规划记录，不得声称 Prompt 可提交。

模型专用格式见 [MiniMax H3](../adapters/minimax-h3.md) 和 [Seedance 2.5](../adapters/seedance-2.5-direct.md)。

## 4. 成片控制

如果剧本未授权画内文字，交付干净摄影母版：对白、旁白和音效只改变音轨。剧情文字必须来自用户确认的 text-locked 资产；签名、填写和显示变化使用同源前后态；编辑型字幕、片名和 UI 留给后期。

显示器、仪表、手机、铭牌和发光面按 canonical 资产锁定材质、发光、亮度、颜色和反射。显示状态变化只能来自 `EV/LOCK`，或者来自用户提交并锁定的新完整剧本版本，不能由对白、报警或人物靠近自动触发。

除非剧本有灯光变化，每个单元锁定同一手动曝光、白平衡、灯具输出、色彩响应、黑位、对比度和 tone mapping。人物动作、切镜和屏幕内容不能自动改变曝光或白平衡。

硬切必须说明切点时间、切前末帧、切后首帧的可辨构图差异，以及保持不变的世界位置、动作后态、道具和光影锚点。连续移动、变焦或形变不能冒充切镜。

角色外观采用封闭允许集合：脸、发型、版型、领口、口袋、接缝、反光条、徽章、文字、色块、配饰和磨损。未在 canonical 或已批准状态中出现的附加标记不得新增。

## 5. API 提交与证据

仅在用户已确认 API 路径后运行对应客户端。AutoDL 提交必须满足：

1. 每个上传字段在实际发送的 H3 `subject_definitions` 中恰好绑定一个标签；代码块外说明不能替代绑定。
2. `active_generation` 记录 `unit_id/task_id/request_metadata_path/request_metadata_hash/submitted_at/status`；没有真实提交证据不能进入 `IN_PRODUCTION`。
3. Prompt、请求元数据、结果元数据和视频都位于当前 `--artifact-root`，并以案例内相对路径登记。
4. 返回视频绑定 `unit_id/task_id/result_url/local_path/video_sha256/request_metadata_path/request_metadata_hash`，并与真实响应一致。
5. Director Workflow Manifest 登记不可变 `video_asset_id` 和 `GENERATED_AWAITING_USER`。v3 `project-ledger.json` 不复制视频任务、视频状态或用户视频决定。
6. 凭证不得出现在 Prompt、Manifest、元数据或日志中。

`autodl_minimax_h3.py submit/run/poll` 输出可登记的 `active_generation`。若提交直接返回完成结果，则登记视频资产并进入 `USER_REVIEW_PENDING`，不伪装停留在 `IN_PRODUCTION`。

## 6. 用户验收

```text
PROMPT_READY -> GENERATED_AWAITING_USER -> USER_ACCEPTED | USER_REJECTED
```

系统只核对任务与文件闭环，不自行判断动作、表演、构图、节奏、身份漂移、手部、文字或光色。API 或下载成功只能进入待用户验收。

用户决定绑定 `video_asset_id + video_asset_sha256` 并记录原话。文件或请求变化后创建新视频版本和新决定。用户接受当前单元后才能正式进入下一单元；用户拒绝时按反馈回到最小责任层。actual tailframe 只能来自已接受视频。

## 7. 交付门禁

交付前运行与当前目标相符的机械检查：

```bash
python3 scripts/check_director_workflow.py director-workflow.json
python3 scripts/check_spatial_contract.py scene-map.json
python3 scripts/check_unit_coverage.py unit-plan.json --render-dir units/
python3 scripts/asset_ledger.py validate --path runs/current-project/asset-ledger.json
python3 scripts/check_reference_set.py delivery.md
python3 scripts/check_continuity.py delivery.md
python3 scripts/validate_h3_prompt.py delivery.md
# 或
python3 scripts/validate_seedance_prompt.py delivery.md
```

机械门禁至少验证：

- 当前 Gate 只要求已到达阶段及其前置，不伪造未来产物。
- v3 Script IR 的 `authorized_changes` 为空；v2 Manifest 为兼容保留该字段。
- `EV/DLG` 覆盖完整、同序、无重复，用户可读拍摄稿与源事实及哈希一致。
- scene map 的边界、路线、机位、视图组来源与用户确认版本一致。
- shot card、coverage、cut contract、unit、continuity 和 Prompt 可相互定位。
- 资产合同、来源链、用户决定、实际文件哈希和 `input_bindings` 一致。
- 目标、Adapter、时长、格式和上传映射匹配；Prompt 不泄漏其他平台字段。
- generated-video 有真实任务、请求元数据、视频文件、用户决定和必要 actual tailframe 证据。

人工复核只交给用户完成：演员、定妆、场景外观、空间调度、镜头方案、资产图片、Prompt 和成片。所有机械检查为通过且当前阶段所需用户审核均为 `USER_APPROVED` 后才能放行；任何 `STALE`、文件哈希变化、待确认项或不一致都阻塞交付。
