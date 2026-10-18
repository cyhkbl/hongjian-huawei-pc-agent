"""扫描 GitHub 当前 main 分支全部文本文件，确认无凭证泄漏。"""
import io
import json
import re
import sys
import urllib.request

BASE = "https://raw.githubusercontent.com/cyhkbl/hongjian-huawei-pc-agent/main"
API = "https://api.github.com/repos/cyhkbl/hongjian-huawei-pc-agent/git/trees/main?recursive=1"

SECRETS = [
    ("modelscope token 前缀", re.compile(r"ms-[0-9a-f]{8}-[0-9a-f]{4}")),
    ("ima client id 前缀", re.compile(r"5a38dbf5[0-9a-f]{8}")),
    ("ima api key 前缀", re.compile(r"Lg/q9PsY[A-Za-z0-9+/]{8}")),
    ("openai-like", re.compile(r"sk-[A-Za-z0-9]{24,}")),
    ("github token", re.compile(r"gho_[A-Za-z0-9]{20,}")),
    ("api key assign", re.compile(r"""api[_-]?key["']?\s*[:=]\s*["'][A-Za-z0-9\-_]{16,}""", re.I)),
]
TEXT_EXT = (".py", ".js", ".html", ".css", ".md", ".json", ".txt", ".ps1", ".yml", ".yaml", ".sh", ".cfg", ".toml", ".svg", ".example")


def fetch(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "audit"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main() -> int:
    tree = json.loads(fetch(API).decode("utf-8"))
    files = [t["path"] for t in tree["tree"] if t["type"] == "blob"]
    print(f"分支文件总数: {len(files)}")
    checked = 0
    hits: list[str] = []
    for p in files:
        if not p.lower().endswith(TEXT_EXT):
            continue
        if p.startswith(("docs/shots/", "docs/samples/")) and p.endswith(".png"):
            continue
        try:
            raw = fetch(f"{BASE}/{urllib.request.quote(p)}")
        except Exception as e:  # noqa: BLE001
            print(f"  读取失败 {p}: {e}")
            continue
        checked += 1
        try:
            txt = raw.decode("utf-8")
        except UnicodeDecodeError:
            txt = raw.decode("utf-8", errors="replace")
        for label, rx in SECRETS:
            # 测试夹具里的假 key 不算
            if p.startswith("tests/") and label in ("api key assign", "openai-like"):
                continue
            m = rx.search(txt)
            if m:
                hits.append(f"{p}  [{label}]  {m.group(0)[:24]}")
    print(f"已扫描文本文件: {checked}")
    if hits:
        print("发现疑似凭证:")
        for h in hits:
            print("  " + h)
        return 1
    print("凭证扫描: 干净")

    # 知识库原文检查
    kb = [p for p in files
          if "产品事实" in p or "图片索引" in p or "官方价格快照" in p or "卖点与限制" in p
          or "全库导航" in p or "型号检索卡" in p or p.startswith("kb_snapshot/")]
    print(f"知识库特征文件: {len(kb)}")
    for p in kb[:10]:
        print("   " + p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
