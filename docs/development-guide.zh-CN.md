# 开发交接指南（第 3 周版）

本文件取代交接包里描述第 1、2 周单用户代码的旧版 `development-guide.zh-CN.md`。第 3 周重写了数据层并加入账号，旧版关于表结构和函数签名的说明已经过时。这一版对应仓库当前代码。

我们的协作方式是**按周轮替**：每周一个人全权推进，另一人 review。本文件让接手下一周的人能直接从仓库看懂现状，不必回头翻交接包。

## 第 3 周做了什么

一句话：把单用户原型改成**每个账号数据隔离**，并把备注里那串自由文本的"课程/项目"换成真正的实体。

改动的动机、逐条对照和几个判断决策，写在 [week-03.md](week-03.md)。这里只讲**接手代码时需要知道的东西**。

## 先跑通一次

```bat
setup.cmd
start.cmd
```

打开 http://127.0.0.1:5000，先注册一个账号（或先跑 `scripts\seed_demo.py`，再用 `demo` / `demo-password` 登录）。首页默认显示**当前这一周**，要看样例课表用顶部日期选择器跳到 2026-09-28。

跑测试：

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

预期 **33 项通过**。用 `.venv\Scripts\python.exe` 全路径，别用裸 `python`（会用到没装 Flask 的系统解释器）。

## 读代码的顺序

| 文件 | 先关注什么 | 什么时候要改 |
| --- | --- | --- |
| `run.py` | 调 `create_app()`，监听本机 5000 | 改启动参数时 |
| `planner/db.py` | 表结构（`_DDL`）、版本探测、`_migrate_v1_to_v3` | 加表/改表/加字段时 |
| `planner/auth.py` | 注册登录、`require_owner` 守卫、`owned_or_404`、legacy 接管 | 改账号或权限规则时 |
| `planner/__init__.py` | 路由、每条查询的 `owner_id` 过滤、课程/项目解析 | 加页面或用户操作时 |
| `planner/importer.py` | `parse_csv` / `comparison` / `prepare` / `confirm` / `ensure_course` | 改导入规则或加格式时 |
| `planner/reports.py` | 快照排版成 PDF、中文字体 | 改周报结构/分页/字体时 |
| `planner/templates/*` | 登录、注册、周页面、上传、预览 | 改交互时 |
| `tests/test_milestone.py` | 33 个检查 | 每次改逻辑前后都要读相关用例 |

## 归属校验：最重要的一条规矩

**每条读写记录的 SQL 都必须带 `owner_id=?`。** 这不是可选的最佳实践，是 Task 2 NFR-S1 的硬要求：

> 把别人的记录从菜单里藏起来不够；直接输入它的标识符访问，也必须被拒绝。

所以：

- 不要用"查出来再在 Python 里过滤"的写法，要在 SQL 里就带上 owner。
- 访问别人的记录要返回 **404，不是 403**。返回 403 等于告诉对方"这个 id 存在，只是不是你的"，泄露了别人有数据这件事。`auth.owned_or_404()` 就是干这个的。
- 新增路由时，`auth.require_owner(app)` 的 `before_request` 守卫默认拦截所有非公开路由（公开的只有 `login`、`register`、`static`）。**加新路由不需要额外写登录检查，但要确认它不在公开名单里、并且查询带了 owner。**

跨账号隔离的测试是 `test_two_accounts_can_import_the_same_source_keys`、`test_report_download_is_owner_scoped`、`test_cross_account_preview_token_rejected`。改归属逻辑前先读这三个。

## 数据库版本与迁移

`db.py` 里 `SCHEMA_VERSION = 3`。每次启动 `initialize()` 会：

1. 探测当前库版本（`detect_version`）：有 `schema_meta` 读版本号；只有旧 `events` 表算 v1；全新库算 v0。
2. v0 → 直接建最新表。v1 → 跑 `_migrate_v1_to_v3`。已是 v3 → 什么都不做。库版本比程序高 → 拒绝启动。

**改表结构时的规矩**（`development-guide` 旧版就警告过，这里再强调）：

- `CREATE TABLE IF NOT EXISTS` 对**已存在**的表是静默跳过，不会加新列。所以给已有表加字段，必须写迁移函数，不能只改 `_DDL`。
- 迁移要放**一个事务**里，失败整体回滚，不能留半新半旧的库。`_migrate_v1_to_v3` 是范本：先备份 `.pre-v3.bak`，改名旧表，建新表，搬数据，末尾 `_verify_counts` 核对行数，任何不一致就 `raise` 触发回滚。
- 迁移里**不要用 `executescript`**——它会先提交当前事务，破坏原子性。逐条 `db.execute`。
- 加新迁移时，写一个新的 `_migrate_v3_to_v4`，在 `initialize` 里按版本分派，并把 `SCHEMA_VERSION` 提到 4。**不要就地改 v1→v3 的逻辑**，那样已经迁移过的库不会重跑。

迁移测试：`test_v1_database_is_migrated_with_data_intact`、`test_first_registration_adopts_legacy_data`。

## 一次 CSV 导入经过哪里

和旧版流程一样，但每一步都带了 `owner_id`：

1. `POST /import` → `prepare(db, owner_id, raw)`：`parse_csv` 严格校验（一行不合格整份拒绝），把行数据和**该账号当前的** `timetable_revision` 存进 `previews`，发一个 token。
2. `GET /import/<token>` → `comparison(db, owner_id, rows)`：按 `source_key` 判 Added / Updated / Unchanged，预览页并排显示新旧值。
3. `POST /import/<token>/confirm` → `confirm(db, owner_id, token)`：开事务，核对 token 属于本人且 revision 未变，`ensure_course` 建/更新课程，Added 用 INSERT、Updated 用 **UPDATE（保留 id，notes.event_id 才不会断）**，每条变更写进 `event_changes`，revision +1，删 token，提交；异常回滚。

两个和旧版不同的点：

- `source_key` 现在只在**账号内**唯一（`UNIQUE(owner_id, source_key)`），行的真正身份是 `events.id`。两个账号可以都有 `demo-se-001`。
- `events.state`（scheduled/cancelled）**不参与 comparison**，重复导入不会把取消的课恢复，也不会报成变更。改 `state` 目前只能改库，取消课的界面是 Week 4。

`parse_csv` 新增一条校验：同一份文件里一个 `course_code` 配了两个不同 `course_title` 会被拒（否则标题会随行翻转、最后一行静默胜出）。CSV 对外的八字段契约没变，见 [import-format.md](import-format.md)。

## 一次 PDF 导出经过哪里

`POST /reports` → `weekly_records(db, owner_id, week)` 查本人本周的课程和记录 → 校验所选 note 都属于本周（别人的 note id 和跨周的 note 一样被拒，不区分）→ 只把选中字段放进 snapshot → `render_pdf` → `reports` 表同时存 `snapshot_json` 和 PDF 字节。

`GET /reports/<id>.pdf` 用 `auth.owned_or_404`，别人的 id 返回 404。

**旧周报冻结**：snapshot 存的是导出当时的值，重开旧版本读的是存的字节，不按最新数据重生成。以后加备注编辑功能，也**绝不能**把历史周报改成"每次下载查最新备注"，否则版本含义就没了（DR-7）。中文字体文件必须保留，否则变方框。

## 课程 / 项目 / academic_items

- `courses`：有 `owner_id` + `code` + `title`，`(owner_id, code)` 唯一。导入时 `ensure_course` 按 code 找，找不到就建，title 变了就地更新（不新建）。
- `projects`：研究项目，`(owner_id, title)` 唯一。备注表单可以新建项目——这是 DR-3 要求的，没课表的研究生不必伪造一门课。
- `academic_items`：**Week 3 建了表和 CHECK 约束，但还没有数据、没有界面**。它是 Week 4 要求修订历史的父记录：一个 assignment/examination 是一个 item，它下面挂多条 dated revision。`kind` 限定 `Assignment/Examination/Meeting/Reading/Experiment/Writing`，`official_due` 留给 Week 5 区分官方截止与个人计划（DR-5）。
- `notes` 现在通过 `course_id` / `project_id` / `item_id` 指向真正的父记录（至少一个非空，有 CHECK 约束），`context` 字段保留只是迁移时的参考文本，不再是权威来源。

## 路由一览

| 请求 | 用途 | 公开? |
| --- | --- | --- |
| `GET/POST /register` | 注册（成功后自动登录） | 是 |
| `GET/POST /login` | 登录 | 是 |
| `POST /logout` | 登出 | 否（需登录） |
| `GET /?week=` | 周视图，默认当前周 | 否 |
| `GET/POST /import` | 上传页、解析上传 | 否 |
| `GET /import/<token>` | 预览变更 | 否 |
| `POST /import/<token>/confirm` | 确认批次 | 否 |
| `POST /import/<token>/cancel` | 取消批次 | 否 |
| `POST /notes` | 创建记录 | 否 |
| `POST /reports` | 生成并保存周报 | 否 |
| `GET /reports/<id>.pdf` | 下载已保存版本 | 否 |

POST 表单都要带 `csrf` 字段；新页面照现有模板处理。**不要为了让请求通过而关掉校验或放宽归属。** SQL 继续用参数占位符，页面内容继续靠模板转义。

## 给 Week 4 接手的人

要求修订历史需要稳定的父记录，那就是 `academic_items`（现在空着）。给一个要求建 item，每次措辞变化作为一条 dated revision 挂在下面，旧文本仍可查（REQ-1.6、DR-4）。验收例子沿用旧指南：**老师更新考试范围 → 新措辞显示为当前 → 旧版本仍可找到 → 已导出的 PDF 不变**。

顺着 Week 3 的归属模式做：每条查询带 `owner_id`，别人的 id 回 404。取消课的界面（`events.state` 已有列和保留逻辑）也可以放在 Week 4，和"课表变更历史展示"一起做，因为都围绕 event。

## 用 GitHub 协作

仓库：https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST

第 3 周的开发在 `feature/account-ownership` 分支上做。合并前请另一人 review。改动前先更新本地默认分支再建自己的功能分支。PR 写清用户操作、结果和实际测试。

**不要提交** `instance/`、`.venv/`、`secret.key`、`.pip-cache/`、`.install-tmp/`、本地数据库——`.gitignore` 已覆盖。注意 `reports/` 目录**没有**被忽略，别往里放导出的周报 PDF 或个人数据（会违反 NFR-S4 的公开包隐私检查）。保留字体许可和第三方声明。

复现问题时记录：用哪个 CSV、卡在哪步、预期 vs 实际、完整报错文字。不要只写"导入坏了"。
