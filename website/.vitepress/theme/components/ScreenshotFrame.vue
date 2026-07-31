<script setup lang="ts">
import { computed } from 'vue'
import { withBase } from 'vitepress'

const props = defineProps<{
  src: string
  alt: string
  caption?: string
  eager?: boolean
}>()

const resolvedSource = computed(() => {
  if (/^(?:https?:)?\/\//.test(props.src) || props.src.startsWith('data:')) return props.src
  return withBase(props.src.startsWith('/') ? props.src : `/${props.src}`)
})
</script>

<template>
  <figure class="screenshot-frame">
    <div class="screenshot-frame__chrome" aria-hidden="true">
      <span></span><span></span><span></span>
      <div class="screenshot-frame__address">PressRoom</div>
    </div>
    <img
      :src="resolvedSource"
      :alt="alt"
      :loading="eager ? 'eager' : 'lazy'"
      :fetchpriority="eager ? 'high' : 'auto'"
      decoding="async"
    />
    <figcaption v-if="caption">{{ caption }}</figcaption>
  </figure>
</template>
