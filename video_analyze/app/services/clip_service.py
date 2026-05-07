"""
视频切片分析服务：构建切片 prompt 并清洗 LLM 返回结果。
输出格式参考 resources/video_clip.md。
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CLIP_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "resources" / "video_clip.md"
_CLIP_PROMPT_TEMPLATE: str | None = None


def _load_clip_prompt_template() -> str:
    """加载 video_clip.md 中的切片规则作为 system prompt。"""
    global _CLIP_PROMPT_TEMPLATE
    if _CLIP_PROMPT_TEMPLATE is not None:
        return _CLIP_PROMPT_TEMPLATE

    if not _CLIP_PROMPT_PATH.exists():
        raise RuntimeError(f"切片规则文件不存在: {_CLIP_PROMPT_PATH}")

    _CLIP_PROMPT_TEMPLATE = _CLIP_PROMPT_PATH.read_text(encoding="utf-8")
    return _CLIP_PROMPT_TEMPLATE


def build_clip_prompt(*, extra_prompt: str = "") -> str:
    """
    构造视频切片分析的完整 prompt。

    将 video_clip.md 中的输出规则作为 system prompt，
    额外追加用户自定义提示词。
    """
    base = _load_clip_prompt_template()
    if extra_prompt:
        return f"{base}\n\n【用户补充要求】\n{extra_prompt}"
    return base


def sanitize_clip_result(raw: dict) -> tuple[dict, list[str]]:
    """
    校验并清洗 LLM 返回的切片结果。

    返回: (清洗后的 dict, 被移除的字段/错误描述列表)
    如果结构严重不符，抛出 ValueError。
    """
    removed: list[str] = []
    cleaned: dict = {}

    # ── 顶层字段 ──
    if "instructions" not in raw:
        raise ValueError("缺少必需字段: instructions")
    if "emotion" not in raw:
        raise ValueError("缺少必需字段: emotion")

    cleaned["emotion"] = str(raw["emotion"]).strip()
    if not cleaned["emotion"]:
        raise ValueError("emotion 不能为空字符串")

    instructions = raw["instructions"]
    if not isinstance(instructions, list):
        raise ValueError(f"instructions 必须是数组，实际为: {type(instructions).__name__}")

    cleaned_instructions: list[dict] = []
    for idx, item in enumerate(instructions):
        if not isinstance(item, dict):
            removed.append(f"instructions[{idx}]: 非对象类型，跳过")
            continue

        # 收集必需字段
        start = item.get("start")
        end = item.get("end")
        time_str = item.get("time_str")
        content = item.get("content")

        missing = []
        if start is None:
            missing.append("start")
        if end is None:
            missing.append("end")
        if time_str is None:
            missing.append("time_str")
        if content is None:
            missing.append("content")

        if missing:
            removed.append(f"instructions[{idx}]: 缺少字段 {missing}，跳过")
            continue

        # 类型校验
        if not isinstance(start, int):
            removed.append(f"instructions[{idx}]: start 不是整数 ({type(start).__name__})，尝试转换")
            try:
                start = int(start)
            except (ValueError, TypeError):
                removed.append(f"instructions[{idx}]: start 无法转换为整数，跳过")
                continue

        if not isinstance(end, int):
            removed.append(f"instructions[{idx}]: end 不是整数 ({type(end).__name__})，尝试转换")
            try:
                end = int(end)
            except (ValueError, TypeError):
                removed.append(f"instructions[{idx}]: end 无法转换为整数，跳过")
                continue

        if start < 0 or end <= start:
            removed.append(f"instructions[{idx}]: 时间段非法 start={start}, end={end}，跳过")
            continue

        cleaned_item = {
            "start": start,
            "end": end,
            "time_str": str(time_str).strip(),
            "content": str(content).strip(),
        }
        cleaned_instructions.append(cleaned_item)

    if not cleaned_instructions:
        raise ValueError("instructions 数组为空或全部校验失败")

    cleaned["instructions"] = cleaned_instructions
    return cleaned, removed
