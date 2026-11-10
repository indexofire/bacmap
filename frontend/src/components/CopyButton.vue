<script setup lang="ts">
import Icon from './Icon.vue'
import { useToast } from '../composables/useToast'

const props = withDefaults(defineProps<{ value: string; label?: string }>(), {
  label: 'ID',
})
const toast = useToast()

async function copy() {
  try {
    await navigator.clipboard.writeText(props.value)
    toast.ok('已复制到剪贴板')
  } catch {
    toast.err('复制失败，请手动选择文本')
  }
}
</script>

<template>
  <button
    class="icon-btn"
    type="button"
    :aria-label="`复制${label}`"
    :title="`复制${label}`"
    @click.stop="copy"
  >
    <Icon name="copy" :size="14" />
  </button>
</template>
