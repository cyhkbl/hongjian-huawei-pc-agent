"""跑全部自测用例，失败时打印失败项。"""
import os
import sys

os.environ.setdefault("KB_MODE", "local")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.selftest import cases, run_case  # noqa: E402
from app.context import build_context  # noqa: E402

ctx = build_context()
cs = cases()
fails = []
for c in cs:
    r = run_case(ctx, c["id"])
    if r["passed"]:
        print(f"PASS {c['id']}")
    else:
        fails.append(c["id"])
        print("FAIL " + c["id"])
        for chk in r["checks"]:
            if not chk["ok"]:
                print("   - " + str(chk.get("name")) + " " + str(chk.get("detail")))
print(f"\nselftest: {len(cs) - len(fails)}/{len(cs)} passed")
sys.exit(1 if fails else 0)
