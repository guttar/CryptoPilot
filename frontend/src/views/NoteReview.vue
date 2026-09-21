<template>
  <div class="note-review">
    <div class="review-header">
      <h2>间隔复习</h2>
      <div class="review-progress" v-if="dueNotes.length > 0">
        剩余 <b>{{ dueNotes.length - currentIndex }}</b> / {{ dueNotes.length }}
      </div>
    </div>

    <!-- Empty State -->
    <div v-if="dueNotes.length === 0" class="empty-state">
      <el-icon style="font-size: 48px; color: #67c23a"><SuccessFilled /></el-icon>
      <h3>太棒了！没有待复习的笔记</h3>
      <p>所有笔记都已按时复习，下次再来检查吧</p>
      <el-button type="primary" @click="$router.push('/notes')">返回笔记列表</el-button>
    </div>

    <!-- Review Card -->
    <div v-else-if="currentNote" class="review-card-container">
      <el-card class="review-card" shadow="always">
        <!-- Front -->
        <div v-if="!showAnswer" class="card-face front">
          <div class="card-title">{{ currentNote.title }}</div>
          <el-divider />
          <div class="card-content">{{ previewText }}</div>
          <el-divider />
          <el-button type="primary" size="large" @click="showAnswer = true" style="width: 100%">
            显示答案 / 自我评估
          </el-button>
        </div>

        <!-- Back (Answer + Quality Rating) -->
        <div v-else class="card-face back">
          <div class="card-title">{{ currentNote.title }}</div>
          <el-divider />
          <div class="card-content-full">{{ currentNote.content_text || '(无详细内容)' }}</div>
          <el-divider />
          <div class="quality-label">回忆质量评分</div>
          <div class="quality-buttons">
            <div
              v-for="level in qualityLevels"
              :key="level.value"
              class="quality-btn"
              :class="{
                selected: selectedQuality === level.value,
                perfect: level.value >= 4,
                good: level.value === 3,
                poor: level.value <= 2,
              }"
              @click="submitRating(level.value)"
            >
              <div class="quality-score">{{ level.value }}</div>
              <div class="quality-desc">{{ level.label }}</div>
            </div>
          </div>
          <div class="quality-hint">
            <span>0-2: 不记得或记错</span>
            <span>3-5: 逐渐回忆正确</span>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { SuccessFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useNotesStore } from '../store/notes'

const store = useNotesStore()

const dueNotes = ref([])
const currentIndex = ref(0)
const showAnswer = ref(false)
const selectedQuality = ref(null)
const submitting = ref(false)

const qualityLevels = [
  { value: 0, label: '完全遗忘' },
  { value: 1, label: '错误但眼熟' },
  { value: 2, label: '错误但熟悉' },
  { value: 3, label: '回忆困难' },
  { value: 4, label: '稍有延迟' },
  { value: 5, label: '完美回忆' },
]

const currentNote = computed(() => {
  return dueNotes.value[currentIndex.value] || null
})

const previewText = computed(() => {
  if (!currentNote.value?.content_text) return ''
  const text = currentNote.value.content_text
  return text.length > 500 ? text.substring(0, 500) + '…' : text
})

async function loadDueNotes() {
  dueNotes.value = await store.fetchDueNotes(50)
  currentIndex.value = 0
  showAnswer.value = false
}

async function submitRating(score) {
  if (submitting.value || !currentNote.value) return
  submitting.value = true
  selectedQuality.value = score

  const result = await store.submitReview(currentNote.value.id, score)
  if (result) {
    const interval = result.interval
    ElMessage.success(
      score >= 3
        ? `回答正确！下次复习在 ${interval} 天后`
        : `已重置，明天再来复习`
    )
  }

  submitting.value = false
  nextCard()
}

function nextCard() {
  if (currentIndex.value < dueNotes.value.length - 1) {
    currentIndex.value++
    showAnswer.value = false
    selectedQuality.value = null
  } else {
    ElMessage.success('本轮复习完成！')
    dueNotes.value = []
  }
}

onMounted(() => {
  loadDueNotes()
})
</script>

<style scoped>
.note-review {
  max-width: 720px;
  margin: 0 auto;
  padding: 40px 20px;
}

.review-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.review-header h2 {
  margin: 0;
}

.review-progress {
  font-size: 14px;
  color: #909399;
}

.empty-state {
  text-align: center;
  padding: 80px 0;
}

.empty-state h3 {
  margin: 16px 0 8px;
}

.empty-state p {
  color: #909399;
  margin-bottom: 24px;
}

.review-card-container {
  display: flex;
  justify-content: center;
}

.review-card {
  width: 100%;
  min-height: 400px;
}

.card-face {
  padding: 20px;
}

.card-title {
  font-size: 20px;
  font-weight: 600;
  text-align: center;
}

.card-content {
  font-size: 15px;
  line-height: 1.8;
  color: #606266;
  text-align: center;
  padding: 20px 0;
}

.card-content-full {
  font-size: 14px;
  line-height: 1.8;
  color: #303133;
  max-height: 300px;
  overflow-y: auto;
  padding: 12px 0;
}

.quality-label {
  text-align: center;
  font-weight: 600;
  margin-bottom: 16px;
  font-size: 15px;
}

.quality-buttons {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.quality-btn {
  flex: 1;
  text-align: center;
  padding: 12px 4px;
  border: 2px solid #dcdfe6;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.quality-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.quality-btn.poor:hover {
  border-color: #f56c6c;
  background: #fef0f0;
}

.quality-btn.good:hover {
  border-color: #e6a23c;
  background: #fdf6ec;
}

.quality-btn.perfect:hover {
  border-color: #67c23a;
  background: #f0f9eb;
}

.quality-btn.selected {
  border-color: #409eff;
  background: #409eff;
  color: #fff;
}

.quality-score {
  font-size: 22px;
  font-weight: bold;
}

.quality-desc {
  font-size: 11px;
  margin-top: 4px;
}

.quality-hint {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #909399;
}
</style>
