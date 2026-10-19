import { createServer } from 'node:http'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

import { chromium } from 'playwright-core'

const frontendUrl = process.env.FRONTEND_URL ?? 'http://127.0.0.1:5173'
const chromePath =
  process.env.CHROME_PATH ??
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const adminEmail = process.env.ADMIN_EMAIL ?? 'admin@techvault.local'
const adminPassword = process.env.ADMIN_PASSWORD ?? 'ChangeMe-123!'
const memberEmail = `member-${Date.now()}@example.com`
const memberPassword = 'password-123'
const teamName = `联调团队-${Date.now()}`
const kbName = `联调知识库-${Date.now()}`
const providerModel = 'fake-model'
const fakeAnswer = 'Answer from fake provider [c1].'
const providerSpecs = [
  {
    name: 'E2E Responses Provider',
    providerType: 'openai_responses',
    path: '/v1/responses',
    auth: 'bearer',
  },
  {
    name: 'E2E Chat Provider',
    providerType: 'openai_chat_completions',
    path: '/v1/chat/completions',
    auth: 'bearer',
  },
  {
    name: 'E2E Anthropic Provider',
    providerType: 'anthropic_messages',
    path: '/v1/messages',
    auth: 'anthropic',
  },
]

const artifactsDir = resolve('artifacts')
await mkdir(artifactsDir, { recursive: true })

const providerRequests = []
const providerServer = createServer(async (request, response) => {
  const chunks = []
  for await (const chunk of request) chunks.push(chunk)
  const payload = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')
  providerRequests.push({
    path: request.url,
    headers: request.headers,
    payload,
  })

  if (request.url === '/v1/responses') {
    if (payload.stream) {
      response.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      })
      response.end(
        'event: response.output_text.delta\n' +
          'data: {"type":"response.output_text.delta","delta":"Answer from "}\n\n' +
          'event: response.output_text.delta\n' +
          'data: {"type":"response.output_text.delta","delta":"fake provider [c1]."}\n\n' +
          'event: response.completed\n' +
          'data: {"type":"response.completed"}\n\n',
      )
      return
    }
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(
      JSON.stringify({
        output: [
          {
            type: 'message',
            content: [{ type: 'output_text', text: fakeAnswer }],
          },
        ],
      }),
    )
    return
  }

  if (request.url === '/v1/messages') {
    if (payload.stream) {
      response.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      })
      response.end(
        'event: content_block_delta\n' +
          'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Answer from "}}\n\n' +
          'event: content_block_delta\n' +
          'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"fake provider [c1]."}}\n\n' +
          'event: message_stop\n' +
          'data: {"type":"message_stop"}\n\n',
      )
      return
    }
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(
      JSON.stringify({
        content: [{ type: 'text', text: fakeAnswer }],
      }),
    )
    return
  }

  if (payload.stream) {
    response.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
    })
    response.end(
      'data: {"choices":[{"delta":{"content":"Answer from "}}]}\n\n' +
        'data: {"choices":[{"delta":{"content":"fake provider [c1]."}}]}\n\n' +
        'data: [DONE]\n\n',
    )
    return
  }

  response.writeHead(200, { 'Content-Type': 'application/json' })
  response.end(
    JSON.stringify({
      choices: [{ message: { content: fakeAnswer } }],
    }),
  )
})
await new Promise((resolveListen, rejectListen) => {
  providerServer.once('error', rejectListen)
  providerServer.listen(0, '127.0.0.1', resolveListen)
})
const providerAddress = providerServer.address()
if (!providerAddress || typeof providerAddress === 'string') {
  throw new Error('fake provider did not bind to a TCP port')
}
const providerBaseUrl = `http://127.0.0.1:${providerAddress.port}/v1`

const browser = await chromium.launch({
  executablePath: chromePath,
  headless: true,
})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const consoleErrors = []
const failedResponses = []
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('pageerror', (error) => consoleErrors.push(error.message))
page.on('response', (response) => {
  if (response.status() >= 400) {
    failedResponses.push({ status: response.status(), url: response.url() })
  }
})

async function login(email, password) {
  await page.goto(`${frontendUrl}/login`)
  await page.fill('[data-testid="login-email"]', email)
  await page.fill('[data-testid="login-password"]', password)
  await page.click('[data-testid="login-submit"]')
}

async function apiRequest(path, { method = 'GET', body, headers = {} } = {}) {
  return page.evaluate(
    async ({ path, method, body, headers }) => {
      const token = window.sessionStorage.getItem('techvault.access_token')
      const requestHeaders = {
        Authorization: `Bearer ${token ?? ''}`,
        ...headers,
      }
      if (body !== undefined) requestHeaders['Content-Type'] = 'application/json'
      const response = await fetch(`/api/v1${path}`, {
        method,
        headers: requestHeaders,
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      const text = await response.text()
      let envelope
      try {
        envelope = JSON.parse(text)
      } catch {
        throw new Error(`${method} ${path} returned non-JSON: ${text}`)
      }
      if (!response.ok) {
        throw new Error(`${method} ${path} failed ${response.status}: ${text}`)
      }
      return envelope
    },
    { path, method, body, headers },
  )
}

async function uploadDocument(teamId, kbId) {
  return page.evaluate(
    async ({ teamId, kbId }) => {
      const token = window.sessionStorage.getItem('techvault.access_token')
      const form = new FormData()
      form.append('team_id', teamId)
      form.append('kb_id', kbId)
      form.append(
        'file',
        new File(
          [
            '# Virtual Threads\n\n' +
              'Virtual threads are lightweight Java threads.\n\n' +
              '## Scheduling\n\n' +
              'The JVM schedules virtual threads on carrier threads.\n',
          ],
          'virtual-threads.md',
          { type: 'text/markdown' },
        ),
      )
      const response = await fetch('/api/v1/docs/upload', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token ?? ''}` },
        body: form,
      })
      const text = await response.text()
      const envelope = JSON.parse(text)
      if (!response.ok) {
        throw new Error(`document upload failed ${response.status}: ${text}`)
      }
      return envelope.data
    },
    { teamId, kbId },
  )
}

async function waitForDocumentActive(teamId, documentId) {
  const deadline = Date.now() + 60_000
  while (Date.now() < deadline) {
    const envelope = await apiRequest(
      `/docs/detail?team_id=${encodeURIComponent(teamId)}` +
        `&document_id=${encodeURIComponent(documentId)}`,
    )
    if (envelope.data.doc_status === 'active') return
    if (envelope.data.doc_status === 'failed') {
      throw new Error(`document ingestion failed: ${documentId}`)
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 500))
  }
  throw new Error(`document ingestion timed out: ${documentId}`)
}

async function setupFakeProviders() {
  const teamId = await page.evaluate(() =>
    window.localStorage.getItem('techvault.team_id'),
  )
  if (!teamId) throw new Error('team id was not selected')
  const knowledgeBases = await apiRequest(
    `/kbs?team_id=${encodeURIComponent(teamId)}&limit=100`,
  )
  const knowledgeBase = knowledgeBases.data.find((item) => item.name === kbName)
  if (!knowledgeBase) throw new Error(`knowledge base not found: ${kbName}`)

  const providers = []
  for (const spec of providerSpecs) {
    const provider = (
      await apiRequest('/providers/create', {
        method: 'POST',
        body: {
          team_id: teamId,
          name: spec.name,
          provider_type: spec.providerType,
          base_url: providerBaseUrl,
          api_key: 'sk-e2e',
          model_ids: [providerModel],
        },
      })
    ).data
    providers.push({ ...spec, ...provider })
  }
  const providerIds = providers.map((provider) => provider.id)
  await apiRequest('/admin/model-policy/update', {
    method: 'POST',
    body: {
      mode: 'external_allowed',
      allowed_provider_ids: providerIds,
      max_data_classification: 'internal',
    },
  })
  await apiRequest('/model-policy/update', {
    method: 'POST',
    body: {
      team_id: teamId,
      mode: 'external_allowed',
      allowed_provider_ids: providerIds,
      max_data_classification: 'internal',
    },
  })
  const kbPolicy = (
    await apiRequest(
      `/kbs/policy?team_id=${encodeURIComponent(teamId)}` +
        `&kb_id=${encodeURIComponent(knowledgeBase.id)}`,
    )
  ).data
  await apiRequest('/kbs/policy/update', {
    method: 'POST',
    headers: { 'If-Match': String(kbPolicy.version) },
    body: {
      team_id: teamId,
      kb_id: knowledgeBase.id,
      mode: 'external_allowed',
    },
  })

  const upload = await uploadDocument(teamId, knowledgeBase.id)
  await waitForDocumentActive(teamId, upload.document.id)
  return { providers, teamId, knowledgeBaseId: knowledgeBase.id }
}

async function assertNoHorizontalOverflow(label) {
  const dimensions = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  if (dimensions.scrollWidth > dimensions.innerWidth + 1) {
    throw new Error(
      `${label} has horizontal overflow: ` +
        `${dimensions.scrollWidth} > ${dimensions.innerWidth}`,
    )
  }
}

async function verifyChatProviderFlow(provider, streamEnabled) {
  await page.goto(`${frontendUrl}/chat`)
  await page.waitForSelector('[data-testid="chat-provider-select"]')
  await page
    .locator('[data-testid^="chat-kb-"][aria-pressed="true"]')
    .waitFor()
  await page.fill('[data-testid="question-input"]', 'What are virtual threads?')
  if (streamEnabled) {
    await page.check('[data-testid="chat-stream-toggle"]')
  } else {
    await page.uncheck('[data-testid="chat-stream-toggle"]')
  }

  const sendButton = page.getByTestId('send-message')
  if (!(await sendButton.isDisabled())) {
    throw new Error('send should be disabled before provider/model selection')
  }
  const disabledStyle = await sendButton.evaluate((element) => {
    const style = window.getComputedStyle(element)
    return { background: style.backgroundColor, color: style.color }
  })
  if (disabledStyle.background !== 'rgb(226, 232, 240)') {
    throw new Error(
      `send button disabled background was ${disabledStyle.background}`,
    )
  }
  await page.screenshot({
    path: resolve(artifactsDir, 'frontend-chat-provider-disabled.png'),
    fullPage: true,
  })

  await page.selectOption('[data-testid="chat-provider-select"]', {
    label: provider.name,
  })
  await page.selectOption('[data-testid="chat-model-select"]', providerModel)
  if (await sendButton.isDisabled()) {
    throw new Error('send should be enabled after provider/model selection')
  }
  const enabledStyle = await sendButton.evaluate((element) => {
    const style = window.getComputedStyle(element)
    return { background: style.backgroundColor, color: style.color }
  })
  if (
    disabledStyle.background === enabledStyle.background &&
    disabledStyle.color === enabledStyle.color
  ) {
    throw new Error('send button does not have a visibly gray disabled state')
  }
  await page.screenshot({
    path: resolve(
      artifactsDir,
      `frontend-chat-provider-selected-${provider.providerType}-${
        streamEnabled ? 'stream' : 'nonstream'
      }.png`,
    ),
    fullPage: true,
  })

  const requestCount = providerRequests.length
  const askResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/api/v1/chats/ask') &&
      response.request().method() === 'POST' &&
      response.ok(),
    { timeout: 30_000 },
  )
  await sendButton.click()
  await askResponse
  await page.getByText(fakeAnswer, { exact: true }).last().waitFor({
    timeout: 30_000,
  })
  await page.getByTestId('send-message').waitFor({ state: 'visible' })
  const deadline = Date.now() + 5_000
  while (providerRequests.length <= requestCount && Date.now() < deadline) {
    await new Promise((resolveWait) => setTimeout(resolveWait, 25))
  }
  if (providerRequests.length !== requestCount + 1) {
    throw new Error(
      `expected one provider request for ${provider.providerType}, ` +
        `received ${providerRequests.length - requestCount}`,
    )
  }
  if (
    (await page.inputValue('[data-testid="chat-provider-select"]')) !==
    provider.id
  ) {
    throw new Error('provider selection did not persist through the ask flow')
  }
  if (
    (await page.inputValue('[data-testid="chat-model-select"]')) !== providerModel
  ) {
    throw new Error('model selection did not persist through the ask flow')
  }
  await assertNoHorizontalOverflow('desktop chat')
  await page.screenshot({
    path: resolve(
      artifactsDir,
      `frontend-chat-provider-result-${provider.providerType}-${
        streamEnabled ? 'stream' : 'nonstream'
      }.png`,
    ),
    fullPage: true,
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByText(fakeAnswer, { exact: true }).waitFor()
  await assertNoHorizontalOverflow('mobile chat')
  await page.screenshot({
    path: resolve(
      artifactsDir,
      `frontend-chat-provider-result-${provider.providerType}-${
        streamEnabled ? 'stream' : 'nonstream'
      }-mobile.png`,
    ),
    fullPage: true,
  })
  await page.setViewportSize({ width: 1440, height: 900 })

  const relevantFailedResponses = failedResponses.filter(
    (response) => !response.url.endsWith('/favicon.ico'),
  )
  const relevantConsoleErrors = consoleErrors.filter(
    (message) =>
      !message.includes('favicon') &&
      !(
        message.includes('status of 404') &&
        relevantFailedResponses.length === 0
      ),
  )
  if (relevantFailedResponses.length || relevantConsoleErrors.length) {
    throw new Error(
      `browser errors: ${JSON.stringify(relevantFailedResponses)} ` +
        `console=${relevantConsoleErrors.join(' | ')}`,
    )
  }
  const providerRequest = providerRequests[providerRequests.length - 1]
  if (providerRequest.path !== provider.path) {
    throw new Error(`unexpected provider path: ${providerRequest.path}`)
  }
  if (provider.auth === 'anthropic') {
    if (providerRequest.headers['x-api-key'] !== 'sk-e2e') {
      throw new Error('Anthropic provider API key was not sent')
    }
    if (providerRequest.headers['anthropic-version'] !== '2023-06-01') {
      throw new Error('Anthropic version header was not sent')
    }
  } else if (providerRequest.headers.authorization !== 'Bearer sk-e2e') {
    throw new Error('Bearer provider API key was not sent')
  }
  if (providerRequest.payload.model !== providerModel) {
    throw new Error('selected model was not sent to the fake provider')
  }
  if (providerRequest.payload.stream !== streamEnabled) {
    throw new Error('browser ask did not use the selected stream mode')
  }
  const prompt =
    provider.providerType === 'openai_responses'
      ? providerRequest.payload.input
      : providerRequest.payload.messages[0].content
  if (!prompt.includes('Virtual threads are lightweight Java threads.')) {
    throw new Error('provider prompt did not contain retrieved context')
  }
}

try {
  await login(adminEmail, adminPassword)
  await page.waitForURL(/\/(teams|knowledge-bases)$/)
  await page.goto(`${frontendUrl}/teams`)
  await page.waitForSelector('[data-testid="team-create-open"]')

  await page.click('[data-testid="team-create-open"]')
  await page.fill('[data-testid="team-name-input"]', teamName)
  await page.click('[data-testid="team-create-submit"]')
  await page.waitForURL('**/knowledge-bases')

  await page.click('[data-testid="kb-create-open"]')
  await page.fill('[data-testid="kb-name-input"]', kbName)
  await page.click('[data-testid="kb-save"]')
  await page.getByText(kbName, { exact: true }).waitFor()

  const { providers } = await setupFakeProviders()
  for (const provider of providers) {
    await verifyChatProviderFlow(provider, true)
    await verifyChatProviderFlow(provider, false)
  }

  await page.goto(`${frontendUrl}/admin/users`)
  await page.waitForSelector('[data-testid="admin-user-team"]')
  await page.selectOption('[data-testid="admin-user-team"]', { label: teamName })
  await page.fill('[data-testid="admin-user-name"]', '联调成员')
  await page.fill('[data-testid="admin-user-email"]', memberEmail)
  await page.fill('[data-testid="admin-user-password"]', memberPassword)
  await page.selectOption('[data-testid="admin-user-role"]', 'member')
  await page.click('[data-testid="admin-user-submit"]')
  await page.getByText('用户已创建').waitFor()

  await page.screenshot({
    path: resolve(artifactsDir, 'frontend-admin.png'),
    fullPage: true,
  })

  await page.goto(`${frontendUrl}/knowledge-bases`)
  await page.getByText(kbName, { exact: true }).click()
  await page.waitForURL(/\/knowledge-bases\/[^/]+$/)
  const memberOption = page
    .locator('label.kb-member-option')
    .filter({ hasText: memberEmail })
    .locator('input')
  await memberOption.check()
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/kbs/members/update') &&
        response.request().method() === 'POST' &&
        response.ok(),
    ),
    page.click('[data-testid="kb-member-save"]'),
  ])

  await page.click('[data-testid="logout-button"]')
  await page.waitForURL('**/login')
  await login(memberEmail, memberPassword)
  await page.waitForURL('**/knowledge-bases')
  await page.getByText(kbName, { exact: true }).waitFor()

  await page.screenshot({
    path: resolve(artifactsDir, 'frontend-integration.png'),
    fullPage: true,
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${frontendUrl}/knowledge-bases`)
  await page.getByText(kbName, { exact: true }).waitFor()
  await page.screenshot({
    path: resolve(artifactsDir, 'frontend-integration-mobile.png'),
    fullPage: true,
  })

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.click('[data-testid="logout-button"]')
  await page.waitForURL('**/login')
  await page.screenshot({
    path: resolve(artifactsDir, 'frontend-login.png'),
    fullPage: true,
  })

  console.log(`integration OK: ${memberEmail} / ${teamName} / ${kbName}`)
} finally {
  await browser.close()
  await new Promise((resolveClose) => providerServer.close(resolveClose))
}
