<script setup lang="ts">
import Icon from './Icon.vue'

withDefaults(
  defineProps<{
    title: string
    hint?: string
    icon?: string
  }>(),
  { icon: 'file-text' },
)
</script>

<template>
  <div class="empty">
    <Icon :name="icon" />
    <h3 class="empty__title">{{ title }}</h3>
    <p v-if="hint" class="empty__hint">{{ hint }}</p>
    <slot />
  </div>
</template>
