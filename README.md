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
| `manifest.json` | `321roll-lite.world-package/1`：世界 id、版本、标题、简介、配色封面、图片对照表、每个文件的大小和 sha256 |
| `world.json` | `321roll-lite.world-bundle/1`：与后台“导出世界”相同的世界文件 |
| `assets/*.webp` | 封面与各幕、地点、结局的场景图，1280 像素宽 |

`index.json`（`321roll-lite.world-index/1`）列出全部安装包的相对路径、大小和 sha256。插件读取索引时可以把仓库地址换成镜像前缀，相对路径保持不变。

## 现在怎么用

插件的市场安装功能完成之前，可以解压安装包，在后台“世界”页导入其中的 `world.json`。

## 重新生成

在插件仓库运行 `python -X utf8 tools/pack_worlds.py`，产物在 `dist/worlds/`。同样的内容会得到字节完全一致的安装包。
