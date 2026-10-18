r"""Print KB statistics and anomalies.

    .\.venv\Scripts\python.exe scripts\kb_audit.py [--mode local|ima|auto] [--dir <KB_LOCAL_DIR>]

Reads settings from the environment/.env (KB_MODE, KB_LOCAL_DIR, IMA_*). Prints no secrets.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.config import get_settings            # noqa: E402
from app.kb import get_kb                      # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode")
    ap.add_argument("--dir")
    a = ap.parse_args()
    s = get_settings()
    if a.mode:
        s = dataclasses.replace(s, kb_mode=a.mode)
    if a.dir:
        s = dataclasses.replace(s, kb_local_dir=a.dir)
    kb = get_kb(s)
    st = kb.status()
    idx = kb._idx                                # noqa: SLF001 - audit tool may look inside
    problems: list[str] = []

    print(f"模式 {st.mode} · 连接 {st.connected} · 库 {st.kb_name or '-'} · 基准日 {st.snapshot_date or '-'}")
    print(st.detail)
    print(f"型号 {st.models} · 事实 {st.facts} · 图片 {st.images} · 价格 {st.prices}\n")

    print("== 型号 ==")
    print(f"{'model_id':11}{'事实':>5}{'spec':>6}{'card':>6}{'sell':>6}{'bound':>6}{'fit':>5}{'unfit':>6}{'图':>4}{'价':>4}  有金额  官方名")
    for m in kb.models():
        fs = kb.facts(m.model_id)
        c = collections.Counter(f.kind for f in fs)
        print(f"{m.model_id:11}{len(fs):5}{c['spec']:6}{c['card']:6}{c['selling']:6}{c['boundary']:6}"
              f"{c['fit']:5}{c['unfit']:6}{len(kb.images(m.model_id)):4}{len(kb.prices(m.model_id)):4}"
              f"  {'是' if m.has_public_price else '否':4}  {m.name}")
        if not fs:
            problems.append(f"{m.model_id} 没有事实")
        if not kb.images(m.model_id):
            problems.append(f"{m.model_id} 没有图片")
        if not m.official_urls:
            problems.append(f"{m.model_id} 没有官方 URL")
    print()

    print("== 事实 ==")
    ids = [f.id for f in idx.facts]
    if len(ids) != len(set(ids)):
        problems.append("事实 id 有重复")
    no_cons = [f for f in idx.facts if f.kind == "card" and not f.constraints]
    print(f"kind 分布：{dict(collections.Counter(f.kind for f in idx.facts))}")
    print(f"category 分布：{dict(collections.Counter(f.category for f in idx.facts))}")
    print(f"无 tag 的事实：{sum(1 for f in idx.facts if not f.tags)} 条；无来源 URL：{sum(1 for f in idx.facts if not f.source_urls)} 条；"
          f"卡片事实缺限定条件：{len(no_cons)} 条")
    noisy = [f.id for f in idx.facts if "即将离开" in f.text or "继续访问" in f.text]
    if noisy:
        problems.append(f"{len(noisy)} 条事实含站外跳转噪声：{noisy[:3]}")
    print()

    print("== 图片 ==")
    bad_files = 0
    for im in idx.images:
        try:
            data, mime = kb.image_bytes(im.id)
            if not data:
                raise OSError("空文件")
        except Exception as e:                    # noqa: BLE001
            bad_files += 1
            problems.append(f"图片不可读 {im.id}：{type(e).__name__}")
    print(f"可读 {len(idx.images) - bad_files}/{len(idx.images)}；official {sum(1 for i in idx.images if i.kind == 'official')} · "
          f"mall {sum(1 for i in idx.images if i.kind == 'mall')}；带配色 {sum(1 for i in idx.images if i.color)}")
    print(f"缺 caption/source_url/page_url：{sum(1 for i in idx.images if not (i.caption and i.source_url and i.page_url))} 张；"
          f"宽高为 0：{sum(1 for i in idx.images if not (i.width and i.height))} 张")
    print("未生成 ImageAsset / 交叉校验提示：")
    shown = 0
    summary: dict[str, int] = collections.defaultdict(int)
    for line in idx.audit:
        if "无法判定型号" in line:
            key = line.split("（目录 ")[-1].split("）")[0]
            summary[key] += 1
        else:
            print("  -", line)
            shown += 1
    for k, n in summary.items():
        print(f"  - 联合检索表中 {n} 张图片无法判定型号（目录「{k}」，通用商城专区素材），按规则不生成 ImageAsset")
    if not shown and not summary:
        print("  （无）")
    print()

    print("== 价格 ==")
    pt = collections.Counter(p.price_type for p in idx.prices)
    print(f"记录 {len(idx.prices)}；映射到重点型号 {sum(1 for p in idx.prices if p.model_id)}；配件/商用/其它 {sum(1 for p in idx.prices if not p.model_id)}")
    print(f"价格类型：{dict(pt)}")
    print(f"有金额 {sum(1 for p in idx.prices if p.amount is not None)}；金额为空 {sum(1 for p in idx.prices if p.amount is None)}")
    print()

    print("== 解析备注（跳过/缺失） ==")
    for n in idx.notes:
        print("  -", n)
    print()

    print("== 别名自检 ==")
    for q in ["MateBook 14", "D 16", "D 16 SE", "Pro", "Pro S", "折叠本", "非凡大师", "GT", "X Pro", "酷睿Ultra版14", "鸿蒙版14"]:
        print(f"  {q:14} -> {[(m.model_id, round(sc, 2)) for m, sc, _ in kb.find_models(q)]}")
    print()

    if problems:
        print(f"!! 发现 {len(problems)} 个问题")
        for p in problems:
            print("  *", p)
        return 1
    print("未发现异常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
