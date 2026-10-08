💬 AI 跑团项目交流群：`696202708`\
🍵 闲聊与约团小窝：`1094220887` &#x20;

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/horizoe10/astrbot_plugin_321roll_lite@main/pages/admin/assets/logo-main.png" width="140" alt="321Roll Lite" />
</p>

<h1 align="center">321Roll Lite</h1>

<p align="center">
  <b>🎲 把跑团桌搬进群聊：AI 当主持，骰子说了算，发一句 <code>/团</code> 就能开局。</b>
</p>

<p align="center">
  <a href="https://github.com/horizoe10/astrbot_plugin_321roll_lite/releases"><img src="https://img.shields.io/github/v/release/horizoe10/astrbot_plugin_321roll_lite?style=flat-square&color=b8925a&label=release" alt="release" /></a>
  <img src="https://img.shields.io/badge/AstrBot-%E2%89%A5%204.26-2b2118?style=flat-square" alt="AstrBot >= 4.26" />
  <img src="https://img.shields.io/badge/Python-%E2%89%A5%203.11-2b2118?style=flat-square" alt="Python >= 3.11" />
  <a href="https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-b8925a?style=flat-square" alt="AGPL-3.0" /></a>
</p>

<p align="center">
  <a href="#-为什么选它">✨ 特色</a> ·
  <a href="#-安装与配置">📦 安装</a> ·
  <a href="#-三分钟开第一桌">🚀 上手</a> ·
  <a href="#-常用指令">📜 指令</a> ·
  <a href="#-六个世界">🗺️ 世界</a> ·
  <a href="#-管理后台">🛠️ 后台</a>
</p>

> 🍺 **AI 酒馆的老朋友看这里：** 321Roll Lite 由 **AI 酒馆**（`astrbot_plugin_tavern`）迭代而来，是 **321Roll** 跑团平台的群聊轻量版。它沿用 321Roll 的世界引擎和世界包规格，能在 QQ、Telegram 等 AstrBot 支持的群聊里直接用。

---

## ✨ 为什么选它

想跑团，却凑不齐时间、找不到主持人，新人又看不懂厚厚的规则书？装上 321Roll Lite，群里几分钟就能开一桌。AI 主持人依据世界设定讲故事，插件掷骰裁定成败，轮到你时点一个选项或者自己写行动就行。不用另装客户端，聊天和跑团都在同一个群里。

- 🎭 **AI 即兴主持**：每一轮剧情由大模型按大家的决定续写。NPC 记得发生过的事，对全队的态度在“敌对”到“盟友”七档之间变化。
- 🎲 **插件掷骰，AI 改不了**：带检定的行动先由插件掷 d20、算加值，骰果落定后才交给 AI 写正文。属性决定底子，运气决定临场。
- 🅰️ **新人点选，老手自由写**：每轮给出 A–D 四个方向，标好难度和风险；老手可以自己描述行动，再带上技能和物品。
- ⏱️ **超时托管，全桌不卡**：每回合有倒计时，有人挂机就自动替他选风险最低的一项，主持人也能随时调整时限。
- 🔍 **16 类文字玩法**：搜查线索、假设推理、证词对质、谈判签约、追逐对抗、拟定计划、机运问卜、神谕和多结局，跑团不止打架。
- 🤫 **私聊群聊两条线**：建卡、看属性、理背包、暗中用药都可以私聊 bot 完成，群里只留下故事本身。

---

## 📦 安装与配置

**运行环境**：AstrBot ≥ 4.26 · Python ≥ 3.11 · 不需要额外的第三方依赖，故事引擎已内置在 `vendor/`。

1. 🛒 **市场安装**：在 AstrBot 插件市场搜索安装，或在插件面板填入仓库地址 `https://github.com/horizoe10/astrbot_plugin_321roll_lite`。
2. 📁 **离线安装**：下载 [Release](https://github.com/horizoe10/astrbot_plugin_321roll_lite/releases) 里的 zip，在面板上传，或解压到 AstrBot 的 `data/plugins/`。
3. 👑 **配置管理员**：在插件配置里填管理员用户 ID（AstrBot 超级管理员默认有权限），需要时开启群白名单。
4. 🤖 **绑定模型**：默认使用各群当前的聊天模型，也可以在插件后台指定专用模型。

> 🧪 **模型兼容**：DeepSeek 这类不严格遵守结构化格式的模型也能用。插件会自动补齐缺失字段、清理多余内容，让故事顺利往下走。

---

## 🚀 三分钟开第一桌

装好插件、配好模型以后，三步就能开团：

> **1️⃣ 开一桌** 管理员在群里发送 `/团 开启`，按序号挑一个世界。
>
> **2️⃣ 入座建卡** 玩家发送 `/团 加入` 入座，再私聊 bot 发送 `/团 选职业 1 角色名` 建卡。
>
> **3️⃣ 开演** 主持人发送 `/团 开演`，AI 给出开场和第一轮选项，冒险开始。

之后轮到谁，谁就在群里发 `/团 选 A`。忘了指令就发 `/团 帮助`。

### 🎬 一局大概长这样

```text
/团 世界                      看看能开哪些世界
/团 开启 1                    管理员开团，选第 1 个世界
/团 加入                      玩家入座
/团 职业                      私聊 bot 看可选职业（群里也行）
/团 选职业 1 林晓              私聊建卡，群里会同步入座公告
/团 开演                      主持人开场，AI 铺开现场并给出第一轮选项
/团 选 A 小心地推门            轮到你时选一项，可以顺手补一句演绎
/团 行动 我爬上房梁检查电线     也可以自己写行动
/团 选 A [用 手电筒]           带上物品或技能，加值自动算进检定
```

🎯 **检定怎么算：** d20 + 属性 + 装备和技能修正，对比难度。简单 8、标准 12、困难 15、极难 18。回合默认 5 分钟，超时自动选风险最低的一项，主持人可以加时，也可以设为不限时。

---

## 📜 常用指令

所有指令都以 `/团` 开头。

| 分类 | 指令 | 用来做什么 |
|---|---|---|
| 🪑 入座 | `世界` `开启` `加入` `职业` `选职业` `角色` `阵容` `退出` `暂离` `返回` | 开桌、入座、建卡、看角色卡 |
| ⚔️ 行动 | `选` `行动` `跳过` `回合` `顺序` `回顾` `全队` `投` `表决` | 选选项、写行动、全队提议与表决 |
| 🎒 道具 | `背包` `技能` `使用` `装备` `卸下` `丢弃` | 看持有物和剩余次数，用、穿、丢 |
| 🔍 调查 | `线索` `搜查` `假设` `结论` `引用` `证词` `追问` `出示` `对照` | 搜证、立假设、质询证人、对照矛盾 |
| 🤝 交涉 | `交涉` `条款` `签署` `关系` `目标` `人物` | 谈判签约、NPC 态度、同伴目标 |
| 🔥 对抗 | `冲突` `辩论` `交锋` | 进度轨对抗、追逐、辩论、孤注一掷 |
| 🗓️ 计划 | `计划` `执行` `时间` `期限` `项目` `休整` | 多步计划、四时日历、期限、长线项目 |
| 🔮 叙事 | `机运` `神谕` `转变` `结局` `尾声` | 问运气、问神谕、角色转变、多结局 |
| 📒 记录 | `记录` `查看` | 用 `#编号` 翻看线索、条款、计划、冲突 |
| 🎬 主持 | `开演` `暂停` `恢复` `完结` `关闭` `存档` `读档` `主持` | 控节奏、回退、审稿、换幕、交棒 |
| 💌 私聊 | `切换` | 同时在多个群入座时，私聊里选当前操作哪一桌 |

💡 记录用 `#编号` 互相引用，例如 `/团 假设 #3 支持 #2`；需要检定的行动在句末写 `[属性 难度]`，例如 `/团 搜查 讲台抽屉 [观察 标准]`。

### 📚 玩法手册

| 手册 | 讲什么 |
|---|---|
| 📘 [核心规则与行动](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/CORE_RULES.md) | 回合轮换、选项与自由行动、d20 算式与难度、技能物品消耗、装备栏位、私聊群聊分工 |
| 🔎 [调查推理与证词对质](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/INVESTIGATION.md) | 搜查检定、线索归档、假设支持与反驳、证词追问、出示物证、矛盾对照 |
| 🤝 [社交交涉与对抗冲突](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/INTERACTION_AND_CONFLICT.md) | 谈判与签约、NPC 七档态度、对抗轨道、孤注一掷、追逐、辩论 |
| 🗓️ [计划时间与叙事走向](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/PLANS_AND_STORY.md) | 多步计划、四时日历、期限与项目、休整、机运、神谕、多结局与尾声 |
| 🎬 [主持人手册](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/HOST_GUIDE.md) | 团桌生命周期、调度顺序、最多回退 5 步、文风篇幅校准、暗中调整、审稿模式、存档读档 |
| 🧭 [世界包制作教程](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/WORLD_PACK_GUIDE.md) | 从模板写一个自己的世界，配图、打包、发布到世界市场 |
| 📐 [世界包规范](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/WORLD_PACK_SPEC.md) | 命名与版本、内容要求、各个 json 与安装包、索引的字段说明 |

---

## 🗺️ 六个世界

插件自带一个纯文字世界，装好就能开团；其余五个在后台“世界 → 世界市场”从官方渠道一键安装，插件本体保持小巧。

| 世界 | 一句话 | 获取 |
|---|---|:-:|
| ⛏️ **灰冠之下：祖约** | 深矿之下不可违背的古老契约 | 📦 自带 |
| 🔔 **第七个不思议** | 放学后多敲一下的钟楼，校园怪谈 | 🛒 市场 |
| 🏹 **狩火** | 群兽迁徙的灾年，原野上的猎杀 | 🛒 市场 |
| 🗡️ **无名剑冢** | 刻在绝壁上的潮痕，一曲武侠悲歌 | 🛒 市场 |
| 🌃 **霓虹典当行** | 抵押整座城市昨日记忆的赛博夜宴 | 🛒 市场 |
| 🎭 **封箱戏** | 锁园里不敲自鸣的铜锣，梨园灵异 | 🛒 市场 |

🖼️ 市场里的六个世界都有带 1280 宽场景图的图文版，也可以填其他索引地址安装社区世界。安装前会核对安装包的 sha256 和每个文件；灰冠之下的图文版会覆盖自带的文字版，卸载后自动恢复。

✍️ **想写自己的世界？** 从 `worlds/_template/` 里的示例世界“雾港灯塔”改起，写好后用自带的打包命令生成安装包和索引：

```bash
python -X utf8 -m roll_lite.worlds.make <世界文件夹> --out <输出目录>
```

完整步骤见 [世界包制作教程](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/WORLD_PACK_GUIDE.md)。

---

## 🛠️ 管理后台

在 AstrBot 管理面板打开“321Roll Lite”插件页，有总览、团桌、世界、玩法、消息、运行、设置七个分区，白金和黑金两套主题跟随系统深浅色。

- 📊 **团桌实况**：幕进度、行动倒计时、席位和资源条，一眼看清每桌跑到哪了。
- 🎛️ **远程主持**：跳过挂机玩家、退回建卡、交棒、请离，和群里的主持指令一样；开了审稿模式时，待审草稿会出现在这里，可以直接发布或批注重写。
- 🕯️ **暗中调整**：改属性、背包、剩余次数、NPC 态度。改动先暂存，等 AI 写完下一轮正文后再生效，不打断沉浸感。
- 🧩 **可视化世界编辑器**：从空白或自己写的世界开始，七步向导（基础信息、规则、技能物品、职业、世界条目、幕与结局、校验导出），右侧实时预览，可以导出 `.world.json` 或可发布的 zip。预设世界和市场世界只读。

### 💬 消息排版

- 📝 **Markdown / 纯文本自动切换**：QQ 官方机器人、Telegram、Discord、飞书、KOOK、Mattermost 等平台推送原生排版，不支持的平台自动降级为纯文本。
- 🖼️ **三段式图片卡片**（白金 / 黑金可选，每段可单独开关）：
  - **个人状态卡**：角色徽章、骰子算式、资源条。
  - **故事正文卡**：首字放大烫金，换幕时自动配上场景大图。
  - **行动选项卡**：A–D 选项的难度、代价和快捷指令。

---

## ⚖️ 许可

- 💻 插件代码（含 `vendor/` 里的故事引擎）以 [GNU AGPL-3.0](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/LICENSE) 发布。
- 📖 官方世界的文字与场景图，包括自带的 `worlds/greycrown-prequel/` 和世界市场官方渠道里的全部世界包，以 [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/deed.zh-hans) 发布：可以署名转载分享，不可商用，不可改编后发布。
- 🆓 示例世界 `worlds/_template/` 以 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/deed.zh-hans) 放弃版权，随意修改、发布、商用。

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/horizoe10/astrbot_plugin_321roll_lite@main/pages/admin/assets/watermark.png" width="56" alt="" /><br />
  <sub>🎲 祝你的每一次 d20 都掷出好结果</sub>
</p>
