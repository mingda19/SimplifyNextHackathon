import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseEnv } from 'node:util'
import { configureAuth } from '../setup_auth.mjs'

test('upgrades an old env without altering database settings or comments', () => {
  const original = '# Keep my configuration\r\nDATABASE_URL="postgresql://example/db"\r\nFAKE_LLM=1'
  const result = configureAuth(original)
  assert.ok(result.content.startsWith(original + '\r\n'))
  assert.deepEqual(result.changed, ['AUTH_JWT_SECRET', 'SERVICE_AUTH_TOKEN'])
  const env = parseEnv(result.content)
  for (const key of result.changed) assert.match(env[key], /^[A-Za-z0-9_-]{64}$/)
  assert.notEqual(env.AUTH_JWT_SECRET, env.SERVICE_AUTH_TOKEN)
})

test('reruns preserve valid secrets and the exact file contents', () => {
  const first = configureAuth('')
  const second = configureAuth(first.content)
  assert.equal(second.content, first.content)
  assert.deepEqual(second.changed, [])
})

test('replaces blank or legacy keys including export, quotes and duplicates', () => {
  const result = configureAuth('AUTH_JWT_SECRET=old\nexport AUTH_JWT_SECRET="dev-only-change-me" # old default\nSERVICE_AUTH_TOKEN=\n')
  const env = parseEnv(result.content)
  assert.equal(env.AUTH_JWT_SECRET.length, 64)
  assert.equal(env.SERVICE_AUTH_TOKEN.length, 64)
  assert.equal(configureAuth(result.content).content, result.content)
})

test('retains the valid signing key when adding the internal service credential', () => {
  const original = 'export AUTH_JWT_SECRET="existing-key-that-is-at-least-32-characters" # keep\n'
  const result = configureAuth(original)
  assert.ok(result.content.startsWith(original))
  assert.deepEqual(result.changed, ['SERVICE_AUTH_TOKEN'])
})

test('separates identical credentials without changing the signing key', () => {
  const key = 'existing-key-that-is-at-least-32-characters'
  const result = configureAuth(`AUTH_JWT_SECRET=${key}\nSERVICE_AUTH_TOKEN=${key}\n`)
  const env = parseEnv(result.content)
  assert.equal(env.AUTH_JWT_SECRET, key)
  assert.notEqual(env.SERVICE_AUTH_TOKEN, key)
  assert.deepEqual(result.changed, ['SERVICE_AUTH_TOKEN'])
})

test('refuses ambiguous auth values without exposing them in errors', () => {
  for (const value of ['"short\nmultiline"', '${EXTERNAL_SECRET}']) {
    assert.throws(() => configureAuth(`AUTH_JWT_SECRET=${value}\n`), {
      message: 'AUTH_JWT_SECRET must be a single literal value; update it manually.',
    })
  }
})
