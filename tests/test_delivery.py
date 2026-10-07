import unittest

from support import make_app
from roll_lite import messages
from roll_lite.delivery import deliver, load_prefs, save_prefs
from roll_lite.render import MARKDOWN, PLAIN, Msg


def one_turn() -> list:
    status = messages.action_status("林晓", "侦探", 3, "翻看*登记簿*", {"kind": "check", "attribute": "观察", "difficulty": "hard",
                                                                    "dc": 15, "face": 14, "modifier": 2, "total": 16,
                                                                    "outcome": "success"}, [("理智", 3, 5, -1)])
    story = messages.narration("钟楼的指针倒退了一格。")
    choices = messages.turn_prompt("林晓", "小林", "10001", 3, [{"label": "A", "text": "去钟楼", "tag": "观察·标准"}], "mixed", 5)
    return [status, story, choices]


class Sink:
    def __init__(self, refuse_markdown: bool = False) -> None:
        self.chains, self.refuse = [], refuse_markdown

    async def __call__(self, chain) -> None:
        if self.refuse and chain.markdown:
            raise RuntimeError("markdown not allowed")
        self.chains.append(chain)


class FakeStar:
    def __init__(self, ok: bool = True, cards: bool = True) -> None:
        self.ok, self.cards_ok, self.rendered, self.cards = ok, cards, [], []

    async def html_render(self, tmpl: str, data: dict, return_url: bool = True, options: dict | None = None) -> str:
        if not (self.ok and self.cards_ok):
            raise RuntimeError("render service down")
        self.cards.append((data["html"], options))
        return f"https://img.example/card{len(self.cards)}.jpg"

    async def text_to_image(self, text: str, return_url: bool = True) -> str:
        if not self.ok:
            raise RuntimeError("t2i service down")
        self.rendered.append(text)
        return f"https://img.example/{len(self.rendered)}.png"


class Delivery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.app = make_app()
        save_prefs(self.app, {"format": MARKDOWN, "interval": 0})

    async def asyncTearDown(self) -> None:
        await self.app.stop()

    async def send(self, platform: str, items=None, sink=None) -> Sink:
        sink = sink or Sink()
        await deliver(self.app, sink, items or one_turn(), platform_name=platform, platform_id=platform + "-1")
        return sink

    async def test_onebot_degrades_to_plain_with_a_real_mention(self) -> None:
        sink = await self.send("aiocqhttp")
        self.assertEqual(len(sink.chains), 3)                       # status, narration, choices in order
        self.assertTrue(all(c.markdown is False and c.t2i is False for c in sink.chains))
        self.assertNotIn("**", "".join(c.text for c in sink.chains))
        self.assertIn("翻看*登记簿*", sink.chains[0].text)            # player text kept as typed
        self.assertEqual(sink.chains[2].chain[0], ("at", "10001"))

    async def test_qq_official_gets_markdown_and_a_text_mention(self) -> None:
        sink = await self.send("qq_official")
        self.assertTrue(all(c.markdown for c in sink.chains))
        self.assertIn("**【成功】**", sink.chains[0].text)
        self.assertIn("翻看\\*登记簿\\*", sink.chains[0].text)       # escaped, not italic
        self.assertTrue(sink.chains[2].text.startswith("@小林 "))

    async def test_plain_switch_wins_everywhere(self) -> None:
        save_prefs(self.app, {"format": PLAIN, "interval": 0})
        sink = await self.send("qq_official")
        self.assertTrue(all(c.markdown is False for c in sink.chains))

    async def test_refused_markdown_is_resent_as_plain_and_remembered(self) -> None:
        sink = await self.send("qq_official", sink=Sink(refuse_markdown=True))
        self.assertEqual(len(sink.chains), 3)
        self.assertTrue(all(c.markdown is False for c in sink.chains))
        self.assertIn("qq_official-1", load_prefs(self.app).blocked)
        again = await self.send("qq_official", sink=Sink(refuse_markdown=True))
        self.assertEqual(len(again.chains), 3)
        save_prefs(self.app, {"format": MARKDOWN, "interval": 0, "reset_blocked": True})
        self.assertEqual(load_prefs(self.app).blocked, ())

    async def test_each_segment_has_its_own_image_switch(self) -> None:
        self.app.star = FakeStar()
        save_prefs(self.app, {"format": MARKDOWN, "interval": 0, "image_narration": True})
        sink = await self.send("aiocqhttp")
        kinds = [[part if isinstance(part, tuple) and part[0] == "image" else None for part in c.chain] for c in sink.chains]
        self.assertFalse(any(kinds[0]))
        self.assertTrue(any(kinds[1]))
        self.assertFalse(any(kinds[2]))
        save_prefs(self.app, {"format": MARKDOWN, "interval": 0, "image_status": True, "image_choices": True})
        sink = await self.send("aiocqhttp")
        images = [any(isinstance(p, tuple) and p[0] == "image" for p in c.chain) for c in sink.chains]
        self.assertEqual(images, [True, False, True])
        self.assertEqual(sink.chains[2].chain[0], ("at", "10001"))   # the mention stays outside the picture

    async def test_failed_image_falls_back_to_text(self) -> None:
        self.app.star = FakeStar(ok=False)
        save_prefs(self.app, {"format": MARKDOWN, "interval": 0, "image_narration": True})
        sink = await self.send("aiocqhttp")
        self.assertIn("倒退了一格", sink.chains[1].text)

    async def test_image_card_first_then_astrbot_template(self) -> None:
        star = self.app.star = FakeStar()
        save_prefs(self.app, {"format": MARKDOWN, "interval": 0, "image_choices": True, "card_theme": "dark"})
        await self.send("aiocqhttp")
        page, options = star.cards[0]
        self.assertIn('class="dark seg-choices"', page)
        self.assertIn("/团 跳过", page)                     # the command row of the choice card
        self.assertGreater(options["quality"], 40)
        self.assertEqual(star.rendered, [])
        star.cards_ok = False
        sink = await self.send("aiocqhttp")
        self.assertEqual(len(star.rendered), 1)              # AstrBot's own text-to-image took over
        self.assertTrue(any(isinstance(p, tuple) and p[0] == "image" for p in sink.chains[2].chain))

    async def test_unknown_card_theme_is_saved_as_light(self) -> None:
        self.assertEqual(save_prefs(self.app, {"card_theme": "neon"}).card_theme, "light")

    async def test_merge_sends_one_message(self) -> None:
        save_prefs(self.app, {"format": MARKDOWN, "interval": 0, "merge": True})
        sink = await self.send("aiocqhttp")
        self.assertEqual(len(sink.chains), 1)
        self.assertIn("┄┄┄", sink.chains[0].text)
        self.assertEqual(sink.chains[0].chain[0], ("at", "10001"))

    def test_bold_and_code_markers(self) -> None:
        msg = Msg().text("**#3** 线索「a_b」 \x60/团 选 A\x60")
        self.assertEqual(msg.render(PLAIN), "#3 线索「a_b」 /团 选 A")
        self.assertEqual(msg.render(MARKDOWN), "**#3** 线索「a\\_b」 \x60/团 选 A\x60")

    def test_markdown_escapes_only_real_line_starts(self) -> None:
        listed = Msg().items(["**1. 封箱戏**　第七夜"]).render(MARKDOWN)
        self.assertEqual(listed, "- **1. 封箱戏**　第七夜")              # no stray backslash inside bold
        prose = Msg().para("1. 第一条\n- 不是列表\n# 也不是标题").render(MARKDOWN)
        self.assertEqual(prose, "1\\. 第一条\n\\- 不是列表\n\\# 也不是标题")
        stacked = Msg().meter("体力", 4, 5).meter("理智", 3, 5).hint("下一步").render(MARKDOWN)
        self.assertIn("4/5  \n理智", stacked)                            # hard break keeps meters on two lines
        self.assertIn("3/5\n\n> 下一步", stacked)                         # quote stands apart


if __name__ == "__main__":
    unittest.main()

