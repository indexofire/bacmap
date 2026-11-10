<script setup lang="ts">
import Icon from './Icon.vue'
import { useToast } from '../composables/useToast'

const toast = useToast()
</script>

<template>
  <div class="toast-stack" aria-live="polite" aria-atomic="false">
    <div
      v-for="item in toast.items"
      :key="item.id"
      class="toast"
      :class="`toast--${item.kind}`"
      role="status"
    >
      <Icon
        :name="item.kind === 'ok' ? 'check-circle' : item.kind === 'err' ? 'x-circle' : 'alert-circle'"
      />
      <span>{{ item.message }}</span>
      <button
        class="icon-btn toast__close"
        type="button"
        aria-label="关闭通知"
        title="关闭通知"
        @click="toast.dismiss(item.id)"
      >
        <Icon name="x" :size="12" />
      </button>
    </div>
  </div>
</template>
