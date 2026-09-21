<template>
  <div class="smart-qa">
    <h3 class="panel-title">智能问答</h3>

    <!-- KB Selector -->
    <div class="kb-selector" v-if="!chatSessionId">
      <el-select
        v-model="selectedKbIds"
        multiple
        placeholder="选择知识库进行问答"
        size="small"
        style="width: 100%"
        collapse-tags
        collapse-tags-tooltip
      >
        <el-option
          v-for="kb in knowledgeBases"
          :key="kb.id"
          :label="kb.name"
          :value="kb.id"
        />
      </el-select>
      <el-button size="small" type="primary" @click="saveKbLinks" style="margin-top: 6px; width: 100%">
        关联所选知识库
      </el-button>
      <el-divider style="margin: 10px 0" />
    </div>

    <!-- Messages -->
    <div class="messages" ref="messagesRef">
      <div v-if="messages.length === 0" class="empty-state">
        <el-icon style="font-size: 32px; color: #ccc"><ChatDotRound /></el-icon>
        <p>输入问题开始智能问答</p>
      </div>
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        :class="['message', msg.role]"
      >
        <div class="message-content">{{ msg.content }}</div>
        <div v-if="msg.sources && msg.sources.length" class="sources">
          <el-collapse>
            <el-collapse-item title="📚 引用来源" name="sources">
              <div v-for="(src, si) in msg.sources" :key="si" class="source-item">
                <div class="source-text">{{ src.text.substring(0, 200) }}...</div>
                <div class="source-meta">
                  <el-tag size="small" type="info">得分: {{ (src.score * 100).toFixed(1) }}%</el-tag>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="input-area">
      <el-input
        v-model="query"
        placeholder="输入您的问题…"
        size="small"
        :disabled="!hasLinkedKbs"
        @keyup.enter="sendMessage"
      >
        <template #append>
          <el-button
            :loading="sending"
            :disabled="!query.trim() || !hasLinkedKbs"
            @click="sendMessage"
          >
            发送
          </el-button>
        </template>
      </el-input>
      <div v-if="!hasLinkedKbs" class="kb-hint">
        请先在笔记中关联知识库
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, nextTick, watch } from 'vue'
import { ChatDotRound } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const props = defineProps({
  noteId: { type: Number, required: true },
})

const knowledgeBases = ref([])
const selectedKbIds = ref([])
const linkedKbIds = ref([])
const messages = ref([])
const query = ref('')
const sending = ref(false)
const messagesRef = ref(null)
const chatSessionId = ref(null)

const hasLinkedKbs = computed(() => linkedKbIds.value.length > 0)

function getToken() {
  return localStorage.getItem('token')
}

async function fetchKBs() {
  try {
    const res = await api.get('/knowledge-bases/')
    knowledgeBases.value = res.data
  } catch (e) {
    console.error('Failed to fetch KBs:', e)
  }
}

async function fetchKbLinks() {
  try {
    const res = await api.get(`/notes/${props.noteId}/kb-links`)
    linkedKbIds.value = res.data
    selectedKbIds.value = [...res.data]
  } catch (e) {
    console.error('Failed to fetch KB links:', e)
  }
}

async function saveKbLinks() {
  try {
    await api.put(`/notes/${props.noteId}`, { kb_ids: selectedKbIds.value })
    linkedKbIds.value = [...selectedKbIds.value]
    ElMessage.success('知识库关联已更新')
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

async function sendMessage() {
  if (!query.value.trim() || !hasLinkedKbs.value || sending.value) return

  const userQuery = query.value
  messages.value.push({ role: 'user', content: userQuery })
  query.value = ''
  scrollToBottom()
  sending.value = true

  const assistantMsg = { role: 'assistant', content: '', sources: [] }
  messages.value.push(assistantMsg)

  try {
    const response = await fetch(`/api/v1/notes/${props.noteId}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getToken()}`,
      },
      body: JSON.stringify({
        query: userQuery,
        session_id: chatSessionId.value,
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
            const last = messages.value.length - 1
            messages.value[last].content += data.content
            scrollToBottom()
          } else if (data.type === 'session_id') {
            chatSessionId.value = data.session_id
          } else if (data.type === 'sources') {
            const last = messages.value.length - 1
            messages.value[last].sources = data.data
          } else if (data.type === 'error') {
            const last = messages.value.length - 1
            messages.value[last].content = `错误: ${data.message}`
            ElMessage.error(data.message)
          }
        } catch (e) {
          // ignore parse errors
        }
      }
    }
  } catch (e) {
    console.error('Smart QA chat failed:', e)
    const last = messages.value.length - 1
    messages.value[last].content = '问答请求失败，请重试'
  } finally {
    sending.value = false
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

onMounted(() => {
  fetchKBs()
  fetchKbLinks()
})
</script>

<style scoped>
.smart-qa {
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

.kb-selector {
  margin-bottom: 8px;
}

.messages {
  flex: 1;
  overflow-y: auto;
  margin-bottom: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.message {
  max-width: 100%;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
}

.message.user {
  background-color: #e3f2fd;
  align-self: flex-end;
}

.message.assistant {
  background-color: #f5f5f5;
  align-self: flex-start;
}

.message-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.sources {
  margin-top: 6px;
}

.source-item {
  padding: 6px 0;
  border-bottom: 1px solid #eee;
}

.source-text {
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
}

.source-meta {
  display: flex;
  gap: 4px;
}

.input-area {
  border-top: 1px solid #eee;
  padding-top: 8px;
}

.kb-hint {
  font-size: 11px;
  color: #e6a23c;
  margin-top: 4px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #999;
  font-size: 13px;
  gap: 8px;
}
</style>
