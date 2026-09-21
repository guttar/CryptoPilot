<template>
  <div class="agent-container">
    <div class="header">
      <h2>智能体管理</h2>
      <el-button type="primary" @click="openDialog()">创建智能体</el-button>
    </div>
    
    <el-table :data="agents" style="width: 100%; margin-top: 20px;" border stripe>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="名称" width="150" />
      <el-table-column prop="type" label="类型" width="120">
        <template #default="scope">
          <el-tag>{{ formatAgentType(scope.row.type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" show-overflow-tooltip />
      <el-table-column prop="updated_at" label="更新时间" width="180">
        <template #default="scope">
          {{ formatDate(scope.row.updated_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="270" fixed="right">
        <template #default="scope">
          <el-button size="small" type="success" @click="openRunDialog(scope.row)">运行</el-button>
          <el-button size="small" @click="openDialog(scope.row)">编辑</el-button>
          <el-button size="small" type="danger" @click="deleteAgent(scope.row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog 
      v-model="dialogVisible" 
      :title="isEdit ? '编辑智能体' : '创建智能体'" 
      width="80%"
      top="5vh"
    >
      <el-tabs v-model="activeTab" type="border-card">
        <!-- 1. 基础元配置 -->
        <el-tab-pane label="基础信息" name="basic">
          <el-form :model="form" label-width="120px">
            <el-form-item label="智能体名称" required>
              <el-input v-model="form.name" placeholder="如：数据分析助手" />
            </el-form-item>
            <el-form-item label="智能体描述">
              <el-input v-model="form.description" type="textarea" :rows="2" placeholder="描述智能体的能力和边界" />
            </el-form-item>
            <el-form-item label="智能体类型" required>
              <el-select v-model="form.type" placeholder="选择类型">
                <el-option label="Function Calling (工具调用型)" value="function_call" />
                <el-option label="ReAct (推理+行动)" value="react" />
                <el-option label="Plan & Execute (规划执行型)" value="plan_execute" />
              </el-select>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 2. 核心能力配置 -->
        <el-tab-pane label="核心能力" name="capability">
          <el-form :model="form" label-width="140px">
            <el-form-item label="系统提示词">
              <el-input 
                v-model="form.system_prompt" 
                type="textarea" 
                :rows="6" 
                placeholder="设定智能体的角色、语气、约束条件等 (System Prompt)" 
              />
            </el-form-item>
            
            <el-divider content-position="left">工具集配置</el-divider>
            <el-form-item label="启用工具">
              <el-checkbox-group v-model="form.tools_config.tools">
                <el-checkbox v-for="tool in availableTools" :key="tool" :label="tool">{{ tool }}</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <el-form-item label="权限设置">
               <el-checkbox-group v-model="form.tools_config.permissions">
                <el-checkbox v-for="perm in availablePermissions" :key="perm" :label="perm">{{ perm }}</el-checkbox>
              </el-checkbox-group>
            </el-form-item>

            <el-divider content-position="left">知识库配置</el-divider>
            <el-form-item label="关联知识库">
              <el-select v-model="form.knowledge_config.kb_ids" multiple placeholder="选择知识库">
                <el-option
                  v-for="kb in knowledgeBases"
                  :key="kb.id"
                  :label="kb.name"
                  :value="kb.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="召回策略">
              <el-radio-group v-model="form.knowledge_config.recall_strategy">
                <el-radio label="vector">向量检索</el-radio>
                <el-radio label="keyword">关键词检索</el-radio>
                <el-radio label="hybrid">混合检索</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="Top K" v-if="form.knowledge_config.recall_strategy">
              <el-slider v-model="form.knowledge_config.top_k" :min="1" :max="20" show-input />
            </el-form-item>
            <el-form-item label="检索重排序">
              <el-switch v-model="form.knowledge_config.enable_rerank" active-text="开启" inactive-text="关闭" />
            </el-form-item>

            <el-divider content-position="left">记忆配置</el-divider>
            <el-form-item label="短期记忆">
              <el-switch v-model="form.memory_config.enable_short_term" active-text="开启" inactive-text="关闭" />
            </el-form-item>
            <el-form-item label="窗口大小" v-if="form.memory_config.enable_short_term">
              <el-input-number v-model="form.memory_config.window_size" :min="1" :max="50" />
            </el-form-item>
             <el-form-item label="长期记忆">
              <el-switch v-model="form.memory_config.enable_long_term" active-text="开启" inactive-text="关闭" />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 3. 执行逻辑配置 -->
        <el-tab-pane label="执行逻辑" name="execution">
          <el-form :model="form" label-width="140px">
            <el-divider content-position="left">推理配置</el-divider>
            <el-form-item label="最大步数">
               <el-input-number v-model="form.reasoning_config.max_steps" :min="1" :max="50" />
            </el-form-item>
            <el-form-item label="并行执行">
               <el-switch v-model="form.reasoning_config.allow_parallel" active-text="允许" inactive-text="禁止" />
            </el-form-item>

            <el-divider content-position="left">安全配置</el-divider>
            <el-form-item label="安全等级">
               <el-select v-model="form.security_config.safety_level">
                 <el-option label="严格 (Strict)" value="strict" />
                 <el-option label="中等 (Moderate)" value="moderate" />
                 <el-option label="宽松 (Loose)" value="loose" />
               </el-select>
            </el-form-item>
             <el-form-item label="允许动作">
               <el-checkbox-group v-model="form.security_config.allowed_actions">
                <el-checkbox label="read_file">读取文件</el-checkbox>
                <el-checkbox label="write_file">写入文件</el-checkbox>
                <el-checkbox label="execute_code">执行代码</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
             <el-form-item label="联网访问">
               <el-switch v-model="form.security_config.allow_internet" active-text="允许" inactive-text="禁止" />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 4. 输出与交互配置 -->
        <el-tab-pane label="输出交互" name="interaction">
          <el-form :model="form" label-width="140px">
            <el-form-item label="输出格式">
               <el-select v-model="form.interaction_config.output_format">
                 <el-option label="Markdown (推荐)" value="markdown" />
                 <el-option label="JSON" value="json" />
                 <el-option label="纯文本" value="text" />
               </el-select>
            </el-form-item>
            <el-form-item label="回复风格">
               <el-select v-model="form.interaction_config.response_style">
                 <el-option label="专业 (Professional)" value="professional" />
                 <el-option label="友好 (Friendly)" value="friendly" />
                 <el-option label="简洁 (Concise)" value="concise" />
               </el-select>
            </el-form-item>
            <el-form-item label="主动澄清">
               <el-switch v-model="form.interaction_config.clarify_enabled" active-text="开启" inactive-text="关闭" />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 5. 调度与部署配置 -->
        <el-tab-pane label="调度部署" name="deployment">
          <el-form :model="form" label-width="140px">
            <el-divider content-position="left">模型配置</el-divider>
            <el-form-item label="底座模型">
               <el-select v-model="form.llm_config.model_name">
                 <el-option label="Qwen Max" value="qwen-max" />
                 <el-option label="Qwen Plus" value="qwen-plus" />
                 <el-option label="GPT-4" value="gpt-4" />
                 <el-option label="GPT-3.5" value="gpt-3.5-turbo" />
               </el-select>
            </el-form-item>
            <el-form-item label="温度 (Temperature)">
               <el-slider v-model="form.llm_config.temperature" :min="0" :max="1" :step="0.1" show-input />
            </el-form-item>
            <el-form-item label="最大Token">
               <el-input-number v-model="form.llm_config.max_tokens" :min="128" :max="8192" :step="128" />
            </el-form-item>

            <el-divider content-position="left">执行配置</el-divider>
            <el-form-item label="超时时间 (秒)">
               <el-input-number v-model="form.execution_config.timeout" :min="10" :max="300" />
            </el-form-item>
            <el-form-item label="重试次数">
               <el-input-number v-model="form.execution_config.retry_times" :min="0" :max="5" />
            </el-form-item>
             <el-form-item label="兜底回复">
              <el-input v-model="form.execution_config.fallback_response" placeholder="无法回答时的默认回复" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" @click="saveAgent">保存</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog v-model="runDialogVisible" title="运行密码协议分析 Agent" width="72%" @closed="closeRunStream">
      <el-form label-position="top">
        <el-form-item label="分析问题">
          <el-input
            v-model="runQuestion"
            type="textarea"
            :rows="4"
            placeholder="例如：检索 TLS 1.3 的密钥派生流程，并检查使用 RSA-1024 与 SHA-1 的风险"
            :disabled="isRunActive"
          />
        </el-form-item>
      </el-form>

      <div v-if="currentRun" class="run-status">
        <el-tag :type="runStatusType">{{ currentRun.status }}</el-tag>
        <span class="run-id">Run {{ currentRun.id }}</span>
      </div>

      <el-timeline v-if="runEvents.length" class="run-timeline">
        <el-timeline-item
          v-for="event in runEvents"
          :key="event.sequence"
          :type="eventType(event.event_type)"
          :timestamp="`#${event.sequence} ${event.event_type}`"
        >
          <pre>{{ formatEventPayload(event.payload) }}</pre>
        </el-timeline-item>
      </el-timeline>

      <el-alert v-if="runAnswer" title="分析结果" type="success" :closable="false" class="run-answer">
        <pre>{{ runAnswer }}</pre>
      </el-alert>

      <template #footer>
        <el-button @click="runDialogVisible = false">关闭</el-button>
        <el-button v-if="isRunActive" type="danger" @click="cancelRun">停止运行</el-button>
        <el-button v-else type="primary" :loading="startingRun" @click="startRun">开始分析</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, reactive, onMounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const agents = ref([])
const knowledgeBases = ref([]) // Fetched KBs
const dialogVisible = ref(false)
const isEdit = ref(false)
const currentId = ref(null)
const activeTab = ref('basic')

// Constant Options
const availableTools = ['search_knowledge_base', 'lookup_protocol', 'validate_crypto_parameters']
const availablePermissions = ['read_file', 'write_file', 'internet_access', 'execute_code']

const runDialogVisible = ref(false)
const runAgentId = ref(null)
const runQuestion = ref('')
const currentRun = ref(null)
const runEvents = ref([])
const runAnswer = ref('')
const startingRun = ref(false)
let streamController = null

const terminalStatuses = new Set(['completed', 'failed', 'cancelled', 'timed_out'])
const isRunActive = computed(() => currentRun.value && !terminalStatuses.has(currentRun.value.status))
const runStatusType = computed(() => {
  const map = { completed: 'success', failed: 'danger', cancelled: 'info', timed_out: 'warning', running: 'primary' }
  return map[currentRun.value?.status] || 'info'
})

const form = reactive({
  name: '',
  description: '',
  type: 'function_call',
  system_prompt: '',
  
  // Structured fields initialized
  tools_config: {
    tools: [],
    permissions: []
  },
  knowledge_config: {
    kb_ids: [],
    recall_strategy: 'hybrid',
    top_k: 5,
    enable_rerank: true
  },
  memory_config: {
    enable_short_term: true,
    window_size: 10,
    enable_long_term: false
  },
  reasoning_config: {
    max_steps: 10,
    allow_parallel: true
  },
  security_config: {
    safety_level: 'moderate',
    allowed_actions: [],
    allow_internet: false
  },
  interaction_config: {
    output_format: 'markdown',
    response_style: 'professional',
    clarify_enabled: true
  },
  llm_config: {
    model_name: 'qwen-max',
    temperature: 0.7,
    max_tokens: 2048
  },
  execution_config: {
    timeout: 60,
    retry_times: 3,
    fallback_response: ''
  }
})

const formatAgentType = (type) => {
  const map = {
    'function_call': 'Function Calling',
    'react': 'ReAct',
    'plan_execute': 'Plan & Execute'
  }
  return map[type] || type
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString()
}

const fetchAgents = async () => {
  try {
    const res = await api.get('/agents/')
    agents.value = res.data
  } catch (error) {
    console.error('Failed to fetch agents:', error)
    ElMessage.error('获取智能体列表失败')
  }
}

const fetchKnowledgeBases = async () => {
  try {
    const res = await api.get('/knowledge-bases/')
    knowledgeBases.value = res.data
  } catch (error) {
    console.error('Failed to fetch knowledge bases:', error)
    ElMessage.warning('获取知识库列表失败')
  }
}

const openDialog = (row = null) => {
  activeTab.value = 'basic'
  fetchKnowledgeBases() // Ensure we have latest KBs
  
  if (row) {
    isEdit.value = true
    currentId.value = row.id
    
    // Copy basic fields
    form.name = row.name
    form.description = row.description
    form.type = row.type
    form.system_prompt = row.system_prompt || ''
    
    // Load config fields, providing defaults if null
    form.tools_config = row.tools_config || { tools: [], permissions: [] }
    form.knowledge_config = { kb_ids: [], recall_strategy: 'hybrid', top_k: 5, enable_rerank: true, ...(row.knowledge_config || {}) }
    form.memory_config = row.memory_config || { enable_short_term: true, window_size: 10, enable_long_term: false }
    form.reasoning_config = row.reasoning_config || { max_steps: 10, allow_parallel: true }
    form.security_config = row.security_config || { safety_level: 'moderate', allowed_actions: [], allow_internet: false }
    form.interaction_config = row.interaction_config || { output_format: 'markdown', response_style: 'professional', clarify_enabled: true }
    form.llm_config = row.llm_config || { model_name: 'qwen-max', temperature: 0.7, max_tokens: 2048 }
    form.execution_config = row.execution_config || { timeout: 60, retry_times: 3, fallback_response: '' }
    
  } else {
    isEdit.value = false
    currentId.value = null
    
    // Reset form
    form.name = ''
    form.description = ''
    form.type = 'function_call'
    form.system_prompt = ''
    
    form.tools_config = { tools: [], permissions: [] }
    form.knowledge_config = { kb_ids: [], recall_strategy: 'hybrid', top_k: 5, enable_rerank: true }
    form.memory_config = { enable_short_term: true, window_size: 10, enable_long_term: false }
    form.reasoning_config = { max_steps: 10, allow_parallel: true }
    form.security_config = { safety_level: 'moderate', allowed_actions: [], allow_internet: false }
    form.interaction_config = { output_format: 'markdown', response_style: 'professional', clarify_enabled: true }
    form.llm_config = { model_name: 'qwen-max', temperature: 0.7, max_tokens: 2048 }
    form.execution_config = { timeout: 60, retry_times: 3, fallback_response: '' }
  }
  dialogVisible.value = true
}

const saveAgent = async () => {
  try {
    const dataToSave = {
      name: form.name,
      description: form.description,
      type: form.type,
      system_prompt: form.system_prompt,
      tools_config: form.tools_config,
      knowledge_config: form.knowledge_config,
      memory_config: form.memory_config,
      reasoning_config: form.reasoning_config,
      security_config: form.security_config,
      interaction_config: form.interaction_config,
      llm_config: form.llm_config,
      execution_config: form.execution_config,
    }

    if (isEdit.value) {
      await api.put(`/agents/${currentId.value}`, dataToSave)
      ElMessage.success('更新成功')
    } else {
      await api.post('/agents/', dataToSave)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    fetchAgents()
  } catch (e) {
    console.error(e)
    ElMessage.error('保存失败')
  }
}

const deleteAgent = async (id) => {
  try {
    await ElMessageBox.confirm('确定要删除该智能体吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await api.delete(`/agents/${id}`)
    ElMessage.success('删除成功')
    fetchAgents()
  } catch (e) {
    if (e !== 'cancel') {
      console.error(e)
      ElMessage.error('删除失败')
    }
  }
}

const openRunDialog = (agent) => {
  closeRunStream()
  runAgentId.value = agent.id
  runQuestion.value = ''
  currentRun.value = null
  runEvents.value = []
  runAnswer.value = ''
  runDialogVisible.value = true
}

const eventType = (name) => {
  if (name.endsWith('.failed')) return 'danger'
  if (name.endsWith('.completed')) return 'success'
  if (name.endsWith('.cancelled') || name.endsWith('.timed_out')) return 'warning'
  return 'primary'
}

const formatEventPayload = (payload) => {
  if (!payload) return ''
  if (payload.answer) return payload.answer
  return JSON.stringify(payload, null, 2)
}

const applyRunEvent = (event) => {
  runEvents.value.push(event)
  const terminal = event.event_type.replace('run.', '')
  if (terminalStatuses.has(terminal)) {
    currentRun.value = { ...currentRun.value, status: terminal }
  }
  if (event.event_type === 'run.completed') {
    runAnswer.value = event.payload.answer || ''
  }
}

const connectRunStream = async (runId) => {
  streamController = new AbortController()
  const token = localStorage.getItem('token')
  try {
    const response = await fetch(`/api/v1/agents/executions/${runId}/stream`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: streamController.signal,
    })
    if (!response.ok || !response.body) throw new Error(`SSE connection failed: ${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
        if (!block || block.startsWith(':')) continue
        const lines = block.split('\n')
        const id = Number(lines.find(line => line.startsWith('id:'))?.slice(3).trim() || 0)
        const eventTypeName = lines.find(line => line.startsWith('event:'))?.slice(6).trim() || 'message'
        const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n')
        applyRunEvent({ sequence: id, event_type: eventTypeName, payload: data ? JSON.parse(data) : {} })
      }
    }
    const finalResponse = await api.get(`/agents/executions/${runId}`)
    currentRun.value = finalResponse.data
    if (finalResponse.data.answer) runAnswer.value = finalResponse.data.answer
  } catch (error) {
    if (error.name !== 'AbortError') {
      console.error(error)
      ElMessage.error('运行事件流连接失败')
    }
  }
}

const startRun = async () => {
  if (!runQuestion.value.trim()) {
    ElMessage.warning('请输入分析问题')
    return
  }
  startingRun.value = true
  runEvents.value = []
  runAnswer.value = ''
  try {
    const response = await api.post(`/agents/${runAgentId.value}/runs`, { question: runQuestion.value })
    currentRun.value = response.data
    connectRunStream(response.data.id)
  } catch (error) {
    console.error(error)
    ElMessage.error(error.response?.data?.detail || '创建 Agent 运行失败')
  } finally {
    startingRun.value = false
  }
}

const cancelRun = async () => {
  if (!currentRun.value) return
  try {
    const response = await api.post(`/agents/executions/${currentRun.value.id}/cancel`)
    currentRun.value = response.data
  } catch (error) {
    console.error(error)
    ElMessage.error('停止运行失败')
  }
}

function closeRunStream() {
  if (streamController) {
    streamController.abort()
    streamController = null
  }
}

onMounted(() => {
  fetchAgents()
})
</script>

<style scoped>
.agent-container {
  padding: 20px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.json-editor-tip {
  font-size: 12px;
  color: #909399;
  margin-bottom: 5px;
}
.run-status {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 18px;
}
.run-id {
  color: #909399;
  font-family: monospace;
  font-size: 12px;
}
.run-timeline {
  max-height: 340px;
  overflow: auto;
  margin-top: 16px;
}
.run-timeline pre,
.run-answer pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
}
.run-answer {
  margin-top: 16px;
}
</style>
