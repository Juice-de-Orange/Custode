## What and why

<!-- What does this change and which problem does it solve? Link the issue: Closes #123 -->

## How it was tested

<!-- make lint / make lint-imports / the pytest and vitest files you ran. A bug fix comes with a
     regression test. Endpoint changed? `make openapi` run and the generated client committed. -->

## Checklist

- [ ] Commits follow Conventional Commits with the module as scope and are signed off (`git commit -s`)
- [ ] Module boundaries respected (`make lint-imports` green), no cross-module import
- [ ] New table or column with tenant data: RLS policy, grants for the four roles, negative test
- [ ] User-facing text in both i18n catalogues (de, en); `BRAND_NAME` never hard-coded
- [ ] `CHANGELOG.md` updated; a lesson learned → `docs/BUGLOG.md`
- [ ] No `.env`, tokens, hostnames or personal data in code, tests or docs
