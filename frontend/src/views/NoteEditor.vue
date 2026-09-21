<template>
  <div class="note-editor">
    <!-- Loading -->
    <div v-if="loading" class="loading">
      <el-skeleton :rows="5" animated />
    </div>

    <template v-else-if="note">
      <!-- Title Bar -->
      <div class="title-bar">
        <div class="title-left">
          <el-button text @click="$router.push('/notes')">
            <el-icon><ArrowLeft /></el-icon>
          </el-button>
          <el-input
            v-model="note.title"
            class="title-input"
            placeholder="笔记标题"
            @input="onTitleChange"
          />
        </div>
        <div class="title-right">
          <!-- Review Status -->
          <el-tooltip :content="reviewTooltip" placement="bottom">
            <el-button
              size="small"
              :type="isDue ? 'danger' : 'default'"
              :icon="Clock"
              @click="showReviewDialog = true"
            >
              {{ isDue ? '待复习' : '复习' }}
            </el-button>
          </el-tooltip>

          <!-- Tag Selector -->
          <el-popover placement="bottom" :width="200" trigger="click">
            <template #reference>
              <el-button size="small" :icon="CollectionTag">
                标签
              </el-button>
            </template>
            <div class="tag-selector">
              <div v-for="tag in store.tags" :key="tag.id" class="tag-option">
                <el-checkbox
                  :model-value="note.tags.includes(tag.name)"
                  @change="toggleTag(tag.name)"
                >
                  <el-tag :color="tag.color" style="color: #fff">{{ tag.name }}</el-tag>
                </el-checkbox>
              </div>
              <el-divider style="margin: 8px 0" />
              <div class="add-tag">
                <el-input v-model="newTagName" placeholder="新标签名" size="small" />
                <el-color-picker v-model="newTagColor" size="small" />
                <el-button size="small" @click="addTag">添加</el-button>
              </div>
            </div>
          </el-popover>

          <!-- Save Button -->
          <el-button
            type="primary"
            size="small"
            :icon="Select"
            @click="saveNote"
            :loading="saving"
          >
            {{ saved ? '已保存' : '保存' }}
          </el-button>

          <!-- More Actions -->
          <el-dropdown trigger="click" @command="handleAction">
            <el-button size="small" :icon="MoreFilled" />
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="archive">
                  {{ note.status === 'archived' ? '取消归档' : '归档' }}
                </el-dropdown-item>
                <el-dropdown-item command="delete" divided style="color: #f56c6c">
                  删除笔记
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>

      <el-divider style="margin: 0 0 8px" />

      <!-- Editor + Side Panel -->
      <div class="editor-layout">
        <div class="editor-main">
          <TipTapEditor
            ref="editorRef"
            v-model="note.content"
            v-model:contentText="note.content_text"
            v-model:contentType="note.content_type"
            :editable="true"
            :noteId="note.id"
          />
        </div>

        <!-- Resizable Divider -->
        <div
          class="resize-handle"
          @mousedown="startResize"
        />

        <!-- AI Side Panel -->
        <div class="side-panel" :style="{ width: panelWidth + 'px' }">
          <el-tabs v-model="activeTab" class="side-tabs">
            <el-tab-pane label="写作助手" name="write">
              <AIWritingAssistant
                :noteContent="note.content_text || ''"
                @insert="onInsertToDoc"
              />
            </el-tab-pane>
            <el-tab-pane label="智能问答" name="qa" v-if="note.id">
              <SmartQA :noteId="note.id" />
            </el-tab-pane>
          </el-tabs>
        </div>
      </div>
    </template>

    <!-- Review Dialog -->
    <el-dialog v-model="showReviewDialog" title="间隔复习" width="400px">
      <div class="review-dialog">
        <div v-if="reviewStatus" class="review-info">
          <div class="review-stat">
            <span>复习次数:</span>
            <b>{{ reviewStatus.review_number || 0 }} 次</b>
          </div>
          <div class="review-stat">
            <span>当前间隔:</span>
            <b>{{ reviewStatus.interval || 0 }} 天</b>
          </div>
          <div class="review-stat">
            <span>难度系数:</span>
            <b>{{ (reviewStatus.ease_factor || 2.5).toFixed(2) }}</b>
          </div>
          <el-divider />
          <div class="review-question">这次复习的回忆质量如何？</div>
          <div class="quality-buttons">
            <div
              v-for="score in qualityLevels"
              :key="score.value"
              class="quality-btn"
              :class="{ selected: selectedQuality === score.value }"
              @click="selectedQuality = score.value"
            >
              <div class="quality-score">{{ score.value }}</div>
              <div class="quality-label">{{ score.label }}</div>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="showReviewDialog = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="selectedQuality === null"
          :loading="reviewing"
          @click="submitReview"
        >
          提交评分
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, Clock, CollectionTag, Select, MoreFilled,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useNotesStore } from '../store/notes'
import TipTapEditor from '../components/TipTapEditor.vue'
import AIWritingAssistant from '../components/AIWritingAssistant.vue'
import SmartQA from '../components/SmartQA.vue'

const route = useRoute()
const router = useRouter()
const store = useNotesStore()

const note = ref(null)
const loading = ref(true)
const saving = ref(false)
const saved = ref(true)
const editorRef = ref(null)

// Side panel
const activeTab = ref('write')
const panelWidth = ref(360)

// Review
const showReviewDialog = ref(false)
const reviewStatus = ref(null)
const selectedQuality = ref(null)
const reviewing = ref(false)

const qualityLevels = [
  { value: 0, label: '完全遗忘' },
  { value: 1, label: '错误但眼熟' },
  { value: 2, label: '错误但熟悉' },
  { value: 3, label: '回忆困难' },
  { value: 4, label: '稍有延迟' },
  { value: 5, label: '完美回忆' },
]

const isDue = computed(() => reviewStatus.value?.is_due)

const reviewTooltip = computed(() => {
  if (!reviewStatus.value) return '暂无复习数据'
  if (reviewStatus.value.is_due) return '已到复习时间'
  if (reviewStatus.value.next_review_at) {
    return `下次复习: ${new Date(reviewStatus.value.next_review_at).toLocaleDateString('zh-CN')}`
  }
  return '尚未设置复习'
})

// Tags
const newTagName = ref('')
const newTagColor = ref('#409EFF')

// Auto-save timer
let autoSaveTimer = null
const AUTO_SAVE_DELAY = 3000

async function loadNote(id) {
  loading.value = true
  const data = await store.getNote(id)
  if (data) {
    note.value = data
    saved.value = true
    await loadReviewStatus()
  } else {
    ElMessage.error('笔记不存在')
    router.push('/notes')
  }
  loading.value = false
}

async function loadReviewStatus() {
  if (!note.value) return
  const status = await store.getReviewStatus(note.value.id)
  reviewStatus.value = status
}

function onTitleChange() {
  saved.value = false
  scheduleAutoSave()
}

function scheduleAutoSave() {
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(saveNote, AUTO_SAVE_DELAY)
}

async function saveNote() {
  if (!note.value) return
  saving.value = true
  const result = await store.updateNote(note.value.id, {
    title: note.value.title,
    content: note.value.content,
    content_text: note.value.content_text,
    content_type: note.value.content_type,
    tags: note.value.tags,
  })
  if (result) {
    saved.value = true
  }
  saving.value = false
}

function toggleTag(tagName) {
  const tags = new Set(note.value.tags || [])
  if (tags.has(tagName)) {
    tags.delete(tagName)
  } else {
    tags.add(tagName)
  }
  note.value.tags = Array.from(tags)
  saved.value = false
  scheduleAutoSave()
}

async function addTag() {
  if (!newTagName.value.trim()) return
  await store.createTag(newTagName.value.trim(), newTagColor.value)
  newTagName.value = ''
}

function onInsertToDoc(text) {
  editorRef.value?.insertContent(text)
  saved.value = false
}

async function submitReview() {
  if (selectedQuality.value === null) return
  reviewing.value = true
  const result = await store.submitReview(note.value.id, selectedQuality.value)
  if (result) {
    ElMessage.success(`复习完成！下次复习: ${new Date(result.next_review_at).toLocaleDateString('zh-CN')}`)
    reviewStatus.value = {
      is_due: false,
      next_review_at: result.next_review_at,
      interval: result.interval,
      ease_factor: result.ease_factor,
      review_number: result.review_number,
      quality_score: result.quality_score,
    }
    showReviewDialog.value = false
    selectedQuality.value = null
  }
  reviewing.value = false
}

async function handleAction(command) {
  if (command === 'archive') {
    const newStatus = note.value.status === 'archived' ? 'active' : 'archived'
    await store.updateNote(note.value.id, { status: newStatus })
    note.value.status = newStatus
    ElMessage.success(newStatus === 'archived' ? '已归档' : '已取消归档')
  } else if (command === 'delete') {
    try {
      await ElMessageBox.confirm('确定删除这篇笔记吗？此操作不可撤销。', '警告', {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      })
      const ok = await store.deleteNote(note.value.id)
      if (ok) {
        ElMessage.success('已删除')
        router.push('/notes')
      }
    } catch (e) {
      // cancelled
    }
  }
}

// Resizable panel
let isResizing = false
let startX = 0
let startWidth = 0

function startResize(e) {
  isResizing = true
  startX = e.clientX
  startWidth = panelWidth.value
  document.addEventListener('mousemove', doResize)
  document.addEventListener('mouseup', stopResize)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function doResize(e) {
  if (!isResizing) return
  const delta = startX - e.clientX
  panelWidth.value = Math.max(280, Math.min(600, startWidth + delta))
}

function stopResize() {
  isResizing = false
  document.removeEventListener('mousemove', doResize)
  document.removeEventListener('mouseup', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

onMounted(async () => {
  const id = parseInt(route.params.id)
  if (id) {
    await loadNote(id)
  }
  await store.fetchTags()
})

onBeforeUnmount(() => {
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  if (note.value && !saved.value) {
    saveNote()
  }
})

// Watch for content changes and auto-save
watch(
  () => note.value?.content_text,
  () => {
    if (note.value?.id && !loading.value) {
      saved.value = false
      scheduleAutoSave()
    }
  }
)
</script>

<style scoped>
.note-editor {
  height: calc(100vh - 60px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.loading {
  padding: 40px;
}

.title-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
}

.title-left {
  display: flex;
  align-items: center;
  flex: 1;
  gap: 8px;
}

.title-input {
  font-size: 20px;
  font-weight: 600;
}

.title-input :deep(.el-input__inner) {
  border: none;
  font-size: 20px;
  font-weight: 600;
  height: 40px;
}

.title-input :deep(.el-input__inner):focus {
  border: none;
  box-shadow: none;
}

.title-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.editor-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.editor-main {
  flex: 1;
  overflow: hidden;
  padding: 0 16px 16px;
}

.resize-handle {
  width: 4px;
  cursor: col-resize;
  background: transparent;
  transition: background 0.2s;
  flex-shrink: 0;
}

.resize-handle:hover {
  background: #409eff;
}

.side-panel {
  flex-shrink: 0;
  border-left: 1px solid #dcdfe6;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.side-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.side-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow: hidden;
}

.side-tabs :deep(.el-tab-pane) {
  height: 100%;
  overflow-y: auto;
}

.tag-selector {
  padding: 8px;
}

.tag-option {
  margin-bottom: 6px;
}

.add-tag {
  display: flex;
  gap: 4px;
  align-items: center;
}

.review-dialog {
  padding: 8px 0;
}

.review-stat {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 14px;
}

.review-question {
  margin: 12px 0;
  font-weight: 600;
}

.quality-buttons {
  display: flex;
  gap: 6px;
}

.quality-btn {
  flex: 1;
  text-align: center;
  padding: 8px 4px;
  border: 2px solid #dcdfe6;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.quality-btn:hover {
  border-color: #409eff;
  background: #ecf5ff;
}

.quality-btn.selected {
  border-color: #409eff;
  background: #409eff;
  color: #fff;
}

.quality-score {
  font-size: 18px;
  font-weight: bold;
}

.quality-label {
  font-size: 10px;
  margin-top: 2px;
}
</style>
