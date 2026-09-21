<template>
  <div class="ai-writing-assistant">
    <h3 class="panel-title">AI 写作助手</h3>

    <!-- Action Buttons -->
    <div class="action-buttons">
      <el-button
        type="primary"
        size="small"
        :loading="loading && currentAction === 'continue'"
        @click="startWrite('continue')"
        style="width: 100%"
      >
        续写
      </el-button>
      <el-button
        type="success"
        size="small"
        :loading="loading && currentAction === 'expand'"
        @click="startWrite('expand')"
        style="width: 100%"
      >
        扩写
      </el-button>
      <el-button
        type="warning"
        size="small"
        :loading="loading && currentAction === 'summarize'"
        @click="startWrite('summarize')"
        style="width: 100%"
      >
        摘要
      </el-button>
    </div>

    <!-- Custom Instruction -->
    <div class="custom-instruction">
      <el-input
        v-model="customInstruction"
        placeholder="输入自定义指令…"
        size="small"
        clearable
      >
        <template #append>
          <el-button
            size="small"
            :loading="loading && currentAction === 'custom'"
            @click="startWrite('custom')"
          >
            执行
          </el-button>
        </template>
      </el-input>
    </div>

    <el-divider style="margin: 12px 0" />

    <!-- Streaming Output -->
    <div class="output-area" ref="outputArea" v-if="output">
      <div class="output-header">
        <span class="output-label">生成结果</span>
        <el-button size="small" text @click="insertToEditor" :disabled="!output">
          插入到文档
        </el-button>
        <el-button size="small" text type="danger" @click="output = ''">
          清空
        </el-button>
      </div>
      <div class="output-content" v-html="renderedOutput" />
    </div>

    <div v-else class="empty-state">
      <el-icon style="font-size: 32px; color: #ccc"><EditPen /></el-icon>
      <p>选择操作开始 AI 写作</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { EditPen } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  noteContent: { type: String, default: '' },
})

const emit = defineEmits(['insert'])

const loading = ref(false)
const currentAction = ref('')
const output = ref('')
const customInstruction = ref('')
const outputArea = ref(null)

const renderedOutput = computed(() => {
  return output.value.replace(/\n/g, '<br>')
})

function getToken() {
  return localStorage.getItem('token')
}

async function startWrite(action) {
  if (!props.noteContent.trim()) {
    ElMessage.warning('笔记内容为空，请先写入内容')
    return
  }

  currentAction.value = action
  loading.value = true
  output.value = ''

  try {
    const response = await fetch('/api/v1/notes/ai/write', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getToken()}`,
      },
      body: JSON.stringify({
        action,
        content: props.noteContent,
        instruction: action === 'custom' ? customInstruction.value : '',
      }),
    })

    if (!response.ok) throw new Error(`HTTP ${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''

      for (const part of parts) {
        if (!part.startsWith('data: ')) continue
        try {
          const data = JSON.parse(part.slice(6))
          if (data.type === 'token') {
            output.value += data.content
            scrollToBottom()
          } else if (data.type === 'done') {
            loading.value = false
          } else if (data.type === 'error') {
            ElMessage.error(data.message || '生成出错')
            loading.value = false
          }
        } catch (e) {
          // ignore parse errors
        }
      }
    }
  } catch (e) {
    console.error('AI write stream failed:', e)
    ElMessage.error('写作请求失败')
  } finally {
    loading.value = false
  }
}

function insertToEditor() {
  if (output.value) {
    emit('insert', output.value)
    ElMessage.success('已插入到文档')
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (outputArea.value) {
      outputArea.value.scrollTop = outputArea.value.scrollHeight
    }
  })
}
</script>

<style scoped>
.ai-writing-assistant {
  padding: 12px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.panel-title {
  margin: 0 0 12px;
  font-size: 15px;
  color: #303133;
}

.action-buttons {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}

.custom-instruction {
  margin-bottom: 4px;
}

.output-area {
  flex: 1;
  overflow-y: auto;
  background: #f9f9f9;
  border-radius: 4px;
  padding: 8px;
  min-height: 100px;
}

.output-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 12px;
}

.output-label {
  font-weight: bold;
  color: #606266;
}

.output-content {
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 13px;
  gap: 8px;
}
</style>
