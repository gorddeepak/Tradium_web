import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    // Tradium deliberately co-locates helpers and components in one file
    // (tradiumUtils.jsx, the chart shells, the ui primitives) — that's the
    // "beginner-simple, avoid over-abstraction" style from CLAUDE.md, so the
    // only-export-components rule fights the project's structure, not a bug.
    rules: {
      'react-refresh/only-export-components': 'off',
      // leading-underscore names are the standard "deliberately unused"
      // marker (e.g. destructuring out fields: `({ id: _id, ...rest })`)
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
  {
    // server/ is plain CommonJS Node code — it needs require/module/process,
    // not browser globals. Same for the build scripts.
    files: ['server/**/*.{js,mjs}', 'scripts/**/*.js', 'vite.config.js'],
    languageOptions: {
      globals: globals.node,
    },
  },
  {
    // src/components/charts/** is vendored shadcn-chart code, and
    // src/features/assistant/ai-elements/** is vendored Vercel AI Elements.
    // The refs-during-render pattern is how those animation internals work;
    // rewriting them risks breaking live code to satisfy a lint rule.
    files: ['src/components/charts/**/*.{js,jsx}', 'src/features/assistant/ai-elements/**/*.{js,jsx}'],
    rules: {
      'react-hooks/refs': 'off',
    },
  },
  {
    // Fetch-on-mount inside useEffect is the codebase's established data-
    // loading idiom (useFunds, useHoldings, useInstrument...). The rule fires
    // on every one of them without pointing at an actual bug.
    files: ['src/**/*.{js,jsx}'],
    rules: {
      'react-hooks/set-state-in-effect': 'off',
    },
  },
])
