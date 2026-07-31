import { h } from 'vue'
import type { Theme } from 'vitepress'
import DefaultTheme from 'vitepress/theme-without-fonts'
import DocsHome from './components/DocsHome.vue'
import DocFeedback from './components/DocFeedback.vue'
import ScreenshotFrame from './components/ScreenshotFrame.vue'
import './styles/base.css'
import './styles/home.css'

export default {
  extends: DefaultTheme,
  Layout: () =>
    h(DefaultTheme.Layout, null, {
      'doc-after': () => h(DocFeedback)
    }),
  enhanceApp({ app }) {
    app.component('DocsHome', DocsHome)
    app.component('ScreenshotFrame', ScreenshotFrame)
  }
} satisfies Theme
