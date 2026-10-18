"""用 ImaFS 探测真实 ima 知识库目录树（BFS 6 层），只打印结构。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.kb.ima_client import ImaClient, ImaError, pick_kb  # noqa: E402
from app.kb.vfs import ImaFS  # noqa: E402

s = get_settings()
c = ImaClient(client_id=s.ima_client_id, api_key=s.ima_api_key, base_url=s.ima_base_url)
found = c.search_knowledge_base(s.ima_kb_name)
kb = pick_kb(found, s.ima_kb_name)
kb_id = kb.get("id") or kb.get("kb_id") or ""
print("kb:", kb.get("name"))

fs = ImaFS(c, kb_id, s.cache_dir, kb_name=kb.get("name") or "")

seen: set[str] = set()
frontier = [""]
for depth in range(6):
    nxt = []
    for path in frontier:
        if path in seen:
            continue
        seen.add(path)
        try:
            entries = fs.list_dir(path)
        except ImaError as e:
            print(f"[{depth}] {path or '(根目录)'}: {e}")
            continue
        except FileNotFoundError:
            continue
        if not entries:
            continue
        n_dir = sum(1 for e in entries if e.is_dir)
        print(f"[{depth}] {path or '(根目录)'}: {len(entries)} 项（{n_dir} 个文件夹）")
        for e in entries:
            mark = "D" if e.is_dir else "f"
            print(f"    {mark}  {e.name[:44]}")
            if e.is_dir:
                nxt.append((path + "/" + e.name).lstrip("/"))
    if not nxt:
        break
    frontier = nxt
print("\n文件夹数:", fs.stats["folders"], " 文件数:", fs.stats["files"])
