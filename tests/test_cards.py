import unittest

from support import make_app
from roll_lite import messages
from roll_lite.cards import card_html
from roll_lite.delivery import card_art
from roll_lite.render import MARKDOWN, PLAIN


class Cards(unittest.TestCase):
    def test_player_and_model_text_is_escaped(self) -> None:
        status = messages.action_status("<b>林</b>", "侦探", 2, "<script>alert(1)</script>", {"kind": "none"}, [("体力", 3, 5, -2)])
        page = card_html(status)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&lt;b&gt;林&lt;/b&gt;", page)

    def test_narration_drop_cap_and_banner_fallback(self) -> None:
        story = messages.narration("第一段。\n\n“有人吗？”\n\n第三段。", "值班室", "第二幕 · 倒走的钟")
        page = card_html(story, "light", {"tag": "第七个不思议", "mark": "七", "tone": "ink", "image": ""})
        self.assertEqual(page.count('class="lead"'), 1)
        self.assertIn('<p class="say">', page)
        self.assertIn('banner cover tone-ink', page)
        self.assertIn("<h1>第二幕 · 倒走的钟</h1>", page)
        plain = card_html(messages.narration("只有正文。"))
        self.assertNotIn("banner", plain.split("<main")[1])

    def test_choice_card_puts_commands_on_their_own_row(self) -> None:
        prompt = messages.turn_prompt("苏晴", "小苏", "1", 3, [{"label": "A", "text": "撬锁", "tag": "力量·困难·失败受伤"}],
                                      "hybrid", 4, loadout=["铜钥匙 ×1"])
        page = card_html(prompt, "dark")
        self.assertIn('<div class="cmds">', page)
        for command in ("/团 选 A", "/团 行动 描述", "/团 跳过"):
            self.assertIn(command, page)
        self.assertIn('<span class="cost">失败受伤</span>', page)
        self.assertIn("4 分钟", page)
        # chat text is unchanged by the card-only hint fields
        self.assertNotIn("跳过", prompt.render(PLAIN))

    def test_scene_npcs_one_per_line_cut_at_the_first_sentence(self) -> None:
        scene = messages.scene_card("后台", "风从门缝里钻进来。", "唱完这出戏",
                                    [("赵金生", "新班主，圆脸上一直挂着汗。说话总带三分笑"), ("老周", "琴师")])
        text = scene.render(PLAIN)
        self.assertIn("· 赵金生　新班主，圆脸上一直挂着汗。\n· 老周　琴师", text)
        self.assertNotIn("三分笑", text)
        self.assertIn("- **赵金生**", scene.render(MARKDOWN))


class Art(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.app = make_app()

    async def asyncTearDown(self) -> None:
        await self.app.stop()

    async def test_builtin_world_without_images_uses_its_cover_mark(self) -> None:
        art = card_art(self.app, {"world": "final-curtain", "key": "act:1", "tag": "谢幕之夜"})
        self.assertEqual((art["mark"], art["tone"], art["image"]), ("戏", "wine", ""))
        self.assertIsNone(card_art(self.app, None))


if __name__ == "__main__":
    unittest.main()

