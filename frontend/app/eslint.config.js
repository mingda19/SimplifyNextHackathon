import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    // TanStack Router file-based routes export `Route` (not a component) and
    // pass their page component to `component:` without exporting it — so
    // this rule always sees "no real component export" and flags every local
    // component in the file, no matter the config. That's inherent to the
    // convention, not a bug, and the tradeoff (full reload instead of Fast
    // Refresh on route-file edits) already exists today — just silence it
    // here instead of leaving noise on every route file.
    files: ['src/routes/**/*.{ts,tsx}'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
])
