# RAG-PDF-System

一个面向个人与团队的知识管理平台，将 AI 笔记写作与企业级 RAG（检索增强生成）管线融合在统一的工作空间中。系统围绕「摄入 — 理解 — 创作 — 回顾」四个环节设计：

- **摄入**：支持 PDF、DOCX、XLSX、PPTX、Markdown、HTML、TXT 等多格式文档，经异步解析、分块、向量化后存入 Milvus 向量库
- **理解**：基于通义千问 Qwen-Max 的 RAG 对话，支持单跳/多跳推理、重排序、来源引用，让 LLM 回答扎根于用户自有知识库
- **创作**：内置 Tiptap 编辑器（富文本/Markdown），结合 AI 联机补全、写作助手（续写/扩写/摘要）和基于 RAG 的智能问答，辅助用户高效写作
- **回顾**：采用 SM-2 间隔复习算法，通过卡片式复习对抗遗忘曲线，提升长期记忆效率

整个系统基于 FastAPI + Vue 3 + LangChain + Milvus + Qwen 构建，前后端分离，可通过 Docker Compose 一键部署。

## 功能概览

| 模块 | 功能 |
|------|------|
| 笔记 | 富文本 / Markdown 编辑器 (Tiptap)，标签管理，自动保存 |
| 间隔复习 | SM-2 遗忘曲线算法，卡片式复习，质量评分 (0-5) |
| AI 联机补全 | 打字停顿后模型实时补全（1.5s 去抖），Tab 快速采纳 |
| AI 写作助手 | 续写、扩写、摘要生成，SSE 流式输出，一键插入文档 |
| 智能问答 | 基于 RAG 的 Agent 对话，关联知识库，文档引用来源展示 |
| RAG 对话 | 单跳 / 多跳推理，会话管理，短期 + 长期记忆 |
| 知识库 | 多格式文档上传，异步解析 → 分块 → 向量化 → 入库 |
| 评估体系 | 自动生成 QA 数据集，LLM-as-Judge 评估，报告导出 |
| 助手编排 | 可配置系统提示词、温度、Top-K，绑定知识库组合 |

## 技术栈

| 组件 | 技术 |
|---|---|
| 后端框架 | FastAPI (Python 3.10+) |
| 前端 | Vue 3 + Element Plus + Pinia + Vite |
| 富文本编辑器 | TipTap (ProseMirror) |
| ORM | SQLAlchemy 2.x (SQLite 本地开发) |
| 向量数据库 | Milvus 2.3.4 |
| 嵌入模型 | DashScope text-embedding-v1 |
| 大语言模型 | 通义千问 Qwen-Max |
| 重排序 | DashScope gte-rerank |
| 消息队列 | RabbitMQ 3 + Celery 5.x |
| 缓存 / 记忆 | Redis 7 |
| 对象存储 | MinIO |

## 前置依赖

- **Python 3.10+**
- **Node.js 18+**
- **Docker & Docker Compose**（用于启动基础服务）
- **DashScope API Key** — 从 [阿里云 DashScope](https://dashscope.aliyun.com/) 获取

## 快速启动

### 1. 克隆项目

```bash
git clone https://github.com/xiebrown/RAGsystem.git
cd RAGsystem
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入必要配置：

```env
# ===== 必填 =====
SECRET_KEY=<随机字符串，可用 openssl rand -hex 32 生成>
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ===== 基础服务（Docker 默认值，无需修改） =====
MILVUS_HOST=localhost
MILVUS_PORT=19530
REDIS_URL=redis://localhost:6379/0
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=rag-documents
```

### 3. 启动基础服务

```bash
docker compose -f docker/docker-compose.yml up -d
```

启动后确认各服务状态：

| 服务 | 端口 | 管理界面 |
|---|---|---|
| Milvus | 19530 | — |
| MinIO | 9000 | http://localhost:9001 |
| RabbitMQ | 5672 | http://localhost:15672 |
| Redis | 6379 | — |
| Flower (Celery 监控) | 5555 | http://localhost:5555 |

### 4. 安装 Python 依赖

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 5. 启动后端

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

后端启动后访问：
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v1/health

### 6. 启动 Celery Worker（可选，文档处理需要）

```bash
celery -A src.worker.celery_app worker --loglevel=info -P solo
```

### 7. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端开发服务器运行在 http://localhost:5173 ，API 请求自动代理到后端 8000 端口。

---

## Docker 一键启动

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

这将同时启动所有 8 个服务：app (后端)、worker (Celery)、flower、rabbitmq、redis、etcd、minio、milvus-standalone。

## 笔记功能详解

### 编辑器
- **富文本模式**：Tiptap 工具栏（H1-H3、粗体、斜体、下划线、列表、引用、代码块、链接、图片）
- **Markdown 模式**：一键切换
- **自动保存**：3 秒去抖自动保存

### 间隔复习（遗忘曲线）
采用 SM-2 算法，根据用户自评质量（0-5 分）动态计算下次复习间隔：

| 评分 | 含义 | 结果 |
|------|------|------|
| 0 | 完全遗忘 | 重置间隔为 1 天 |
| 1-2 | 记错但熟悉 | 重置间隔为 1 天 |
| 3 | 回忆困难但正确 | 第 1 次 1 天，第 2 次 6 天，之后 × 难度系数 |
| 4-5 | 顺利回忆 | 同上，但难度系数提升更多 |

### AI 联机补全
- 编辑器输入停顿 **1.5 秒** 后自动触发
- 灰色文字显示在光标位置
- **Tab** 键采纳补全，**Esc** 键拒绝

### AI 写作助手
- **续写**：从当前内容自然延续
- **扩写**：丰富细节和深度表达
- **摘要**：生成简洁摘要
- 全部通过 **SSE 流式** 逐 token 输出

### 智能问答
- 笔记可关联已有知识库
- 基于 RAG 的 Agent 对话，自动引用来源文档
- 引用来源可折叠展开，显示匹配度得分

## 项目结构

```
RAGsystem/
├── config/                   # 配置文件
├── src/
│   ├── main.py               # FastAPI 应用入口
│   ├── settings.py           # 全局设置（.env 驱动）
│   ├── api/
│   │   ├── dependencies.py   # JWT 鉴权依赖
│   │   └── routers/
│   │       ├── auth.py       # 注册 / 登录
│   │       ├── chat.py       # RAG 对话接口
│   │       ├── notes.py      # 笔记 CRUD / 复习 / AI 补全 / 写作 / 问答
│   │       ├── agent.py      # AI Agent 管理
│   │       ├── assistant.py  # 助手编排
│   │       ├── knowledge_base.py  # 知识库管理
│   │       ├── evaluation.py # 评估体系
│   │       ├── storage.py    # MinIO 文件管理
│   │       ├── monitor.py    # 文档状态监控
│   │       └── health.py     # 健康检查
│   ├── database/
│   │   ├── models.py         # SQLAlchemy 数据模型（含 Note / NoteReview / NoteTag...）
│   │   ├── sql_session.py    # 数据库会话管理
│   │   └── vector_db.py      # Milvus 向量库客户端
│   ├── embedding/            # 嵌入服务
│   ├── llm/                  # 大模型客户端
│   ├── processors/           # 文档解析器（PDF/DOCX/XLSX/PPTX/MD/HTML）
│   ├── retrieval/            # 检索 & 重排序
│   ├── services/
│   │   ├── rag_service.py    # RAG 主流程（单跳 / 多跳 / 流式）
│   │   ├── note_service.py   # 笔记业务 + SM-2 算法 + AI 提示工程
│   │   ├── memory_service.py # 短期 + 长期记忆
│   │   └── evaluator.py      # RAG 评估
│   ├── utils/                # 工具函数（JWT / 日志 / 预览）
│   └── worker/               # Celery 任务
│       ├── celery_app.py
│       └── tasks.py
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── TipTapEditor.vue       # 富文本/Markdown 编辑器
│       │   ├── AICompletion.vue       # AI 联机补全覆盖层
│       │   ├── AIWritingAssistant.vue # AI 写作助手侧面板
│       │   └── SmartQA.vue           # 智能问答面板
│       ├── views/
│       │   ├── NotesList.vue          # 笔记列表/搜索/筛选
│       │   ├── NoteEditor.vue         # 笔记编辑（编辑器+AI面板）
│       │   └── NoteReview.vue         # 间隔复习卡片
│       │   ├── Chat.vue / Assistant.vue / KnowledgeBase.vue / ...
│       ├── store/
│       │   └── notes.js              # Pinia 笔记状态管理
│       └── router/index.js
├── docker/                   # Docker 部署配置
├── scripts/                  # 评估 & 工具脚本
├── docs/                     # 文档
├── .env.example              # 环境变量模板
├── .env                      # 本地环境变量（不入库）
├── .gitignore
└── requirements.txt
```

## API 概览

所有 API 前缀：`/api/v1`

### 笔记
| 方法 | 路由 | 说明 |
|------|------|------|
| GET | `/notes/` | 笔记列表（分页、搜索、标签筛选） |
| POST | `/notes/` | 创建笔记 |
| GET | `/notes/{id}` | 笔记详情（含复习状态） |
| PUT | `/notes/{id}` | 更新笔记 |
| DELETE | `/notes/{id}` | 删除笔记 |
| GET | `/notes/{id}/review-status` | 间隔复习状态 |
| POST | `/notes/{id}/review` | 提交复习评分（SM-2） |
| GET | `/notes/review/due` | 到期笔记列表 |
| POST | `/notes/ai/complete` | AI 联机补全 |
| POST | `/notes/ai/write` | AI 写作助手（SSE 流式） |
| POST | `/notes/{id}/chat` | 智能问答（SSE 流式 + 来源引用） |
| GET/POST | `/notes/tags/list`, `/notes/tags` | 标签管理 |

### 系统
| 方法 | 路由 | 说明 |
|------|------|------|
| POST | `/auth/register` | 用户注册 |
| POST | `/auth/login/access-token` | 登录获取 JWT |
| GET | `/health` | 健康检查 |
| CRUD | `/knowledge-bases` | 知识库管理 |
| CRUD | `/assistants` | 助手编排 |
| CRUD | `/agents` | AI Agent 管理 |
| CRUD | `/evaluations` | 评估任务 |
| POST | `/chat/` | RAG 对话（含流式） |

完整文档访问 http://localhost:8000/docs

## 许可证

MIT
