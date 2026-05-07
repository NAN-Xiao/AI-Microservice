import unittest
from pathlib import Path

from app.routers import analyze as analyze_router
from app.routers import clip as clip_router
from app.services.tag_schema import build_tag_prompt
from app.services.task_store import task_store


class RouteRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_analyze_worker_uses_shared_llm_helpers(self):
        original_analyze = analyze_router.llm_service.analyze

        async def fake_analyze(video_url: str, prompt: str) -> str:
            return '{"category":{"sub":["allowed"]}}'

        analyze_router.llm_service.analyze = fake_analyze
        try:
            task = await task_store.create(
                "http://example.com/video.mp4",
                custom_tags={"category": {"sub": ["allowed"]}},
            )

            await analyze_router._run_analysis(
                task.task_id,
                task.video_url,
                custom_tags={"category": {"sub": ["allowed"]}},
            )

            saved = await task_store.get(task.task_id)
            self.assertIsNotNone(saved)
            self.assertEqual(saved.status.value, "completed")
            self.assertEqual(saved.result, {"category": {"sub": ["allowed"]}})
        finally:
            analyze_router.llm_service.analyze = original_analyze

    async def test_task_detail_routes_do_not_cross_task_types(self):
        analyze_task = await task_store.create("http://example.com/analyze.mp4")
        clip_task = await task_store.create("http://example.com/clip.mp4", task_type="clip")

        clip_lookup = await clip_router.get_clip_task(analyze_task.task_id)
        analyze_lookup = await analyze_router.get_task(clip_task.task_id)

        self.assertEqual(clip_lookup.code, 404)
        self.assertEqual(analyze_lookup.code, 404)


class PromptTemplateTests(unittest.TestCase):
    def test_analyze_prompt_uses_resource_markdown_template(self):
        template_path = Path(__file__).resolve().parent / "resources" / "video_analyze.md"

        self.assertTrue(template_path.is_file())
        template = template_path.read_text(encoding="utf-8")
        self.assertIn("{tag_skeleton}", template)
        self.assertIn("{allowed_tags}", template)

        prompt = build_tag_prompt(
            override_tags={"一级": {"二级": ["标签A"]}},
            extra_prompt="额外要求",
        )

        self.assertIn("请先分析视频，再严格按以下要求输出结果", prompt)
        self.assertIn('"一级": {', prompt)
        self.assertIn("- 二级: 标签A", prompt)
        self.assertIn("## 用户补充要求", prompt)
        self.assertIn("额外要求", prompt)


if __name__ == "__main__":
    unittest.main()
