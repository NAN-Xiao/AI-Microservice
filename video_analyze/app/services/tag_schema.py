"""
标签体系管理。
从 video_tags.json 加载标签体系，从 video_tags_prompt.md 加载额外规则。
支持热更新（修改文件后自动生效，无需重启）。
"""

import json
import logging
from pathlib import Path

from app.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

_RESOURCES_DIR = PROJECT_ROOT / "resources"
_TAGS_FILE = _RESOURCES_DIR / "video_tags.json"
_PROMPT_FILE = _RESOURCES_DIR / "video_tags_prompt.md"

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


def update_tag_schema(new_tags: dict) -> dict:
    """
    校验并更新标签体系，同时持久化到 video_tags.json。
    返回包含统计信息的 dict。
    """
    global _cached_tags, _cached_tags_mtime

    errors = validate_tag_schema(new_tags)
    if errors:
        raise ValueError(f"标签模板格式错误: {'; '.join(errors)}")

    with open(_TAGS_FILE, "w", encoding="utf-8") as f:
        json.dump(new_tags, f, ensure_ascii=False, indent=2)

    _cached_tags = new_tags
    _cached_tags_mtime = _TAGS_FILE.stat().st_mtime

    total_tags = sum(
        len(tags) for level2 in new_tags.values() for tags in level2.values()
    )
    logger.info("标签体系已更新，分类数: %d，总标签数: %d", len(new_tags), total_tags)

    return {
        "categories": len(new_tags),
        "subcategories": sum(len(v) for v in new_tags.values()),
        "total_tags": total_tags,
    }


def validate_tag_schema(tags: dict) -> list[str]:
    """校验标签模板结构: { 一级分类: { 二级分类: [标签, ...] } }"""
    errors = []
    if not isinstance(tags, dict) or len(tags) == 0:
        return ["顶层必须是非空对象"]

    for level1, level2_dict in tags.items():
        if not isinstance(level2_dict, dict):
            errors.append(f"'{level1}' 的值必须是对象，实际为 {type(level2_dict).__name__}")
            continue
        for level2, values in level2_dict.items():
            if not isinstance(values, list):
                errors.append(f"'{level1}.{level2}' 的值必须是数组，实际为 {type(values).__name__}")
            elif not all(isinstance(v, str) for v in values):
                errors.append(f"'{level1}.{level2}' 数组中所有元素必须是字符串")
    return errors


def build_tag_prompt(*, override_tags: dict | None = None) -> str:
    """
    构建视频分析提示词。
    override_tags: 调用方传入的自定义标签体系，不传则使用服务端默认 video_tags.json。
    """
    tags = override_tags if override_tags is not None else get_tag_schema()

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

    return (
        "请先分析视频，再严格按以下要求输出结果：\n\n"
        "一、最终答案只能输出一个 JSON 对象，不能输出任何 JSON 之外的内容。\n"
        "二、不要输出标题、说明、注释、前言、后记、分析报告、时间轴、营销总结、投放建议或可优化建议。\n"
        "三、JSON 的对象结构必须完全按照 tags.json 的结构。\n"
        "四、除了数组 [] 内可以多选候选标签外，其他所有内容都必须保留：不能新增字段、删除字段、改名、改层级、改顺序、改外层结构。\n"
        "五、每个二级字段的值必须是数组；采用宽松输出策略，只要能基于画面、字幕、配音、节奏、镜头语言、营销表达做出高概率判断，就应优先填写标签；只有确实没有依据时才输出空数组 []。\n"
        "六、【最重要】数组中的每一个值必须是下方「候选标签范围」中的原文，逐字匹配，禁止自造标签、改写近义词、缩写、合并或拆分。任何不在候选列表中的标签都会被系统自动丢弃，等于白写。\n"
        "七、输出目标偏向高召回，不要因为不是百分百确定就把大量字段留空。\n"
        "八、如果输出结果不是一个合法 JSON 对象，请先自检并修正，再输出最终答案。\n\n"
        "标签 JSON 结构模板（必须严格照此结构输出）：\n"
        f"{json.dumps(tag_skeleton, ensure_ascii=False, indent=2)}\n\n"
        "候选标签范围（只能从以下列表中逐字选择，系统会校验每一个标签，不在此列表中的会被自动删除）：\n"
        f"{chr(10).join(allowed_lines).strip()}\n\n"
        f"{extra_rules}".strip()
    )


def sanitize_tags(raw: dict, *, override_tags: dict | None = None) -> tuple[dict, list[str]]:
    """
    清洗 LLM 输出的标签。
    override_tags: 调用方传入的自定义标签体系，不传则使用服务端默认。
    返回 (清洗后的结果, 被移除的非法标签列表)
    """
    schema = override_tags if override_tags is not None else get_tag_schema()
    cleaned: dict = {}
    removed: list[str] = []

    for level1, level2_dict in raw.items():
        if level1 not in schema:
            removed.append(f"[未知分类] {level1}")
            continue

        if not isinstance(level2_dict, dict):
            removed.append(f"[格式错误] {level1}: 期望对象，实际为 {type(level2_dict).__name__}")
            continue

        cleaned[level1] = {}
        for level2, values in level2_dict.items():
            if level2 not in schema[level1]:
                removed.append(f"[未知子类] {level1}.{level2}")
                continue

            if not isinstance(values, list):
                removed.append(f"[格式错误] {level1}.{level2}: 期望数组，实际为 {type(values).__name__}")
                cleaned[level1][level2] = []
                continue

            allowed = set(schema[level1][level2])
            valid = []
            for tag in values:
                if tag in allowed:
                    valid.append(tag)
                else:
                    removed.append(f"[非法标签] {level1}.{level2}: '{tag}'")
            cleaned[level1][level2] = valid

    for level1, level2_dict in schema.items():
        if level1 not in cleaned:
            cleaned[level1] = {}
        for level2 in level2_dict:
            if level2 not in cleaned[level1]:
                cleaned[level1][level2] = []

    return cleaned, removed


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
