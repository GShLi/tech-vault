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

const artifactsDir = resolve('artifacts')
await mkdir(artifactsDir, { recursive: true })

const browser = await chromium.launch({
  executablePath: chromePath,
  headless: true,
})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

async function login(email, password) {
  await page.goto(`${frontendUrl}/login`)
  await page.fill('[data-testid="login-email"]', email)
  await page.fill('[data-testid="login-password"]', password)
  await page.click('[data-testid="login-submit"]')
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
}
