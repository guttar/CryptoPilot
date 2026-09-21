import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const useNotesStore = defineStore('notes', () => {
  const notes = ref([])
  const currentNote = ref(null)
  const dueNotes = ref([])
  const tags = ref([])
  const loading = ref(false)
  const total = ref(0)

  // ── CRUD ──────────────────────────────────────────────────────────

  async function fetchNotes(params = {}) {
    loading.value = true
    try {
      const res = await api.get('/notes/', { params })
      notes.value = res.data.items
      total.value = res.data.total
    } catch (e) {
      console.error('Failed to fetch notes:', e)
      notes.value = []
    } finally {
      loading.value = false
    }
  }

  async function getNote(id) {
    loading.value = true
    try {
      const res = await api.get(`/notes/${id}`)
      currentNote.value = res.data
      return res.data
    } catch (e) {
      console.error('Failed to get note:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  async function createNote(data = {}) {
    loading.value = true
    try {
      const res = await api.post('/notes/', data)
      return res.data
    } catch (e) {
      console.error('Failed to create note:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  async function updateNote(id, data) {
    try {
      const res = await api.put(`/notes/${id}`, data)
      if (currentNote.value && currentNote.value.id === id) {
        currentNote.value = res.data
      }
      return res.data
    } catch (e) {
      console.error('Failed to update note:', e)
      return null
    }
  }

  async function deleteNote(id) {
    try {
      await api.delete(`/notes/${id}`)
      notes.value = notes.value.filter(n => n.id !== id)
      return true
    } catch (e) {
      console.error('Failed to delete note:', e)
      return false
    }
  }

  // ── Tags ──────────────────────────────────────────────────────────

  async function fetchTags() {
    try {
      const res = await api.get('/notes/tags/list')
      tags.value = res.data
    } catch (e) {
      console.error('Failed to fetch tags:', e)
    }
  }

  async function createTag(name, color = '#409EFF') {
    try {
      const res = await api.post('/notes/tags', { name, color })
      tags.value.push(res.data)
      return res.data
    } catch (e) {
      console.error('Failed to create tag:', e)
      return null
    }
  }

  // ── Spaced Repetition ─────────────────────────────────────────────

  async function submitReview(id, qualityScore) {
    try {
      const res = await api.post(`/notes/${id}/review`, { quality_score: qualityScore })
      return res.data
    } catch (e) {
      console.error('Failed to submit review:', e)
      return null
    }
  }

  async function getReviewStatus(id) {
    try {
      const res = await api.get(`/notes/${id}/review-status`)
      return res.data
    } catch (e) {
      console.error('Failed to get review status:', e)
      return null
    }
  }

  async function fetchDueNotes(limit = 20) {
    try {
      const res = await api.get('/notes/review/due', { params: { limit } })
      dueNotes.value = res.data
      return res.data
    } catch (e) {
      console.error('Failed to fetch due notes:', e)
      return []
    }
  }

  // ── KB Links ──────────────────────────────────────────────────────

  async function getKbLinks(noteId) {
    try {
      const res = await api.get(`/notes/${noteId}/kb-links`)
      return res.data
    } catch (e) {
      console.error('Failed to get KB links:', e)
      return []
    }
  }

  return {
    notes,
    currentNote,
    dueNotes,
    tags,
    loading,
    total,
    fetchNotes,
    getNote,
    createNote,
    updateNote,
    deleteNote,
    fetchTags,
    createTag,
    submitReview,
    getReviewStatus,
    fetchDueNotes,
    getKbLinks,
  }
})
