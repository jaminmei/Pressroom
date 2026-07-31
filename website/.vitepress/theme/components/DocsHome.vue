<script setup lang="ts">
import { computed } from 'vue'
import { useData, withBase } from 'vitepress'

const { lang } = useData()
const isChinese = computed(() => lang.value.toLowerCase().startsWith('zh'))
const prefix = computed(() => (isChinese.value ? '/zh-CN' : ''))

function docsLink(path: string): string {
  return withBase(`${prefix.value}${path}`)
}

const content = computed(() =>
  isChinese.value
    ? {
        eyebrow: '开源 · 自托管 · 面向生产环境',
        titleStart: '让文档 AI 从画布',
        titleAccent: '可靠地走向生产。',
        intro:
          'PressRoom 是 Document Conversion 的公开源代码版。在一个可视化工作空间中构建、运行、评测并发布文档处理工作流，连接 OCR、版面分析、预处理和视觉模型。',
        primaryCta: '10 分钟快速开始',
        secondaryCta: '探索工作流',
        proofLabel: '平台特性',
        proofs: ['自托管', '类型化 DAG', 'Workspace RBAC'],
        screenshotAlt: 'PressRoom 可视化工作流编辑器，展示一个文档 OCR 处理流程',
        screenshotCaption: '类型约束的画布，让每一步输入与输出都清晰可见。',
        quickEyebrow: '第一条工作流',
        quickTitle: '从 PDF 到可验证的 OCR 结果，只需 10 分钟',
        quickCopy: '使用公开模板完成一个真实流程，再按需替换 Engine 或 Model Provider。',
        steps: [
          ['01', '启动 Standard Profile', '使用 Docker Compose 启动 Web、API、PostgreSQL 与串行执行器。'],
          ['02', '应用 PDF → OCR 模板', '从 Template Center 创建一条已连线并通过类型校验的工作流。'],
          ['03', '运行、评测、发布', '检查节点结果，与 Ground Truth 对比，然后生成工作流级 API。']
        ],
        learnMore: '打开快速开始',
        platformEyebrow: '一个连续的工作空间',
        platformTitle: '构建、评测、交付，不必切换上下文',
        platformCopy: '从实验到 API 使用同一条可追溯的工作流定义。',
        cards: [
          ['build', 'Build', '组合带类型的节点', '连接 OCR、转换、图像预处理、版面检测与 OpenAI 兼容视觉模型。', '/workflows/editor-and-nodes'],
          ['evaluate', 'Evaluate', '用真实数据验证质量', '维护 Databases 与版本化 Ground Truth，比较不同工作流运行的输出。', '/evaluation/ground-truth'],
          ['ship', 'Ship', '开放工作流 API', '为已解锁 Publication State 的工作流创建访问密钥，并通过 URL 或文件上传调用。', '/publish/api-access']
        ],
        railEyebrow: '端到端链路',
        railTitle: '每个阶段都可观察、可替换、可复现',
        railAriaLabel: '文档工作流的五个阶段，可横向滚动',
        railItems: [
          ['输入', 'PDF · 图片 · URL'],
          ['增强', '旋转 · 去噪 · 清晰化'],
          ['理解', 'OCR · Layout · VLM'],
          ['评测', 'Ground Truth · Runs'],
          ['发布', 'Workflow API']
        ],
        communityEyebrow: '开放协作',
        communityTitle: '把你的文档工作流带到 PressRoom',
        communityCopy: '从安装指南开始，或前往 GitHub 查看源代码、报告问题并参与改进。',
        communityPrimary: '阅读安装指南',
        communitySecondary: '在 GitHub 查看'
      }
    : {
        eyebrow: 'Open source · Self-hosted · Production-minded',
        titleStart: 'Take document AI from canvas',
        titleAccent: 'to dependable production.',
        intro:
          'PressRoom is the public source edition of Document Conversion. Build, run, evaluate, and publish document-processing workflows in one visual workspace with OCR, layout analysis, preprocessing, and vision models.',
        primaryCta: 'Start in 10 minutes',
        secondaryCta: 'Explore workflows',
        proofLabel: 'Platform qualities',
        proofs: ['Self-hosted', 'Typed DAGs', 'Workspace RBAC'],
        screenshotAlt: 'PressRoom visual workflow editor showing a document OCR processing pipeline',
        screenshotCaption: 'A typed canvas keeps every input, output, and transformation visible.',
        quickEyebrow: 'Your first workflow',
        quickTitle: 'From PDF to verified OCR in 10 minutes',
        quickCopy: 'Run a real path with a public template, then swap in the engines or model providers you need.',
        steps: [
          ['01', 'Start the Standard Profile', 'Bring up the web app, API, PostgreSQL, and serial executor with Docker Compose.'],
          ['02', 'Apply the PDF → OCR template', 'Create a connected, type-valid workflow directly from Template Center.'],
          ['03', 'Run, evaluate, and publish', 'Inspect node results, compare ground truth, then create a workflow-scoped API.']
        ],
        learnMore: 'Open the quickstart',
        platformEyebrow: 'One continuous workspace',
        platformTitle: 'Build, evaluate, and ship without losing context',
        platformCopy: 'Move from experiment to API with the same traceable workflow definition.',
        cards: [
          ['build', 'Build', 'Compose typed nodes', 'Connect OCR, conversion, image preprocessing, layout detection, and OpenAI-compatible vision models.', '/workflows/editor-and-nodes'],
          ['evaluate', 'Evaluate', 'Validate quality on real data', 'Maintain databases and versioned ground truth, then compare outputs across workflow runs.', '/evaluation/ground-truth'],
          ['ship', 'Ship', 'Expose a workflow API', 'Create access keys for publication-enabled workflows and invoke them by URL or file upload.', '/publish/api-access']
        ],
        railEyebrow: 'The complete path',
        railTitle: 'Every stage is observable, replaceable, and reproducible',
        railAriaLabel: 'Five stages in the document workflow; scroll horizontally',
        railItems: [
          ['Ingest', 'PDF · Image · URL'],
          ['Enhance', 'Rotate · Denoise · Restore'],
          ['Understand', 'OCR · Layout · VLM'],
          ['Evaluate', 'Ground truth · Runs'],
          ['Publish', 'Workflow API']
        ],
        communityEyebrow: 'Built in the open',
        communityTitle: 'Bring your document workflow to PressRoom',
        communityCopy: 'Begin with the installation guide, or visit GitHub to inspect the source, report an issue, and contribute.',
        communityPrimary: 'Read the install guide',
        communitySecondary: 'View on GitHub'
      }
)
</script>

<template>
  <div class="docs-home">
    <section class="home-hero" aria-labelledby="home-hero-title">
      <div class="home-hero__glow home-hero__glow--one" aria-hidden="true"></div>
      <div class="home-hero__glow home-hero__glow--two" aria-hidden="true"></div>
      <div class="home-shell home-hero__grid">
        <div class="home-hero__copy">
          <div class="home-eyebrow">
            <span class="home-eyebrow__pulse" aria-hidden="true"></span>
            {{ content.eyebrow }}
          </div>
          <h1 id="home-hero-title">
            {{ content.titleStart }}
            <span>{{ content.titleAccent }}</span>
          </h1>
          <p>{{ content.intro }}</p>
          <div class="home-actions">
            <a class="home-button home-button--primary" :href="docsLink('/getting-started/installation')">
              {{ content.primaryCta }}
              <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m6 3 5 5-5 5" /></svg>
            </a>
            <a class="home-button home-button--secondary" :href="docsLink('/workflows/studio-and-templates')">
              {{ content.secondaryCta }}
            </a>
          </div>
          <div class="home-proof" :aria-label="content.proofLabel">
            <span v-for="proof in content.proofs" :key="proof">
              <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7" /></svg>
              {{ proof }}
            </span>
          </div>
        </div>

        <figure class="home-product">
          <div class="home-product__bar" aria-hidden="true">
            <span></span><span></span><span></span>
            <div>PressRoom / Workflow Studio</div>
          </div>
          <img
            :src="withBase('/images/product/workflow-editor.webp')"
            :alt="content.screenshotAlt"
            width="1600"
            height="1000"
            fetchpriority="high"
            decoding="async"
          />
          <figcaption>{{ content.screenshotCaption }}</figcaption>
        </figure>
      </div>
    </section>

    <main>
      <section class="home-section home-quickstart" aria-labelledby="quickstart-title">
        <div class="home-shell home-quickstart__grid">
          <header class="home-section__intro">
            <span class="home-kicker">{{ content.quickEyebrow }}</span>
            <h2 id="quickstart-title">{{ content.quickTitle }}</h2>
            <p>{{ content.quickCopy }}</p>
            <a class="home-text-link" :href="docsLink('/getting-started/first-workflow')">
              {{ content.learnMore }}
              <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m6 3 5 5-5 5" /></svg>
            </a>
          </header>
          <ol class="home-steps">
            <li v-for="step in content.steps" :key="step[0]">
              <span>{{ step[0] }}</span>
              <div><h3>{{ step[1] }}</h3><p>{{ step[2] }}</p></div>
            </li>
          </ol>
        </div>
      </section>

      <section class="home-section home-platform" aria-labelledby="platform-title">
        <div class="home-shell">
          <header class="home-section__heading">
            <span class="home-kicker">{{ content.platformEyebrow }}</span>
            <h2 id="platform-title">{{ content.platformTitle }}</h2>
            <p>{{ content.platformCopy }}</p>
          </header>
          <div class="home-card-grid">
            <a v-for="card in content.cards" :key="card[0]" class="home-card" :href="docsLink(card[4])">
              <div class="home-card__icon" :class="`home-card__icon--${card[0]}`" aria-hidden="true">
                <svg v-if="card[0] === 'build'" viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="7" height="6" rx="2" /><rect x="14" y="14" width="7" height="6" rx="2" /><path d="M10 7h4a3 3 0 0 1 3 3v4" /></svg>
                <svg v-else-if="card[0] === 'evaluate'" viewBox="0 0 24 24" fill="none"><path d="M4 19V9M10 19V5M16 19v-7M22 19H2" /><path d="m3 7 6-4 6 6 6-5" /></svg>
                <svg v-else viewBox="0 0 24 24" fill="none"><path d="M12 3v12M7 10l5 5 5-5" /><path d="M5 15v4h14v-4" /></svg>
              </div>
              <span class="home-card__label">{{ card[1] }}</span>
              <h3>{{ card[2] }}</h3>
              <p>{{ card[3] }}</p>
              <svg class="home-card__arrow" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4" /></svg>
            </a>
          </div>
        </div>
      </section>

      <section class="home-section home-rail-section" aria-labelledby="rail-title">
        <div class="home-shell">
          <header class="home-section__heading home-section__heading--light">
            <span class="home-kicker">{{ content.railEyebrow }}</span>
            <h2 id="rail-title">{{ content.railTitle }}</h2>
          </header>
          <div class="home-rail" :aria-label="content.railAriaLabel" tabindex="0">
            <div v-for="(item, index) in content.railItems" :key="item[0]" class="home-rail__item">
              <span class="home-rail__number">0{{ index + 1 }}</span>
              <div><strong>{{ item[0] }}</strong><small>{{ item[1] }}</small></div>
              <svg v-if="index < content.railItems.length - 1" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m7 4 6 6-6 6" /></svg>
            </div>
          </div>
        </div>
      </section>

      <section class="home-community">
        <div class="home-shell home-community__panel">
          <div>
            <span class="home-kicker">{{ content.communityEyebrow }}</span>
            <h2>{{ content.communityTitle }}</h2>
            <p>{{ content.communityCopy }}</p>
          </div>
          <div class="home-actions">
            <a class="home-button home-button--primary" :href="docsLink('/getting-started/installation')">
              {{ content.communityPrimary }}
            </a>
            <a class="home-button home-button--secondary" href="https://github.com/jaminmei/Pressroom" target="_blank" rel="noopener noreferrer">
              {{ content.communitySecondary }}
              <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M4 12 12 4M6 4h6v6" /></svg>
            </a>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>
