"""
标签体系管理。
从 video_tags.json 加载标签体系，从 video_tags_prompt.md 加载额外规则。
支持热更新（修改文件后自动生效，无需重启）。
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).parent.parent
_TAGS_FILE = _BASE_DIR / "video_tags.json"
_PROMPT_FILE = _BASE_DIR / "video_tags_prompt.md"

_cached_tags: dict | None = None
_cached_tags_mtime: float = 0
_cached_prompt_mtime: float = 0
_cached_prompt: str = ""


def get_tag_schema() -> dict:
    """获取当前标签体系，文件更新后自动重新加载。"""
    global _cached_tags, _cached_tags_mtime

    current_mtime = _TAGS_FILE.stat().st_mtime
    if _cached_tags is None or current_mtime != _cached_tags_mtime:
        logger.info("加载标签体系: %s", _TAGS_FILE)
        with open(_TAGS_FILE, "r", encoding="utf-8") as f:
            _cached_tags = json.load(f)
        _cached_tags_mtime = current_mtime
        logger.info("标签体系已更新，分类数: %d", len(_cached_tags))

    return _cached_tags


def build_tag_prompt(extra_prompt: str = "") -> str:
    """
    从 video_tags.json + video_tags_prompt.md 构建视频分析提示词。
    两个文件都支持热更新。
    """
    tags = get_tag_schema()

    tag_skeleton = {
        level1: {level2: [] for level2 in level1_value}
        for level1, level1_value in tags.items()
    }

    allowed_lines: list[str] = []
    for level1, level1_value in tags.items():
        allowed_lines.append(level1)
        for level2, options in level1_value.items():
            allowed_lines.append(f"- {level2}: {', '.join(options)}")
        allowed_lines.append("")

    extra_rules = _load_prompt_file()
    if extra_prompt:
        extra_rules = f"{extra_rules}\n\n{extra_prompt}".strip()

    return (
        "请先分析视频，再严格按以下要求输出结果：\n\n"
        "一、最终答案只能输出一个 JSON 对象，不能输出任何 JSON 之外的内容。\n"
        "二、不要输出标题、说明、注释、前言、后记、分析报告、时间轴、营销总结、投放建议或可优化建议。\n"
        "三、JSON 的对象结构必须完全按照 tags.json 的结构。\n"
        "四、除了数组 [] 内可以多选候选标签外，其他所有内容都必须保留：不能新增字段、删除字段、改名、改层级、改顺序、改外层结构。\n"
        "五、每个二级字段的值必须是数组；采用宽松输出策略，只要能基于画面、字幕、配音、节奏、镜头语言、营销表达做出高概率判断，就应优先填写标签；只有确实没有依据时才输出空数组 []。\n"
        "六、数组中的值只能从 tags.json 提供的候选项中选择，禁止自造标签或改写近义词。\n"
        "七、输出目标偏向高召回，不要因为不是百分百确定就把大量字段留空。\n"
        "八、如果输出结果不是一个合法 JSON 对象，请先自检并修正，再输出最终答案。\n\n"
        "标签 JSON 结构模板（必须严格照此结构输出）：\n"
        f"{json.dumps(tag_skeleton, ensure_ascii=False, indent=2)}\n\n"
        "候选标签范围（必须只从这里选）：\n"
        f"{chr(10).join(allowed_lines).strip()}\n\n"
        f"{extra_rules}".strip()
    )


def _load_prompt_file() -> str:
    """加载额外提示词文件，支持热更新。"""
    global _cached_prompt, _cached_prompt_mtime

    if not _PROMPT_FILE.is_file():
        return ""

    current_mtime = _PROMPT_FILE.stat().st_mtime
    if current_mtime != _cached_prompt_mtime:
        logger.info("加载额外提示词: %s", _PROMPT_FILE)
        _cached_prompt = _PROMPT_FILE.read_text(encoding="utf-8").strip()
        _cached_prompt_mtime = current_mtime

    return _cached_prompt
