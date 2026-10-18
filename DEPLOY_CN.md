# 上传到 GitHub（已完成）

仓库已就位：https://github.com/cyhkbl/hongjian-huawei-pc-agent（public，main 分支，129 个文件）。

推送时做过两项自检，都不通过会中止推送：

- 凭证扫描：排查 `gho_`/`ghp_`、`sk-`、`IMA_OPENAPI_CLIENTID/APIKEY` 的真实值与形如 `api_key="..."` 的赋值，测试夹具里的假 key 除外。
- 知识库泄漏扫描：确认 `P1-产品参数库`、`产品事实.md`、`图片索引.csv`、`08-官方公开价格快照`、`runs/`、`.kb_cache/`、`kb_local/` 都没有被 `git ls-files` 跟踪。

以后再改代码，直接 `git push` 即可，改完可以再跑一次 `scripts\push_github.ps1` 复核。

# 部署到魔搭创空间

项目已带 `Dockerfile` 和 `ms_deploy.json`，服务监听 `0.0.0.0:7860`，本地 `python -m app.main` 也是同一个端口。创空间用 Docker 类型需要绑定阿里云账号并实名。

**注意**：我不持有你的魔搭账号，也不该经手你的令牌。下面的命令留给你执行；文件我已经准备好。

```powershell
# 在你自己的终端里执行
$env:MODELSCOPE_API_TOKEN = "<个人中心 → 访问令牌 里生成的令牌>"
git clone https://www.modelscope.cn/studios/<你的用户名>/hongjian.git
cd hongjian
git remote add gh https://github.com/cyhkbl/hongjian-huawei-pc-agent.git
git fetch gh main
git checkout -b main gh/main
git push origin main
```

页面方式也可以：创空间 → 创建 → 类型选 Docker → 资源选 2 vCPU 16 GB → 上传本仓库文件（`app/`、`Dockerfile`、`ms_deploy.json`、`requirements.txt`、`README.md`）。

然后在创空间的 **设置 → 环境变量（密文管理）** 里加：

| 变量 | 值 |
|---|---|
| `IMA_OPENAPI_CLIENTID` | ima 接口凭证的 Client ID |
| `IMA_OPENAPI_APIKEY` | ima 接口凭证的 API Key |
| `KB_MODE` | `ima` |
| `LLM_BASE_URL` | 任意 OpenAI 兼容接口，如 `https://api-inference.modelscope.cn/v1` |
| `LLM_API_KEY` | 对应 key，可留空 |
| `LLM_MODEL` | 对应模型名，可留空 |

`LLM_*` 留空时后端走确定性编排器，全链路照样可用，只是文案不走大模型。`ima` 凭证没有的话 `KB_MODE` 留空，会用本地镜像模式（演示用，知识库份额外配置 `KB_LOCAL_DIR`）——但创空间里没有知识库副本，所以建议尽量把 ima 凭证配上。

部署完打开公网地址，确认三件事：页面能打开、右上角知识库状态显示已连接、跑一次“给 MateBook Pro 写个开学季小红书”能看到四段结果。

# 说明书

`作品说明书` 按赛题要求写，重点放在功能走查和运行结果，另附架构、提示词设计、ima 调用方式、部署步骤和已知限制。demo 视频需要你录屏，脚本见 `docs/作品说明书.md` 的最后一节。
