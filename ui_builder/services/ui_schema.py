"""
UI 分析 prompt 管理。
构建让 LLM 输出 Figma 风格设计 JSON 的 system / user prompt。
支持热更新：修改 ui_builder_prompt.md 后自动追加规则。

注意：此模块与 Unity 完全无关，只关心"设计描述"。
Figma→Unity 的映射由 unity_mapper.py 负责。
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_EXTRA_RULES_PATH = Path(__file__).parent.parent / "ui_builder_prompt.md"

FIGMA_TYPES = [
    ("frame",           "容器/分组，任何可包含子元素的区域（页面、卡片、行、弹窗等）"),
    ("text",            "文字标签、标题、段落、价格、描述等一切文本"),
    ("image",           "图片、头像、缩略图、Banner、广告位"),
    ("icon",            "小图标（返回箭头、搜索、购物车、设置齿轮等）"),
    ("rectangle",       "纯色块/背景/分割线/装饰矩形"),
    ("button",          "可点击的按钮（含文字或图标）"),
    ("input",           "文本输入框、搜索框"),
    ("switch",          "开关/Toggle，二选一状态切换"),
    ("checkbox",        "复选框，可多选"),
    ("slider",          "滑块/进度条/音量条"),
    ("dropdown",        "下拉选择菜单"),
    ("scroll_area",     "可滚动区域（内容超出可视范围时）"),
    ("list",            "纵向列表布局（子元素从上到下排列）"),
    ("horizontal_list", "横向列表布局（子元素从左到右排列）"),
    ("grid",            "网格布局（子元素按行列排列）"),
]


def _build_type_reference() -> str:
    lines = []
    for t, desc in FIGMA_TYPES:
        lines.append(f"- `{t}` — {desc}")
    return "\n".join(lines)


def _build_example() -> str:
    return json.dumps({
        "name": "Root",
        "type": "frame",
        "rect": {"x": 0, "y": 0, "width": 1080, "height": 1920},
        "style": {"fill": "#FFFFFF"},
        "children": [
            {
                "name": "StatusBar",
                "type": "frame",
                "rect": {"x": 0, "y": 0, "width": 1080, "height": 44},
                "style": {"fill": "#2196F3"},
                "children": []
            },
            {
                "name": "Header",
                "type": "frame",
                "rect": {"x": 0, "y": 44, "width": 1080, "height": 112},
                "style": {"fill": "#2196F3"},
                "children": [
                    {
                        "name": "BackArrow",
                        "type": "icon",
                        "rect": {"x": 16, "y": 26, "width": 60, "height": 60},
                        "style": {"fill": "#FFFFFF"},
                        "children": []
                    },
                    {
                        "name": "Title",
                        "type": "text",
                        "rect": {"x": 90, "y": 26, "width": 400, "height": 60},
                        "style": {"text_content": "设置", "font_size": 28, "text_color": "#FFFFFF", "text_align": "middle_left"},
                        "children": []
                    }
                ]
            },
            {
                "name": "ContentArea",
                "type": "scroll_area",
                "rect": {"x": 0, "y": 156, "width": 1080, "height": 1640},
                "style": {"fill": "#F5F5F5", "scroll_direction": "vertical"},
                "children": [
                    {
                        "name": "SettingsList",
                        "type": "list",
                        "rect": {"x": 0, "y": 0, "width": 1080, "height": 1640},
                        "style": {"spacing": 2},
                        "children": [
                            {
                                "name": "DarkModeRow",
                                "type": "frame",
                                "rect": {"x": 0, "y": 0, "width": 1080, "height": 80},
                                "style": {"fill": "#FFFFFF"},
                                "children": [
                                    {
                                        "name": "DarkModeLabel",
                                        "type": "text",
                                        "rect": {"x": 24, "y": 10, "width": 600, "height": 60},
                                        "style": {"text_content": "深色模式", "font_size": 22, "text_color": "#333333", "text_align": "middle_left"},
                                        "children": []
                                    },
                                    {
                                        "name": "DarkModeSwitch",
                                        "type": "switch",
                                        "rect": {"x": 960, "y": 20, "width": 80, "height": 40},
                                        "style": {"checked": False},
                                        "children": []
                                    }
                                ]
                            },
                            {
                                "name": "NotificationRow",
                                "type": "button",
                                "rect": {"x": 0, "y": 82, "width": 1080, "height": 80},
                                "style": {"fill": "#FFFFFF", "text_content": "通知设置", "font_size": 22, "text_color": "#333333"},
                                "children": [
                                    {
                                        "name": "ArrowIcon",
                                        "type": "icon",
                                        "rect": {"x": 1010, "y": 20, "width": 40, "height": 40},
                                        "style": {"fill": "#CCCCCC"},
                                        "children": []
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "BottomNav",
                "type": "horizontal_list",
                "rect": {"x": 0, "y": 1796, "width": 1080, "height": 124},
                "style": {"fill": "#FFFFFF", "spacing": 0},
                "children": [
                    {
                        "name": "NavHome",
                        "type": "button",
                        "rect": {"x": 0, "y": 0, "width": 270, "height": 124},
                        "style": {"text_content": "首页", "font_size": 16, "text_color": "#999999"},
                        "children": []
                    },
                    {
                        "name": "NavSettings",
                        "type": "button",
                        "rect": {"x": 270, "y": 0, "width": 270, "height": 124},
                        "style": {"text_content": "设置", "font_size": 16, "text_color": "#2196F3"},
                        "children": []
                    }
                ]
            }
        ]
    }, ensure_ascii=False, indent=2)


def build_system_prompt() -> str:
    """构建 system prompt：Figma 风格设计 JSON 输出规则。"""
    type_ref = _build_type_reference()
    example = _build_example()

    extra_rules = ""
    if _EXTRA_RULES_PATH.is_file():
        try:
            extra_rules = _EXTRA_RULES_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            pass

    prompt = f"""你是一名资深 UI/UX 设计师，擅长将 UI 设计稿还原为 Figma 风格的结构化描述。

## 你的任务

分析用户提供的 UI 示意图（截图、线框图或设计稿），输出一棵 Figma 风格的 UI 组件树 JSON。
你只需要描述"设计"本身——每个元素是什么、在哪、长什么样、有什么交互意图。
不需要考虑任何具体引擎或框架的实现细节。

## 可用设计元素类型

{type_ref}

## 分析维度（必须全部考虑）

### A. 视觉还原
- 识别所有可见元素：文字、图标、图片、背景色、分割线、装饰性矩形等
- 估算每个元素的位置和尺寸（像素），基准画布 1080×1920
- 还原嵌套层级：哪些是容器（frame），哪些是叶子元素

### B. 功能推断
- 看到搜索图标或输入区域 → `input`
- 看到文字标签旁有箭头">" → 整行是 `button`（可点击跳转）
- 看到图片网格/卡片列表 → `scroll_area` 内含 `grid`
- 看到标签页/Tab 栏 → `horizontal_list` 内含多个 `button`
- 看到开关/复选框 → `switch` 或 `checkbox`
- 看到下拉选择 → `dropdown`
- 看到进度条/音量条 → `slider`
- 看到计数器（"−" 数字 "+"） → `frame` 内含两个 `button` + 一个 `text`

### C. 交互与动态效果
- 内容可能超出可视区域 → 外层包 `scroll_area`（指定 scroll_direction）
- 列表项数量可变 → `scroll_area` 内部用 `list` 或 `grid`
- 水平滑动的横幅/轮播 → `scroll_area`（scroll_direction: horizontal）
- 底部导航栏 → 固定在底部的 `horizontal_list`
- 弹窗/对话框 → 半透明遮罩 `rectangle` + 居中 `frame`
- 浮动按钮 → 固定在右下的 `button`

### D. 布局策略
- 横向等分排列 → `horizontal_list`
- 纵向列表 → `list`（设置 spacing）
- 网格排列 → `grid`（设置 columns、cell_width、cell_height）
- 元素有明显规律（等间距、对齐）→ 优先用布局容器而非逐个定位

## 节点格式（严格遵守）

每个节点必须包含以下 5 个字段，不多不少：

```
{{
  "name": "英文 PascalCase 名称，描述功能（如 SearchInput、ProductCard、NavBar）",
  "type": "元素类型（必须从上面的可用类型中选）",
  "rect": {{"x": 像素X, "y": 像素Y, "width": 宽度, "height": 高度}},
  "style": {{样式和属性}},
  "children": [子节点数组，叶子节点为空数组 []]
}}
```

### rect 规则
- 坐标系：原点在左上角，x 向右，y 向下
- 单位：像素，基准画布 1080×1920
- 子节点的 rect 相对于父节点（局部坐标）
- 根节点 rect 固定为 {{"x": 0, "y": 0, "width": 1080, "height": 1920}}

### style 可用属性
- `fill` — 背景色/填充色，#RRGGBB 格式
- `opacity` — 透明度，0~1
- `corner_radius` — 圆角半径，像素
- `border_color` — 边框颜色，#RRGGBB
- `border_width` — 边框宽度，像素
- `text_content` — 文本内容（text 和 button 类型使用）
- `font_size` — 字号，像素
- `text_color` — 文字颜色，#RRGGBB
- `text_align` — 文字对齐：top_left / top_center / top_right / middle_left / middle_center / middle_right / bottom_left / bottom_center / bottom_right
- `font_weight` — 字重：normal / bold
- `scroll_direction` — 滚动方向：vertical / horizontal / both（scroll_area 使用）
- `spacing` — 子元素间距，像素（list / horizontal_list / grid 使用）
- `padding` — 内边距 [上, 右, 下, 左]（布局容器使用）
- `columns` — 列数（grid 使用）
- `cell_width` / `cell_height` — 网格单元尺寸（grid 使用）
- `checked` — 是否选中，true/false（switch / checkbox 使用）
- `placeholder` — 占位文字（input 使用）
- `options` — 选项列表（dropdown 使用）
- `min_value` / `max_value` / `current_value` — 范围值（slider 使用）

只填有意义的属性，不需要的可以省略。

## 完整示例

{example}

## 输出规则（最高优先级）

一、只输出一个 JSON 对象，根节点 type 必须是 frame。
二、不要输出 JSON 之外的任何内容：不要有标题、解释、注释、分析报告、markdown 标记、代码围栏。
三、直接以 {{ 开头，以 }} 结尾。
四、确保 JSON 合法：字符串用双引号，没有尾逗号，布尔值用 true/false。
五、如果输出结果不是合法 JSON，先自检修正，再输出最终答案。"""

    if extra_rules:
        prompt += f"\n\n## 补充规则\n{extra_rules}"

    return prompt


def build_user_prompt(extra_prompt: str = "") -> str:
    """构建 user prompt：分析指令 + 用户额外要求。"""
    base = "请分析这张 UI 示意图，输出完整的 Figma 风格组件树 JSON。"
    if extra_prompt:
        base += f"\n\n用户补充要求：\n{extra_prompt}"
    return base
