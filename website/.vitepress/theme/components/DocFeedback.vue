<script setup lang="ts">
import { computed } from 'vue'
import { useData, useRoute } from 'vitepress'

const REPOSITORY_ISSUES_URL = 'https://github.com/jaminmei/Pressroom/issues/new'
const PUBLISHED_SITE_URL = 'https://jaminmei.github.io/Pressroom'

const { frontmatter, lang, page } = useData()
const route = useRoute()

const isChinese = computed(() => lang.value.toLowerCase().startsWith('zh'))
const isVisible = computed(
  () => frontmatter.value.layout !== 'home' && frontmatter.value.feedback !== false && page.value.relativePath !== '404.md'
)

const normalizedPath = computed(() => {
  const path = route.path.replace(/^\/Pressroom(?=\/|$)/, '') || '/'
  return path.startsWith('/') ? path : `/${path}`
})

const pageUrl = computed(() => `${PUBLISHED_SITE_URL}${normalizedPath.value}`)

const issueUrl = computed(() => {
  const locale = isChinese.value ? 'zh-CN' : 'en'
  const title = `[Docs] ${page.value.title || 'Documentation'} (${locale})`
  const body = isChinese.value
    ? [
        '### 文档页面',
        '',
        `- 页面：${pageUrl.value}`,
        `- 语言：${locale}`,
        '',
        '### 需要改进的内容',
        '',
        '<!-- 请描述不清楚、缺失或已经过时的内容。请勿粘贴密钥、文档内容或私有端点。 -->'
      ].join('\n')
    : [
        '### Documentation page',
        '',
        `- Page: ${pageUrl.value}`,
        `- Language: ${locale}`,
        '',
        '### What needs improvement?',
        '',
        '<!-- Describe anything unclear, missing, or outdated. Do not paste credentials, document content, or private endpoints. -->'
      ].join('\n')

  const query = new URLSearchParams({ title, body })
  return `${REPOSITORY_ISSUES_URL}?${query.toString()}`
})
</script>

<template>
  <aside v-if="isVisible" class="docs-feedback" aria-labelledby="docs-feedback-title">
    <div class="docs-feedback__icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M7.5 18.5 3.5 20l1.1-4.3A8 8 0 1 1 7.5 18.5Z" />
        <path d="M8 10h8M8 13.5h5" />
      </svg>
    </div>
    <div class="docs-feedback__copy">
      <strong id="docs-feedback-title">{{ isChinese ? '这篇指南有帮助吗？' : 'Could this guide be better?' }}</strong>
      <span>{{ isChinese ? '告诉我们哪里不清楚或已经过时。' : 'Tell us what is unclear, missing, or out of date.' }}</span>
    </div>
    <a class="docs-feedback__link" :href="issueUrl" target="_blank" rel="noopener noreferrer">
      {{ isChinese ? '提交文档 Issue' : 'Open a docs issue' }}
      <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M4 12 12 4M6 4h6v6" />
      </svg>
    </a>
  </aside>
</template>
