"""真实 ima 模式建库测试：连上后打印规模与抽样。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.kb import get_kb  # noqa: E402

s = get_settings()
s2 = dict(s.__dict__)
s2["kb_mode"] = "ima"
from app.config import Settings  # noqa: E402
st = Settings(**s2)
t0 = time.time()
kb = get_kb(st)
kb.refresh()
print(f"建库耗时 {time.time() - t0:.1f}s")
print("mode =", kb.status().mode, "connected =", kb.status().connected)
print("detail =", kb.status().detail)
print("models =", len(kb.models()))
for m in kb.models():
    print(f"   {m.model_id:12s} {m.name}")
fs = kb.facts("pro-hm")
print("pro-hm facts =", len(fs))
imgs = kb.images("pro-hm")
print("pro-hm images =", len(imgs), [i.id[:26] for i in imgs[:3]])
pr = kb.prices("pro-hm")
print("pro-hm prices =", len(pr), [(p.price_type, p.amount) for p in pr[:3]])
r = kb.search("MateBook Pro 屏幕亮度", model_id="pro-hm")
print("search hits =", len(r), [h.title for h in r[:3]])
