# 321Roll Lite 世界包市场

这个分支只存放世界安装包，不包含插件代码。插件本体在 [main 分支](https://github.com/horizoe10/astrbot_plugin_321roll_lite)。

| 世界 | 安装包 |
|---|---|
| 封箱戏 · 第七夜，台下多出一排看客 | [final-curtain-r1.zip](packs/final-curtain-r1.zip) |
| 灰冠之下：祖约 · 冠落纪 236 年，赤髓煤脉现世 | [greycrown-prequel-r1.zip](packs/greycrown-prequel-r1.zip) |
| 无名剑冢 · 第一道潮痕，是用剑刻的 | [nameless-sword-tomb-r1.zip](packs/nameless-sword-tomb-r1.zip) |
| 霓虹典当行 · 今夜有人当掉了整座城的昨天 | [neon-pawnshop-r1.zip](packs/neon-pawnshop-r1.zip) |
| 第七个不思议 · 钟楼在放学后多敲了一下 | [seventh-mystery-r1.zip](packs/seventh-mystery-r1.zip) |
| 狩火 · 群兽迁徙之年 | [wildfire-hunt-r1.zip](packs/wildfire-hunt-r1.zip) |

## 安装包内容

每个世界一个 zip，文件名带世界版本号（`-r1`）。更新世界时提升版本号并新增文件，已发布的文件不再修改，所以 `index.json` 里的 sha256 始终有效。

| 文件 | 内容 |
|---|---|
| `manifest.json` | `321roll-lite.world-package/2`：世界 id、版本、标题、简介、配色封面、图片对照表与图片清单、每个文件的大小和 sha256 |
| `world.json` | `321roll-lite.world-bundle/1`：与后台“导出世界”相同的世界文件 |
| `assets.bin` | 封面与各幕、地点、结局的场景图（1280 像素宽）合成的一个文件。每张图都做了混淆，解压后无法直接预览，免得翻文件时被剧透；插件安装时逐张还原并核对 sha256 |

`index.json`（`321roll-lite.world-index/1`）列出全部安装包的相对路径、大小、sha256 和 `previews/` 下的 640 宽预览图。插件读取索引时可以把仓库地址换成 jsDelivr 或代理前缀，相对路径保持不变。

## 现在怎么用

在 AstrBot 插件后台打开“世界 → 世界市场”，默认索引就是这个分支的 `index.json`，点“安装图文版”即可。服务器访问不了 GitHub 时，可以下载 zip 后在市场页“离线安装”里上传。

## 制作自己的世界包

官方世界和第三方世界用同一个打包命令生成：`python -X utf8 -m roll_lite.worlds.make <世界文件夹> --out <输出目录>`。完整步骤见 [世界包制作教程](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/WORLD_PACK_GUIDE.md)。

## 许可

本分支的世界包与预览图以 [CC BY-NC-ND 4.0](LICENSE) 发布：可以署名转载和分享，不可商用，不可改编后发布。
