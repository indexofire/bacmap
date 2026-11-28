<script setup lang="ts">
import { useChat } from '../composables/useChat'
import ChatWorkspace from './ChatWorkspace.vue'

const chat = useChat()
</script>

<template>
  <Teleport to="body">
    <div
      v-if="chat.drawerOpen.value"
      class="chat-scrim"
      aria-hidden="true"
      @click="chat.setDrawer(false)"
    />
    <aside v-if="chat.drawerOpen.value" class="chat-drawer" aria-label="AI 助手">
      <ChatWorkspace mode="drawer" @close="chat.setDrawer(false)" />
    </aside>
  </Teleport>
</template>

<style scoped>
.chat-drawer {
  position: fixed;
  top: var(--topbar-height);
  right: 0;
  bottom: 0;
  width: min(460px, 92vw);
  z-index: 60;
  border-left: 1px solid var(--border);
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.18);
  background: var(--panel);
}
.chat-scrim {
  display: none;
}
@media (max-width: 1199px) {
  .chat-scrim {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 59;
    background: rgba(0, 0, 0, 0.25);
  }
  .chat-drawer {
    top: 0;
  }
}
</style>
