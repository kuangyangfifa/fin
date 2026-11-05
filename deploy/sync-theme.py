#!/usr/bin/env python3
"""从 fin-remark 主模块的设计令牌生成退费模块的主题覆盖层。

用法：python deploy/sync-theme.py
来源：web/static/css/custom.css 的 :root 块
产出：web/refund/public/assets/theme.css（请勿手工编辑产出文件）

主模块样式表保持零改动，避免影响既有页面；退费模块以内联样式在前、
本覆盖层在后的方式加载，从而只覆盖视觉变量与少量硬编码渐变/阴影。
"""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
SRC = WEB / "static" / "css" / "custom.css"
DST = WEB / "refund" / "public" / "assets" / "theme.css"

REQUIRED = [
    "--primary-color", "--primary-light", "--primary-dark",
    "--body-bg", "--card-bg", "--surface-bg",
    "--text-primary", "--text-secondary",
    "--success", "--success-light", "--warning", "--warning-light",
    "--danger", "--danger-light",
    "--shadow", "--shadow-md", "--radius", "--font-sans",
]


def read_tokens(css: str) -> dict:
    block = re.search(r":root\s*\{(.*?)\}", css, re.S)
    if not block:
        raise SystemExit("未能在 custom.css 中找到 :root 块")
    return {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block.group(1))}


def tint(hex_color: str, weight: float = 0.08) -> str:
    """主色按 weight 比例混入白色，得到浅底/聚焦光圈用的派生色。"""
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        raise SystemExit(f"无法解析主色：{hex_color}")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(c * weight + 255 * (1 - weight)):02x}" for c in rgb)


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.strip().lstrip("#")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha})"


def main() -> None:
    css = SRC.read_text(encoding="utf-8")
    t = read_tokens(css)
    missing = [k for k in REQUIRED if k not in t]
    if missing:
        raise SystemExit(f"custom.css 缺少设计令牌：{', '.join(missing)}")

    primary = t["--primary-color"]
    primary_dark = t["--primary-dark"]
    primary_light = t["--primary-light"]
    soft = tint(primary)
    # 通用字体族 sans-serif 必须位于 font-family 列表末尾，先剥离再补中文字体。
    font_stack = re.sub(r",\s*sans-serif\s*$", "", t["--font-sans"]).strip().rstrip(",")
    # 表格/分割线色取自 custom.css 中的边框色，令牌表未显式定义，故在此声明来源。
    line = "#e2e8f0"

    out = f"""/* 由 deploy/sync-theme.py 生成，请勿手工修改。
   来源：static/css/custom.css 的 :root 设计令牌。
   本文件必须在 index.html 内联 <style> 之后加载才能生效。 */
:root{{
  --brand:{primary};
  --brand-d:{primary_dark};
  --brand-soft:{soft};
  --bg:{t['--body-bg']};
  --card:{t['--card-bg']};
  --ink:{t['--text-primary']};
  --muted:{t['--text-secondary']};
  --line:{line};
  --line-2:{t['--surface-bg']};
  --ok:{t['--success']};
  --ok-soft:{t['--success-light']};
  --warn:{t['--warning']};
  --warn-soft:{t['--warning-light']};
  --danger:{t['--danger']};
  --danger-soft:{t['--danger-light']};
  --shadow-sm:{t['--shadow']};
  --shadow-md:{t['--shadow-md']};
  --radius:{t['--radius']};
}}
body{{
  font-family:{font_stack}, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background:var(--bg);
}}

/* 内联样式中硬编码的旧蓝色，统一改为财务系统同款深紫渐变与靛蓝阴影 */
.auth-hero{{background:linear-gradient(150deg,#1e1b4b 0%,#312e81 55%,{primary_dark} 100%);}}
.btn.primary{{background:linear-gradient(135deg,{primary},{primary_light});box-shadow:0 8px 18px {rgba(primary, 0.28)};}}
.btn.primary:hover{{box-shadow:0 10px 24px {rgba(primary, 0.38)};}}
.btn.sub{{background:{soft};color:{primary_dark};}}
.btn.ghost:hover{{background:{soft};}}
.field-i:focus-within,textarea:focus{{box-shadow:0 0 0 3px {soft};}}
.upload:hover{{border-color:{primary};background:{soft};}}
.att-item:hover{{border-color:{primary};background:{soft};color:{primary_dark};}}
.seg2 button.on,.seg3 button.on{{color:{primary};}}
.tag.s1{{background:{soft};color:{primary_dark};}}
.tag.s2{{background:{t['--success-light']};color:#065f46;}}

/* 模块间导航：退费模块顶栏的返回入口 */
.to-home{{display:inline-flex;align-items:center;justify-content:center;text-decoration:none;color:{t['--text-secondary']};}}
.to-home:hover{{color:{primary};border-color:{primary};}}
.to-home svg{{width:18px;height:18px;}}

/* hidden 属性兜底：避免组件样式中的 display 覆盖内建隐藏行为 */
[hidden]{{display:none !important;}}
"""
    DST.write_text(out, encoding="utf-8")
    print(f"已生成 {DST.relative_to(WEB)}（主色 {primary}，浅底 {soft}）")


if __name__ == "__main__":
    main()
