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

You need **two processes running at the same time**:

- Django API in `memberportal` on port **8000**
- Vue/Quasar UI in `src-frontend` on port **8080**

The frontend proxies `/api` to `localhost:8000`, so if Django is not running, login and everything else will fail. You work in the browser at `http://127.0.0.1:8080/` — not on port 8000.

Keep two terminals open. Leave each server running.

Docker (`docs/GETTING_STARTED.md`) is the production-style install. Use the steps below to hack on this fork.

More detail lives in [memberportal/README.md](memberportal/README.md) (Linux/Windows, Stripe webhooks, Black) and [src-frontend/README.md](src-frontend/README.md) (linting, icons, other build targets).

### Prerequisites

- **Python 3.9+** (the backend README still says 3.7+; we use `black==25.1.0`, which needs 3.9+)
- **pip**
- **Node 18** via [nvm](https://github.com/nvm-sh/nvm): `nvm install 18`
- **MySQL client libraries** — needed to install the `mysqlclient` Python package even though local dev uses SQLite

On macOS:

```bash
brew install python3 mysql
```

On Ubuntu, see [memberportal/README.md](memberportal/README.md). You will also want `libpng-dev` for the frontend.

### 1. Pre-commit hooks (repo root)

From the **repo root** (this folder, not `memberportal` or `src-frontend`):

```bash
npm install
```

That installs Husky so eslint/prettier (frontend) and black (Python) run on commit. Do this once per clone. Pre-commit hooks must pass or your PR may be rejected.

### 2. Backend (terminal 1)

```bash
cd memberportal
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```

You should see `(venv)` in your prompt. Stay in this venv for every `manage.py` command.

If pip fails on Apple Silicon or newer macOS:

```bash
CFLAGS='-I/usr/local/opt/zlib/include -L/usr/local/opt/zlib/lib' pip3 install -r requirements.txt
```

On Windows, activate with `venv\Scripts\activate` and install from `requirements-win.txt`. See [memberportal/README.md](memberportal/README.md).

Point Django at local files. Without these env vars it tries production paths like `/usr/src/data/` and will fail:

```bash
export MM_LOG_LOCATION=errors.log
export MM_DB_LOCATION=db.sqlite3
```

Create the SQLite database and load the fixture user:

```bash
python3 manage.py migrate
python3 manage.py loaddata fixtures/initial.json
python3 manage.py runserver
```

You want: `Starting development server at http://127.0.0.1:8000/`

Leave this running. After model changes, run `migrate` again in this venv with the same env vars, or you will get errors like “column does not exist”.

You can also prefix each command instead of exporting:

```bash
MM_LOG_LOCATION=errors.log MM_DB_LOCATION=db.sqlite3 python3 manage.py migrate
```

### 3. Frontend (terminal 2)

```bash
cd src-frontend
nvm use 18
npm install
npm run dev
```

Open **http://127.0.0.1:8080/**

### 4. First login (fixture account)

Go to **http://127.0.0.1:8080/login** — that is the member portal, not Django admin.

| | |
|---|---|
| Email | `default@example.com` |
| Password | `MemberMatters!` |

This project has **no username**. Login is always email + password.

Django admin at `http://localhost:8080/admin/` is a **separate session**. Being logged in there does not log you into the Vue app, and the other way around.

### 5. “Membership is currently inactive”

The fixture user is supposed to show an orange banner: *Membership is currently inactive. This may affect access.* Login did not fail.

The fixture profile `state` is `noob` (“Needs Induction”). The dashboard shows that banner for any status other than `active` or `accountonly`. You may also see a subscription chip of **Inactive** — that is separate; the fixture has no Stripe plan.

Member states:

| State | Meaning |
|---|---|
| `noob` | New member, needs induction (fixture default) |
| `active` | Full member access |
| `inactive` | Membership turned off |
| `accountonly` | Account without membership |

Staff / superuser flags do **not** make membership `active`. To hide the banner, open the profile in Django admin at `http://localhost:8080/admin/profile/profile/` and set **State** to **Active**.

### 6. Create your own account (do this)

Do **not** create the user in Django admin if you want to log into the portal. That admin has no “set password” widget, so the account cannot log in until you fix it (see below).

1. Open **http://127.0.0.1:8080/register** and create an account. That hashes the password correctly.
2. Log in at **http://127.0.0.1:8080/login** with that **email** and password.
3. Log into Django admin with the fixture account (or any existing superuser) at `http://localhost:8080/admin/profile/user/`.
4. Open your new user. Tick **super user**, **staff**, and **admin**.
5. Open the linked profile at `http://localhost:8080/admin/profile/profile/` and set **State** to **Active** if you want the inactive banner gone.
6. Change or remove the default admin (`default@example.com`) once your account works.

Registration tries to send a verification email through Mailgun. Locally there is no valid Mailgun config (the API key default is `PLEASE_CHANGE_ME`, and the sending domain is empty). The portal now skips that email in local/dev and marks the account verified so you can log in. If you already saw *Sorry, we're having trouble performing that action*, the account was created — do **not** register again. Open the user in Django admin and tick **Email verified**, then log in.

### 7. If you already created the user in Django admin

You will not see a password + confirm form. The `password` field (if you notice it at all) stores a **hash**. Leaving it blank gives an unusable password. Typing a plaintext password there will not work for portal login.

Set the password from `memberportal` with the venv active and the same env vars. The “username” is the **email**:

```bash
cd memberportal
source venv/bin/activate
export MM_LOG_LOCATION=errors.log
export MM_DB_LOCATION=db.sqlite3
python3 manage.py changepassword you@example.com
```

It will prompt twice for the new password. Then log in at `http://127.0.0.1:8080/login`.

Or in the shell:

```bash
python3 manage.py shell
```

```python
from profile.models import User

u = User.objects.get(email="you@example.com")
u.set_password("your-password")
u.email_verified = True
u.save()
```

If login says the email is not verified, tick **Email verified** on the User in admin (admin-created users usually already have this).

### Day-to-day

Keep both terminals running. Re-run `migrate` after model changes. Stripe webhooks are optional; skip them unless you are working on billing (see [memberportal/README.md](memberportal/README.md)).

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
