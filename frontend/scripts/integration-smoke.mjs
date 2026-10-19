import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

import { chromium } from 'playwright-core'

const frontendUrl = process.env.FRONTEND_URL ?? 'http://127.0.0.1:5173'
const chromePath =
  process.env.CHROME_PATH ??
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const email = `ui-${Date.now()}@example.com`
const password = 'password-123'
const teamName = `联调团队-${Date.now()}`
const kbName = `联调知识库-${Date.now()}`

const artifactsDir = resolve('artifacts')
await mkdir(artifactsDir, { recursive: true })

const browser = await chromium.launch({
  executablePath: chromePath,
  headless: true,
})

const page = await browser.newPage({
  viewport: { width: 1440, height: 900 },
})

try {
  await page.goto(`${frontendUrl}/register`)
  await page.fill('[data-testid="register-display-name"]', '联调用户')
  await page.fill('[data-testid="register-email"]', email)
  await page.fill('[data-testid="register-password"]', password)
  await page.fill('[data-testid="register-confirm-password"]', password)
  await page.click('[data-testid="register-submit"]')
  await page.waitForURL('**/teams')

  await page.click('[data-testid="team-create-open"]')
  await page.fill('[data-testid="team-name-input"]', teamName)
  await page.click('[data-testid="team-create-submit"]')
  await page.waitForURL('**/knowledge-bases')

  await page.click('[data-testid="kb-create-open"]')
  await page.fill('[data-testid="kb-name-input"]', kbName)
  await page.click('[data-testid="kb-save"]')
  await page.getByText(kbName, { exact: true }).waitFor()

  await page.reload()
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

  console.log(`integration OK: ${email} / ${teamName} / ${kbName}`)
} finally {
  await browser.close()
}
