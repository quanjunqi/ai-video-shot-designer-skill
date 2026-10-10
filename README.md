# AI Video Shot Designer

将中文或英文剧本转换为结构化镜头计划，并按用户确认的直接模型或 API 目标交付 MiniMax H3 或 Seedance 2.5 Prompt。核心不是生成故事板图片，而是建立一条可校验的生产事实链：

```text
Script IR / EV-DLG-LOCK
  -> Scene Map
  -> Beat Plan
  -> Scene Direction Brief + Coverage Plan
  -> Shot Card
  -> Unit Plan + Continuity Ledger
  -> Canonical Assets
  -> Confirmed Execution Target
  -> Target Prompt
  -> Generated Video
  -> User Acceptance
  -> Actual Tailframe
```

每个生成单元服从已确认目标的 Adapter 时长契约。当前 MiniMax H3 项目契约上限为 15 秒；用户提供的 Seedance 2.5 直接模型契约为 4—30 秒。`shot_card` 决定拍什么和怎样拍，`scene_map` 决定空间事实，continuity ledger 决定跨镜状态，最终 Prompt 只是面向模型的执行转译。

## 架构

```text
SKILL.md                 轻量入口与按需路由
references/              11 份人工决策合同，不放机器配置或模板
  core/                  共同创作流程、审核、台账和不变量
  contracts/             剧本锁与视觉开发合同
  planning/              空间调度与镜头规划
  production/            单元、资产、执行、Manifest 与交付
  adapters/              目标模型专用 Prompt 结构
config/                  阶段、依赖、策略和 Adapter 的机器事实源
assets/templates/        可复制的结构化模板
scripts/shotdesigner/    领域实现、台账和校验器
scripts/*.py             薄命令行入口
tests/                   标准库 unittest 回归
```

`SKILL.md` 只路由当前阶段所需文档，不预读全部 `references/`。一个领域只有一份权威文档；JSON 策略目录归 `config/directing/`，场景模板归 `assets/templates/`，避免知识说明、运行配置和输出模板混在一起。

## 为什么默认没有分镜位图

分镜位图不能可靠承载镜头内时间、动作三态、精确坐标、焦点变化、摄影机动力学、声音、负面约束或完整 H3 文本。让图片模型先猜一张图，再让视频模型解释这张图，会引入第二套不稳定语义。

因此新流程默认不生成单格状态图、拼接分镜板或任何用于“先确认分格”的位图。用户需要总览时，可以从已锁定镜头卡派生导演总版，用于检查覆盖、顺序和明显偏差；它不进入视频输入，也不成为构图图或 Prompt 的来源。

构图参考图只有一个触发条件：目标视频模型明确需要单帧条件，并且 `shot_card + scene_map + canonical assets` 仍不能稳定约束该镜头。此时图片直接从这三类事实派生，不经过故事板。

## 工作流

1. 锁定用户完整剧本和源文件哈希，建立 `EV/DLG/LOCK`，不修改内容。
2. 由用户确认全片视觉风格与质感。
3. AI 提交导演解读与媒介实现分析，再确认视觉风格和技术制作规格。
4. 展示完整剧本覆盖和 `PLANNED` 初步生成单元；它不是分镜，暂定继续也不是批准。
5. AI 内部完成角色分析，只把可行动的选角简报交给用户确认；通过后生成中性演员候选，用户选定后登记为演员基准图。
6. 按场次状态规划角色定妆；先确认状态和组件需求，再逐项生成、选择服装结构/面料/穿着效果、发型、妆容与配饰，最后融合角色定妆并生成四视图供确认。
7. 先确认场景功能稿，再生成无人场景母版和同源补充视图，由用户逐张确认。
8. 从已确认视图建立确定性 `scene_map`，分别确认空间骨架、人物走位和机位运动图。
9. 逐场确认导演意图、表演、声音、屏幕文字、覆盖模式、切镜合同、`shot_card` 和剪辑方案。
10. 镜头与剪辑获批后编译 `EXECUTABLE` 单元，并选择当前单元所需的最小资产集合。
11. 确认直接模型或 API、目标模型及平台；未知组合保持 `unresolved`。
12. 锁定素材上传顺序，生成目标 Adapter Prompt 并由用户确认。
13. 逐单元生成视频，任务成功只进入待审核；用户接受后才解锁下一单元。
14. 从已接受视频提取 actual tailframe；真实尾态优先于计划尾态驱动连续下一单元。

每个阶段的批准绑定具体产物版本和 SHA-256。上游变化只使受影响的当前下游变为 `STALE`，不会删除历史文件或审核记录。节点上下文统一由 `prepare_context` 或 `project_ledger.py context build/inspect` 编译；视频这类跨角色、跨场景、跨单元节点必须显式传入实际 artifact keys，缓存只复用派生数据，不跳过人工审核。

详细入口见 [SKILL.md](SKILL.md)。核心契约：

- [锁定剧本与覆盖](references/contracts/script.md)
- [视觉开发](references/contracts/visual-development.md)
- [空间连续性](references/planning/spatial.md)
- [镜头规划](references/planning/shots.md)
- [生成单元](references/production/units.md)
- [资产生产](references/production/assets.md)
- [Prompt、视频与交付](references/production/execution.md)
- [MiniMax H3](references/adapters/minimax-h3.md)
- [v2.2 视频生产证据](references/production/manifest-v2.md)

## 安装

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

图片质量工具依赖 Pillow，Skill 校验工具可能依赖 PyYAML。核心 H3 与跨层校验器本身保持命令行可运行。

## 校验

```bash
python3 scripts/validate_h3_prompt.py draft.md
python3 scripts/validate_seedance_prompt.py seedance-draft.md
python3 scripts/check_shot_language.py --strict --scope internal draft.md
python3 scripts/check_continuity.py draft.md
python3 scripts/check_spatial_contract.py scene_map.json
python3 scripts/render_blocking_map_text.py scene_map.json reviews/scene-layout.md
python3 scripts/render_blocking_map_text.py scene_map.json reviews/scene-camera-plan.md --review-type camera_plan
python3 scripts/render_scene_map.py scene_map.json reviews/scene-map.svg --shot shot_01
python3 scripts/check_reference_set.py draft.md
python3 scripts/check_director_workflow.py director-workflow.json
python3 scripts/check_unit_coverage.py unit-plan.json --render-dir units/
python3 scripts/casting_workflow.py --help
python3 scripts/visual_workflow.py --help
python3 scripts/check_v3_artifact.py --help
python3 scripts/render_directing_map.py scene-map.json reviews/directing-map.svg
python3 scripts/project_ledger.py --help
python3 -m unittest discover -s tests -t .
python3 scripts/self_check.py
```

跨层校验采用薄 CLI、Gate 流水线和领域 validator 分层。Adapter 与工作流状态来自
`config/`，镜头卡、coverage、空间审阅、视频生产证据和 Prompt 交付规则分别由
`scripts/shotdesigner/validators/` 下的模块维护；错误码和 CLI JSON 结构保持兼容。

v3.1 `co-direct` 项目使用小型 `project-ledger.json` 与追加式 `review-ledger.jsonl`，用于绑定用户实际确认的产物版本，并按 `config/workflow/dependencies.json` 标记受上游变化影响的当前下游产物。作用域登记角色、定妆状态、场景和单元；它们不复制现有 Manifest、图片资产台账或领域文件的详细事实。

复杂或完整批次应在 manifest 的 `artifacts` 中绑定真实 Prompt 文件和 scene map 的相对路径与 SHA-256。跨层校验器会按已确认执行目标检查直接模型稿或 AutoDL 稿，不只相信内嵌声明。

`render_blocking_map_text.py` 按连续空间直接生成“场景空间确认稿”：空间骨架、人物与关键物件、必要的走位变化、有明确房间边界并同时标出实体和 `C1↑/C2↙` 的俯视平面图、镜头站位说明与必须保持项。门显示在边界上，外部机位显示在边界外，不使用会混淆内外关系的九宫分类表。它不允许手写第二套用户地图；坐标、内部 ID、签名和路线表留在 scene map 与 manifest 内部。`render_scene_map.py` 生成供系统排错的精确坐标、禁入区、机位和视锥 SVG，默认不要求用户阅读。用户可见的布局、路线、落点、机位位置、朝向或拍摄目标变化都会让旧确认失效；焦距和曝光等不改变确认稿内容的技术调整可以继承确认。两种投影都不得加入 `video_inputs`。

## 图片与资产

canonical 角色、场景和道具资产用于锁定身份、外观、场景结构和道具形态。v3 `co-direct` 的演员候选既可在图片 API 已配置时自动生成，也可默认导出单图 Prompt，由用户在任意外部图片工具自行生成和筛选；定妆组件、角色融合、场景母版和同源补充视图沿用同一双路线原则。用户明确回传“选好的”图片时直接登记为选定结果，不再要求候选编号或二次确认。两条路线最终共用文件校验、SHA-256 登记和用户决定合同；Prompt 和接口返回成功都不等于用户批准。

```bash
python3 scripts/casting_workflow.py export-prompt casting-brief.json unit-plan.json project-ledger.json actor-prompt.md --project-root .
python3 scripts/casting_workflow.py import-candidates casting-brief.json unit-plan.json project-ledger.json candidate-batch.json candidates actor-01.png actor-02.png actor-03.png actor-04.png --project-root .
```

```bash
python3 scripts/check_image_quality.py output.png --kind asset
python3 scripts/asset_ledger.py register-user-file --help
python3 scripts/asset_ledger.py validate --path runs/current-project/asset-ledger.json
```

每个案例自行维护隔离的资产目录和台账。用户回传文件使用 `register-user-file` 登记实际路径、来源、生成方和 SHA-256；只有用户明确确认的最终状态资产才能进入本次上传集合。

## AutoDL MiniMax H3 接口

仅当用户确认 `API / AutoDL Art / MiniMax H3` 时使用 `scripts/autodl_minimax_h3.py`。直接模型交付不运行该脚本，也不输出 `ref_image_N`。Token 只通过本地 `.env` 的 `AUTODL_ART_TOKEN` 提供。

直接提交并等待下载：

```bash
python3 scripts/autodl_minimax_h3.py run \
  --prompt-file outputs/current-project/deliverables/unit-01.md \
  --artifact-root outputs/current-project \
  --unit-id U01 \
  --duration 12 \
  --resolution '768p横' \
  --ref-image 'https://example.com/character.png' \
  --ref-image 'https://example.com/scene.png' \
  --prefix current-project-u01
```

只提交或查询已有任务：

```bash
python3 scripts/autodl_minimax_h3.py submit \
  --prompt $'subject_definitions:\n<Subject 1> is the approved character shown in ref_image_0.\nsummary:\n[reference generation] test.\nretention_analysis:\n<Subject 1> ([Shot 1]): fully_preserved.\ndetailed_description:\n[Shot 1] At 00:00.000, hold a stable medium shot.\noverall_soundscape:\nRoom tone.\nnon_diegetic_music:\nN/A' \
  --artifact-root outputs/current-project \
  --unit-id U01 \
  --ref-image 'https://example.com/ref.png'
python3 scripts/autodl_minimax_h3.py poll TASK_ID \
  --artifact-root outputs/current-project \
  --unit-id U01 \
  --request-metadata outputs/current-project/stage5/metadata/videos/current-project-u01_result.json \
  --prefix current-project-u01
```

`--prompt-file` 会自动提取 Markdown 中唯一的 H3 六字段代码块，并在联网前按 AutoDL Art `minimax_h3_zm_u24` 当前适配器合同校验 Prompt 1-10000 字符、时长、分辨率、1-9 张参考图和最多 3 路参考音频。10000 字符是该适配器的请求限制，不代表已核实的 MiniMax H3 官方上下文上限。

每张上传图还必须在实际六字段的 `subject_definitions` 中显式绑定，例如 `ref_image_0 -> <Subject 1>` 写成：

```text
<Subject 1> is the approved character shown exclusively in ref_image_0, preserving the exact face and clothing.
```

客户端要求每个 `ref_image_N` 在一个官方标签定义中恰好出现一次，并把 `api_field / prompt_slot / url` 绑定写入无敏感信息元数据；代码块外的说明不能代替此绑定。canonical 资产使用 `<Subject N>`，actual tailframe 和按需构图图使用 `<Picture N>`。

每次提交必须把 `--artifact-root` 指向当前隔离案例目录。Prompt、请求元数据和下载视频不得越出该目录；客户端会输出可直接登记到 manifest 的 `active_generation`。图片资产台账只管理图片，不能写入视频状态或用户验收。

## Adapter 配置与版本边界

执行目标、能力和机械限制以 `config/adapters/*.json` 为单一事实源。工作流状态、Gate 字段和版本能力分别以 `config/workflow/states.json`、`config/workflow/versions.json` 为单一事实源。配置中的 `evidence` 区分 `adapter_verified`、`project_contract` 与 `user_contract`；Markdown 只解释规则，不作为运行时参数来源。

- 新项目：`schema_version: "2.2"`、`planning_mode: "shot-card-first"`，逐场包含 `scene_direction_briefs/coverage_plans`，每张镜头卡包含 `strategy_selection` 并绑定获批 `camera_id`。
- 既有项目：`2.0/2.1` 保持兼容，不强制补写 v2.2 覆盖层。
- 历史项目：v1 manifest 可只读保留 `storyboards/storyboard_source`，校验器会给出迁移警告。
- 平台执行参数以 `config/adapters/` 为机器事实源；解释性合同位于 [adapters](references/adapters/)。

许可证见 [LICENSE](LICENSE)。

## 前端质量门禁（apps/web）

`apps/web` 的交付强制步骤：**`cd apps/web && npm run gate`**（= 严格 typecheck `tsconfig.app.json` + eslint + `quality-gate.mjs` 静态反模式扫描，详见 `ITERATION_QA.md` 反例库 R1-R10）。`GATE=0` 才允许交付。

仓库根 `.husky/pre-commit` 已在提交时自动执行该门禁（`git config core.hooksPath .husky` 已生效，本仓库本地已配置）。新 clone 者需执行一次：

```bash
git config core.hooksPath .husky
```

紧急跳过（仅用于明确例外）：`SKIP_GATE=1 git commit`。质量与反例清单的单一权威见 `ITERATION_QA.md`。
