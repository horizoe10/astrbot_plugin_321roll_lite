# 世界包规范

本文规定 321Roll Lite 世界包的命名、内容要求和文件格式，供世界作者和第三方工具参考。制作步骤见 [世界包制作教程](WORLD_PACK_GUIDE.md)，可直接改用的示例在插件的 `worlds/_template/`。

插件会在安装前完整检查每个世界包，不符合本规范的包不会被安装。下文中“必填”表示缺少就无法通过检查。

## 1. 命名与版本

对外显示的版本写成“最低插件版本 + 档位与修订号”，例如 0.7 P2：前半是装这个世界至少要的插件版本（只写到小版本），后半是档位字母和这一档的第几次修订。修订号一路递增，不随插件版本归零：0.7 P2 之后是 0.8 P3。最低插件版本由打包工具按世界用到的内容自动推算：基础字段 0.5，用了 creation、economy 或 pacing 是 0.7。安装包文件名也按这个写，例如 greycrown-prequel-0.7-P2.zip。

- **世界编号（id）**：1–101 个字符，只能用字母、数字和 `_ . : -`，以字母或数字开头。建议全小写，用 `作者.世界名` 的形式，例如 `alice.fog-harbor`。发布后不再修改。
- **保留编号**：官方世界使用 `greycrown-prequel`、`seventh-mystery`、`wildfire-hunt`、`nameless-sword-tomb`、`neon-pawnshop`、`final-curtain`，第三方世界不要使用。
- **版本号（revision）**：从 1 开始的整数。每次发布新内容都加 1；同一个版本号只对应一份内容。
- **安装包文件名**：`<id>-r<revision>.zip`。已发布的文件不再修改或删除。
- **版本档（edition）**：选填，`core`（核心版 Core·世界卡：轻量化的世界设定，保留核心内容与开篇，后续走向交给主持人）、`pro`（进阶版 Pro·世界包：更完整的世界观、人物和剧情设定）、`max`（旗舰版 Max·世界模组：完整的世界体系，更丰富的规则与交互）；不写视为 `pro`。界面显示档位字母加修订号，如 C1、P2、M1。各档修订号各自从 1 起；同一个世界的不同档位用不同编号（如 `<id>-core`）。Lite 只安装 `core` 与 `pro`，进阶版里读不了的部分（天气、氛围音与 `extensions`）自动略过；`max` 需要 321Roll 全量版，Lite 拒收；不认识的档位提示更新插件。早先写成 `lite`、`plus` 的包按 `core`、`pro` 读取。
- **标题**：`主标题 · 副标题`，中间是空格、间隔号、空格。副标题可以省略。

档位之外还要核对实际规则。Lite 的文字子集支持属性与资源、职业、技能物品、现有 creation/economy/pacing、幕与结局；天气、氛围音等可选表现按既有约定略过。世界原文中声明全量版的 `resource_effects`（资源效果与阈值）或 `perception_overlays`（角色感知叠层）时，Lite 会明确拒绝导入或开新桌，即使外层标为 C/P；不会静默忽略这些规则。未知可选扩展仍按各自正式契约处理，不代表能自动识别所有未来规则能力。

## 2. 内容要求

- **授权**：文字和图片须为原创，或已取得发布授权。使用 AI 生成的图片时，遵守所用工具的条款。建议在发布仓库里写明作者和授权方式。
- **合规**：内容须符合法律法规和所在平台、群聊的规则。用 `boundaries` 写明这个世界不涉及的内容。
- **适合文字跑团**：玩法要能在群聊里用文字完成，不依赖地图、图片辨认或精确计时。
- **不剧透**：真相写在 `secret` 和 `guidance` 里。`seed`、公开条目的 `summary`、幕的标题与引言、结局名称都会展示给玩家，不要写进谜底。
- **篇幅**：世界观单独计算，上限 6000 字，建议控制在 4000 字以内。只给 AI 主持读的部分（当前幕、结局条件、主持要点和全部设定条目）合计上限 12000 字，超出时从最后一条设定条目开始整条去掉。开场（`seed` 加开场地点、时间和局面）合计上限 3000 字。
- **数值**：属性范围、加值和资源上限保持小而直观。模板中的 6–16 属性、+2 技能、10 点体力可作为参考。

## 3. 世界文件夹

```text
<世界文件夹>/
├── pack.json           必填，格式 321roll.world-template/1
├── presentation.json   选填，格式 321roll.world-pack-presentation/1
├── extensions.json     选填，叙事默认与场景差分登记
└── images/             选填，场景图
```

文件一律使用 UTF-8 编码的 JSON。插件自带的 `worlds/` 目录中，以 `_` 开头的文件夹不会被当作世界加载。

## 4. pack.json

### 顶层

| 字段 | 类型 | 要求 |
|---|---|---|
| `format` | 文本 | 必填，固定为 `321roll.world-template/1` |
| `id` | 文本 | 必填，见第 1 节 |
| `revision` | 整数 | 必填，1–1000000 |
| `title` | 文本 | 必填，≤100 字 |
| `worldview` | 文本 | 必填，≤6000 字，只给 AI |
| `seed` | 文本 | 必填，≤3000 字，开团时发到群里 |
| `style` | 文本 | ≤300 字，文风基调 |
| `boundaries` | 文本 | ≤1000 字，内容禁区 |
| `guidance` | 文本 | ≤2000 字，真相与主持要点 |
| `attributes` | 列表 | 3–12 项 |
| `budget` | 整数 | 职业属性总点数，介于全部属性下限之和与上限之和之间 |
| `modifier` | 对象 | `baseline`（−100–100）、`divisor`（1–100），加值 = ⌊(属性 − baseline) ÷ divisor⌋ |
| `resources` | 列表 | 1–8 种 |
| `rules` | 对象 | 见下 |
| `skills`、`items` | 列表 | 各 ≤200 项 |
| `archetypes` | 列表 | 1–200 个职业 |
| `entries` | 列表 | ≤200 条 |
| `initial` | 对象 | 开场 |
| `inventory` | 对象 | 选填，装备栏位，见“进阶：装备” |

列表中每一项都有 `id`（同上编号规则，同一列表内不重复）和 `name`（必填，≤100 字）。

### attributes 属性

`min`、`max`：整数，−100–100，`min ≤ max`。

### resources 资源

`min`（≥0）、`max`（≥ max(1, min)）、`initial`（介于两者之间），均为整数。

### rules 规则

| 字段 | 要求 |
|---|---|
| `dcMin`、`dcMax` | 难度范围，1–100 |
| `dc` | 默认难度，在范围内 |
| `difficulties` | 4 个严格递增的整数：简单、标准、困难、极难 |
| `seats` | 世界席位上限，1–16 |
| `minPlayers`、`recommendedMin`、`recommendedMax` | 最少人数与推荐人数，均 ≤ `seats`，推荐下限 ≤ 推荐上限 |
| `mode` | `hybrid` 选项与自由行动、`choice_only` 只用选项、`dialogue_only` 只用自由行动 |
| `expectedResults` | 布尔，AI 是否在选项里给出预期结果 |
| `skillSlots` | 每个职业最多几个技能，0–20 |
| `failureCost` + `failureResource` | 检定失败扣多少、扣哪种资源；为 0 时资源留空 |
| `restCost` + `restCostResource` | 休整时消耗 |
| `restGain` + `restGainResource` | 休整时恢复 |

### skills 技能、items 物品

| 字段 | 要求 |
|---|---|
| `text` | ≤2000 字，效果说明，玩家可见 |
| `attribute` | 加值适用的属性 id；不参与检定时留空 |
| `modifier` | 加值，−20–20 |
| `cost` + `costResource` | 每次使用扣的资源，在掷骰前扣除 |
| `gain` + `gainResource` | 每次使用恢复的资源 |
| `uses` | 每个周期可用次数，0–1000，0 为不限 |
| `reset` | `scene` 每幕回满、`rest` 休整后回满、`never` 不恢复 |

物品另有 `initial`（每个角色开局几件，0–10000）和 `consume`（每用一次减少几件，0–10000）。技能由职业决定，物品所有角色开局都带。

### archetypes 职业

- `text`：一句定位，例如“查档与推理（偏科型）”。
- `attributes`：对象，必须包含全部属性 id，每项在该属性范围内，总和等于 `budget`。
- `skills`：技能 id 列表，不重复，数量 ≤ `rules.skillSlots`。

### entries 设定条目

| 字段 | 要求 |
|---|---|
| `kind` | `region` 地区、`place` 地点、`faction` 势力、`npc` 人物、`goal` 目标、`clue` 线索 |
| `public` | 布尔，玩家能否查到 |
| `summary` | ≤4000 字，公开描述 |
| `secret` | ≤4000 字，只给 AI 的隐藏设定 |
| `links` | 其他条目 id 的列表，不能连自己 |

### initial 开场

`place`（必填，≤100 字）、`time`（≤100 字）、`state`（≤2000 字，开场局面）、`links`（只能引用 `public: true` 的条目）。

### 进阶：装备

需要装备栏位的世界可以加 `inventory: {"slots": ["hand", "body"], "capacity": 20}`：`slots` 是不重复的栏位 id（≤20 个），`capacity` 是负重上限（整数或 `null` 表示不限）。物品可加 `equipment`：

| 字段 | 要求 |
|---|---|
| `slot` | 所占栏位 id，或 `null` |
| `durability_max`、`charge_max` | 耐久、充能上限，整数或 `null` |
| `durability_cost`、`charge_cost` | 选填，每次使用消耗，不超过对应上限 |
| `carrying_units` | 每件的负重 |

全部开局物品的负重之和不能超过 `capacity`。

### 进阶：建卡 creation

选填。不写时三种建卡模式都开放（核心版世界只开放快选和定制），出身取公开的 `faction`、`region` 条目，背景问题用通用的三问。

| 字段 | 要求 |
|---|---|
| `modes` | 开放的模式，`quick`（快选）、`custom`（定制）、`forge`（精雕）的子集；快选始终开放 |
| `move` | 定制和精雕最多挪动的属性点数，0–12，默认 4 |
| `swap` | 定制最多换掉的职业技能数，0 到 `rules.skillSlots`，默认 1 |
| `origins` | 出身列表，最多 12 个：`name`（30 字内，必填）、`text`（200 字内，前 80 字会显示给玩家并交给 AI 主持）、`item`（选该出身时多带的物品 id） |
| `questions` | 1–3 个背景问题，每个 2–40 字；定制答第 1 个，精雕全答；玩家每段回答 2–100 字。只写 1 个问题时就是“写一段背景” |
| `relation` | 精雕最后是否有“开局关系”一步，默认 `true`；写 `false` 时精雕写完背景就能确认，人物关系全在游玩中发展 |
| `kits` | 精雕可选的装备包，最多 8 个：`name`（20 字内）、`text`（80 字内）、`items`（物品 id → 数量 1–10） |
| `details` | 人物细节，最多 4 项，只写进故事、不影响数值：`name`（8 字内，不能重名）、`text`（给玩家的提示，60 字内）、`options`（最多 8 个，每个 `name` 20 字内、`text` 60 字内）、`free`（有选项时是否允许玩家自己写一句，默认 `true`；没有选项时必须允许）、`modes`（出现在 `custom`、`forge` 中的哪些，默认只在精雕） |
| `traits` | 特质，最多 8 个，每人最多选一个：`name`（12 字内，不能重名）、`text`（性格描述，80 字内）、`up` 和 `down`（都必填，见下）、`modes`（出现在 `custom`、`forge` 中的哪些，默认只在精雕；某种模式里一个特质都没有时，那种模式就没有特质这一步） |

特质的 `up`（利，加值）和 `down`（弊，减值）写法相同：`value` 是 1 或 2；`attribute` 是属性 id，不写表示任何属性；`when` 是触发时机，不写表示任何时候：

| `when` | 何时生效 |
|---|---|
| `any` | 任何时候 |
| `hard` | 困难及以上的检定 |
| `easy` | 普通及以下的检定 |
| `hurt` | 任一资源掉到一半或更低时 |
| `alone` | 这次检定没人援手 |
| `helped` | 这次检定有人援手 |
| `allIn` | 这次检定押了孤注 |

利和弊由插件在掷骰时计算，计入修正并写在检定回执上；AI 主持只读到特质名、性格描述和这次是帮了忙还是拖了后腿，读不到数字。特质不换点数，请让利和弊大致相当。

```json
"creation": {
  "modes": ["quick", "custom", "forge"],
  "move": 4,
  "swap": 1,
  "origins": [{"name": "雾港本地人", "text": "在码头长大，认得每一条船", "item": "hemp-rope"}],
  "questions": ["你为什么在今夜来到雾港？", "你欠谁一个人情？", "你最怕什么？"],
  "kits": [{"name": "守夜包", "text": "灯和热汤，够熬一整夜", "items": {"storm-lantern": 1, "ginger-soup": 2}}],
  "details": [{"name": "信仰", "text": "雾港人多少都信点什么", "modes": ["custom", "forge"],
               "options": [{"name": "灯塔娘娘", "text": "渔家供的海神"}, {"name": "什么都不信"}]}],
  "traits": [{"name": "临危不乱", "text": "越危险越冷静，平时反倒丢三落四", "modes": ["custom", "forge"],
              "up": {"when": "hard", "value": 1}, "down": {"when": "easy", "attribute": "perception", "value": 1}}]
}
```

数量超过上限、字段写错或引用了不存在的物品和属性时，世界包会在安装、导入和保存时被拒绝，并提示是哪一项出了问题。

不管哪种模式，最终的卡都要通过和快选相同的检查：属性在范围内、合计等于 `budget`，技能来自技能池且不超过技能槽。`move` 和 `swap` 是上限，主持人可以用 `/团 主持 建卡 挪点 N`、`换技能 N` 按桌调低，不能调高。

### 进阶：经济 economy

可选。写了 `economy` 的世界，每位角色有独立钱包：故事里会得钱失钱，玩家在“整备”时到当前地点的店里买卖。不写就没有钱。需要插件 0.7 以上。

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| currency | 是 | 货币名，1–8 字，如“煤筹” |
| initial | 否 | 开局钱数，0–100000，默认 0 |
| prices | 否 | 物品 id → 售价（1–100000）；没定价的物品不出售 |
| sell | 否 | 卖回店里按售价的百分之几回收，0–100，默认 50 |
| wage | 否 | 每次换幕发给每位角色的工钱，0–10000，默认 0 |
| storyLimit | 否 | 一段正文里模型最多给或扣多少钱，1–100000，默认 20 |
| kitMoney | 否 | 精雕放弃装备包时折成的钱，0 表示不能折钱 |
| autoOutfit | 否 | true 时走进有店的地点自动开始整备，默认由主持人发起 |
| shops | 否 | 商店列表，最多 12 家 |

每家店：id（唯一）、name（1–20 字）、kind（类别，最多 8 字）、place（设定条目 id，玩家所在场景对上这个地点时才能在这家店买；留空表示随处可买）、items（1–30 个已定价的物品 id）、text（一句说明，最多 80 字）。出身（creation.origins）可以加 money（-100000–100000），表示开局多带或少带的钱，钱包不会低于 0。

开局钱数大致够买一两件常用品，工钱让每幕能补一件，稀缺物品贵到要攒钱或在故事里赚。从 P 版派生 C 版时不继承 economy；C 版要用就在 core.json 的 mechanics 里单独写。完整示例见内置祖约的 pack.json。

### 进阶：节奏 pacing

可选。每个世界都按轮计节奏（在座的人各行动一次算一轮）；不写 `pacing` 就用默认值，写了只改数字。需要插件 0.7 以上。

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| sceneRounds | 否 | 一个场景待满几轮后，正文必须让局面变化，0–50，默认 4；0 表示不催 |
| actRounds | 否 | 一幕走满几轮后提议换幕，0–100，默认 8；0 表示不催 |
| acts | 否 | 幕号 → 这一幕的轮数（1–100），给长的一幕单独多给几轮，如 `{"3": 12}` |
| graceRounds | 否 | 提醒之后再过几轮自动推进（世界推进、自动换幕），1–10，默认 2 |
| targetRounds | 否 | 全程走满几轮后发起收尾表决，0–1000；不写时为各幕轮数之和（核心版按三幕算），0 表示不设 |
| hardRounds | 否 | 全程走到几轮必定进入收尾，0–1000，不能小于 targetRounds；不写时为目标的 1.5 倍、且至少多 2 轮 |
| endingPrompt | 否 | false 时不在目标轮数、最后一幕走满或全员倒下时自动提议收尾；默认 true |

```json
"pacing": { "sceneRounds": 4, "actRounds": 8, "acts": { "3": 12 }, "targetRounds": 36 }
```

收尾的流程固定：表决同意过半后再走 2 轮收拢线索，然后写终章，每位玩家留一句尾声。AI 判断某个结局条件已满足时，会把一个选项写成“收束：结局名——走向”，玩家选它就发起收尾表决，所以 presentation.json 里的结局名要写清楚、彼此好区分；AI 会照抄结局名，插件也会把意思明显相同的名字对回预设结局，终章卡据此配上结局图。主持人可以在团桌上把各层轮数调长或调短，不受世界包限制。从 P 版派生 C 版时，pacing 会去掉按幕单独设置的 acts；C 版要另定就在 core.json 的 mechanics 里写。

## 5. presentation.json

| 字段 | 要求 |
|---|---|
| `format` | `321roll.world-pack-presentation/1` |
| `pack` | 对应的世界 id |
| `cover` | 选填，`{"mark": 1–2 个字, "tone": 配色}`，配色为 `ink`、`ember`、`neon`、`jade`、`wine`、`slate` 之一；不填时取标题首字 |
| `acts` | 幕：`number`（整数，必填）、`title`（必填）、`lead`（一句引言）、`image`（选填） |
| `places` | 地点：`entry`（条目 id）、`name`（必填）、`aliases`（别名列表）、`image`（选填） |
| `endings` | 结局：`id`、`name`（必填）、`rule`（达成条件，AI 据此收束故事）、`image`（选填） |
| `shared` | 选填，图片共用对照，`{"图片编号": "另一张图片的编号"}` |

幕按 `number` 排序。其他字段（例如 321Roll 的天气、环境音）会被忽略。

## 6. 场景图

- 放在 `images/`，文件名是图片编号加扩展名，支持 `.webp`、`.png`、`.jpg`、`.jpeg`。图片编号 1–81 个字符，只能用字母、数字和 `_ . -`。
- 有场景图时必须有 `cover`。
- 幕、地点、结局写了 `image` 时按它找文件，找不到会报错；没写时依次尝试 `act-<number>`、`place-<entry>`、`ending-<id>`，找不到就不配图。
- `shared` 里列出的编号不需要单独的文件。
- 建议 16:9、宽度 ≥1280 像素。打包命令会缩放到 1280 宽并转成 WebP（质量 82），预览图为 640 宽。
- 开场、换幕、地点与结局图会随正文发送。正文卡渲染成功时用横幅；文字正文或渲染降级时在正文前单独发图；终章单独发结局图。后台“场景图”开关控制独立发图，默认开，卡片横幅不受该开关影响。独立图片缓存为 JPEG；图片失败不阻塞正文，相同图片不连续重发。

### 季节、时段与事件差分

作者目录可加 `extensions.json`，打包器会写入 `world.json.extensions`，并收录登记图片：

```json
{
  "321roll-lite": {
    "scene_variants": {
      "act_seasons": ["autumn", "winter"],
      "places": {
        "station": {
          "base": {"season": "autumn", "time": "morning"},
          "variants": [
            {"image": "station-winter-dusk", "season": "winter", "time": "dusk"},
            {"image": "station-snow", "season": "winter", "time": "morning", "weather": "snow"},
            {"image": "station-festival", "acts": [2], "time": "night"}
          ]
        }
      }
    }
  }
}
```

- `act_seasons` 必须与从 1 起连续编号的幕一一对应，值为 `spring/summer/autumn/winter`。`places` 的键引用 `presentation.places.entry`。
- `base` 可省略，允许 `season`、`time`；省略时是无条件母版，排在差分之后。每条差分必填已有图片 `image`，并至少填一种条件：`season`、`time`、`acts`、`weather`。`time` 为 `morning/day/dusk/night`；`acts` 为有效幕号列表；`weather` 目前仅 `snow`，同时指定 `season: winter`。
- 所有条件同时满足才入选。优先级依次是限定幕号、天气、季节、时段，再按登记顺序；缺少时段候选时，保持其余条件，按白天、傍晚、清晨、夜晚回退。再无候选用母版 → 当前幕 → 第一幕 → 封面 → 色调底图。
- 地点按场景标题匹配名称与别名，最长匹配优先，同长度取最先出现者。季节取当前幕；时段先看场景标题，再看房间时钟。仅标题明确下雪时使用雪景。
- 安装会检查登记语义和图片引用，不合法整包拒收。登记和图片版本在开局冻结；更新或卸载不影响已开团桌的图片，被团桌引用的旧资源保留。
- 场景标题由模型填写为“地点 · 清晨/白天/傍晚/夜晚”，下雪加“ · 下雪”。同地点换时段、离开后返回都重新选图；发送层记录已发送或发送失败的 key，不连续重试同图。
- 后台地点下默认折叠差分；编辑器不编辑此登记表。全量版忽略本命名空间，使用原有母版。已发布差分变化须提升世界 revision；发布前将 `min_plugin` 与实际支持差分的发布版本配对。

## 7. 世界文件 .world.json

后台“导出 JSON”和“导入世界文件”使用的单文件格式：

```json
{ "format": "321roll-lite.world-bundle/1", "pack": { … }, "presentation": { … } }
```

`world.json` 和导出的 JSON 文件还可以带 `extensions`。Lite 读取上述场景差分及世界的叙事默认：

| 位置 | 取值 | 含义 |
|---|---|---|
| `extensions."321roll".randomness` | 0–100 的整数，步长 5 | 即兴程度：≤14 严谨，≤34 稳健，≤64 均衡，≤84 灵动，其余奔放 |
| `extensions."321roll-lite".dialogue` | `description_high`、`description_soft`、`balanced`、`dialogue_soft`、`dialogue_high` | 对白与描写：多描写、偏描写、均衡、偏对白、多对白 |
| `extensions."321roll-lite".length` | `free`、`minimal`、`balanced`、`epic` | 正文篇幅：不限、简洁、均衡、长篇 |

没写的项使用插件默认（均衡、偏对白、不限）；值不合法时忽略，不拒收。开桌时团桌复制一份当时的世界默认，主持人之后可以逐项调整。管理员在后台世界页调整预设或市场世界的叙事默认时，只保存在本机，不改动安装包。自定义世界在编辑器“基本信息”里设置，导出安装包或 JSON 时会一起写进 `extensions`。

## 8. 安装包 .zip

格式标识 `321roll-lite.world-package/2`。zip 中只允许以下文件，放在压缩包根目录，不能加密：

| 文件 | 内容 |
|---|---|
| `manifest.json` | 清单，必填 |
| `world.json` | 世界文件，即第 7 节的格式，必填 |
| `assets.bin` | 全部场景图，有图片时才有 |

### manifest.json

| 字段 | 内容 |
|---|---|
| `format` | `321roll-lite.world-package/2` |
| `id`、`revision` | 与 `world.json` 中的世界一致 |
| `edition` | 选填，版本档，见第 1 节；不写视为 `pro` |
| `title`、`summary` | 标题与一句简介 |
| `min_plugin` | 需要的最低插件版本，例如 `0.7.0`；打包工具按世界用到的内容自动推算 |
| `cover` | `{"mark", "tone"}`，或 `null` |
| `banner` | 封面图的资源编号，或 `null` |
| `assets` | 资源表，每项 `{"id", "type", "offset", "size", "sha256"}` |
| `images` | 图片编号到资源编号的对照，例如 `{"cover": "a00", "act-1": "a01"}` |
| `files` | 除清单外每个文件的 `{"size", "sha256"}` |

### assets.bin

文件以 10 字节标记 `R3LASSET\x00\x02` 开头，后面依次拼接每张图片。资源编号为 `a00`、`a01`…；`offset` 从标记之后算起，各项首尾相接；`type` 为 `webp`、`png` 或 `jpg`；`sha256` 是还原后图片的摘要。

每张图片单独混淆：用 SHAKE-256 对 UTF-8 文本 `321roll-lite/assets:<id>:<revision>:<资源编号>` 生成与图片等长的字节流，与图片逐字节异或。还原时再异或一次即可。这样做只是让解压后的图片无法直接预览，不是加密；`world.json` 保持明文。

### 安装时的检查

插件安装前会依次核对：zip 结构和文件白名单、清单里每个文件的大小和 sha256、每张图片还原后的格式与 sha256、世界内容（第 4、5 节）、世界引擎编译、`min_plugin`。任何一项不通过都会拒绝安装，不会写入任何文件。安装包里的内容只会被读取，从不执行。

## 9. 索引 index.json

世界市场通过索引发现世界。索引和安装包放在同一个公开仓库里：

```json
{
  "format": "321roll-lite.world-index/1",
  "name": "爱丽丝的世界",
  "worlds": [
    {
      "id": "alice.fog-harbor", "revision": 1, "title": "雾港灯塔 · 无人看守的灯，昨夜亮了",
      "summary": "立冬前夜，雾比往年都浓。", "cover": {"mark": "雾", "tone": "slate"},
      "images": 8, "min_plugin": "0.1.0",
      "file": "packs/alice.fog-harbor-r1.zip", "size": 18975, "sha256": "…",
      "preview": "previews/alice.fog-harbor-r1.webp"
    }
  ]
}
```

- 必填：`id`、`revision`、`title`（≤100 字）、`file`、`size`、`sha256`（64 位小写十六进制）。
- 选填：`summary`、`cover`、`images`、`min_plugin`、`preview`、`edition`（版本档；写明 `pro` 时市场卡片标“含进阶版效果（Lite 中不显示）”，`max` 标“需要全量版”且不能安装）。
- `file` 和 `preview` 是相对索引所在位置的路径，也可以写完整的 http(s) 地址。
- 每个世界只列最新版本。格式不对的条目会被跳过，其余条目照常显示。
- 已安装的世界与索引行编号、修订号相同而 sha256 不同时，市场显示“内容不同”，可以替换安装。

官方渠道默认提供核心版（C），也会提供部分进阶版（P）。

## 10. 上限

| 项目 | 上限 |
|---|---|
| 安装包 | 64 MiB（67,108,864 字节；旧版为 32 MiB） |
| world.json、manifest.json | 各 2 MB |
| 场景图 | 每个世界 200 张，每张 6 MB |
| 索引文件 | 1 MB，500 个世界 |
| 世界市场来源 | 10 个索引地址 |

超过 32 MiB 的安装包须声明支持 64 MiB 上限的最低插件／平台版本；旧版仍会拒绝，单纯重新打包不能升级使用者的读包器。
