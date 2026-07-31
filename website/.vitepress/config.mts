import { readFileSync } from 'node:fs'
import { defineConfig, type DefaultTheme, type HeadConfig } from 'vitepress'

const SITE_ORIGIN = 'https://jaminmei.github.io'
const SITE_BASE = '/Pressroom/'
const SITE_URL = `${SITE_ORIGIN}${SITE_BASE}`
const REPOSITORY_URL = 'https://github.com/jaminmei/Pressroom'

const frontendPackage = JSON.parse(
  readFileSync(new URL('../../frontend/package.json', import.meta.url), 'utf8')
) as { version: string }

const productVersion = frontendPackage.version

const englishSidebar: DefaultTheme.SidebarItem[] = [
  {
    text: 'Getting started',
    items: [
      { text: 'Welcome to PressRoom', link: '/getting-started/overview' },
      { text: 'Installation', link: '/getting-started/installation' },
      { text: 'Your first workflow', link: '/getting-started/first-workflow' }
    ]
  },
  {
    text: 'Concepts',
    items: [{ text: 'Core concepts', link: '/concepts/core-concepts' }]
  },
  {
    text: 'Build workflows',
    items: [
      { text: 'Studio and templates', link: '/workflows/studio-and-templates' },
      { text: 'Editor and nodes', link: '/workflows/editor-and-nodes' },
      { text: 'Model providers', link: '/workflows/providers' },
      { text: 'Runs and results', link: '/workflows/run-and-results' }
    ]
  },
  {
    text: 'Evaluate',
    items: [
      { text: 'Databases', link: '/evaluation/databases' },
      { text: 'Ground truth', link: '/evaluation/ground-truth' }
    ]
  },
  {
    text: 'Publish and integrate',
    items: [
      { text: 'API access', link: '/publish/api-access' },
      { text: 'Workflow API reference', link: '/api-reference/workflow-api' }
    ]
  },
  {
    text: 'Deploy and administer',
    items: [
      { text: 'Docker Compose', link: '/deployment/compose' },
      {
        text: 'Security and troubleshooting',
        link: '/administration/security-and-troubleshooting'
      }
    ]
  }
]

const chineseSidebar: DefaultTheme.SidebarItem[] = [
  {
    text: '开始使用',
    items: [
      { text: 'PressRoom 简介', link: '/zh-CN/getting-started/overview' },
      { text: '安装与启动', link: '/zh-CN/getting-started/installation' },
      { text: '创建第一个工作流', link: '/zh-CN/getting-started/first-workflow' }
    ]
  },
  {
    text: '核心概念',
    items: [{ text: '理解 PressRoom', link: '/zh-CN/concepts/core-concepts' }]
  },
  {
    text: '构建工作流',
    items: [
      { text: 'Studio 与模板', link: '/zh-CN/workflows/studio-and-templates' },
      { text: '编辑器与节点', link: '/zh-CN/workflows/editor-and-nodes' },
      { text: 'Model Providers', link: '/zh-CN/workflows/providers' },
      { text: '运行与结果', link: '/zh-CN/workflows/run-and-results' }
    ]
  },
  {
    text: '评测',
    items: [
      { text: 'Databases', link: '/zh-CN/evaluation/databases' },
      { text: 'Ground Truth', link: '/zh-CN/evaluation/ground-truth' }
    ]
  },
  {
    text: '发布与集成',
    items: [
      { text: 'API Access', link: '/zh-CN/publish/api-access' },
      { text: 'Workflow API 参考', link: '/zh-CN/api-reference/workflow-api' }
    ]
  },
  {
    text: '部署与管理',
    items: [
      { text: 'Docker Compose', link: '/zh-CN/deployment/compose' },
      {
        text: '安全与故障排查',
        link: '/zh-CN/administration/security-and-troubleshooting'
      }
    ]
  }
]

const englishTheme: DefaultTheme.Config = {
  nav: [
    { text: 'Guide', link: '/getting-started/overview', activeMatch: '^/(getting-started|concepts)/' },
    { text: 'Workflows', link: '/workflows/studio-and-templates', activeMatch: '^/workflows/' },
    { text: 'Evaluate', link: '/evaluation/databases', activeMatch: '^/evaluation/' },
    {
      text: 'API',
      link: '/api-reference/workflow-api',
      activeMatch: '^/(publish|api-reference)/'
    },
    { text: 'Deploy', link: '/deployment/compose', activeMatch: '^/(deployment|administration)/' },
    { text: `v${productVersion}`, link: `${REPOSITORY_URL}/releases`, target: '_blank' }
  ],
  sidebar: englishSidebar,
  outline: { level: [2, 3], label: 'On this page' },
  docFooter: { prev: 'Previous', next: 'Next' },
  lastUpdated: { text: 'Last updated', formatOptions: { dateStyle: 'medium' } },
  darkModeSwitchLabel: 'Appearance',
  lightModeSwitchTitle: 'Switch to light theme',
  darkModeSwitchTitle: 'Switch to dark theme',
  sidebarMenuLabel: 'Menu',
  returnToTopLabel: 'Return to top',
  langMenuLabel: 'Change language',
  skipToContentLabel: 'Skip to content',
  notFound: {
    title: 'Page not found',
    quote: 'This page may have moved. The documentation home is a good place to continue.',
    linkLabel: 'Go to documentation home',
    linkText: 'Back to home'
  },
  footer: {
    message: 'Open-source documentation for PressRoom.',
    copyright: 'See the repository for the license terms that apply to each component.'
  }
}

const chineseTheme: DefaultTheme.Config = {
  nav: [
    {
      text: '使用指南',
      link: '/zh-CN/getting-started/overview',
      activeMatch: '^/zh-CN/(getting-started|concepts)/'
    },
    {
      text: '工作流',
      link: '/zh-CN/workflows/studio-and-templates',
      activeMatch: '^/zh-CN/workflows/'
    },
    { text: '评测', link: '/zh-CN/evaluation/databases', activeMatch: '^/zh-CN/evaluation/' },
    {
      text: 'API',
      link: '/zh-CN/api-reference/workflow-api',
      activeMatch: '^/zh-CN/(publish|api-reference)/'
    },
    {
      text: '部署',
      link: '/zh-CN/deployment/compose',
      activeMatch: '^/zh-CN/(deployment|administration)/'
    },
    { text: `v${productVersion}`, link: `${REPOSITORY_URL}/releases`, target: '_blank' }
  ],
  sidebar: chineseSidebar,
  outline: { level: [2, 3], label: '本页内容' },
  docFooter: { prev: '上一页', next: '下一页' },
  lastUpdated: { text: '最后更新', formatOptions: { dateStyle: 'medium' } },
  darkModeSwitchLabel: '外观',
  lightModeSwitchTitle: '切换到浅色模式',
  darkModeSwitchTitle: '切换到深色模式',
  sidebarMenuLabel: '目录',
  returnToTopLabel: '返回顶部',
  langMenuLabel: '切换语言',
  skipToContentLabel: '跳到正文',
  notFound: {
    title: '页面未找到',
    quote: '此页面可能已移动，可以从文档首页继续浏览。',
    linkLabel: '前往文档首页',
    linkText: '返回首页'
  },
  footer: {
    message: 'PressRoom 开源文档。',
    copyright: '各组件适用的许可证条款请参阅项目仓库。'
  }
}

function tokenizeForSearch(value: string): string[] {
  // Keep the regexes inside this function: VitePress serializes search
  // callbacks into the browser, where module-level closures are unavailable.
  const cjkRunPattern = /^[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]+$/u
  const tokenPattern =
    /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]+|[\p{Letter}\p{Number}]+/gu
  const normalized = value.normalize('NFKC').toLocaleLowerCase()
  const tokens: string[] = []

  for (const match of normalized.matchAll(tokenPattern)) {
    const term = match[0]
    if (!cjkRunPattern.test(term)) {
      tokens.push(term)
      continue
    }

    const characters = [...term]
    tokens.push(...characters)
    for (let index = 0; index < characters.length - 1; index += 1) {
      tokens.push(`${characters[index]}${characters[index + 1]}`)
    }
    if (characters.length > 2) tokens.push(term)
  }

  return [...new Set(tokens)]
}

function routeFromRelativePath(relativePath: string): string {
  if (relativePath === 'index.md') return ''
  if (relativePath.endsWith('/index.md')) return relativePath.slice(0, -'index.md'.length)
  return relativePath.replace(/\.md$/, '')
}

function absolutePageUrl(route: string): string {
  return new URL(route, SITE_URL).toString()
}

function seoHead(relativePath: string, title: string, description: string): HeadConfig[] {
  if (relativePath === '404.md') {
    return [['meta', { name: 'robots', content: 'noindex, nofollow' }]]
  }

  const route = routeFromRelativePath(relativePath)
  const isChinese = route === 'zh-CN' || route.startsWith('zh-CN/')
  const languageNeutralRoute = isChinese ? route.replace(/^zh-CN\/?/, '') : route
  const englishRoute = languageNeutralRoute
  const chineseRoute = `zh-CN/${languageNeutralRoute}`
  const canonical = absolutePageUrl(route)
  const englishUrl = absolutePageUrl(englishRoute)
  const chineseUrl = absolutePageUrl(chineseRoute)
  const socialImage = new URL(
    isChinese ? 'images/product/press-room-hero.zh-CN.webp' : 'images/product/press-room-hero.webp',
    SITE_URL
  ).toString()

  return [
    ['link', { rel: 'canonical', href: canonical }],
    ['link', { rel: 'alternate', hreflang: 'en', href: englishUrl }],
    ['link', { rel: 'alternate', hreflang: 'zh-CN', href: chineseUrl }],
    ['link', { rel: 'alternate', hreflang: 'x-default', href: englishUrl }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:site_name', content: 'Press Room Docs' }],
    ['meta', { property: 'og:title', content: title }],
    ['meta', { property: 'og:description', content: description }],
    ['meta', { property: 'og:url', content: canonical }],
    ['meta', { property: 'og:image', content: socialImage }],
    [
      'meta',
      {
        property: 'og:image:alt',
        content: isChinese ? 'PressRoom 文档工作流工作空间' : 'PressRoom document workflow workspace'
      }
    ],
    ['meta', { property: 'og:locale', content: isChinese ? 'zh_CN' : 'en_US' }],
    ['meta', { property: 'og:locale:alternate', content: isChinese ? 'en_US' : 'zh_CN' }],
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
    ['meta', { name: 'twitter:title', content: title }],
    ['meta', { name: 'twitter:description', content: description }],
    ['meta', { name: 'twitter:image', content: socialImage }]
  ]
}

export default defineConfig({
  base: SITE_BASE,
  cleanUrls: true,
  ignoreDeadLinks: 'localhostLinks',
  lastUpdated: true,
  appearance: true,
  title: 'Press Room Docs',
  titleTemplate: ':title · Press Room Docs',
  description: 'Build, evaluate, and publish production-ready document AI workflows with PressRoom.',
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${SITE_BASE}brand-mark.svg` }],
    ['link', { rel: 'sitemap', type: 'application/xml', href: `${SITE_BASE}sitemap.xml` }],
    ['meta', { name: 'theme-color', content: '#7132f5' }],
    ['meta', { name: 'color-scheme', content: 'light dark' }]
  ],
  sitemap: { hostname: SITE_URL },
  locales: {
    root: {
      label: 'English',
      lang: 'en-US',
      title: 'Press Room Docs',
      description: 'Build, evaluate, and publish production-ready document AI workflows with PressRoom.',
      themeConfig: englishTheme
    },
    'zh-CN': {
      label: '简体中文',
      lang: 'zh-CN',
      link: '/zh-CN/',
      title: 'Press Room 文档',
      titleTemplate: ':title · Press Room 文档',
      description: '使用 PressRoom 构建、评测并发布可用于生产环境的文档 AI 工作流。',
      themeConfig: chineseTheme
    }
  },
  themeConfig: {
    logo: { src: '/brand-mark.svg', alt: 'PressRoom' },
    siteTitle: 'Press Room Docs',
    search: {
      provider: 'local',
      options: {
        miniSearch: {
          options: {
            tokenize: tokenizeForSearch,
            processTerm: (term) => term.normalize('NFKC').toLocaleLowerCase()
          },
          searchOptions: {
            boost: { title: 5, titles: 2.5, text: 1 },
            prefix: true,
            fuzzy: (term) =>
              /^[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]+$/u.test(
                term
              ) || term.length < 5
                ? false
                : 0.15
          }
        },
        locales: {
          'zh-CN': {
            translations: {
              button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
              modal: {
                displayDetails: '显示详细列表',
                resetButtonTitle: '重置搜索',
                backButtonTitle: '关闭搜索',
                noResultsText: '没有找到相关内容',
                footer: {
                  selectText: '选择',
                  selectKeyAriaLabel: '回车',
                  navigateText: '切换',
                  navigateUpKeyAriaLabel: '向上',
                  navigateDownKeyAriaLabel: '向下',
                  closeText: '关闭',
                  closeKeyAriaLabel: 'Esc'
                }
              }
            }
          }
        }
      }
    },
    socialLinks: [{ icon: 'github', link: REPOSITORY_URL, ariaLabel: 'PressRoom on GitHub' }],
    externalLinkIcon: true,
    i18nRouting: true
  },
  transformPageData(pageData) {
    const isChinese = pageData.relativePath.startsWith('zh-CN/')
    const title = pageData.title || (isChinese ? 'Press Room 文档' : 'Press Room Docs')
    const description =
      pageData.description ||
      (isChinese
        ? '使用 PressRoom 构建、评测并发布可用于生产环境的文档 AI 工作流。'
        : 'Build, evaluate, and publish production-ready document AI workflows with PressRoom.')

    if (pageData.frontmatter.layout === 'home') pageData.titleTemplate = false

    pageData.frontmatter.head = [
      ...(pageData.frontmatter.head ?? []),
      ...seoHead(pageData.relativePath, title, description)
    ]
  }
})
