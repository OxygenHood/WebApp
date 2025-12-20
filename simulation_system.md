# 仿真系统设计文档

## 引言
- 目标：面向既有目标分配与火力分配算法的效果验证，构建可视化仿真系统，支撑算法在台海作战场景下的快速对比、调优与结果留痕。
- 范围：涵盖用户登录、作战场景配置、模型管理与选择、地图仿真演示及日志存证；不包含训练环节，模型由外部生成后接入。
- 受众：算法与系统研发人员、测试人员以及指挥决策支持相关的业务方。

## 仿真系统需求分析
- 功能需求
  - 认证与权限：`/login`、`/logout`，会话由 `app.secret_key` 管理，所有业务页均需登录。
  - 场景管理：台海作战场景的创建/编辑/软删除；支持地图选点录入我方无人机（坐标/高度/载荷雷达、AR-1、PL-10、机炮）与敌方侦察无人机、武装直升机、坦克、装甲车、军事基地等单位及编号。
  - 模型管理：扫描 `models/target_allocation` 与 `models/fire_allocaltion` 下模型产物，解析 `config.json`、`progress.txt`、目录元数据，入库去重，展示算法/环境/场景、步数、最佳指标，支持重命名与奖励曲线查看。
  - 仿真评估：`/simulation` 需同时选择场景、目标分配与火力分配模型后方可启动；基于 Leaflet 地图渲染单位、目标高亮与动态连线，支持开始/暂停/停止重置。
  - 日志记录：前端交互、仿真事件、异常通过 `/api/save_log` 统一落盘到按日分文件的 `logs/`。
  - 数据接口：`/api/scenarios`、`/api/scenario/<id>`、`/api/models`、`/api/model/<id>/rename`、`/model/<id>/reward` 为前端下拉、详情与图表提供数据。
- 数据与存储
  - 数据库：SQLite 文件 `webapp.db`。核心表
    - `users(id, username, password_hash)`：登录账户。
    - `scenarios(id, name, description, created_by, created_at, status, our_drone_count, our_drone_positions, our_drone_payloads, enemy_reconnaissance_drones/positions, enemy_attack_helicopters/positions, enemy_tanks/positions, enemy_armored_vehicles/positions, enemy_military_bases/positions)`。
    - `models(id, name, category, seed, version, algo, env, scenario, config_path UNIQUE, progress_path, status, best_score, last_step, created_at)`：文件系统同步而来，`config_path` 唯一索引避免重复。
  - 文件系统：`models/`（目标/火力分配模型目录，含 config/progress/reward.png）、`logs/`（按日仿真日志）、`static/config/`（敌方单位价值与武器配置 JSON）。
- 非功能需求
  - 可用性：地图交互（Leaflet）、状态徽标与必选提示降低误操作；侧边栏记忆展开/宽度。
  - 扩展性：模型目录新增即自动同步；场景/单位类型、武器/敌方配置可通过 JSON 扩展。
  - 可运维性：日志按日分文件；模型路径归一化与唯一索引阻止重复入库，异常容错保留已有数据。

## 系统设计
- 总体架构
  - 前端：Flask + Jinja2 产出页面；Leaflet 负责地图；原生 JS 负责模型/场景选择、仿真循环、日志上报；`static/config` 提供敌方单位价值与武器参数。
  - 后端：`app.py` 内集中路由，页面与 API 共享；SQLite 持久化；文件系统扫描同步模型；`send_file` 提供奖励曲线。
  - 布局：`templates/base.html` 提供侧边导航/头部，导航状态与宽度通过 `static/js/script.js` 记忆并可拖拽调整。
- 核心模块与路由
  - 认证：`/login` 登录校验（SHA256 哈希）、`/logout`；`login_required` 装饰器保护业务页。
  - 场景：`/pipeline` 列表（仅 active），`/create_scenario`/`/edit_scenario/<id>` 表单校验并存储无人机/敌方 JSON，`/delete_scenario/<id>` 软删除（状态置 deleted）。
  - 模型：`/model` 分组展示，`/model/<id>` 读取配置与奖励曲线，`/model/<id>/reward` 输出 PNG，`/api/model/<id>/rename` 重命名。
  - 仿真：`/simulation` 页面，依赖 `/api/scenarios`（下拉列表）与 `/api/scenario/<id>`（地图数据）和 `/api/models`（模型下拉）。
  - 日志：`/api/save_log` 接收前端日志，按日写入 `logs/simulation_YYYYMMDD.txt`，格式 `[时间][级别][用户名] message`。
- 数据存储设计
  - `users`：`(id, username UNIQUE, password_hash)`。
  - `scenarios`：位置字段以多行文本 `lat,lng[,alt/code]` 存储；`our_drone_payloads` 存入聚合值与每架无人机细节（高度、编号、载荷）；默认高度/载荷回填以兼容老数据。
  - `models`：新增时归一化 `config_path` 相对 `models/`，并建唯一索引；记录算法/env/scenario、种子、目录时间戳、进度步数与最佳得分；`status` 默认 available。
  - 文件：模型目录命名 `seed-<seed>-<yyyy-mm-dd-hh-mm-ss>`，内含 `config.json`、`progress.txt`、`reward.png`；仿真日志每日新文件；武器与敌方价值配置以 JSON 供前端读取。
- 模型同步流程
  - `ensure_models_table()` 创建表并调用 `deduplicate_models()` 用规范化路径合并重复。
  - `collect_models_from_fs()` 遍历模型目录，解析 `config.json` 的 `main_args/algo/env/exp_name` 与 `env_args/scenario`，从进度文件滚动提取 `last_step/best_score`，并解析目录名获取 `seed/version`。
  - `sync_models_from_fs()` 用 `INSERT ... ON CONFLICT(config_path)` 写入或更新，保证页面/API 读取前最新。
- 场景处理与兼容
  - 创建/编辑时要求至少一架无人机；存储时汇总载荷总量及每架载荷；敌方单位数量与位置分字段存储，编号随位置行尾。
  - 读取详情时优先解析 `our_drone_payloads.drones`，缺失字段回填默认高度/载荷；按数量与位置行恢复敌方单位对象，兼容旧的三字段或四字段格式。
  - 删除采用软删除，列表与 API 仅返回 `status='active'` 数据。
- 仿真渲染与逻辑
  - 地图以台湾海峡为中心，提供卫星/标准/地形多底图与比例尺；单位使用自定义 divIcon 标记与弹窗/Tooltip。
  - 页面加载即获取敌方单位价值配置与武器配置，作为目标价值与射击参数；开始仿真前要求场景 + 目标/火力模型均已选择。
  - 目标选择：综合敌方价值、距离、现有分配负载三项权重选择最优目标，记录分配次数；点击无人机高亮当前目标并画连线。
  - 运动与交战：按单位类型速度逐步逼近目标/随机航迹，定时尝试射击；依据武器射程/命中率/毁伤率判定结果并消耗载荷；击毁后移除标记并重新分配目标。
  - 控制：开始/暂停/继续共用按钮，停止会终止循环并重新加载场景复位；关键事件通过 `/api/save_log` 落盘。
- 接口清单（主要）
  - 页面：`/` 首页统计、`/pipeline` 场景、`/model` 模型、`/model/<id>` 详情、`/simulation` 仿真。
  - API：`/api/models`、`/api/model/<id>/rename`、`/api/scenarios`、`/api/scenario/<id>`、`/api/save_log`、`/model/<id>/reward`。

## 仿真系统工作流程
1) 登录：用户在 `/login` 认证成功后进入首页，带会话状态访问各功能。
2) 场景配置：在 `/create_scenario` 或 `/edit_scenario/<id>` 录入我方无人机（经纬高、载荷雷达/AR-1）与敌方单位（类型、数量、坐标、编号），保存入库。
3) 模型准备：将目标分配/火力分配模型成果置于对应目录，`sync_models_from_fs()` 自动扫描入库，前端下拉实时可选；可在模型详情查看奖励曲线或重命名。
4) 仿真设置：在 `/simulation` 选择场景后加载至地图，选择目标分配与火力分配模型，状态牌显示当前选择与就绪状态。
5) 仿真运行：点击“开始仿真”后初始化运动数据、加载武器/敌方配置，单位按速度/航迹移动并按射程概率攻击目标；可暂停/继续或停止重置，过程事件与射击结果写入日志。
6) 结果观测：通过地图标记、弹窗、目标高亮连线、状态徽标与日志文本验证两类算法在当前场景下的协同表现，为后续算法调优与再训练提供依据。
