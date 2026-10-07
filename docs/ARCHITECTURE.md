# 架构说明

## 分层

```text
AstrBot 消息事件 ──> main.py ──> commands.Router ──> 各功能模块的指令处理函数
AstrBot 插件页面 ──> web/api.py ──> web/service.py ──┘（后台房间操作复用同一套指令）
                                        │
              ┌─────────────────────────┼──────────────────────────┐
         rooms/lifecycle         plays/hosted、collaboration     plays/custom
              │                         │                          │
              └──── storage.Store（SQLite） ──── engine.gateway ───┘
                                                     │
                                         vendor/story_engine（321Roll 世界引擎）
                                                     │
                                         engine.bridge ──> AstrBot 聊天模型
```

平台（Lite）掌握权威状态：权限、骰子、资源、记录版本和回合顺序都由 Lite 决定并写库。世界引擎只做两件事：校验玩法动作并提出记录操作提案（纯函数），以及在模型调用前后编译上下文、校验模型输出。模型只写正文、选项和建议，不能改骰面和数值。

## 模块

| 模块 | 职责 |
|---|---|
| `main.py` | AstrBot 插件入口：识别 `/团` 与 `／团`，构造 `Caller`，把回复发回群里 |
| `roll_lite/app.py` | 装配配置、数据库、引擎网关、路由、钩子和定时器（每 5 秒一次 tick） |
| `roll_lite/commands.py` | 指令路由（支持“主持 直述”这样的两级指令）、`#编号` 与 `[属性 难度]` 解析 |
| `roll_lite/render.py` | 结构化消息 `Msg`（区块：标题、引用、检定、资源条、选项……），渲染成 Markdown 或纯文本 |
| `roll_lite/messages.py` | 全部消息排版：开团卡、角色卡、个人状态、正文、选项、表决、玩法回执、状态、终章、帮助 |
| `roll_lite/delivery.py` | 投递：按全局设置和平台选择格式，Markdown 拒收后降级，三段转图片，@ 提及，分段间隔与合并，失败进入待重发 |
| `roll_lite/cards.py` | 图片卡：把 `Msg` 排成白金/黑金两套卡片 HTML（状态、正文、选项三种版式），尺寸随渲染视口等比缩放；封面配色与大字 |
| `roll_lite/loadout.py` | 技能与物品规则（移植自 321Roll 全量版）：行动准备、直接使用、装备与丢弃、按场景或休整恢复次数 |
| `roll_lite/adjust.py` | 主持调整队列：后台提交，在下一回合正文提交时生效 |
| `roll_lite/people.py` | 人物表：模型 NPC 与关系记录合并，态度针对队伍，记录每位玩家的影响 |
| `roll_lite/plays/kit.py` | 背包、使用、装备、卸下、丢弃、主持 新场景、人物、私聊切换 |
| `roll_lite/storage.py` | SQLite 表结构与写事务（`BEGIN IMMEDIATE`，带版本号检查） |
| `roll_lite/features.py` | 玩法开关：全局默认加单群覆盖，带依赖关系 |
| `roll_lite/worlds/catalog.py` | 世界格式校验（移植自 321Roll）、内置、自定义与市场世界、世界简介；市场版版本号不低于内置版时替换内置文本版 |
| `roll_lite/worlds/package.py` | 世界安装包（`321roll-lite.world-package/1`）：可复现的打包，以及写盘前的完整校验（文件白名单、大小、sha256、图片格式、世界内容） |
| `roll_lite/worlds/market.py` | 世界市场：索引与下载线路（jsDelivr / 代理前缀 / 直连，失败回退直连一次）、安装、更新、卸载、场景图读取、导出安装包 |
| `roll_lite/rooms/lifecycle.py` | 开团、入座、选职业、开演、暂停、完结、收桌、存读档、状态 |
| `roll_lite/plays/hosted.py` | 托管回合：开场、行动理解、平台掷骰、正文、A–D 选项、超时自动选择、主持指令 |
| `roll_lite/plays/collaboration.py` | 全队提议、集体事件与表决 |
| `roll_lite/plays/custom.py` | 14 类引擎玩法：指令解析、调用引擎、掷骰选分支、按版本号落库 |
| `roll_lite/engine/gateway.py` | 引擎唯一入口；模型输出被引擎拒绝时带拒绝原因重试，最多 3 次 |
| `roll_lite/engine/bridge.py` | 引擎的 PlatformBridge：调用 AstrBot 模型，附上按本房规则调整过的 JSON Schema，记录调用 |
| `roll_lite/web/` | 后台接口；`service.py` 是纯函数，`api.py` 注册到 AstrBot，`preview.py` 用真实排版生成消息样例 |
| `pages/admin/` | 后台页面（原生 HTML/CSS/JS 模块，无构建步骤）；`views/world_editor.js` 是七步世界编辑器，前端校验对应 `catalog.validate_world`，保存时仍以后端校验和引擎编译为准 |

模块之间通过 `app.hooks` 通知：`story_started`、`roster_changed`、`room_paused`、`room_resumed`、`story_completed`、`room_closed`、`room_restored`、`status_lines`、`tick`。

## 消息投递

功能代码只返回 `Reply.messages`（`Msg` 或短字符串），不关心平台。`delivery.deliver()` 统一处理：读取 `message.prefs`，用 `render.target_format()` 决定格式（全局选 Markdown、平台在支持名单里、且未被记为拒收），把标为 `status`、`narration`、`choices` 的段落按开关交给 `cards.card_html()` 排版，再经 `Star.html_render` 出图（JPEG 质量 92）；失败时退回 `Star.text_to_image`，再失败发文字。带 `Msg.art` 的正文卡由 `delivery.card_art()` 取市场安装的场景图做横幅，取不到就用封面配色和大字。其余段落渲染成文字后按 1800 字切分，再逐条发送并按间隔等待。发送 Markdown 失败时，把该平台写入 `message.markdown_blocked`，从失败的那一条起改用纯文本重发。指令回复走 `event.send`，主动消息走 `context.send_message`，后者失败时写入待重发表。

## 托管回合

1. 开演时调用 `generate_initial_story`，写入场景、目标、NPC，并为第一位玩家生成 A–D 选项（每项带检定规则）。
2. 玩家 `/团 选 A` 时，平台直接按该选项的检定规则掷骰；`/团 行动` 时先调用 `propose_intent` 由模型判断是否需要检定。
3. 骰果和资源变化先写入 `turns.receipt_json`，再调用 `narrate_committed` 生成正文、事实、NPC 和下一轮选项。正文失败时骰果保留，主持人 `/团 主持 重试`。
4. 超时由 tick 发现，调用 `rank_timeout_choices` 选风险最低的选项。

## 引擎玩法

`custom.perform()` 读取该玩法需要的记录，连同成员和房间规则交给 `evaluate_custom_play`；引擎返回按结果分支（always、success/failure 或抽签区间）组织的操作。Lite 只接受 `create`、`update`、`resources`、`harm`、`complete_room` 五种操作，掷骰后在一个事务里核对记录版本并落库。动作含检定、抽签、耗时、休整或险关结算时，要求轮到本人，并在完成后把回合交给下一位。允许的动作清单见 `custom.ALLOWED`，与 [PLAY_SCOPE.md](PLAY_SCOPE.md) 一致。

## 数据表

`rooms`、`actors`、`records`（玩法记录，`seq` 即 `#编号`）、`turns`、`events`（时间线）、`facts`、`npcs`、`votes`、`operations`、`model_calls`、`saves`、`outbox`、`audit`、`settings`、`worlds`（自定义世界和市场安装的世界，后者 `origin_json` 记录来源、sha256、场景图对照和资源目录）。每个群同时最多一桌未收桌的团（`rooms_one_open` 唯一索引）。

市场安装先在内存里校验整个安装包并编译世界，再把原始 zip 和图片写到 `<数据目录>/market/<世界>/r<版本>-<sha8>/`，写入 `worlds` 表后才删除旧目录，中途失败时数据库始终指向一份完整的资源。插件页运行在受限 iframe 里，读不到数据目录，所以场景图通过 `worlds/image` 以 data URL 返回；市场卡片的预览图由浏览器按所选线路直接加载。

## 与 321Roll 同步

- 世界引擎：`tools/sync_engine.py` 原样复制 `321Roll/source/engine/story_engine`，并在 `vendor/ENGINE_MANIFEST.json` 记录版本和每个文件的 SHA-256。不要直接修改 `vendor/`。
- 世界包：`tools/sync_worlds.py` 原样复制 `pack.json` 与 `presentation.json`，不带场景图。`tools/pack_worlds.py` 再用 321Roll 的场景图生成市场安装包、640 宽预览图和 `index.json`，同样的内容总是得到字节相同的 zip。
- 模型输出 Schema：`roll_lite/engine/model_output.py` 复制自 321Roll `contracts/model_output.py`；桥接层发送前会删除 Lite 不使用的上下文扩展字段，并把属性、难度枚举换成本房的值。
