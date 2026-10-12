# 321Roll Lite 世界市场

这个分支只存放世界安装包，不包含插件代码。插件本体在 [main 分支](https://github.com/horizoe10/astrbot_plugin_321roll_lite)。

| 世界 | 版本 | 安装包 |
|---|---|---|
| 封箱戏（核心版） · 第七夜，台下多出一排看客 | C2 | [final-curtain-core-0.7-C2.zip](packs/final-curtain-core-0.7-C2.zip) |
| 灰冠之下：祖约（核心版） · 冠落纪 236 年，赤髓煤脉现世 | C3 | [greycrown-prequel-core-0.7-C3.zip](packs/greycrown-prequel-core-0.7-C3.zip) |
| 霓虹典当行（核心版） · 今夜有人当掉了整座城的昨天 | C2 | [neon-pawnshop-core-0.7-C2.zip](packs/neon-pawnshop-core-0.7-C2.zip) |
| 第七个不思议（核心版） · 钟楼在放学后多敲了一下 | C2 | [seventh-mystery-core-0.7-C2.zip](packs/seventh-mystery-core-0.7-C2.zip) |
| 狩火（核心版） · 群兽迁徙之年 | C2 | [wildfire-hunt-core-0.7-C2.zip](packs/wildfire-hunt-core-0.7-C2.zip) |
| 花信风：四时有信（核心版） · 九月相逢，来年盛夏 | C2 | [chenglan-academy-core-0.7-C2.zip](packs/chenglan-academy-core-0.7-C2.zip) |

## 版本档

世界分三档，版本写作"档位字母＋修订号"（如 C1、P2），各档修订号各自从 1 起：

| 档位 | 中文名 | 内容 | 定位 | Lite 插件 |
|---|---|---|---|---|
| **Core** | 核心版 | 世界卡 | 轻量化的世界设定，保留核心内容，开篇之后的走向更多交给主持人即兴发挥 | 支持 |
| **Pro** | 专业版 | 世界包 | 更完整的世界观、人物和剧情设定 | 支持（天气与氛围音等效果在 Lite 中不显示，其余照常可玩） |
| **Max** | 旗舰版 | 世界模组 | 完整的世界体系，支持更丰富的规则与交互 | 不支持，需要 321Roll 全量版 |

本分支默认提供核心版，以后也可能投放部分专业版。官方核心版默认的叙事风格为"奔放"（花信风为"灵动"），开团后主持人可以随时查看、修改或清除。

2026-10-12 起，五个官方核心版更新为 C2（灰冠为 C3），按 Lite 0.7 的建卡规则重做了职业、技能、道具与建卡，补充了场景和插画，最低 Lite 0.7.0；旧插件会提示先升级。《无名剑冢》核心版已从本分支撤下，已经安装的照常可用。

《花信风：四时有信》默认灵动，保留人物与世界设定，开篇后自由续写；C2 重做了建卡，包含 28 张基准场景图，最低 Lite 0.7.0。含十二个月日历、可选素材、后日谈与 163 张场景图的 [P2 专业版](https://github.com/horizoe10/321Roll/tree/worlds-pro) 在专业版市场，最低 Lite 0.7.0。

原先的 r1 世界包已从本分支撤下；已经安装的照常可用。

## 安装包内容

每个世界一个 zip，文件名带最低 Lite 小版本和版本档（如 `-0.7-C2`）。更新世界时提升修订号并新增文件，已发布的文件不再修改，所以 `index.json` 里的 sha256 始终有效。

| 文件 | 内容 |
|---|---|
| `manifest.json` | `321roll-lite.world-package/2`：世界 id、版本（含 `edition` 档位）、标题、简介、配色封面、图片对照表与图片清单、每个文件的大小和 sha256 |
| `world.json` | `321roll-lite.world-bundle/1`：世界文件；`extensions` 中是全量版用的数据，Lite 只读其中的默认叙事风格 |
| `assets.bin` | 封面与场景图（1280 像素宽）合成的一个文件。每张图都做了混淆，解压后无法直接预览，免得翻文件时被剧透；插件安装时逐张还原并核对 sha256 |

`index.json`（`321roll-lite.world-index/1`）列出全部安装包的相对路径、大小、sha256、版本档和 `previews/` 下的 640 宽预览图。插件读取索引时可以把仓库地址换成 jsDelivr 或代理前缀，相对路径保持不变。

## 现在怎么用

在 AstrBot 插件后台打开"世界 → 世界市场"，默认索引就是这个分支的 `index.json`，点"安装"即可。服务器访问不了 GitHub 时，可以下载 zip 后在市场页"离线安装"里上传。

## 制作自己的世界

官方世界和第三方世界用同一个打包命令生成：`python -X utf8 -m roll_lite.worlds.make <世界文件夹> --out <输出目录>`。完整步骤见 [世界包制作教程](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/WORLD_PACK_GUIDE.md)。

## 许可

本分支的世界安装包与预览图以 [CC BY-NC-ND 4.0](LICENSE) 发布：可以署名转载和分享，不可商用，不可改编后发布。

旧版本的安装包（各世界的 C1，以及 `packs/lite-0.6.0/` 下的花信风 C1）仅作历史归档保留，索引已指向新版本。
