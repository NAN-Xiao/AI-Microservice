"""
Unity Mapper：将 LLM 返回的 Figma 风格设计 JSON 映射为 Unity UGUI 预制体数据。

处理流水线：
1. Figma type → Unity type 映射
2. Figma style → Unity properties 映射
3. 像素 rect → RectTransform 转换
4. 组件包装 — properties 拆分为 components[] 数组
5. 补全默认值
"""

import logging
import re

logger = logging.getLogger(__name__)

_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{3,8})$")
_NUM_RE = re.compile(r"[\d.]+")

DEFAULT_CANVAS_SIZE = (1080, 1920)

# ── Figma type → Unity type 映射表 ──
_TYPE_MAP = {
    "frame":           "Panel",
    "text":            "Text",
    "image":           "Image",
    "icon":            "Image",
    "rectangle":       "Image",
    "button":          "Button",
    "input":           "InputField",
    "switch":          "Toggle",
    "checkbox":        "Toggle",
    "slider":          "Slider",
    "dropdown":        "Dropdown",
    "scroll_area":     "ScrollView",
    "list":            "VerticalLayoutGroup",
    "horizontal_list": "HorizontalLayoutGroup",
    "grid":            "GridLayoutGroup",
}

# ── Figma text_align → Unity alignment 映射 ──
_ALIGN_MAP = {
    "top_left":       "UpperLeft",
    "top_center":     "UpperCenter",
    "top_right":      "UpperRight",
    "middle_left":    "MiddleLeft",
    "middle_center":  "MiddleCenter",
    "middle_right":   "MiddleRight",
    "bottom_left":    "LowerLeft",
    "bottom_center":  "LowerCenter",
    "bottom_right":   "LowerRight",
    "left":           "MiddleLeft",
    "center":         "MiddleCenter",
    "right":          "MiddleRight",
}


def map_to_unity(raw_node: dict,
                 canvas_w: int | None = None,
                 canvas_h: int | None = None) -> dict:
    """入口：将 Figma 设计树递归转换为 Unity 预制体数据。"""
    cw = canvas_w or DEFAULT_CANVAS_SIZE[0]
    ch = canvas_h or DEFAULT_CANVAS_SIZE[1]
    result = _process_node(raw_node, None, cw, ch, is_root=True)
    return result


def _process_node(node: dict, parent_rect: dict | None,
                  canvas_w: int, canvas_h: int, is_root: bool = False) -> dict:
    figma_type = node.get("type", "frame")
    name = node.get("name", "Node")
    raw_rect = node.get("rect", {})
    style = node.get("style", {})
    raw_children = node.get("children", [])

    if is_root:
        unity_type = "Canvas"
    else:
        unity_type = _TYPE_MAP.get(figma_type, "Panel")
        if figma_type not in _TYPE_MAP:
            logger.warning("未知 Figma 类型 '%s'，降级为 Panel", figma_type)

    rect = _normalize_rect(raw_rect, parent_rect, canvas_w, canvas_h)
    rt = _rect_to_rect_transform(rect, parent_rect, canvas_w, canvas_h, unity_type)
    components = _build_components(unity_type, figma_type, style)

    children = []
    for child in raw_children:
        if isinstance(child, dict):
            children.append(_process_node(child, rect, canvas_w, canvas_h))

    # Button 的 text_content 自动生成 Text 子节点
    if unity_type == "Button" and style.get("text_content") and not _has_text_child(children):
        children.append(_make_text_child(style, rect))

    return {
        "name": name,
        "type": unity_type,
        "rectTransform": rt,
        "components": components,
        "children": children,
    }


def _has_text_child(children: list[dict]) -> bool:
    return any(c.get("type") == "Text" for c in children)


def _make_text_child(style: dict, parent_rect: dict) -> dict:
    """为 Button 自动生成内部 Text 子节点。"""
    return {
        "name": "Text",
        "type": "Text",
        "rectTransform": {
            "anchorMin": [0, 0], "anchorMax": [1, 1],
            "sizeDelta": [0, 0], "anchoredPosition": [0, 0], "pivot": [0.5, 0.5],
        },
        "components": [{
            "type": "Text",
            "text": str(style.get("text_content", "")),
            "fontSize": int(_to_float(style.get("font_size", 24))),
            "color": _normalize_color(style.get("text_color", "#323232")),
            "alignment": _map_alignment(style.get("text_align", "middle_center")),
            "raycastTarget": False,
        }],
        "children": [],
    }


# ── 坐标转换 ──

def _normalize_rect(raw_rect: dict, parent_rect: dict | None, canvas_w: int, canvas_h: int) -> dict:
    x = _to_float(raw_rect.get("x", 0))
    y = _to_float(raw_rect.get("y", 0))
    w = _to_float(raw_rect.get("width", canvas_w if parent_rect is None else parent_rect.get("width", 100)))
    h = _to_float(raw_rect.get("height", canvas_h if parent_rect is None else parent_rect.get("height", 100)))
    return {"x": x, "y": y, "width": w, "height": h}


def _rect_to_rect_transform(rect: dict, parent_rect: dict | None,
                             canvas_w: int, canvas_h: int, unity_type: str) -> dict:
    if unity_type == "Canvas":
        return {
            "anchorMin": [0, 0], "anchorMax": [1, 1],
            "sizeDelta": [0, 0], "anchoredPosition": [0, 0], "pivot": [0.5, 0.5],
        }

    pw = parent_rect["width"] if parent_rect else canvas_w
    ph = parent_rect["height"] if parent_rect else canvas_h
    if pw <= 0:
        pw = canvas_w
    if ph <= 0:
        ph = canvas_h

    x, y, w, h = rect["x"], rect["y"], rect["width"], rect["height"]

    anchor_min_x = _clamp01(round(x / pw, 4))
    anchor_max_x = _clamp01(round((x + w) / pw, 4))
    anchor_min_y = _clamp01(round(1 - (y + h) / ph, 4))
    anchor_max_y = _clamp01(round(1 - y / ph, 4))

    return {
        "anchorMin": [anchor_min_x, anchor_min_y],
        "anchorMax": [anchor_max_x, anchor_max_y],
        "sizeDelta": [0, 0],
        "anchoredPosition": [0, 0],
        "pivot": [0.5, 0.5],
    }


# ── 组件构建：Figma style → Unity components[] ──

def _build_components(unity_type: str, figma_type: str, style: dict) -> list[dict]:
    fill = _normalize_color(style.get("fill", "#FFFFFF"))

    if unity_type == "Canvas":
        return [
            {"type": "Canvas", "renderMode": "ScreenSpaceOverlay"},
            {"type": "CanvasScaler", "uiScaleMode": "ScaleWithScreenSize",
             "referenceResolution": [DEFAULT_CANVAS_SIZE[0], DEFAULT_CANVAS_SIZE[1]]},
            {"type": "GraphicRaycaster"},
        ]

    if unity_type == "Panel":
        return [{"type": "Image", "color": fill, "raycastTarget": True}]

    if unity_type == "Image":
        return [{"type": "Image", "color": fill, "raycastTarget": True,
                 "imageType": "Simple", "preserveAspect": figma_type == "image"}]

    if unity_type == "Text":
        return [{
            "type": "Text",
            "text": str(style.get("text_content", "")),
            "fontSize": int(_to_float(style.get("font_size", 24))),
            "color": _normalize_color(style.get("text_color", "#323232")),
            "alignment": _map_alignment(style.get("text_align", "upper_left")),
            "fontStyle": "Bold" if style.get("font_weight") == "bold" else "Normal",
            "raycastTarget": False,
        }]

    if unity_type == "Button":
        return [
            {"type": "Image", "color": fill},
            {"type": "Button", "interactable": True},
        ]

    if unity_type == "Toggle":
        return [
            {"type": "Toggle",
             "isOn": bool(style.get("checked", False)),
             "interactable": True},
        ]

    if unity_type == "Slider":
        return [{
            "type": "Slider",
            "value": _to_float(style.get("current_value", 0)),
            "minValue": _to_float(style.get("min_value", 0)),
            "maxValue": _to_float(style.get("max_value", 1)),
            "direction": "LeftToRight",
            "interactable": True,
        }]

    if unity_type == "Dropdown":
        raw_opts = style.get("options", [])
        options = [str(o) for o in raw_opts] if isinstance(raw_opts, list) else []
        return [
            {"type": "Image", "color": fill},
            {"type": "Dropdown", "options": options, "value": 0, "interactable": True},
        ]

    if unity_type == "InputField":
        return [
            {"type": "Image", "color": fill},
            {"type": "InputField",
             "text": str(style.get("text_content", "")),
             "placeholder": str(style.get("placeholder", "请输入...")),
             "textColor": _normalize_color(style.get("text_color", "#323232")),
             "fontSize": int(_to_float(style.get("font_size", 24))),
             "contentType": "Standard", "lineType": "SingleLine",
             "interactable": True},
        ]

    if unity_type == "ScrollView":
        direction = style.get("scroll_direction", "vertical")
        h_scroll = direction in ("horizontal", "both")
        v_scroll = direction in ("vertical", "both")
        return [
            {"type": "Image", "color": fill},
            {"type": "ScrollRect",
             "horizontal": h_scroll, "vertical": v_scroll,
             "movementType": "Elastic", "elasticity": 0.1,
             "inertia": True, "scrollSensitivity": 1},
            {"type": "Mask"},
        ]

    if unity_type == "VerticalLayoutGroup":
        return [{
            "type": "VerticalLayoutGroup",
            "spacing": _to_float(style.get("spacing", 0)),
            "padding": _to_rect_offset(style.get("padding"), [0, 0, 0, 0]),
            "childAlignment": "UpperLeft",
            "childForceExpandWidth": True,
            "childForceExpandHeight": False,
            "childControlWidth": True,
            "childControlHeight": False,
        }]

    if unity_type == "HorizontalLayoutGroup":
        return [{
            "type": "HorizontalLayoutGroup",
            "spacing": _to_float(style.get("spacing", 0)),
            "padding": _to_rect_offset(style.get("padding"), [0, 0, 0, 0]),
            "childAlignment": "MiddleCenter",
            "childForceExpandWidth": True,
            "childForceExpandHeight": True,
            "childControlWidth": True,
            "childControlHeight": True,
        }]

    if unity_type == "GridLayoutGroup":
        cw = _to_float(style.get("cell_width", 100))
        ch = _to_float(style.get("cell_height", 100))
        cols = int(_to_float(style.get("columns", 2)))
        return [{
            "type": "GridLayoutGroup",
            "cellSize": [cw, ch],
            "spacing": _to_vector2(style.get("spacing"), [0, 0]),
            "padding": _to_rect_offset(style.get("padding"), [0, 0, 0, 0]),
            "startCorner": "UpperLeft",
            "startAxis": "Horizontal",
            "childAlignment": "UpperLeft",
            "constraint": "FixedColumnCount" if cols > 0 else "Flexible",
            "constraintCount": cols,
        }]

    return [{"type": "Image", "color": fill}]


# ── 工具函数 ──

def _map_alignment(figma_align) -> str:
    if not isinstance(figma_align, str):
        return "UpperLeft"
    return _ALIGN_MAP.get(figma_align.lower().replace("-", "_").replace(" ", "_"), "UpperLeft")


def _normalize_color(value) -> str:
    if not isinstance(value, str):
        return "#FFFFFFFF"
    value = value.strip()
    m = _COLOR_RE.match(value)
    if not m:
        return "#FFFFFFFF"
    hex_str = m.group(1).upper()
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str) + "FF"
    elif len(hex_str) == 4:
        hex_str = "".join(c * 2 for c in hex_str)
    elif len(hex_str) == 6:
        hex_str += "FF"
    elif len(hex_str) == 8:
        pass
    else:
        return "#FFFFFFFF"
    return f"#{hex_str}"


def _to_float(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _NUM_RE.search(value)
        if m:
            return float(m.group())
    return 0.0


def _to_vector2(value, default) -> list:
    if isinstance(value, (int, float)):
        v = float(value)
        return [v, v]
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return [_to_float(value[0]), _to_float(value[1])]
    return list(default)


def _to_rect_offset(value, default) -> list:
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        return [int(_to_float(v)) for v in value[:4]]
    return list(default)


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))
