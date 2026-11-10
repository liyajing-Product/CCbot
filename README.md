# Health House · 个人健康 Agent

Health House 是一个以网页为主要入口的个人健康助手。当前项目提供健康对话、健康档案、记忆管理、用药与日程提醒，以及用户自定义模型配置。

仓库：[liyajing-Product/personal_agent](https://github.com/liyajing-Product/personal_agent) · 版本：`0.8.2` · 许可证：[MIT](LICENSE)

## 当前界面与使用流程

| 入口 | 当前行为 |
| --- | --- |
| 首页 | 默认进入欢迎页，展示胶囊 IP、四张功能卡片和对话输入框 |
| AI 健康助手 | 打开对话区，恢复该浏览器中当前用户的历史对话 |
| 健康记忆 | 查看、编辑和删除已记录的档案要点与近期记忆 |
| 用药与日程 | 右侧抽屉展示已有提醒；没有提醒时显示缺省插画，可新建每日用药提醒或一次性日程 |
| 健康档案 | 侧边抽屉维护个人及健康信息，并提供模型设置、家人守护等配置入口 |
| 个人空间 | 查看病史、当前用药和过敏记录等健康概览 |

首页四个快捷入口是“记录身体近况”“安排用药提醒”“整理就医笔记”“回顾健康记忆”。用药提醒可直接通过表单填写，不要求先用自然语言与模型对话。

新建提醒的网页流程为：填写属性 → 核对提醒卡片 → 确认创建。确认卡右上角可返回修改已填写的内容。已有提醒支持查看详情、修改、暂停、恢复、删除和运行记录查询；这些管理动作按各自的按钮与接口执行，不统一宣称所有操作都经过同一种确认卡。

界面使用品牌色 `#3ABA8A`、PingFang 优先字体及统一宽度的抽屉。首页首次点击输入框时播放全屏暖色冲击柔光，覆盖页面视口；再次点击不重播，重新进入首页后重置。光效使用透明 Canvas，结束即清理，支持减少动态效果；当前没有页面截图扭曲、色散或边缘折射。

## 对话、档案与提醒如何工作

前端使用原生 HTML / CSS / JavaScript，后端为 FastAPI。页面通过同源 `/api/*` 请求与后端通信。

- **对话与就医笔记**：`/api/chat` 等接口进入 LangGraph 编排，由模型网关调用可用模型，结合当前用户的上下文与记忆返回文本或交互卡片。生成的内容用于记录、整理和辅助沟通，不替代医生诊断或处方。
- **档案与健康概览**：档案抽屉、个人空间直接调用档案接口。已保存的个人资料、病史、用药和过敏信息由后端存储；这些表单操作不必经过模型。
- **记忆管理**：后端提供档案事实和近期事件的查询、编辑与删除接口；浏览器另有对话记录缓存。清除本机对话记录不等于删除服务端健康档案或全部记忆。
- **用药与日程**：网页表单通过日程 API 创建待确认方案，用户确认后保存；调度器到点生成站内提醒。是否自动执行取决于后端调度器是否启用、进程是否持续运行及部署环境。
- **模型设置**：用户可在档案抽屉填写 OpenAI 兼容接口的 Base URL、模型名与 API Key。保存前会发起小规模连接验证；失败时显示原因，不将失败结果当作配置成功。

主要实现入口：

| 模块 | 文件 |
| --- | --- |
| 页面和导航 | [static/index.html](static/index.html)、[static/js/workspace.js](static/js/workspace.js) |
| 输入、对话与光效 | [composer.js](static/js/composer.js)、[flows.js](static/js/flows.js)、[shockwave.js](static/js/shockwave.js) |
| 档案及模型设置界面 | [drawer.js](static/js/drawer.js) |
| 日程界面与服务 | [schedules.js](static/js/schedules.js)、[app/agent/schedules/](app/agent/schedules/) |
| FastAPI 接口 | [app/main.py](app/main.py) |
| 对话编排与模型网关 | [app/graph.py](app/graph.py)、[app/gateway/](app/gateway/) |
| 用户模型配置 | [app/user_model.py](app/user_model.py) |
| 家人守护关系 | [app/care.py](app/care.py) |

## 数据、身份与隐私边界

- 当前网页以**服务端签名的浏览器会话**识别用户，不是完整的手机号注册、密码登录或跨设备账号系统。更换浏览器或丢失会话 Cookie 后，不能假定会自动找回原来的身份与数据。
- 默认数据目录为 `DATA_DIR`（默认 `./data`）。业务数据默认使用 SQLite，LangGraph 检查点也使用本地 SQLite。浏览器对话缓存与服务端数据是两套存储。
- 用户提交的模型 API Key 使用 `SECRETS_FERNET_KEY` 加密后保存，配置查询只返回脱敏状态。**健康档案和整个数据库并非因此自动获得全库加密。** 服务器磁盘、备份、访问权限和 HTTPS 仍需部署者配置。
- 使用真实模型时，后端会向所配置的模型服务商发送请求，其中可能包括用户输入与参与上下文组装的健康信息、记忆。API Key 也会用于该服务商的鉴权；不能将此产品描述为“数据从不离开服务器”。保存模型配置时的连接测试也会调用对应接口，可能产生少量模型费用。
- 项目有身份校验、隐私拦截、出站检查、日志脱敏及相关测试。它们是代码层面的防护，不代表已完成生产安全认证，也不能保证模型回复永远正确或所有敏感信息永远不会泄漏。
- 家人守护需通过邀请与确认建立关系，相关页面可以查看被授权的健康档案；不是默认向所有家人开放全部对话与提醒。
- 不应把 `.env`、API Key、会话凭证、数据库和真实健康资料提交到 GitHub。仓库忽略规则与 Vercel 上传忽略规则已排除本地运行数据和环境文件。

## 本地运行

建议使用 Python 3.12，与 [Dockerfile](Dockerfile) 保持一致。

```bash
git clone https://github.com/liyajing-Product/personal_agent.git
cd personal_agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -c requirements.lock
cp .env.example .env
```

编辑本机 `.env`，至少设置 `AUTH_SECRET`。如果需要在网页中保存用户自己的模型 API Key，同时设置 `SECRETS_FERNET_KEY`。可在本机生成这两个值，妥善保存，不提交到仓库：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

分别将输出填入 `AUTH_SECRET` 和 `SECRETS_FERNET_KEY`。然后启动：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8789
```

- 首页：`http://127.0.0.1:8789/`
- 健康检查：`http://127.0.0.1:8789/health`
- 管理页面：`http://127.0.0.1:8789/admin`，管理接口另需管理员令牌

要体验真实 AI 对话，需要配置可访问的模型。可以在网页的健康档案抽屉中保存用户模型配置，也可以由部署者配置服务端默认模型。没有可用模型时不能将页面启动等同于 AI 对话已经可用。

## 当前需要的配置

下面列出与网页主流程直接相关的配置；完整环境变量模板见 [`.env.example`](.env.example)。模板中的渠道、向量检索和观测选项不代表默认启用。

| 配置 | 用途与条件 |
| --- | --- |
| `AUTH_SECRET` | 签名服务端用户会话；缺失时受保护接口不可用 |
| `SECRETS_FERNET_KEY` | 加密保存用户模型 API Key 和安全输入区内容；不配置则不能使用相关保存功能 |
| `DATA_DIR` | 服务端数据目录，正式部署需要持久磁盘和备份 |
| `LLM_FAST_BASE_URL` / `LLM_FAST_MODEL` / `LLM_FAST_API_KEY` | 部署者配置的 FAST 档默认模型 |
| `LLM_STRONG_BASE_URL` / `LLM_STRONG_MODEL` / `LLM_STRONG_API_KEY` | 部署者配置的 STRONG 档默认模型 |
| `KIMI_API_KEY` 等厂商变量 | 模型网关支持的其他密钥入口；按实际选用厂商配置，详见 [模型网关文档](docs/llm-gateway.md) |
| `PROACTIVE_ENABLED=1` | 启用后端主动调度；示例模板默认关闭，不启用时保存提醒不等于会到点执行 |
| `PROACTIVE_TZ=Asia/Shanghai` | 应用调度时区；单条日程也记录自己的时区 |
| `HARNESS_ADMIN_TOKENS` | 管理接口鉴权，普通用户网页流程不需要填写管理员令牌 |
| `HEALTH_HOUSE_BACKEND_URL` | **Vercel 构建环境**中的持久 FastAPI 后端 HTTPS 源站地址，不是用户模型接口地址 |

用户在网页填写的 Base URL 应是模型基础接口地址，不要包含 `/chat/completions`。保存成功提示约 1.5 秒消失；失败提示展示原因，约 3 秒消失。删除用户模型配置后，回到部署者配置的模型，而非保证仍有真实模型可用。

## 部署现状与方式

当前采用的部署拆分是：**Vercel 承载前端，持久服务器运行 FastAPI 与调度器**。

- GitHub 仓库已用于同步当前项目代码。
- Vercel 项目已建立并关联该仓库，但仍需配置可访问的持久后端地址，尚不能把它当作已完成的全功能公网版本。
- 本地 `127.0.0.1:8789` 只在开发机器上可用，不是可以填写到 Vercel 的公网后端地址。

Vercel 部署步骤：

1. 先将 FastAPI 部署到可保存 `DATA_DIR`、持续运行调度器的服务器，并配置必要的会话、加密与模型环境变量。
2. 在 Vercel 项目环境变量中设置 `HEALTH_HOUSE_BACKEND_URL`，值为后端 HTTPS 源站地址，不含账号、路径、查询参数或片段。
3. 使用 [vercel.json](vercel.json) 构建；[构建脚本](scripts/build-vercel.mjs) 输出前端静态文件，并同源代理 `/api/*` 和 `/health` 到后端。
4. 执行 `npx vercel --prod` 或通过 Git 集成发布，随后验证首页、会话、档案读写、模型调用和提醒执行。

构建缺少后端地址会明确报错。Vercel Functions 的临时文件系统不能直接替代本项目的持久 SQLite 数据目录，常驻调度也不能直接照搬到无状态函数中。仅给业务库配置 PostgreSQL，并不会自动迁移仍使用 SQLite 的对话检查点和所有文件存储。

仓库保留了 [Dockerfile](Dockerfile)、[render.yaml](render.yaml) 和 [部署参考](docs/deploy.md)。这些属于后端托管选项；必须按实际平台配置持久存储，不能仅凭容器启动就宣称长期记忆与定时服务已可靠上线。

## 可选集成，不是默认已上线能力

仓库仍保留飞书、OpenClaw 微信桥、家人守护和部分后台基础设施。这些代码的存在不等于当前公网部署已接通。

| 集成 | 当前说明 |
| --- | --- |
| 飞书 | 有长连接、绑定和消息处理代码；需要开关、应用凭证、平台权限与可持续运行的后端，不能只靠网页部署启用 |
| OpenClaw 微信桥 | 有桥接代码；需要独立网关、插件、Webhook 配置和用户绑定，不是直接接入个人微信的即开即用能力 |
| 家人守护 | 网页抽屉有邀请及关系管理入口，后端有授权健康档案查询；实际分享访问需可用后端与访问地址 |
| 向量检索、Langfuse、PostgreSQL / RLS | 保留可选实现和配置，不能代表当前默认运行栈或已完成生产验收 |

接入细节参见 [渠道文档](docs/channels.md) 与 [OpenClaw 桥说明](integrations/openclaw-personal-agent-bridge/README.md)。主产品仍是本 README 上述的网页健康工作空间。

## 开发与检查

```bash
pip install -r requirements-dev.txt -c requirements.lock
python -m pytest -q
node tests/model_config_ui.mjs
node tests/unit/schedules_create_ui.mjs
node tests/unit/schedules_ui.mjs
node tests/session_wall_stick_ui.mjs
```

[光效测试](tests/test_shockwave_frontend.py) 使用独立 Chrome / Chromium 与合成页面检查全屏 Canvas、两侧覆盖、边缘渐隐、首次点击和播放结束清理；没有可用浏览器时跳过。

模型金标测试分 mock 与 live 模式。日常检查可使用 mock；live 会调用实际服务并可能收费，不应将所有测试笼统描述为“永远不会花额度”。

```bash
AUTH_SECRET=test-only python tests/golden/run_golden.py --mode mock --judge-gate
```

进一步阅读：[CONTRIBUTING.md](CONTRIBUTING.md)、[日程服务](docs/schedules.md)、[模型网关](docs/llm-gateway.md)、[管理接口](docs/admin.md)。较早的设计文档可能描述了通用 Agent 阶段的结构，判断当前行为应以实现与测试为准。
