// One-time auth configuration upgrade. Requires Node.js 20.12 or newer.
// Run from any directory: node scripts/setup_auth.mjs
import { randomBytes } from 'node:crypto'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseEnv } from 'node:util'

const keys = ['AUTH_JWT_SECRET', 'SERVICE_AUTH_TOKEN']
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

export function configureAuth(content) {
  const values = parseEnv(content)
  const changed = []
  for (const key of keys) {
    const value = values[key] || ''
    // Avoid rewriting multiline or interpolated configuration incorrectly.
    if (/[\r\n]/.test(value) || value.includes('$')) {
      throw new Error(`${key} must be a single literal value; update it manually.`)
    }
  }
  for (const key of keys) {
    const value = values[key] || ''
    if (value.length < 32 || value === 'dev-only-change-me' ||
        (key === 'SERVICE_AUTH_TOKEN' && value === values.AUTH_JWT_SECRET)) {
      values[key] = randomBytes(48).toString('base64url')
      changed.push(key)
    }
  }
  const newline = content.includes('\r\n') ? '\r\n' : '\n'
  for (const key of changed) {
    const assignment = new RegExp(`^[ \\t]*(?:export[ \\t]+)?${key}[ \\t]*=[^\\r\\n]*`, 'gm')
    if (assignment.test(content)) {
      content = content.replace(assignment, `${key}=${values[key]}`)
    } else {
      if (content && !content.endsWith('\n')) content += newline
      content += `${key}=${values[key]}${newline}`
    }
  }
  return { content, changed }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const target = resolve(root, '.env')
    const source = existsSync(target) ? target : resolve(root, '.env.example')
    const original = readFileSync(source, 'utf8')
    const { content, changed } = configureAuth(original)
    if (changed.length || source !== target) {
      writeFileSync(target, content, { mode: 0o600 })
    }
    console.log(changed.length ? `Configured ${changed.join(', ')} in .env.` : 'Auth configuration is already valid.')
    console.log('Existing valid signing keys and database settings were preserved. Secret values are not printed.')
    for (const key of keys) {
      if (Object.hasOwn(process.env, key)) {
        console.log(`Check your shell's ${key}: exported values override .env.`)
      }
    }
    console.log('Restart all backend services with the updated .env, then sign in again with your existing account.')
  } catch (error) {
    console.error(error.message)
    process.exitCode = 1
  }
}
