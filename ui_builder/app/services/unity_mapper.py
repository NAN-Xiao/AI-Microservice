"""
Unity Mapper —— Figma 风格设计 JSON → Unity UGUI 预制体数据。

══════════════════════════════════════════════════════════════════
映射规范（所有规则均在此文件中显式定义，无隐含约定）
══════════════════════════════════════════════════════════════════

1. 每种 Figma type 有一个对应的 **结构构建器（_build_xxx）**，负责：
   - 确定输出的 Unity 节点层级（1:1 或 1:N 展开）
   - 挂载的组件列表及属性来源
   - Figma 子节点放到输出结构的哪个节点下

2. 简单 1:1 映射（子节点直接挂在输出节点下）：
   - frame        → Panel       : Image(color=fill)
   - text         → Text        : Text(text, fontSize, color, alignment, fontStyle)
   - image/icon   → Image       : Image(color=fill, preserveAspect)
   - rectangle    → Image       : Image(color=fill)
   - switch/check → Toggle      : Toggle(isOn, interactable)
   - dropdown     → Dropdown    : Image + Dropdown(options)
   - list         → VLG         : VerticalLayoutGroup(spacing, padding, childControl*)
   - h_list       → HLG         : HorizontalLayoutGroup(spacing, padding, childControl*)
   - grid         → GLG         : GridLayoutGroup(cellSize, spacing, columns)

3. 复合类型（1:N 展开，生成标准 Unity 子层级）：
   - scroll_area  → ScrollView  : [Name] / Viewport / Content
   - button       → Button      : [Name] / Text（当有 text_content 时）
   - input        → InputField  : [Name] / Text / Placeholder
   - slider       → Slider      : [Name] / Background / FillArea>Fill / HandleArea>Handle

4. LayoutGroup 子节点规则（当父节点是 VLG / HLG / GLG 时）：
   - RectTransform 切换为绝对像素尺寸（sizeDelta），不使用锚点拉伸
   - 追加 LayoutElement 组件，preferred 尺寸 = Figma rect 的 width / height

5. 分辨率适配：
   - 先用图片原始分辨率构建整棵树（锚点为相对比例）
   - 再按 scale = min(target/source) 统一缩放所有绝对像素值
   - CanvasScaler.referenceResolution = 等比缩放后的实际尺寸
"""

import logging
import re

logger = logging.getLogger(__name__)

_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{3,8})$")
_NUM_RE = re.compile(r"[\d.]+")

DEFAULT_CANVAS_SIZE = (1080, 1920)

# ══════════════════════════════════════════════════════════════════
# Figma type → Unity type 映射表
# ══════════════════════════════════════════════════════════════════

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

_ALIGN_MAP = {
    "top_left": "UpperLeft", "top_center": "UpperCenter", "top_right": "UpperRight",
    "middle_left": "MiddleLeft", "middle_center": "MiddleCenter", "middle_right": "MiddleRight",
    "bottom_left": "LowerLeft", "bottom_center": "LowerCenter", "bottom_right": "LowerRight",
    "left": "MiddleLeft", "center": "MiddleCenter", "right": "MiddleRight",
}

_LAYOUT_TYPES = {"VerticalLayoutGroup", "HorizontalLayoutGroup", "GridLayoutGroup"}

_STRETCH = {"anchorMin": [0, 0], "anchorMax": [1, 1],
            "sizeDelta": [0, 0], "anchoredPosition": [0, 0], "pivot": [0.5, 0.5]}


# ══════════════════════════════════════════════════════════════════
# 公共入口
# ══════════════════════════════════════════════════════════════════

def map_to_unity(raw_node: dict,
                 source_w: int | None = None, source_h: int | None = None,
                 target_w: int | None = None, target_h: int | None = None) -> dict:
    """将 Figma 设计树转换为 Unity 预制体数据。

    source = 图片原始分辨率；target = 用户期望的目标分辨率。
    缩放策略：scale = min(target/source)，保持宽高比。
    """
    sw = source_w or DEFAULT_CANVAS_SIZE[0]
    sh = source_h or DEFAULT_CANVAS_SIZE[1]
    tw = target_w or sw
    th = target_h or sh

    result = _process_node(raw_node, None, sw, sh, is_root=True)

    scale = min(tw / sw, th / sh)
    canvas_w = round(sw * scale)
    canvas_h = round(sh * scale)
    _set_canvas_reference(result, canvas_w, canvas_h)

    if abs(scale - 1.0) > 1e-6:
        logger.info("等比缩放 %dx%d → %dx%d (scale=%.4f)", sw, sh, canvas_w, canvas_h, scale)
        _scale_tree(result, scale, scale, is_root=True)

    return result


# ══════════════════════════════════════════════════════════════════
# 递归处理 + 分发
# ══════════════════════════════════════════════════════════════════

def _process_node(node: dict, parent_rect: dict | None,
                  cw: int, ch: int,
                  is_root: bool = False,
                  parent_unity_type: str = "") -> dict:
    """递归处理单个 Figma 节点，分发到对应的结构构建器。"""
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

    rect = _normalize_rect(raw_rect, parent_rect, cw, ch)

    # ── RectTransform 策略 ──
    in_layout = parent_unity_type in _LAYOUT_TYPES
    if in_layout:
        rt = _layout_child_rt(rect, parent_unity_type)
    else:
        rt = _anchor_rt(rect, parent_rect, cw, ch, unity_type)

    # ── 递归处理子节点 ──
    children = []
    for child in raw_children:
        if isinstance(child, dict):
            children.append(_process_node(child, rect, cw, ch,
                                          parent_unity_type=unity_type))

    # ── 分发到结构构建器 ──
    builder = _BUILDERS.get(unity_type, _build_panel)
    result = builder(name=name, unity_type=unity_type, figma_type=figma_type,
                     rt=rt, style=style, rect=rect, children=children,
                     raw_children=raw_children, cw=cw, ch=ch)

    # ── LayoutGroup 子节点规则：追加 LayoutElement ──
    if in_layout:
        _inject_layout_element(result["components"], rect, parent_unity_type)

    return result


# ══════════════════════════════════════════════════════════════════
# 结构构建器 —— 简单 1:1 映射
# ══════════════════════════════════════════════════════════════════

def _build_canvas(*, name, rt, style, children, cw, ch, **_) -> dict:
    """根节点 → Canvas + CanvasScaler + GraphicRaycaster"""
    return _node(name, "Canvas", rt, [
        {"type": "Canvas", "renderMode": "ScreenSpaceOverlay"},
        {"type": "CanvasScaler", "uiScaleMode": "ScaleWithScreenSize",
         "referenceResolution": [cw, ch]},
        {"type": "GraphicRaycaster"},
    ], children)


def _build_panel(*, name, unity_type, style, rt, children, **_) -> dict:
    """frame → Panel : Image(fill)"""
    fill = _color(style.get("fill", "#FFFFFF"))
    return _node(name, unity_type or "Panel", rt,
                 [{"type": "Image", "color": fill, "raycastTarget": True}],
                 children)


def _build_text(*, name, style, rt, children, **_) -> dict:
    """text → Text : Text 组件"""
    return _node(name, "Text", rt, [{
        "type": "Text",
        "text": str(style.get("text_content", "")),
        "fontSize": int(_f(style.get("font_size", 24))),
        "color": _color(style.get("text_color", "#323232")),
        "alignment": _align(style.get("text_align", "upper_left")),
        "fontStyle": "Bold" if style.get("font_weight") == "bold" else "Normal",
        "raycastTarget": False,
    }], children)


def _build_image(*, name, figma_type, style, rt, children, **_) -> dict:
    """image / icon / rectangle → Image"""
    fill = _color(style.get("fill", "#FFFFFF"))
    return _node(name, "Image", rt, [{
        "type": "Image", "color": fill, "raycastTarget": True,
        "imageType": "Simple", "preserveAspect": figma_type == "image",
    }], children)


def _build_toggle(*, name, style, rt, children, **_) -> dict:
    """switch / checkbox → Toggle"""
    return _node(name, "Toggle", rt, [{
        "type": "Toggle",
        "isOn": bool(style.get("checked", False)),
        "interactable": True,
    }], children)


def _build_dropdown(*, name, style, rt, children, **_) -> dict:
    """dropdown → Image + Dropdown"""
    fill = _color(style.get("fill", "#FFFFFF"))
    raw_opts = style.get("options", [])
    options = [str(o) for o in raw_opts] if isinstance(raw_opts, list) else []
    return _node(name, "Dropdown", rt, [
        {"type": "Image", "color": fill},
        {"type": "Dropdown", "options": options, "value": 0, "interactable": True},
    ], children)


def _build_vlg(*, name, style, rt, children, **_) -> dict:
    """list → VerticalLayoutGroup"""
    return _node(name, "VerticalLayoutGroup", rt, [{
        "type": "VerticalLayoutGroup",
        "spacing": _f(style.get("spacing", 0)),
        "padding": _rect_offset(style.get("padding"), [0, 0, 0, 0]),
        "childAlignment": "UpperLeft",
        "childForceExpandWidth": True, "childForceExpandHeight": False,
        "childControlWidth": True, "childControlHeight": True,
    }], children)


def _build_hlg(*, name, style, rt, children, **_) -> dict:
    """horizontal_list → HorizontalLayoutGroup"""
    return _node(name, "HorizontalLayoutGroup", rt, [{
        "type": "HorizontalLayoutGroup",
        "spacing": _f(style.get("spacing", 0)),
        "padding": _rect_offset(style.get("padding"), [0, 0, 0, 0]),
        "childAlignment": "MiddleCenter",
        "childForceExpandWidth": False, "childForceExpandHeight": True,
        "childControlWidth": True, "childControlHeight": True,
    }], children)


def _build_glg(*, name, style, rt, children, **_) -> dict:
    """grid → GridLayoutGroup"""
    cell_w = _f(style.get("cell_width", 100))
    cell_h = _f(style.get("cell_height", 100))
    cols = int(_f(style.get("columns", 2)))
    return _node(name, "GridLayoutGroup", rt, [{
        "type": "GridLayoutGroup",
        "cellSize": [cell_w, cell_h],
        "spacing": _vec2(style.get("spacing"), [0, 0]),
        "padding": _rect_offset(style.get("padding"), [0, 0, 0, 0]),
        "startCorner": "UpperLeft", "startAxis": "Horizontal",
        "childAlignment": "UpperLeft",
        "constraint": "FixedColumnCount" if cols > 0 else "Flexible",
        "constraintCount": cols,
    }], children)


# ══════════════════════════════════════════════════════════════════
# 结构构建器 —— 复合类型（1:N 展开）
# ══════════════════════════════════════════════════════════════════

def _build_button(*, name, style, rt, children, **_) -> dict:
    """button → [Name](Image+Button) / Text

    展开规范：
    - [Name]       : Image(fill) + Button(interactable)
    - [Name]/Text  : Text(text_content, fontSize, color)  stretch 铺满父级
    - Figma 子节点挂在 [Name] 下（与 Text 同级）
    - 仅当 style.text_content 存在时才生成 Text 子节点
    """
    fill = _color(style.get("fill", "#FFFFFF"))
    comps = [
        {"type": "Image", "color": fill},
        {"type": "Button", "interactable": True},
    ]
    all_children = list(children)

    text_content = style.get("text_content")
    if text_content and not any(c.get("type") == "Text" for c in children):
        all_children.append(_node("Text", "Text", dict(_STRETCH), [{
            "type": "Text",
            "text": str(text_content),
            "fontSize": int(_f(style.get("font_size", 24))),
            "color": _color(style.get("text_color", "#323232")),
            "alignment": _align(style.get("text_align", "middle_center")),
            "raycastTarget": False,
        }], []))

    return _node(name, "Button", rt, comps, all_children)


def _build_input_field(*, name, style, rt, rect, children, **_) -> dict:
    """input → [Name](Image+InputField) / Text / Placeholder

    展开规范：
    - [Name]             : Image(fill) + InputField(contentType, lineType, interactable)
    - [Name]/Text        : Text(text_content, fontSize, textColor)  留 10px 内边距
    - [Name]/Placeholder : Text(placeholder, fontSize, placeholderColor=50%灰)  同上
    - InputField.textComponent → Text, InputField.placeholder → Placeholder
    - Figma 子节点挂在 [Name] 下
    """
    fill = _color(style.get("fill", "#FFFFFF"))
    text_color = _color(style.get("text_color", "#323232"))
    font_size = int(_f(style.get("font_size", 24)))
    text_val = str(style.get("text_content", ""))
    placeholder = str(style.get("placeholder", "请输入..."))

    padded_rt = {
        "anchorMin": [0, 0], "anchorMax": [1, 1],
        "sizeDelta": [-20, -10], "anchoredPosition": [0, 0], "pivot": [0.5, 0.5],
    }

    text_child = _node("Text", "Text", dict(padded_rt), [{
        "type": "Text", "text": text_val, "fontSize": font_size,
        "color": text_color, "alignment": "MiddleLeft",
        "fontStyle": "Normal", "raycastTarget": False,
    }], [])

    placeholder_child = _node("Placeholder", "Text", dict(padded_rt), [{
        "type": "Text", "text": placeholder, "fontSize": font_size,
        "color": _color("#80808080"), "alignment": "MiddleLeft",
        "fontStyle": "Italic", "raycastTarget": False,
    }], [])

    all_children = [text_child, placeholder_child] + list(children)

    return _node(name, "InputField", rt, [
        {"type": "Image", "color": fill},
        {"type": "InputField",
         "contentType": "Standard", "lineType": "SingleLine",
         "interactable": True},
    ], all_children)


def _build_slider(*, name, style, rt, rect, children, **_) -> dict:
    """slider → [Name](Slider) / Background / FillArea>Fill / HandleArea>Handle

    展开规范：
    - [Name]                    : Slider(value, min, max, direction)
    - [Name]/Background         : Image(fill=#E0E0E0)  stretch 铺满
    - [Name]/FillArea           : RectTransform  stretch 铺满，右侧留 handle 空间
    - [Name]/FillArea/Fill      : Image(fillColor=#4CAF50)  stretch 铺满 FillArea
    - [Name]/HandleArea         : RectTransform  stretch 铺满，用于约束 Handle 滑动范围
    - [Name]/HandleArea/Handle  : Image(#FFFFFF)  固定 30×30，居中
    - Slider.fillRect → Fill, Slider.handleRect → Handle
    """
    value = _f(style.get("current_value", 0))
    min_v = _f(style.get("min_value", 0))
    max_v = _f(style.get("max_value", 1))
    fill = _color(style.get("fill", "#E0E0E0"))

    h = rect["height"]
    handle_size = max(h * 0.8, 20)

    bg = _node("Background", "Image", dict(_STRETCH),
               [{"type": "Image", "color": fill, "raycastTarget": True}], [])

    fill_node = _node("Fill", "Image", dict(_STRETCH),
                       [{"type": "Image", "color": _color("#4CAF50FF"),
                         "raycastTarget": False}], [])
    fill_area = _node("FillArea", "Panel", {
        "anchorMin": [0, 0.25], "anchorMax": [1, 0.75],
        "sizeDelta": [0, 0], "anchoredPosition": [0, 0], "pivot": [0.5, 0.5],
    }, [], [fill_node])

    handle = _node("Handle", "Image", {
        "anchorMin": [0.5, 0.5], "anchorMax": [0.5, 0.5],
        "sizeDelta": [handle_size, handle_size],
        "anchoredPosition": [0, 0], "pivot": [0.5, 0.5],
    }, [{"type": "Image", "color": "#FFFFFFFF", "raycastTarget": True}], [])
    handle_area = _node("HandleArea", "Panel", dict(_STRETCH), [], [handle])

    all_children = [bg, fill_area, handle_area] + list(children)

    return _node(name, "Slider", rt, [{
        "type": "Slider",
        "value": value, "minValue": min_v, "maxValue": max_v,
        "direction": "LeftToRight", "interactable": True,
    }], all_children)


def _build_scroll_view(*, name, style, rt, rect, children, raw_children, **_) -> dict:
    """scroll_area → [Name](Image+ScrollRect) / Viewport(Image+Mask) / Content

    展开规范：
    - [Name]                    : Image(fill) + ScrollRect(direction)
    - [Name]/Viewport           : Image + Mask(showMaskGraphic=false)  stretch 铺满
    - [Name]/Viewport/Content   : RectTransform  sizeDelta 从 Figma 子节点包围盒计算
    - Figma 子节点挂在 Content 下
    - ScrollRect.viewport → Viewport, ScrollRect.content → Content
    - Content 尺寸规则：
      · 垂直：宽 stretch 跟 Viewport，高 = max(子节点包围盒高, viewport高)
      · 水平：高 stretch 跟 Viewport，宽 = max(子节点包围盒宽, viewport宽)
    """
    fill = _color(style.get("fill", "#FFFFFF"))
    direction = style.get("scroll_direction", "vertical")
    is_v = direction in ("vertical", "both")
    is_h = direction in ("horizontal", "both")

    content_w, content_h = _content_bounds(raw_children, rect["width"], rect["height"])

    if is_v:
        content_rt = {"anchorMin": [0, 1], "anchorMax": [1, 1],
                      "sizeDelta": [0, content_h], "anchoredPosition": [0, 0],
                      "pivot": [0.5, 1]}
    elif is_h:
        content_rt = {"anchorMin": [0, 0], "anchorMax": [0, 1],
                      "sizeDelta": [content_w, 0], "anchoredPosition": [0, 0],
                      "pivot": [0, 0.5]}
    else:
        content_rt = {"anchorMin": [0, 1], "anchorMax": [1, 1],
                      "sizeDelta": [0, content_h], "anchoredPosition": [0, 0],
                      "pivot": [0.5, 1]}

    content = _node("Content", "Panel", content_rt, [], children)

    viewport = _node("Viewport", "Panel", dict(_STRETCH), [
        {"type": "Image", "color": "#FFFFFFFF", "raycastTarget": True},
        {"type": "Mask", "showMaskGraphic": False},
    ], [content])

    return _node(name, "ScrollView", rt, [
        {"type": "Image", "color": fill, "raycastTarget": True},
        {"type": "ScrollRect",
         "horizontal": is_h, "vertical": is_v,
         "movementType": "Elastic", "elasticity": 0.1,
         "inertia": True, "scrollSensitivity": 1},
    ], [viewport])


# ══════════════════════════════════════════════════════════════════
# 构建器注册表
# ══════════════════════════════════════════════════════════════════

_BUILDERS = {
    "Canvas":                _build_canvas,
    "Panel":                 _build_panel,
    "Text":                  _build_text,
    "Image":                 _build_image,
    "Toggle":                _build_toggle,
    "Dropdown":              _build_dropdown,
    "Button":                _build_button,
    "InputField":            _build_input_field,
    "Slider":                _build_slider,
    "ScrollView":            _build_scroll_view,
    "VerticalLayoutGroup":   _build_vlg,
    "HorizontalLayoutGroup": _build_hlg,
    "GridLayoutGroup":       _build_glg,
}


# ══════════════════════════════════════════════════════════════════
# RectTransform 策略
# ══════════════════════════════════════════════════════════════════

def _anchor_rt(rect: dict, parent_rect: dict | None,
               cw: int, ch: int, unity_type: str) -> dict:
    """标准锚点拉伸策略：Figma rect → 相对锚点比例。"""
    if unity_type == "Canvas":
        return dict(_STRETCH)

    pw = parent_rect["width"] if parent_rect else cw
    ph = parent_rect["height"] if parent_rect else ch
    if pw <= 0: pw = cw
    if ph <= 0: ph = ch

    x, y, w, h = rect["x"], rect["y"], rect["width"], rect["height"]
    return {
        "anchorMin": [_c01(round(x / pw, 4)),       _c01(round(1 - (y + h) / ph, 4))],
        "anchorMax": [_c01(round((x + w) / pw, 4)), _c01(round(1 - y / ph, 4))],
        "sizeDelta": [0, 0], "anchoredPosition": [0, 0], "pivot": [0.5, 0.5],
    }


def _layout_child_rt(rect: dict, parent_type: str) -> dict:
    """LayoutGroup 子节点策略：绝对像素尺寸（不使用锚点拉伸）。

    规则（显式声明）：
    - VLG 子节点：宽度 stretch 跟随父级，高度 = Figma rect.height
    - HLG 子节点：高度 stretch 跟随父级，宽度 = Figma rect.width
    - GLG 子节点：绝对宽高（由 cellSize 控制，这里给兜底值）
    """
    w, h = rect["width"], rect["height"]
    if parent_type == "VerticalLayoutGroup":
        return {"anchorMin": [0, 1], "anchorMax": [1, 1],
                "sizeDelta": [0, h], "anchoredPosition": [0, 0], "pivot": [0.5, 1]}
    if parent_type == "HorizontalLayoutGroup":
        return {"anchorMin": [0, 0], "anchorMax": [0, 1],
                "sizeDelta": [w, 0], "anchoredPosition": [0, 0], "pivot": [0, 0.5]}
    return {"anchorMin": [0, 1], "anchorMax": [0, 1],
            "sizeDelta": [w, h], "anchoredPosition": [0, 0], "pivot": [0, 1]}


def _inject_layout_element(components: list[dict], rect: dict, parent_type: str):
    """LayoutGroup 子节点规则：追加 LayoutElement。

    显式声明：preferred 尺寸直接取自 Figma rect。
    - VLG → preferredHeight = rect.height
    - HLG → preferredWidth  = rect.width
    - GLG → preferredWidth + preferredHeight（兜底）
    """
    le = {"type": "LayoutElement"}
    if parent_type == "VerticalLayoutGroup":
        le["preferredHeight"] = rect["height"]
    elif parent_type == "HorizontalLayoutGroup":
        le["preferredWidth"] = rect["width"]
    else:
        le["preferredWidth"] = rect["width"]
        le["preferredHeight"] = rect["height"]
    components.append(le)


# ══════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════

def _node(name: str, ntype: str, rt: dict, comps: list, children: list) -> dict:
    return {"name": name, "type": ntype, "rectTransform": rt,
            "components": comps, "children": children}


def _normalize_rect(raw: dict, parent: dict | None, cw: int, ch: int) -> dict:
    return {
        "x": _f(raw.get("x", 0)),
        "y": _f(raw.get("y", 0)),
        "width": _f(raw.get("width", cw if parent is None else parent.get("width", 100))),
        "height": _f(raw.get("height", ch if parent is None else parent.get("height", 100))),
    }


def _content_bounds(raw_children: list, fw: float, fh: float) -> tuple[float, float]:
    """从 Figma 子节点 rect 计算内容区域包围盒。"""
    if not raw_children:
        return fw, fh
    mx, my = 0.0, 0.0
    for c in raw_children:
        if not isinstance(c, dict):
            continue
        r = c.get("rect", {})
        mx = max(mx, _f(r.get("x", 0)) + _f(r.get("width", 0)))
        my = max(my, _f(r.get("y", 0)) + _f(r.get("height", 0)))
    return max(mx, fw), max(my, fh)


def _align(v) -> str:
    if not isinstance(v, str):
        return "UpperLeft"
    return _ALIGN_MAP.get(v.lower().replace("-", "_").replace(" ", "_"), "UpperLeft")


def _color(v) -> str:
    if not isinstance(v, str):
        return "#FFFFFFFF"
    v = v.strip()
    m = _COLOR_RE.match(v)
    if not m:
        return "#FFFFFFFF"
    h = m.group(1).upper()
    if len(h) == 3:   h = "".join(c * 2 for c in h) + "FF"
    elif len(h) == 4: h = "".join(c * 2 for c in h)
    elif len(h) == 6: h += "FF"
    elif len(h) != 8: return "#FFFFFFFF"
    return f"#{h}"


def _f(v) -> float:
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str):
        m = _NUM_RE.search(v)
        if m: return float(m.group())
    return 0.0


def _vec2(v, default) -> list:
    if isinstance(v, (int, float)):
        return [float(v), float(v)]
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return [_f(v[0]), _f(v[1])]
    return list(default)


def _rect_offset(v, default) -> list:
    if isinstance(v, (list, tuple)) and len(v) >= 4:
        return [int(_f(x)) for x in v[:4]]
    return list(default)


def _c01(v: float) -> float:
    return max(0.0, min(1.0, v))


# ══════════════════════════════════════════════════════════════════
# 分辨率缩放（后处理）
# ══════════════════════════════════════════════════════════════════

def _set_canvas_reference(root: dict, tw: int, th: int):
    for comp in root.get("components", []):
        if comp.get("type") == "CanvasScaler":
            comp["referenceResolution"] = [tw, th]
            return


def _scale_tree(node: dict, sx: float, sy: float, is_root: bool = False):
    if not is_root:
        rt = node.get("rectTransform", {})
        sd = rt.get("sizeDelta", [0, 0])
        rt["sizeDelta"] = [round(sd[0] * sx, 2), round(sd[1] * sy, 2)]
        ap = rt.get("anchoredPosition", [0, 0])
        rt["anchoredPosition"] = [round(ap[0] * sx, 2), round(ap[1] * sy, 2)]

    for comp in node.get("components", []):
        _scale_comp(comp, sx, sy)

    for child in node.get("children", []):
        _scale_tree(child, sx, sy)


def _scale_comp(c: dict, sx: float, sy: float):
    t = c.get("type", "")
    if t in ("Canvas", "CanvasScaler", "GraphicRaycaster"):
        return

    if t == "LayoutElement":
        for k in ("preferredWidth", "minWidth"):
            if k in c: c[k] = round(c[k] * sx, 2)
        for k in ("preferredHeight", "minHeight"):
            if k in c: c[k] = round(c[k] * sy, 2)
        return

    if t == "Text":
        if "fontSize" in c:
            c["fontSize"] = max(1, round(c["fontSize"] * min(sx, sy)))
        return

    if t in ("VerticalLayoutGroup", "HorizontalLayoutGroup"):
        if "spacing" in c:
            c["spacing"] = round(c["spacing"] * (sy if t == "VerticalLayoutGroup" else sx), 2)
        if "padding" in c:
            p = c["padding"]
            c["padding"] = [round(p[0]*sy), round(p[1]*sx), round(p[2]*sy), round(p[3]*sx)]
        return

    if t == "GridLayoutGroup":
        if "cellSize" in c:
            cs = c["cellSize"]
            c["cellSize"] = [round(cs[0]*sx, 2), round(cs[1]*sy, 2)]
        if "spacing" in c and isinstance(c["spacing"], list) and len(c["spacing"]) >= 2:
            sp = c["spacing"]
            c["spacing"] = [round(sp[0]*sx, 2), round(sp[1]*sy, 2)]
        if "padding" in c:
            p = c["padding"]
            c["padding"] = [round(p[0]*sy), round(p[1]*sx), round(p[2]*sy), round(p[3]*sx)]
        return

    if t == "InputField":
        if "fontSize" in c:
            c["fontSize"] = max(1, round(c["fontSize"] * min(sx, sy)))
        return
