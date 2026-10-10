# TASK_STATE.md

> 更新日期：2026-09-18。后续会话先读本文件。

## v3 共同创作改造

- 产品边界已收敛为 AI 短剧导演；用户确认的剧本不可删除、改写、重排或擅自补写。
- v3 默认工作模式为 `co-direct`。主流程见 `references/core/workflow.md`。
- 第一阶段底座已完成：`project-ledger.json` 当前快照模型、追加式 `review-ledger.jsonl`、不可变版本审核绑定、配置驱动依赖和作用域失效传播。
- 新增 `scripts/project_ledger.py`，支持项目初始化、产物登记、用户决定登记、下游失效和快照查看。
- v3 详细业务事实暂不搬入项目总台账；现有 v2.2 Manifest、图片资产台账和领域文件继续保持各自权威，避免双重事实源。
- 第二阶段已完成：锁定源剧本文件路径与 SHA-256；v3 禁止 `authorized_changes`；`script_manifest.sequence` 与单元 `script_refs` 必须逐项同序、恰好一次覆盖全部 `EV/DLG`。
- 新增确定性《单元拍摄稿》渲染和文件复核。动作来自锁定 `events[].fact`，对白逐字来自 `dialogues[].text`；手工改写稿件或替换文件会被哈希与内容双重拦截。
- 新增 `scripts/check_unit_coverage.py`，剧本覆盖合同并入 `references/contracts/script.md`。
- 第三阶段已完成：角色客观需求合同、OpenAI-compatible 图片生成服务、配置化供应商参数、演员候选批次、项目路径隔离，以及用户选择候选后按同一文件哈希登记 `actor_baseline`。
- 角色需求禁止演员评分和排名，只允许剧本引用、身份/身体事实、表演任务、必要视图和未知项。需求文件未获用户批准或哈希发生变化时，不得调用图片 API。
- 图片 API 凭据只从 `IMAGE_API_BASE_URL/IMAGE_API_TOKEN/IMAGE_API_TEXT_MODEL` 读取，不进入候选批次元数据。API 成功只产生 `AWAITING_USER` 候选。
- 后续阶段已完成：定妆组件逐项候选与审核、多参考角色融合及二次审核、场景母版、同源补充视图、视图组、空间骨架绑定、人物走位与摄影机路径确定性 SVG、镜头方案、单元资产与 Prompt 审核门、视频拒绝精确退回。
- v3 粗粒度阶段配置位于 `config/workflow/co-direct-stages.json`。项目登记全部角色、场景和单元作用域后，`project_ledger.py advance` 会逐作用域检查所需产物均为当前 `USER_APPROVED` 版本。
- 依赖登记现在冻结上游 `artifact_id + version + sha256`；新上游版本会自动把同作用域下游标记为 `STALE`，历史文件和审核记录不删除。
- v3 使用 schema 3.0 项目快照管理共同创作阶段；底层视频任务、下载证据、用户视频决定和 actual tailframe 继续由 v2.2 Director Workflow Manifest 唯一管理。
- 计划内架构改造项已全部实施。真实项目仍需逐阶段提供剧本、用户选择和 API 配置，不能用测试数据自动推进。

## 知识层架构

- `references/` 已从历史平铺文档收敛为 11 份 Markdown，共 1549 行，根目录无文件。
- `core/workflow.md` 统一流程、审核、项目台账、依赖失效和生产不变量。
- `contracts/` 只保留剧本锁与视觉开发；`planning/` 只保留空间调度与镜头规划。
- `production/` 统一生成单元、资产、执行交付和 v2.2 底层视频证据；`adapters/` 只保留模型专用 Prompt 结构。
- 镜头与 coverage 策略 JSON 位于 `config/directing/`；scene map 模板位于 `assets/templates/`，不再混入 references。
- 图片资产台账默认名为 `asset-ledger.json`，与 v3 `project-ledger.json` 明确分权；旧 `project_ledger.json` 仅作自动兼容回退。

## 当前版本

- 共同创作工作流：v3 `co-direct`
- 视频生产证据：v2.2 `shot-card-first` Manifest
- 镜头事实源：`shot_card`
- 空间事实源：`scene_map`
- 连续性事实源：`continuity ledger`
- 视频执行层：用户确认的 `直接模型 / API` 路由；当前实现 MiniMax H3 直接模型、AutoDL MiniMax H3 API 与基于用户 Prompt 契约的 Seedance 2.5 直接模型
- 默认不生成分镜位图；导演总版和空间确认图只供人工审阅，不进入视频输入。

## 当前规则重点

1. 每个案例使用独立目录、台账和本次新生成素材，不复用历史图片、视频、Prompt、API 响应或 actual tailframe。
2. H3 字符优先分配给镜头任务、动作因果、连续性空间、摄影执行和必要异常防护。
3. 项目内部策略 ID 不进入 H3；业界通行的摄影、构图、调度、剪辑和表演术语必须保留，并展开为主体、触发、方向、路径、时机和尾态。
4. 默认交付“导演语言落点”，让用户逐镜看到语言库的实际贡献。
5. 关键可读文字在资产阶段锁定；签名、填写和盖章使用同源前后态资产。
6. `10000` 字符是 AutoDL Art `minimax_h3_zm_u24` 当前适配器请求合同，不是已核实的 MiniMax H3 官方上下文上限。
7. 视频成片不由 Skill 自动验收。默认一次只交付 1 个生成单元；用户明确接受当前单元后才解锁下一单元。系统只校验任务/文件归属、用户决定记录和 actual tailframe 来源等客观完整性。
8. 生成视频资产必须绑定 `unit_id + task_id + result_url + local_path + video sha256 + request metadata hash/path`；用户决定同时绑定 `video_asset_id + video_asset_sha256`，文件替换后旧决定自动失效。
9. 顶层状态绑定 `active_unit_id + delivery.mode`：Prompt-only 可由 `PROMPT_READY` 交付；generated-video 必须由 `USER_ACCEPTED` 交付。
10. 空间确认拆为同源两阶段：coverage 前确认 `layout`（边界/锚点/路线/落点），coverage 后确认 `camera_plan`（机位/方向/目标）。机位变化不会使未变化的布局确认失效。
11. 画面文字分为物件固有、动态状态、编辑型和非叙事不可读四类；剧情文字资产必须带期望文字和用户逐字确认，动态前后态共享资产根。
12. `generation_duration_seconds` 为 1-15 整数；容量使用 beat 率、物理动作密度、切镜数和精度风险等可测字段。图片模型路由来自 `.env`/项目台账，不再把默认模型名当作普遍真理。
13. 工作流 Gate 真正渐进：当前阶段只要求已到达层及其前置层，不为消除报错提前伪造未来产物；`SPACE_READY` 起绑定空间文件，`PROMPTS_VALIDATED` 起绑定真实 H3 交付稿。
14. `IN_PRODUCTION` 必须登记不可变 `active_generation`；AutoDL 客户端直接输出该对象，并把默认元数据/视频目录派生到当前 `--artifact-root`。所有 artifact 和生产文件使用案例根内相对路径。
15. scene map 必须显式登记真实 `space_boundary` 与人物 `movement_routes`；路线不能穿边界、不可通行区或适用禁区。inside/outside 机位与边界一致，attached 机位必须绑定已知 `attached_to`。
16. 图片资产台账不再拥有视频状态、用户决定或 actual tailframe 来源权威；这些只由 director workflow manifest 管理。
17. `h3_execution_facts` 每镜至少包含 `start_state/end_state`，并按路线、画面方向、手别、持有者、唯一数量和物件朝向风险追加事实；空对象不通过。
18. 动态文字状态必须共享真实 canonical 根、具备可传递 `derived_from` 证明，并逐状态登记 `expected_text_by_asset` 和用户逐字确认。
19. 最迟在 `ASSETS_READY` 前由用户确认交付方式、目标模型和 API 平台（如适用）；未确认时最多推进到 `UNITS_READY`。这只是执行目标路由，不新增质量模式。
20. 当前放行 `minimax-h3-direct-v1`、`autodl-minimax-h3-v1` 与 `seedance-2.5-direct-v1`。Seedance 2.5 API 和其他未知 API 保持 `unresolved`，不得套用 H3/AutoDL 格式冒充可提交稿。
21. 每单元 `input_bindings` 用连续 `order + media_type + slot + asset_id` 锁定实际素材顺序。直接模型显示“第 N 个素材”且不出现 API 字段；AutoDL 按图片/音频各自顺序映射 `ref_image_0/ref_audio_0` 并唯一绑定。
22. AutoDL 的 1-10000 字符、时长、分辨率和媒体数量只属于该 API 适配器合同。直接模型沿用 1-15 秒作为当前项目兼容策略，不宣称是 MiniMax 官方硬上限。
23. 每项生产资产必须建立机器可读 `asset_contract`，覆盖身份边界、所需视角/元素、禁止元素、拓扑、状态、变量区、用途、上传策略、来源和复核合同；角色、场景、有方向道具、屏幕文字、环境/外观状态、游戏/IP、特效、构图、实际尾帧和音频各有专用字段。
24. v3 的演员、身份视图、定妆、融合角色和场景候选均支持两条执行路线：图片 API 自动生成，或导出单图 Prompt 后由用户在任意工具生成并回传。外部路线不向用户规定生成数量、筛选方式或候选编号；用户明确表示回传图已选定时，直接登记该文件和用户决定。两条路线共用文件校验、SHA-256 和用户选择合同；图片 API 不再是流程前置条件。
25. 单张非拼贴图片不能同时锁定互斥表面。失败根资产使全部后代失效。内部谱系与视频上传集合分离；`lineage-final-only` 最终状态图默认替代同谱系 canonical 的本次上传位置。
26. `STYLE-01` 只锁定项目级媒介与图像质感，不得包含画幅、焦段、景深、机位、构图、表演、场景物件、时间天气或具体光源。文生 canonical 使用纯净质感锁；引用编辑以 `inherit-source` 保持源图，只修改声明的变量区，不重复全局锁；H3 `summary` 使用纯净质感锁一次。

## 当前案例

- 案例根：`runs/e2e-episode-01-20260917`
- U01 视频已由用户接受；接受记录绑定视频 SHA-256 `0ba9b395ff56780c2edbd47521d084971ccc5b1829e71d98e0aab15a4f1ef421`。
- U02 已解锁，但尚未生成 Prompt 或提交视频。
- 旧手机 `a04` 因正面屏幕与背板/后摄形成不可能拓扑，已标为“历史失败，禁止复用”；其通知后代 `a07` 同步失效，未登记的 `a07b` 亦禁止使用。
- 新手机正面 canonical 为 `a08`，文件 `assets/generated/a08_phone_front_01.png`，SHA-256 `bbbc42c79fe9869e94a3a8c7b1294ab1674d395d88076add50516050fc79381e`，已由用户明确确认。
- 出租屋场景图实际包含唯一黑色办公椅，已把椅子加入 scene map 与场景资产闭合集。该布局事实变更使 SPACE-ROOM 布局确认失效，当前等待用户重确认；机位方案维持待确认。
- U02 通知态改为 Prompt-only 协作：有效稿为 `assets/prompts/a09_phone_notification.txt`，计划契约为 `assets/contracts/a09_phone_notification_planned_contract.json`。该派生 Prompt 已移除全局电影风格段，只继承 a08 的质感、光线、视角、构图、材质和背景，并限定只修改显示区。此前在规则切换前由接口产生的 `a09_phone_notification_01.png` 未登记、未获用户决定，禁止进入 U02。
- 用户在任意外部图片模型自行生成通知态并确认。回传后使用 `asset_ledger.py register-user-file` 登记；U02 实际上传只使用用户确认的最终通知态手机图，不同时上传手机 canonical。

## 清理状态

- 历史压力案例、`reports/` 与 `outputs/` 已删除；`tests/` 现为标准库 `unittest` 回归套件。
- 历史测试案例、生成视频、图片、API 元数据和失败产物已删除。
- v1 分镜板复现脚本、旧位置图规则、历史变更记录和示例案例已删除。
- 本地 `.venv`、Python 缓存与 `.DS_Store` 不进入发布包；`dist/` 只保留当前通过复验的发布包。
- `.env` 保留，继续作为本地 API 凭据来源，不得打包或提交。

## 当前交付包

`dist/ai-video-shot-designer-20260918-v3.1-co-direct.skill`

SHA-256：

`a0400ca693c2a188f7b664c27c3fdefa2456ece515b04e3f7df1f6375dd3404f`

发布包共 118 个条目，包含 11 份 reference、机器配置、模板、领域实现、CLI 和回归测试；不含 `.env`、`runs/`、`outputs/`、`dist/`、缓存、生成媒体或真实凭据。归档已在独立临时目录完成解包复验。

## 本轮验证

- v3 台账、剧本覆盖、选角、定妆、场景、调度、镜头和生产门禁回归已覆盖；64 项 `unittest` 与 `scripts/self_check.py` 全部通过。
- 图片与视频 Adapter 已分目录加载：图片配置位于 `config/adapters/image-generation/`，不会被既有视频 Prompt Adapter 加载器误读。
- `project_ledger.py` CLI 冒烟通过：视觉风格产物登记、精确版本批准和 JSONL 审核记录一致。
- Skill `quick_validate.py`、Python 编译和 `git diff --check` 通过。

- `python3 scripts/self_check.py`：通过。覆盖渐进状态门、案例路径隔离、AutoDL 提交回执、视频证据与验收版本、图片台账权威边界、音频/图片标签绑定、整数时长、容量公式、文字真实来源链、H3 执行事实、空间边界/路线/附着机位和空间双签名。
- `python3 -m py_compile scripts/*.py scripts/shotdesigner/*.py scripts/shotdesigner/validators/*.py tests/*.py`：通过。
- `python3 -m unittest discover -s tests -t .`：43 项通过；Python 3.14 工作区和系统 Python 3.9 解包目录均通过。
- `python3 scripts/check_spatial_contract.py assets/templates/scene-map.json`：通过。
- `render_blocking_map_text.py` 的 layout 与 camera_plan 双投影：使用临时目录通过，未保留测试产物。
- `git diff --check`：通过。
- Markdown 相对链接扫描与 SKILL frontmatter 检查：通过；11 份 reference 无失效链接、无根目录文件。
- Skill 归档敏感信息与冗余扫描：通过。
- 执行目标路由回归：通过。覆盖未确认目标拦截、MiniMax H3 直接模型、AutoDL MiniMax H3、Seedance 2.5 直接模型、未实现 API 拦截、直接稿 API 字段泄漏和 AutoDL 上传顺序绑定。
- 官方 `quick_validate.py`：通过。`PyYAML 6.0.3` 已按用户要求安装到当前用户的全局 Python 环境，不再依赖临时虚拟环境。
- 图片外部生成路线：`casting_workflow.py` 与 `visual_workflow.py` 均支持导出 Prompt、导入用户回传图片、文件质量校验、项目内复制、SHA-256 登记及统一候选选择；隔离目录 CLI 烟测通过。
- 资产契约回归：通过。覆盖契约内部互斥、用户外部生成文件登记、用户文件哈希、canonical 与最终状态重复上传、失败祖先传播；不再把 OCR 或 Skill 视觉判断作为放行条件。
- 当前案例资产台账 schema v2 校验：通过；SPACE-ROOM 空间校验通过（`shot_states` 未提供，仅产生非阻塞警告）。
- Skill 包敏感字段和冗余目录扫描：通过。
- 本轮新增 `check_asset_prompt.py`：区分 `canonical_create`、`reference_edit` 与 `composition_create`；派生编辑重复完整项目质感锁时阻塞。当前 a09 操作感知检查与 self-check 均通过。

## 下一步

1. 向用户交付 `a09_phone_notification.txt`，由用户自行生成并判断通知态图片。
2. 用户回传并明确确认后，用 `asset_ledger.py register-user-file --kind derived --source a08` 登记文件、来源和 SHA-256，再标记“用户确认”。
3. 获取用户选定的 U01 actual tailframe 后，生成 U02 shot cards 与 MiniMax H3 直接模型稿；输入只含 actual tailframe（如确需连续）和用户确认的最终通知态手机图。
