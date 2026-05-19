// ESLint flat config for the Agent Shield console.
//
// Elydora upstream shipped NO ESLint config (tech_stack.md §3.3 / cicd.md §2 —
// "Elydora ships none; we add the lint gate"). This config ADDS the gate that
// the CI `console` job (.github/workflows/ci.yml -> `npm run lint`) requires,
// WITHOUT rewriting the inherited Elydora source (W1 directive: bring the
// console up "UNCHANGED"). Accordingly, stylistic / strictness rules that the
// pre-existing Elydora code does not already satisfy are relaxed to "warn" or
// "off" so the gate is green on the unchanged code while still catching real
// correctness regressions in the Governance section we add in later weeks.
// `eslint .` exits non-zero only on ERRORS, so warnings keep CI green.

import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import nextPlugin from '@next/eslint-plugin-next';
import globals from 'globals';

export default tseslint.config(
  {
    // Generated / build / vendor — never linted.
    ignores: [
      '.next/**',
      'out/**',
      'node_modules/**',
      'next-env.d.ts',
      // AUTO-GENERATED from contracts/*.schema.json by contracts/codegen.
      // Source of truth is contracts/; do not lint the generated artifact.
      'src/types/contracts.d.ts',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx,mjs,js}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: {
      'react-hooks': reactHooks,
      '@next/next': nextPlugin,
    },
    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs['core-web-vitals'].rules,
      // react-hooks: enable the two classic, stable rules explicitly rather
      // than spreading eslint-plugin-react-hooks@7's recommended superset —
      // v7 promoted many "you-might-not-need-an-effect" heuristics
      // (set-state-in-effect, purity, immutability, …) to ERROR, which the
      // inherited Elydora source (kept UNCHANGED per W1) does not satisfy.
      // rules-of-hooks is the only true bug-class rule → ERROR; deps → warn.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // Relaxed for the inherited Elydora code (kept "UNCHANGED" per W1):
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      'no-empty': ['warn', { allowEmptyCatch: true }],
    },
  },
  {
    files: ['*.mjs', 'eslint.config.mjs', 'postcss.config.mjs', 'next.config.ts'],
    languageOptions: { globals: { ...globals.node } },
  },
);
