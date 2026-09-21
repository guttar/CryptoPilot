<template>
  <div class="tiptap-editor" @keydown.tab.prevent="onTab">
    <!-- Toolbar -->
    <div class="editor-toolbar" v-if="editable">
      <div class="toolbar-group">
        <el-tooltip content="标题 1" placement="bottom">
          <el-button size="small" text @click="toggleHeading(1)" :class="{ active: editor?.isActive('heading', { level: 1 }) }">
            <b>H1</b>
          </el-button>
        </el-tooltip>
        <el-tooltip content="标题 2" placement="bottom">
          <el-button size="small" text @click="toggleHeading(2)" :class="{ active: editor?.isActive('heading', { level: 2 }) }">
            <b>H2</b>
          </el-button>
        </el-tooltip>
        <el-tooltip content="标题 3" placement="bottom">
          <el-button size="small" text @click="toggleHeading(3)" :class="{ active: editor?.isActive('heading', { level: 3 }) }">
            <b>H3</b>
          </el-button>
        </el-tooltip>
      </div>
      <el-divider direction="vertical" />
      <div class="toolbar-group">
        <el-tooltip content="粗体" placement="bottom">
          <el-button size="small" text @click="editor?.chain().focus().toggleBold().run()" :class="{ active: editor?.isActive('bold') }">
            <b>B</b>
          </el-button>
        </el-tooltip>
        <el-tooltip content="斜体" placement="bottom">
          <el-button size="small" text @click="editor?.chain().focus().toggleItalic().run()" :class="{ active: editor?.isActive('italic') }">
            <i>I</i>
          </el-button>
        </el-tooltip>
        <el-tooltip content="下划线" placement="bottom">
          <el-button size="small" text @click="editor?.chain().focus().toggleUnderline().run()" :class="{ active: editor?.isActive('underline') }">
            <u>U</u>
          </el-button>
        </el-tooltip>
        <el-tooltip content="删除线" placement="bottom">
          <el-button size="small" text @click="editor?.chain().focus().toggleStrike().run()" :class="{ active: editor?.isActive('strike') }">
            <s>S</s>
          </el-button>
        </el-tooltip>
      </div>
      <el-divider direction="vertical" />
      <div class="toolbar-group">
        <el-tooltip content="无序列表" placement="bottom">
          <el-button size="small" text @click="editor?.chain().focus().toggleBulletList().run()" :class="{ active: editor?.isActive('bulletList') }">
            <el-icon><List /></el-icon>
          </el-button>
        </el-tooltip>
        <el-tooltip content="有序列表" placement="bottom">
          <el-button size="small" text @click="editor?.chain().focus().toggleOrderedList().run()" :class="{ active: editor?.isActive('orderedList') }">
            1.
          </el-button>
        </el-tooltip>
        <el-tooltip content="任务列表" placement="bottom">
          <el-button size="small" text @click="editor?.chain().focus().toggleTaskList().run()" :class="{ active: editor?.isActive('taskList') }">
            ☑
          </el-button>
        </el-tooltip>
        <el-tooltip content="引用" placement="bottom">
          <el-button size="small" text @click="editor?.chain().focus().toggleBlockquote().run()" :class="{ active: editor?.isActive('blockquote') }">
            "
          </el-button>
        </el-tooltip>
        <el-tooltip content="代码块" placement="bottom">
          <el-button size="small" text @click="editor?.chain().focus().toggleCodeBlock().run()" :class="{ active: editor?.isActive('codeBlock') }">
            &lt;/&gt;
          </el-button>
        </el-tooltip>
      </div>
      <el-divider direction="vertical" />
      <div class="toolbar-group">
        <el-tooltip content="插入链接" placement="bottom">
          <el-button size="small" text @click="setLink">
            <el-icon><LinkIcon /></el-icon>
          </el-button>
        </el-tooltip>
        <el-tooltip content="插入图片" placement="bottom">
          <el-button size="small" text @click="addImage">
            <el-icon><Picture /></el-icon>
          </el-button>
        </el-tooltip>
      </div>
      <el-divider direction="vertical" />
      <div class="toolbar-group">
        <el-tooltip content="撤销" placement="bottom">
          <el-button size="small" text @click="editor?.chain().focus().undo().run()">
            <el-icon><RefreshLeft /></el-icon>
          </el-button>
        </el-tooltip>
        <el-tooltip content="重做" placement="bottom">
          <el-button size="small" text @click="editor?.chain().focus().redo().run()">
            <el-icon><RefreshRight /></el-icon>
          </el-button>
        </el-tooltip>
      </div>
      <div style="flex: 1" />
      <el-switch
        v-model="isMarkdown"
        active-text="Markdown"
        inactive-text="富文本"
        size="small"
        @change="toggleMode"
      />
    </div>

    <!-- Editor Content -->
    <div class="editor-content" ref="editorContainer">
      <editor-content :editor="editor" />
    </div>

    <!-- AI Completion overlay (teleported to editor container) -->
    <div
      v-if="showCompletion && completionText"
      class="completion-overlay"
      :style="completionStyle"
    >
      <span class="completion-text">{{ completionText }}</span>
      <span class="completion-hint">Tab 采纳 · Esc 拒绝</span>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onBeforeUnmount, nextTick, computed } from 'vue'
import { useEditor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import Placeholder from '@tiptap/extension-placeholder'
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight'
import { createLowlight, common } from 'lowlight'
import { ElMessage, ElMessageBox } from 'element-plus'
import { List, Link as LinkIcon, Picture, RefreshLeft, RefreshRight } from '@element-plus/icons-vue'
import api from '../api'

const lowlight = createLowlight(common)

const props = defineProps({
  modelValue: { type: Object, default: null },
  contentText: { type: String, default: '' },
  editable: { type: Boolean, default: true },
  contentType: { type: String, default: 'rich_text' },
  noteId: { type: Number, default: null },
})

const emit = defineEmits(['update:modelValue', 'update:contentText', 'update:contentType'])

const editorContainer = ref(null)
const isMarkdown = ref(props.contentType === 'markdown')
const showCompletion = ref(false)
const completionText = ref('')
const completionStyle = ref({})
let completionTimer = null

// ── Editor Setup ────────────────────────────────────────────────────

const editor = useEditor({
  content: props.modelValue || '',
  editable: props.editable,
  extensions: [
    StarterKit.configure({
      heading: { levels: [1, 2, 3] },
      codeBlock: false,
    }),
    Underline,
    Link.configure({
      openOnClick: true,
      HTMLAttributes: { rel: 'noopener noreferrer', target: '_blank' },
    }),
    Image.configure({ inline: false }),
    TaskList,
    TaskItem.configure({ nested: true, HTMLAttributes: { class: 'task-item' } }),
    Placeholder.configure({ placeholder: '开始写作…' }),
    CodeBlockLowlight.configure({ lowlight }),
  ],
  editorProps: {
    attributes: {
      class: 'prose prose-sm max-w-none focus:outline-none min-h-[400px] p-4',
    },
    handleKeyDown: (view, event) => {
      if (event.key === 'Tab' && showCompletion.value && completionText.value) {
        event.preventDefault()
        acceptCompletion()
        return true
      }
      if (event.key === 'Escape' && showCompletion.value) {
        dismissCompletion()
        return true
      }
      return false
    },
  },
  onUpdate: ({ editor: ed }) => {
    const json = ed.getJSON()
    const text = ed.getText()
    emit('update:modelValue', json)
    emit('update:contentText', text)
    triggerCompletion(text)
  },
  onSelectionUpdate: () => {
    // Cancel completion on selection change
    if (showCompletion.value) {
      dismissCompletion()
    }
  },
})

function toggleHeading(level) {
  editor.value?.chain().focus().toggleHeading({ level }).run()
}

function setLink() {
  if (!editor.value) return
  const previousUrl = editor.value.getAttributes('link').href
  ElMessageBox.prompt('输入链接 URL', '插入链接', {
    inputValue: previousUrl || 'https://',
    inputType: 'url',
  }).then(({ value }) => {
    if (value === null) return
    if (value === '') {
      editor.value.chain().focus().extendMarkRange('link').unsetLink().run()
      return
    }
    editor.value.chain().focus().extendMarkRange('link').setLink({ href: value }).run()
  }).catch(() => {})
}

function addImage() {
  if (!editor.value) return
  ElMessageBox.prompt('输入图片 URL', '插入图片', {
    inputValue: 'https://',
    inputType: 'url',
  }).then(({ value }) => {
    if (value) {
      editor.value.chain().focus().setImage({ src: value }).run()
    }
  }).catch(() => {})
}

function toggleMode(val) {
  emit('update:contentType', val ? 'markdown' : 'rich_text')
  // Re-set content - in markdown mode we could use the text content
  ElMessage.info(val ? '已切换到 Markdown 模式' : '已切换到富文本模式')
}

// ── AI Inline Completion ────────────────────────────────────────────

function triggerCompletion(text) {
  if (completionTimer) clearTimeout(completionTimer)
  dismissCompletion()

  const trimmed = text.trim()
  if (trimmed.length < 3) return

  completionTimer = setTimeout(async () => {
    try {
      const res = await api.post('/notes/ai/complete', {
        text_before_cursor: text,
        content_type: isMarkdown.value ? 'markdown' : 'rich_text',
      })
      if (res.data.completion) {
        completionText.value = res.data.completion
        showCompletion.value = true
        updateCompletionPosition()
      }
    } catch (e) {
      // Silently fail for completion
    }
  }, 1500)
}

function updateCompletionPosition() {
  // Position at the end of the editor content
  nextTick(() => {
    if (editorContainer.value) {
      const rect = editorContainer.value.getBoundingClientRect()
      completionStyle.value = {
        top: `${rect.height - 40}px`,
        left: '20px',
      }
    }
  })
}

function acceptCompletion() {
  if (!editor.value || !completionText.value) return
  editor.value.commands.insertContent(completionText.value)
  dismissCompletion()
}

function dismissCompletion() {
  showCompletion.value = false
  completionText.value = ''
}

function onTab() {
  // Handled in handleKeyDown
}

// ── Expose methods for parent ───────────────────────────────────────

function insertContent(text) {
  editor.value?.commands.insertContent(text)
}

function getText() {
  return editor.value?.getText() || ''
}

function getJSON() {
  return editor.value?.getJSON() || {}
}

defineExpose({ insertContent, getText, getJSON })

// ── Lifecycle ───────────────────────────────────────────────────────

onBeforeUnmount(() => {
  if (completionTimer) clearTimeout(completionTimer)
  editor.value?.destroy()
})
</script>

<style scoped>
.tiptap-editor {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fff;
}

.editor-toolbar {
  display: flex;
  align-items: center;
  padding: 4px 8px;
  border-bottom: 1px solid #dcdfe6;
  background: #fafafa;
  flex-wrap: wrap;
  gap: 2px;
}

.toolbar-group {
  display: flex;
  align-items: center;
  gap: 2px;
}

.editor-toolbar .el-button.is-text.active {
  background-color: #e6f1fe;
  color: #409eff;
}

.editor-content {
  flex: 1;
  overflow-y: auto;
  position: relative;
  min-height: 400px;
}

.completion-overlay {
  position: absolute;
  color: #999;
  font-style: italic;
  pointer-events: none;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 8px;
}

.completion-text {
  opacity: 0.6;
}

.completion-hint {
  font-size: 11px;
  color: #409eff;
  background: #ecf5ff;
  padding: 1px 6px;
  border-radius: 3px;
  pointer-events: auto;
}

:deep(.ProseMirror) {
  min-height: 400px;
  padding: 16px;
  outline: none;
}

:deep(.ProseMirror p.is-editor-empty:first-child::before) {
  content: attr(data-placeholder);
  float: left;
  color: #adb5bd;
  pointer-events: none;
  height: 0;
}

:deep(.ProseMirror pre) {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 4px;
  font-family: 'Fira Code', monospace;
}

:deep(.ProseMirror blockquote) {
  border-left: 3px solid #409eff;
  padding-left: 12px;
  color: #666;
  margin: 8px 0;
}

:deep(.ProseMirror ul),
:deep(.ProseMirror ol) {
  padding-left: 24px;
}

:deep(.ProseMirror img) {
  max-width: 100%;
  border-radius: 4px;
}

:deep(.ProseMirror a) {
  color: #409eff;
  text-decoration: underline;
}
</style>
