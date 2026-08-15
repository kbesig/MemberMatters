# RocMakers MemberMatters

RocMakers' membership portal — a fork of [MemberMatters](https://github.com/membermatters/MemberMatters). This repo is for our organisation and volunteer engineers, not a public product page.

Upstream docs cover the generic product, Docker Hub images, hardware, and other makerspaces. Use those when you need them; this README is only what you need to work here.

## This fork

We track upstream and add RocMakers-specific behaviour:

- Billing groups (households) and subscription add-ons
- Shelf rental
- Extra profile fields (address, birthdate, admin notes)
- One-off scripts to import members and households from the legacy system

Keep RocMakers-only changes easy to spot so we can pull upstream updates without a fight.

## Local development

Vue/Quasar frontend in `src-frontend`, Django backend in `memberportal`. The frontend dev server proxies `/api` to `localhost:8000`, so Django must run there.

1. From the repo root, install pre-commit hooks:

   ```bash
   npm install
   ```

   Husky and lint-staged run eslint/prettier on frontend files and black on Python.

2. Backend: [memberportal/README.md](memberportal/README.md) — venv, migrate, load fixtures, `runserver` on port 8000.

3. Frontend: [src-frontend/README.md](src-frontend/README.md) — Node 18 via nvm, `npm install`, `npm run dev`. Open `http://127.0.0.1:8080/`.

Fixture login is `default@example.com` / `MemberMatters!`. Create your own account, promote it in Django admin at `http://localhost:8080/admin/profile/user/` (super user, staff, and admin), then change or remove the default admin.

## Working on the repo

- Branch from `main` as `feature/<short-name>`. Open a PR back into `main`.
- Do not push directly to `main`.
- Pre-commit hooks must pass. Write for the next volunteer: clear names, comments where needed, no clever shortcuts.
- If a change would also help upstream, say so in the PR.

The `upstream` remote points at `membermatters/MemberMatters`. We merge their work into this fork periodically.

## Other docs

Upstream docs still in this tree; they may mention Docker Hub or other organisations:

- [memberportal/README.md](memberportal/README.md) — Django backend
- [src-frontend/README.md](src-frontend/README.md) — Vue frontend
- [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) — Docker install
- [docs/POST_INSTALL_STEPS.md](docs/POST_INSTALL_STEPS.md) — production config
- [CHANGELOG.md](CHANGELOG.md) — upstream changelog

## License

Same as upstream: [MIT](LICENSE).
