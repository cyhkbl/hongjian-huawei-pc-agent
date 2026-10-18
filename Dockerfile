FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=7860 \
    KB_MODE=local \
    KB_LOCAL_DIR=/app/kb_snapshot \
    CACHE_DIR=/mnt/workspace/hongjian/kb_cache \
    RUNS_DIR=/mnt/workspace/hongjian/runs

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 知识库快照随镜像分发（只有文本资料与图片，不含任何凭证）。
# 这些内容不进 GitHub 源码仓库，只在推送到魔搭的分支里，因为主办方禁止对外传播知识库原文。
COPY kb_snapshot ./kb_snapshot

# ima / LLM 凭证由平台密文注入，不写入镜像。
# 配了 IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY 并把 KB_MODE 改成 ima，
# 就能切换成实时读取 ima 共享知识库。
EXPOSE 7860
CMD ["python", "-m", "app.main"]
