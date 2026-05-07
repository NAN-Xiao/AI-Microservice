"""
标签体系管理。
从 video_tags.json 加载标签体系，从 video_analyze.md 加载提示词模板。
支持热更新（修改文件后自动生效，无需重启）。
"""

import json
import logging
import os
import tempfile
from pathlib import Path

from app.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

_RESOURCES_DIR = PROJECT_ROOT / "resources"
_TAGS_FILE = _RESOURCES_DIR / "video_tags.json"
_PROMPT_FILE = _RESOURCES_DIR / "video_analyze.md"

_cached_tags: dict | None = None
_cached_tags_mtime: float = 0
_cached_prompt_template_mtime: float = 0
_cached_prompt_template: str = ""


def get_tag_schema() -> dict:
    """获取当前标签体系，文件更新后自动重新加载。"""
    global _cached_tags, _cached_tags_mtime

    if not _TAGS_FILE.is_file():
        logger.error("标签文件不存在: %s", _TAGS_FILE)
        raise FileNotFoundError(f"标签文件不存在: {_TAGS_FILE}")

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

    # 原子写：先写临时文件再替换，防止中途崩溃导致文件损坏
    tmp_fd, tmp_path = tempfile.mkstemp(dir=_RESOURCES_DIR, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(new_tags, f, ensure_ascii=False, indent=2)
        Path(tmp_path).replace(_TAGS_FILE)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

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


def build_tag_prompt(*, override_tags: dict | None = None, extra_prompt: str = "") -> str:
    """
    构建视频分析提示词。
    override_tags: 调用方传入的自定义标签体系，不传则使用服务端默认 video_tags.json。
    extra_prompt: 用户额外提示词，会追加到 prompt 末尾。
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

    prompt = _load_prompt_template().format(
        tag_skeleton=json.dumps(tag_skeleton, ensure_ascii=False, indent=2),
        allowed_tags=chr(10).join(allowed_lines).strip(),
    )
    if extra_prompt:
        prompt = f"{prompt}\n\n## 用户补充要求\n{extra_prompt.strip()}"

    return prompt.strip()


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


def _load_prompt_template() -> str:
    """加载分析提示词模板，支持热更新。"""
    global _cached_prompt_template, _cached_prompt_template_mtime

    if not _PROMPT_FILE.is_file():
        logger.error("分析提示词模板不存在: %s", _PROMPT_FILE)
        raise FileNotFoundError(f"分析提示词模板不存在: {_PROMPT_FILE}")

    current_mtime = _PROMPT_FILE.stat().st_mtime
    if current_mtime != _cached_prompt_template_mtime:
        logger.info("加载分析提示词模板: %s", _PROMPT_FILE)
        _cached_prompt_template = _PROMPT_FILE.read_text(encoding="utf-8").strip()
        _cached_prompt_template_mtime = current_mtime

    return _cached_prompt_template
