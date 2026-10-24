// 프론트엔드 코드 검사 설정. `npm run lint`(또는 저장소 루트의 `just lint`)로 돌립니다.
//
// 바탕은 셋입니다 — ESLint 의 권장 규칙, typescript-eslint 의 권장 규칙(타입 정보를
// 쓰지 않는 판), React 훅 규칙 둘. 검사 대상은 `src` 의 .ts/.tsx 입니다.
import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    plugins: { 'react-hooks': reactHooks },
    rules: {
      // 훅은 컴포넌트·훅의 맨 위에서만, 늘 같은 차례로 부릅니다.
      'react-hooks/rules-of-hooks': 'error',
      // 효과·메모의 의존 목록에 빠진 값이 있으면 경고합니다. 일부러 뺀 자리는 그 줄에
      // `eslint-disable-next-line react-hooks/exhaustive-deps` 와 까닭을 적습니다.
      'react-hooks/exhaustive-deps': 'warn',
      // 쓰지 않는 이름을 알립니다. 밑줄로 시작하는 이름은 일부러 비워 둔 자리로 봅니다.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
      // 아래 규칙은 끕니다. 지금 코드에 그 규칙에 걸리는 자리가 있습니다.
      'prefer-const': 'off',
    },
  },
)
