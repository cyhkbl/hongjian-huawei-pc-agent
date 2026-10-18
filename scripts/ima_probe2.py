"""探测真实 ima 知识库根列表与点击“文件夹不存在”的具体原因（只打印结构与错误）。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.kb.ima_client import ImaClient, ImaError, pick_kb  # noqa: E402


def main() -> int:
    s = get_settings()
    c = ImaClient(client_id=s.ima_client_id, api_key=s.ima_api_key, base_url=s.ima_base_url)
    found = c.search_knowledge_base(s.ima_kb_name)
    kb = pick_kb(found, s.ima_kb_name)
    kb_id = kb.get("id") or kb.get("kb_id") or ""
    print("kb_id =", kb_id)

    # A. root: no folder_id at all
    items = c.iter_knowledge_list(kb_id, None, folder_title="(根)")
    print("\nA. 不带 folder_id 的根列表:", len(items), "项")
    for it in items:
        print("   ", json.dumps({k: (str(v)[:30]) for k, v in it.items()}, ensure_ascii=False))

    # B. use the returned media_id as folder_id
    top = items[0]
    mid = str(top.get("media_id") or "")
    pfid = str(top.get("parent_folder_id") or "")
    print("\nB. 根条目的 media_id =", mid[:18] + "…", " parent_folder_id =", pfid[:18] + "…")

    for label, fid in (("用 media_id 当 folder_id", mid), ("用 parent_folder_id 当 folder_id", pfid)):
        try:
            sub = c.iter_knowledge_list(kb_id, fid, folder_title=label)
            print(f"\n{label}: {len(sub)} 项")
            for it in sub[:15]:
                print("   ", json.dumps({k: (str(v)[:34]) for k, v in it.items()}, ensure_ascii=False))
        except ImaError as e:
            print(f"\n{label}: 失败 code={e.code} msg={e.msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
