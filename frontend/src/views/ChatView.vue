<script setup lang="ts">
import { onMounted, ref } from 'vue'
import Icon from '../components/Icon.vue'
import ChatWorkspace from '../components/ChatWorkspace.vue'
import { useChat } from '../composables/useChat'
import { fmtRelative as timeAgo } from '../lib/format'

const chat = useChat()
const confirmDelete = ref('')

onMounted(() => {
  if (!chat.config.value) void chat.init()
  else void chat.refreshSessions()
})

async function remove(id: string) {
  if (confirmDelete.value !== id) {
    confirmDelete.value = id
    return
  }
  confirmDelete.value = ''
  await chat.removeSession(id)
}
</script>

<template>
  <div class="chat-page">
    <aside class="chat-page__side">
      <div class="chat-page__side-head">
        <span class="chat-page__side-title">会话</span>
        <button class="icon-btn" type="button" title="新对话" aria-label="新对话" @click="chat.newSession()">
          <Icon name="plus" />
        </button>
      </div>
      <button
        class="chat-page__new"
        :class="{ 'chat-page__session--active': !chat.activeSessionId.value }"
        type="button"
        @click="chat.newSession()"
      >
        <Icon name="plus" :size="12" /> 新对话
      </button>
      <div
        v-for="s in chat.sessions.value"
        :key="s.session_id"
        class="chat-page__session"
        :class="{ 'chat-page__session--active': s.session_id === chat.activeSessionId.value }"
        role="button"
        tabindex="0"
        @click="chat.selectSession(s.session_id)"
        @keydown.enter="chat.selectSession(s.session_id)"
      >
        <div class="chat-page__session-main">
          <span class="chat-page__session-title">{{ s.title || '未命名会话' }}</span>
          <span class="chat-page__session-meta">{{ timeAgo(s.updated_at) }}</span>
        </div>
        <button
          class="icon-btn chat-page__session-del"
          :class="{ 'chat-page__session-del--confirm': confirmDelete === s.session_id }"
          type="button"
          :title="confirmDelete === s.session_id ? '再次点击确认删除' : '删除会话'"
          :aria-label="'删除会话'"
          @click.stop="remove(s.session_id)"
        >
          <Icon name="trash" :size="13" />
        </button>
      </div>
      <p v-if="!chat.sessions.value.length" class="chat-page__empty muted">暂无会话</p>
    </aside>
    <main class="chat-page__main">
      <div v-if="chat.config.value?.enabled === false" class="chat-page__off muted">
        AI 对话未启用（chat.mode = off）。
      </div>
      <ChatWorkspace v-else mode="page" />
    </main>
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  height: calc(100vh - var(--topbar-height) - 2 * var(--sp-5));
  min-height: 420px;
  border: 1px solid var(--border);
  border-radius: var(--r-card);
  overflow: hidden;
  background: var(--panel);
}
.chat-page__side {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  overflow-y: auto;
  padding: var(--sp-2);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  background: var(--surface-faint);
}
.chat-page__side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--sp-1);
}
.chat-page__side-title {
  font-weight: 600;
  font-size: var(--fs-label);
}
.chat-page__new {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  border: 1px dashed var(--border);
  background: none;
  color: var(--text-2);
  border-radius: var(--r-ctl);
  padding: var(--sp-2);
  cursor: pointer;
  font-size: var(--fs-label);
  text-align: left;
}
.chat-page__new:hover {
  border-color: var(--control-border-hover);
}
.chat-page__session {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  border-radius: var(--r-ctl);
  padding: var(--sp-2);
  cursor: pointer;
  border: 1px solid transparent;
}
.chat-page__session:hover {
  background: var(--surface-hover);
}
.chat-page__session--active {
  background: var(--surface-hover);
  border-color: var(--accent-line);
}
.chat-page__session-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.chat-page__session-title {
  font-size: var(--fs-label);
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-page__session-meta {
  font-size: var(--fs-caption);
  color: var(--text-3);
}
.chat-page__session-del {
  visibility: hidden;
}
.chat-page__session:hover .chat-page__session-del,
.chat-page__session-del--confirm {
  visibility: visible;
}
.chat-page__session-del--confirm {
  color: var(--st-fail-text);
}
.chat-page__empty {
  padding: var(--sp-2);
  font-size: var(--fs-caption);
}
.chat-page__main {
  flex: 1;
  min-width: 0;
}
.chat-page__off {
  padding: var(--sp-5);
  text-align: center;
}
</style>
