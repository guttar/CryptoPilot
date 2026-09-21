<template>
  <div class="notes-list">
    <!-- Header -->
    <div class="list-header">
      <h2>笔记</h2>
      <div class="header-actions">
        <el-button type="primary" @click="createNewNote">
          <el-icon><Plus /></el-icon> 新建笔记
        </el-button>
        <el-button @click="$router.push('/notes/review')">
          <el-icon><Clock /></el-icon> 复习
          <el-tag v-if="dueCount > 0" type="danger" size="small" style="margin-left: 4px">
            {{ dueCount }}
          </el-tag>
        </el-button>
      </div>
    </div>

    <!-- Filters -->
    <div class="filter-bar">
      <el-input
        v-model="searchQuery"
        placeholder="搜索笔记…"
        prefix-icon="Search"
        clearable
        class="search-input"
        @input="debouncedSearch"
      />
      <el-select
        v-model="tagFilter"
        placeholder="按标签筛选"
        clearable
        style="width: 150px"
        @change="fetchData"
      >
        <el-option
          v-for="tag in store.tags"
          :key="tag.id"
          :label="tag.name"
          :value="tag.name"
        >
          <span>{{ tag.name }}</span>
        </el-option>
      </el-select>
      <el-select
        v-model="statusFilter"
        placeholder="状态"
        clearable
        style="width: 110px"
        @change="fetchData"
      >
        <el-option label="活跃" value="active" />
        <el-option label="归档" value="archived" />
      </el-select>
    </div>

    <!-- Loading -->
    <div v-if="store.loading" class="loading-state">
      <el-skeleton :rows="3" animated />
    </div>

    <!-- Notes Grid -->
    <div v-else-if="store.notes.length === 0" class="empty-state">
      <el-empty description="还没有笔记，开始写第一篇吧">
        <el-button type="primary" @click="createNewNote">新建笔记</el-button>
      </el-empty>
    </div>

    <div v-else class="notes-grid">
      <el-card
        v-for="note in store.notes"
        :key="note.id"
        shadow="hover"
        class="note-card"
        @click="$router.push(`/notes/${note.id}`)"
      >
        <div class="card-header">
          <div class="card-title">{{ note.title }}</div>
          <el-tag v-if="note.is_due" type="danger" size="small" effect="dark">
            待复习
          </el-tag>
        </div>
        <div class="card-preview">
          {{ note.content_text ? note.content_text.substring(0, 120) : '空笔记' }}
        </div>
        <div class="card-footer">
          <div class="card-tags">
            <el-tag
              v-for="tag in (note.tags || [])"
              :key="tag"
              size="small"
              style="margin-right: 4px"
            >
              {{ tag }}
            </el-tag>
          </div>
          <span class="card-date">{{ formatDate(note.updated_at) }}</span>
        </div>
      </el-card>
    </div>

    <!-- Pagination -->
    <div class="pagination" v-if="store.total > 20">
      <el-pagination
        background
        layout="prev, pager, next"
        :total="store.total"
        :page-size="pageSize"
        v-model:current-page="currentPage"
        @current-change="onPageChange"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Clock, Search } from '@element-plus/icons-vue'
import { useNotesStore } from '../store/notes'

const router = useRouter()
const store = useNotesStore()

const searchQuery = ref('')
const tagFilter = ref('')
const statusFilter = ref('active')
const currentPage = ref(1)
const pageSize = ref(20)
const dueCount = ref(0)

let debounceTimer = null

function debouncedSearch() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    currentPage.value = 1
    fetchData()
  }, 300)
}

function fetchData() {
  const params = {
    skip: (currentPage.value - 1) * pageSize.value,
    limit: pageSize.value,
    status: statusFilter.value || undefined,
    tag: tagFilter.value || undefined,
    search: searchQuery.value || undefined,
  }
  store.fetchNotes(params)
}

async function fetchDueCount() {
  const due = await store.fetchDueNotes(999)
  dueCount.value = due.length
}

function onPageChange(page) {
  currentPage.value = page
  fetchData()
}

async function createNewNote() {
  const note = await store.createNote({ title: '新笔记' })
  if (note) {
    router.push(`/notes/${note.id}`)
  }
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now - d
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  if (days === 0) {
    const hours = Math.floor(diff / (1000 * 60 * 60))
    if (hours === 0) return '刚刚'
    return `${hours} 小时前`
  }
  if (days < 7) return `${days} 天前`
  return d.toLocaleDateString('zh-CN')
}

onMounted(() => {
  store.fetchTags()
  fetchData()
  fetchDueCount()
})
</script>

<style scoped>
.notes-list {
  padding: 20px;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.list-header h2 {
  margin: 0;
  font-size: 22px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.search-input {
  width: 240px;
}

.notes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.note-card {
  cursor: pointer;
  transition: transform 0.15s;
}

.note-card:hover {
  transform: translateY(-2px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.card-title {
  font-weight: 600;
  font-size: 15px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 8px;
}

.card-preview {
  font-size: 13px;
  color: #666;
  line-height: 1.5;
  margin-bottom: 12px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

.card-date {
  font-size: 12px;
  color: #999;
  white-space: nowrap;
}

.pagination {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}

.loading-state {
  padding: 40px;
}

.empty-state {
  padding: 60px 0;
  display: flex;
  justify-content: center;
}
</style>
