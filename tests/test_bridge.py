import json
import unittest

from support import Player, make_app, scripted_model

from roll_lite.engine.bridge import localize_schema
from roll_lite.engine.conform import conform, problems
from roll_lite.engine.gateway import OMITTED_OUTPUT_FIELDS
from roll_lite.engine.model_output import model_output_schema

NARRATIVE = "se-hosted-narrative-model-output/1.6.0"


def deepseek_style(system: str, prompt: str) -> str:
    """The usual slips of a model without strict structured output, on top of a valid narration."""
    text = scripted_model(system, prompt)
    if "根据机械回执叙述" not in system:
        return text
    value = json.loads(text)
    value["progress"] = {}                                   # null keys left out
    value["facts"][0]["fact_ref"] = "fact.9"                 # copied from the input facts
    value["annotations"] = []                                # a field of another contract
    del value["npcs"]                                        # empty list left out
    return json.dumps(value, ensure_ascii=False)


class Conform(unittest.TestCase):
    def test_repairs_shape_slips_only(self) -> None:
        schema = localize_schema(model_output_schema(NARRATIVE), {"attributes": {"wit": "机敏"}}, OMITTED_OUTPUT_FIELDS)
        raw = {"paragraphs": ["灯闪了一下。"], "facts": [{"kind": "world_fact", "subject_ref": "scene", "text": "灯会闪", "fact_ref": "f1"}],
               "suggestions": ["看看灯"], "suggestion_checks": [{"kind": "narrative", "attribute_ref": "", "difficulty": "", "failure_cost": ""}],
               "progress": None, "decision_node": None}
        fixed, notes = conform(raw, schema)
        self.assertEqual(fixed["progress"], {"scene": None, "goal": None})
        self.assertEqual(fixed["npcs"], [])
        self.assertNotIn("fact_ref", fixed["facts"][0])
        self.assertNotIn("decision_node", fixed)
        self.assertEqual(problems(fixed, schema), [])
        self.assertIn("fact_ref", raw["facts"][0])            # the input is left untouched
        self.assertTrue(any("facts[0].fact_ref" in note for note in notes))

    def test_reports_what_it_cannot_repair(self) -> None:
        schema = localize_schema(model_output_schema(NARRATIVE), {"attributes": {"wit": "机敏"}}, OMITTED_OUTPUT_FIELDS)
        fixed, _ = conform({"facts": [], "npcs": [], "suggestions": [], "progress": {"scene": "钟楼", "goal": None}}, schema)
        found = problems(fixed, schema)
        self.assertIn("输出 缺少字段 paragraphs", found)
        self.assertIn("suggestions 至少要有 1 项（现在 0 项）", found)
        self.assertTrue(any(line.startswith("progress.scene") for line in found))


class ModelRepairFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await self.app.stop()

    async def start(self, responder) -> Player:
        self.app = make_app(responder=responder)
        host = Player(self.app, "admin", "主持")
        await host.say("/团 开启 1")
        await host.say("/团 加入")
        await host.say("/团 选职业 1 林晓")
        await host.say("/团 开演")
        return host

    async def test_deepseek_style_narration_is_accepted(self) -> None:
        host = await self.start(deepseek_style)
        reply = await host.say("/团 选 A")
        self.assertIn("走廊里的灯闪了一下", reply)
        with self.app.store.read() as c:
            row = c.execute("SELECT status,note FROM model_calls WHERE contract=? ORDER BY id DESC LIMIT 1", (NARRATIVE,)).fetchone()
        self.assertEqual(row["status"], "ok")
        self.assertIn("补上 progress.scene=null", row["note"])
        self.assertIn("删除多余字段 annotations", row["note"])

    async def test_rejection_names_the_field_and_the_retry_sees_it(self) -> None:
        attempts = []

        def missing_once(system: str, prompt: str) -> str:
            text = scripted_model(system, prompt)
            if "根据机械回执叙述" in system:
                attempts.append(system)
                if len(attempts) == 1:
                    value = json.loads(text)
                    del value["paragraphs"]
                    return json.dumps(value, ensure_ascii=False)
            return text

        host = await self.start(missing_once)
        self.assertIn("走廊里的灯闪了一下", await host.say("/团 选 A"))
        self.assertEqual(len(attempts), 2)
        self.assertIn("- 输出 缺少字段 paragraphs", attempts[1])
        with self.app.store.read() as c:
            rejected = c.execute("SELECT error FROM model_calls WHERE status='rejected'").fetchone()
        self.assertIn("缺少字段 paragraphs", rejected["error"])

    async def test_failed_narration_reads_plainly(self) -> None:
        def never(system: str, prompt: str) -> str:
            text = scripted_model(system, prompt)
            if "根据机械回执叙述" in system:
                value = json.loads(text)
                value["suggestions"] = []
                return json.dumps(value, ensure_ascii=False)
            return text

        host = await self.start(never)
        reply = await host.say("/团 选 A")
        self.assertIn("这一段正文没写出来", reply)
        self.assertIn("/团 主持 重试", reply)
