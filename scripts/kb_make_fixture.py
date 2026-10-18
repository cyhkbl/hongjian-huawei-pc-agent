"""Generate tests/fixtures/kb_mini: a tiny, fully invented KB with the same layout as the real one."""
import csv, io, sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "kb_mini"
P1 = ROOT / "P1-产品参数库"

MODELS = [
    dict(dir="01-鸿蒙电脑/HUAWEI MateBook Pro", card="HUAWEI MateBook Pro", slug="matebook-pro", hs=("示例Pro", 1.2, "12.0"), color="示例蓝", w=14.0),
    dict(dir="01-鸿蒙电脑/HUAWEI MateBook Pro S", card="HUAWEI MateBook Pro S", slug="matebook-pro-s", hs=("示例ProS", 0.8, "9.9"), color="示例紫", w=13.0),
]


def w(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def csv_text(rows):
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    for r in rows:
        wr.writerow(r)
    return buf.getvalue()


union = [["文件名", "产品型号", "画面说明", "原始图片URL", "页面来源", "本地目录"]]
price = [["记录ID", "规范产品名称", "原始产品名称", "分类", "精确款式", "型号或SKU", "价格类型", "页面金额（元）", "参考或划线金额（元）",
          "条件摘要", "库存状态", "地区上下文", "登录状态", "核验时间", "来源标题", "官方URL", "取证方式", "证据摘要", "核验状态", "映射备注", "原始记录ID"]]
for i, m in enumerate(MODELS):
    name = m["card"]
    base = P1 / m["dir"]
    short = name.replace("HUAWEI ", "")
    page = f"https://example.invalid/{m['slug']}/"
    w(base / "产品事实.md", f"""# {name} - 产品事实

> 来源：示例。抓取日期：2026-10-17。示例数据，非真实产品。

## 来源

- 产品页：{page}
- 规格页：{page}specs/

## 官方规格摘录

## 操作系统

ExampleOS 1.0

## 尺寸与重量

宽度

300.0 mm

重量

{m['hs'][1]} kg

*实际重量依配置不同可能有所差异。

## 屏幕

尺寸

{m['w']} 英寸

类型

示例 OLED

刷新率

120 Hz

*示例脚注：亮度为实验室典型值。

## 电池

容量

{50 + i * 5} Wh（额定容量）

## 接口

左侧：USB Type-C × 1

右侧：USB Type-C × 1

## 特色应用

示例协同、示例笔记

即将离开example.invalid

您即将跳转至第三方页面，华为无法控制，也无法对该页面内容负责。

继续访问

取消
""")
    w(base / "卖点与限制.md", f"""# {name}｜卖点与限制

> 事实基准日：2026-10-17。

## 一句话定位

适合示例场景的{short}，仅作测试。

## 六个沟通角度

### 1. 型号身份卡

**可用结论**

{short}是示例系统的轻薄本。

**支撑事实**

- 系统为ExampleOS 1.0。
- 重量{m['hs'][1]} kg。

**表达边界**

- 重量依配置而异。

### 2. 屏幕与显示卡

**可用结论**

{m['w']}英寸示例OLED，刷新率120 Hz。

**支撑事实**

- 屏幕{m['w']}英寸。

**表达边界**

- 亮度为实验室典型值。
""")
    w(base / "来源清单.csv", csv_text([["资料类型", "标题", "URL", "来源机构", "抓取日期"], ["产品页", name, page, "示例", "2026-10-17"]]))
    cap = f"{short} {m['color']}外观示例图"
    imgs = [(f"hwpc_{m['slug']}_外观_01.png", cap, (40 + i * 10, 30)), (f"hwpc_{m['slug']}_屏幕_02.png", f"{short} 示例屏幕", (50, 30))]
    rows = [["文件名", "产品型号", "来源页面", "原始图片URL", "官网图片说明", "宽度", "高度", "建议用途"]]
    for fn, c, size in imgs:
        (base / "images").mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, (30 + 80 * i, 90, 160)).save(base / "images" / fn)
        rows.append([fn, name, page, f"https://example.invalid/img/{fn}", c, size[0], size[1], "示例用途"])
        union.append([fn, name, c, f"https://example.invalid/img/{fn}", page, f"P1-产品参数库/{m['dir']}"])
    w(base / "图片索引.csv", csv_text(rows))
    # cards
    card_base = P1 / "06-型号检索卡" / m["card"]
    for no, title, facts in [(1, "01-型号身份卡", [f"系统为ExampleOS 1.0。", f"重量{m['hs'][1]} kg。"]),
                              (2, "02-屏幕与显示卡", [f"屏幕{m['w']}英寸示例OLED。", "刷新率120 Hz。"])]:
        w(card_base / f"{title}.md", f"""# {name}｜{title}

> 状态：示例；抓取基准日 2026-10-17。

## 检索结论

示例结论。

## 已确认事实

""" + "\n".join(f"- {f}" for f in facts) + f"""

## 限定条件

- 示例限定：以实际销售版本为准。

## 适用任务

- 示例适用任务一。

## 不适用或需先验证的任务

- 示例不适用任务一。

## 待核验项

- 示例待核验项一。

## 来源入口

- 华为官方产品页：{page}

<!-- v6-expanded-lookup-card -->

## 字段解读

这一段必须被忽略。
""")
    # price rows
    price.append([f"PRICE-{i*2+1:04d}", name, name, "消费级PC", f"示例款 {i}", "SKU-X", "官方商城页面价" if i == 0 else "未公开金额",
                  "5000" if i == 0 else "", "", "示例条件", "有货", "大陆", "未登录", "2026-10-17T10:00:00+08:00", "示例", page, "示例", "示例", "已核验", "", ""])
    price.append([f"PRICE-{i*2+2:04d}", name, name, "消费级PC", "官网", "", "官网参考起价", "4900", "", "", "", "", "", "2026-10-17T10:00:00+08:00", "示例", page, "", "", "示例", "", ""])
price.append(["PRICE-0005", "示例配件", "示例配件", "电脑配件", "配件", "", "官方询价", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
w(P1 / "00-全库横向索引" / "全部图片联合检索表.csv", csv_text(union))
w(P1 / "08-官方公开价格快照" / "官方价格快照.csv", csv_text(price))
print("ok", ROOT)
