# 世界包模板：雾港灯塔

这是一个可以直接开团的小世界，用来当作写新世界的起点。插件不会把这个文件夹当成可玩的世界加载（以 `_` 开头的文件夹都会跳过）。

| 文件 | 内容 |
|---|---|
| `pack.json` | 规则、属性、资源、技能、物品、职业、设定条目和开场 |
| `presentation.json` | 封面、三幕、两个地点、三个结局；地点“回潮馆”与第二幕共用一张图 |

## 用法

1. 把整个文件夹复制到插件目录外，改成你的世界名。
2. 改 `pack.json` 的 `id`、`title`，以及 `presentation.json` 的 `pack`，然后逐项替换内容。
3. 想先试玩：在后台“世界 → 导入世界文件”里选 `pack.json`，并附上 `presentation.json`，校验后导入。
4. 想配图：新建 `images/`，放入 `cover`、`act-1`、`act-2`、`act-3`、`place-lighthouse`、`ending-homecoming`、`ending-dark-cape`、`ending-half-light` 这几张图（webp、png 或 jpg）。
5. 在插件目录运行打包命令：

   ```bash
   python -X utf8 -m roll_lite.worlds.make <你的世界文件夹> --out <输出目录>
   ```

完整步骤见 [世界包制作教程](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/WORLD_PACK_GUIDE.md)，字段说明见 [世界包规范](https://github.com/horizoe10/astrbot_plugin_321roll_lite/blob/main/docs/WORLD_PACK_SPEC.md)。

这个模板以 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/deed.zh-hans) 放弃版权：可以随意修改、发布和商用，不需要署名。用它改出来的世界，授权方式由你自己决定。
