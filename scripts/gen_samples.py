"""生成 docs/samples/ 下的 8 份示范成稿（含核验结果），同时跑一次 e2e 冒烟。"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("KB_MODE", "local")

from app.context import build_context  # noqa: E402
from app.agent.pipeline import run  # noqa: E402
from app.agent.export import export  # noqa: E402
from app.models import RunRequest  # noqa: E402

TASKS = [
    ("给 MateBook Pro 写一篇开学季小红书，面向大学新生", "pro-hm_back_to_school_xiaohongshu.md"),
    ("MateBook 14 鸿蒙版 写一篇职场办公公众号，面向刚入职的运营", "mb14-hm_office_wechat_mp.md"),
    ("MateBook 14 鸿蒙版 内容创作 小红书，面向剪辑新手", "mb14-hm_creator_xiaohongshu.md"),
    ("MateBook D 16 家庭换新朋友圈，给父母换一台用十年的电脑", "d16_home_upgrade_moments.md"),
    ("MateBook Fold 非凡大师 新品首发 门店海报", "fold_new_launch_poster.md"),
    ("MateBook Pro S 门店到访 门店朋友圈", "pros-hm_store_visit_moments.md"),
    ("MateBook 14 酷睿 Ultra 企业采购 公众号，面向行政和IT", "mb14-ultra_enterprise_procurement_wechat_mp.md"),
    ("MateBook 14 鸿蒙版 节日营销 小红书", "mb14-hm_festival_xiaohongshu.md"),
]


def main() -> int:
    ctx = build_context()
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "samples")
    os.makedirs(out, exist_ok=True)
    bad = 0
    for text, fname in TASKS:
        try:
            r = run(RunRequest(text=text), ctx)
        except Exception as e:  # noqa: BLE001
            print(f"ERR {fname}: {e}")
            bad += 1
            continue
        if r.article is None:
            print(f"SKIP {fname}: status={r.status} refusal={r.refusal[:60]}")
            continue
        data, mime, name = export(r, "md", ctx.kb)
        path = os.path.join(out, fname)
        with io.open(path, "wb") as fh:
            fh.write(data)
        n_img = len(r.article.image_refs)
        verdict = r.verification.verdict if r.verification else "-"
        print(f"OK {fname}  verdict={verdict} imgs={n_img} sentences={r.verification.stats.get('sentences') if r.verification else '-'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
