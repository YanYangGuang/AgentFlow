# AgentFlow

AI 智能体工作流平台：从任务意图，到可追踪的智能执行。

当前已交付 V1.0 里程碑第 1–5 阶段的基础能力：Vue 3 + TypeScript + Vite 前端，FastAPI + SQLAlchemy + SQLite 后端。系统以**安全沙盒**为初始环境；侧栏总开关切换整个工作区的新运行环境。真实模型执行仍受后端 `AGENTFLOW_ENABLE_LIVE_EXECUTION` 开关和模型凭据双重保护。

## 当前功能

- 工作台：后端统计、任务创建、最近任务、本地活动趋势和环境信息。
- 任务中心：搜索、状态与模式筛选、分页、创建、编辑、取消、删除和任务详情。
- 独立运行记录：每个任务的每次运行单独保存状态、模式、工作流版本快照、时间、耗时、输出与失败信息。
- 运行追踪：分页和筛选运行记录、查看运行详情及不可变工作流快照。
- 评测中心：持久化评测数据集，对保存的流程逐条批量运行；每条用例关联独立运行记录，按期望关键词或执行成功条件评分，并按数据集/模型/模式汇总对比。真实评测沿用实际模型执行，失败不会使用演示结果兜底。
- 流程编排：创建和保存版本化工作流、拖放节点、画布连线、节点配置、DAG 结构校验、启动演示执行。
- 工作流执行器：后端异步执行 DAG，持久化运行快照、节点状态和事件；工具仅包含本地白名单文本摘要与 JSON 校验。
- 模型设置：显示后端模型配置状态并测试连接；LLM 节点真实调用支持超时、错误状态和服务商返回的 Token 用量。
- 凭据边界：API Key 仅从后端环境变量读取，前端不会提交或回显；真实执行需显式启用，不会在失败时回退演示结果。
- 安全沙盒：使用本地确定性执行器，不调用外部模型；新数据库不再插入伪造的历史任务或指标。
- 主题与布局：浅色默认、暗色切换、响应式侧栏和页面导航。
- API：健康检查、统计摘要、任务 CRUD、取消，以及任务运行历史和运行记录查询。
- SQLite 持久化任务。演示任务不计真实 Token，未知用量显示为空。
- 真实模式请求会明确返回未配置错误，不会回退成演示结果。

运行追踪和评测结果通过轮询获取进度，断开后可重新查询持久化状态。评测通过率是显式关键词匹配规则，不代表主观质量评分；未设置期望关键词的用例只统计工作流是否成功。评测任务不会计入普通工作台任务统计。评测模型标签记录启动时后端的默认模型配置；模型选择目前复用模型供应商页面中的默认模型。其余导航仍为精简建设中页面；SSE 实时推送和自动化测试尚未实现。当前真实模型适配仅支持兼容 OpenAI Chat Completions API 的服务商；真实执行是单用户本地开发能力，公开部署前必须增加身份认证和访问控制。

## 本地启动

需要 Node.js LTS 和 Python 3.10+。

终端一前端：

```powershell
cd frontend
npm install
npm run dev
```

终端二后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
或者
python.exe -m pip install -r requirements.txt

uvicorn app.main:app --reload
或者
python -m uvicorn app.main:app --reload
```

前端默认地址为 Vite 显示的本地地址，后端 API 文档为 `http://127.0.0.1:8000/docs`。首次启动会在 `backend/agentflow.db` 创建 SQLite 数据库。前端开发代理会将 `/api` 请求转发到后端。

### 配置真实模型与供应商凭据

根目录 `.env.example` 是空密钥模板；复制为根目录 `.env` 后，在本机设置 `AGENTFLOW_LLM_API_KEY`。供应商设置页保存的 API Key 使用 `AGENTFLOW_CREDENTIAL_ENCRYPTION_KEY` 加密后写入 SQLite；加密密钥只保存在后端环境中，必须做好安全备份，密钥丢失将无法解密已保存的供应商凭据。旧 OpenRouter 环境变量仍可作为兼容配置使用。真实运行和连接测试需设置 `AGENTFLOW_ENABLE_LIVE_EXECUTION=true`。连接测试会访问服务商接口，模型调用可能产生费用。

## API 概览

- `GET /api/v1/health`
- `GET /api/v1/system/runtime`、`PUT /api/v1/system/runtime/mode`：读取/切换全局执行环境；切到真实环境需要后端开关已开启且默认模型凭据有效
- `GET /api/v1/models`、`POST /api/v1/models/test`
- `GET /api/v1/models/providers`、`PUT /api/v1/models/providers/{code}`
- `POST /api/v1/models/providers/{code}/test`、`GET /api/v1/models/providers/{code}/models`、`DELETE /api/v1/models/providers/{code}/credential`
- `GET /api/v1/dashboard/summary`
- `GET /api/v1/tasks?q=&status=&page=1&page_size=10`
- `POST /api/v1/tasks`，请求体 `{"title":"整理用户反馈","description":"可选说明","mode":"demo"}`
- `GET /api/v1/tasks/{task_id}`
- `PATCH /api/v1/tasks/{task_id}`
- `DELETE /api/v1/tasks/{task_id}`
- `POST /api/v1/tasks/{task_id}/cancel`
- `GET /api/v1/tasks/{task_id}/runs`
- `GET /api/v1/runs?status=&mode=demo&page=1&page_size=10`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/workflows`、`POST /api/v1/workflows`、`GET /api/v1/workflows/{workflow_id}`
- `PUT /api/v1/workflows/{workflow_id}/default`：切换工作区默认流程；`DELETE /api/v1/workflows/{workflow_id}`：归档非默认流程，保留历史快照
- `PUT /api/v1/workflows/{workflow_id}`：保存新版本快照
- `GET /api/v1/workflows/{workflow_id}/versions`
- `POST /api/v1/workflows/{workflow_id}/validate`
- `POST /api/v1/workflows/{workflow_id}/runs`：快速返回运行记录并在后台执行
- `GET /api/v1/runs/{run_id}/nodes`、`GET /api/v1/runs/{run_id}/events`
- `GET /api/v1/evaluations/datasets`、`POST /api/v1/evaluations/datasets`
- `POST /api/v1/evaluations/datasets/{dataset_id}/runs`：按指定演示/真实模式批量执行已保存工作流并快速返回评测记录
- `GET /api/v1/evaluations`、`GET /api/v1/evaluations/{evaluation_id}`

## 环境变量

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AGENTFLOW_LLM_PROVIDER` | `OpenRouter` | 设置页显示的服务商名称 |
| `AGENTFLOW_LLM_BASE_URL` | `https://openrouter.ai/api/v1` | API 根地址或完整 Chat Completions 地址 |
| `AGENTFLOW_LLM_MODEL` | `nvidia/nemotron-3.5-lightning:free` | 默认模型名称 |
| `AGENTFLOW_LLM_API_KEY` | 空 | 后端模型凭据 |
| `AGENTFLOW_CREDENTIAL_ENCRYPTION_KEY` | 空 | Fernet 密钥，用于加密数据库中的供应商凭据；首次配置 UI 凭据前必须设置 |
| `AGENTFLOW_ENABLE_LIVE_EXECUTION` | `false` | 明确开启真实模型执行 |

## 项目结构

```text
frontend/  Vue 应用、路由、状态、API 和页面
backend/   FastAPI 接口、SQLAlchemy 模型和 SQLite 数据库
```
