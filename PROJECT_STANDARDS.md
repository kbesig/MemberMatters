# MemberMatters Project Standards & Conventions

Comprehensive guide to code style, naming conventions, and project patterns across MemberMatters.

---

## Table of Contents
1. [Django Backend Standards](#django-backend-standards)
2. [Vue 3/TypeScript Frontend Standards](#vue-3typescript-frontend-standards)
3. [General Project Standards](#general-project-standards)

---

# Django Backend Standards

## Code Formatting & Linting

**Formatter**: Black (`black==25.1.0`)
- Enforced via GitHub Actions: `.github/workflows/black.yml`
- Default line length: 88 characters
- Single trailing comma in multi-line constructs (Black default)
- Enforces consistent code style across all PRs

**Commit Check**: 
```yaml
- uses: psf/black@stable  # Run on all PRs
```

## Import Organization

**Pattern**: Standard library → Django → Third-party → Local imports

```python
# Standard library
import os
import sys
import json
import logging
from datetime import timedelta, datetime
from typing import Optional

# Third-party
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.conf import settings
from rest_framework import status, permissions
from constance import config
import stripe

# Local
from profile.models import User, Profile
from api_general.models import SiteSession
from services.emails import send_single_email
```

## Model Patterns

### Basic Model Structure

```python
from django.db import models
from django_prometheus.models import ExportModelOperationsMixin

class Kiosk(ExportModelOperationsMixin("kiosk"), models.Model):
    """Model that tracks kiosk devices and their status."""
    
    id = models.AutoField(primary_key=True)
    name = models.CharField("Name", max_length=30, unique=True)
    kiosk_id = models.CharField("Kiosk Id", max_length=70, unique=True)
    ip_address = models.GenericIPAddressField(
        "IP Address of device", unique=True, null=True, blank=True
    )
    last_seen = models.DateTimeField(null=True)
    authorised = models.BooleanField("Is this kiosk authorised?", default=False)
    
    def checkin(self):
        """Update last_seen timestamp when device checks in."""
        self.last_seen = timezone.now()
        self.save()
    
    def get_unavailable(self):
        """Check if device hasn't been seen in 5 minutes."""
        if self.last_seen:
            if timezone.now() - timedelta(minutes=5) > self.last_seen:
                return True
        return False
    
    def __str__(self):
        return self.name
```

### Key Patterns

1. **ExportModelOperationsMixin**: Adds Prometheus metrics tracking
   - Usage: `class Model(ExportModelOperationsMixin("model-name"), models.Model)`
   - Argument is the metric name (used in Prometheus labels)

2. **AutoField IDs**: Explicitly defined for clarity
   ```python
   id = models.AutoField(primary_key=True)
   ```

3. **Foreign Keys**: Always specify `on_delete`
   ```python
   user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
   door = models.ForeignKey("access.Doors", on_delete=models.CASCADE, null=True, blank=True)
   ```

4. **Field Descriptions**: First argument provides human-readable name
   ```python
   all_members = models.BooleanField("Members have access by default", default=False)
   ```

5. **__str__ Method**: Always include for admin interface
   ```python
   def __str__(self):
       return f"{self.user.get_full_name()} - {self.description}"
   ```

## Views Structure

### APIView Pattern

```python
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
import logging

logger = logging.getLogger("billing")

class StripeAPIView(APIView):
    """Base class for Stripe-related API endpoints."""
    
    permission_classes = (permissions.IsAdminUser,)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not config.ENABLE_STRIPE:
            return
        try:
            stripe.api_key = config.STRIPE_SECRET_KEY
            stripe.api_version = "2025-06-30.basil"
        except OperationalError as error:
            capture_exception(error)


class MemberBucksAddCard(StripeAPIView):
    """
    get: gets the client secret used to add new card details.
    post: saves the customers card details.
    """
    
    def get(self, request):
        profile = request.user.profile
        # Implementation...
        return Response({"clientSecret": secret})
    
    def post(self, request):
        # Implementation...
        return Response(status=status.HTTP_200_OK)
```

### Key Patterns

1. **Docstring Format**: HTTP methods with descriptions
   ```python
   """
   get: This method returns the site config.
   post: Attempts to authenticate a user.
   """
   ```

2. **Permission Classes**: As tuple
   ```python
   permission_classes = (permissions.AllowAny,)
   permission_classes = (permissions.IsAdminUser,)
   ```

3. **Response Pattern**: Always use `Response()` with optional status
   ```python
   return Response(data_dict)
   return Response(status=status.HTTP_200_OK)
   return Response(statusObject, status=status.HTTP_503_SERVICE_UNAVAILABLE)
   ```

## Admin Interface Patterns

```python
from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget

class UserResource(resources.ModelResource):
    """Resource for bulk user import/export."""
    
    first_name = fields.Field(
        column_name="first_name",
        attribute="first_name",
        widget=ForeignKeyWidget(Profile, "first_name"),
    )
    
    def dehydrate_first_name(self, user):
        """Custom export field logic."""
        try:
            return user.profile.first_name
        except Exception:
            return ""
    
    def before_import_row(self, row, **kwargs):
        """Hook for data preprocessing during import."""
        user, created = User.objects.get_or_create(
            email=row["email"],
            defaults={"email": row["email"], "admin": row["admin"]},
        )
        if created:
            Profile.objects.create(user=user, first_name=row["first_name"])


class UserAdmin(ImportExportModelAdmin):
    resource_class = UserResource
    list_display = ('email', 'admin', 'staff')
```

## Logging Patterns

### Logger Setup

```python
import logging

# Module-level logger with specific module name
logger = logging.getLogger("billing")  # or "access", "general", "profile"
```

### Available Logger Names
- `"access"` - Door/interlock access control
- `"billing"` - Stripe and subscription handling
- `"general"` - General API operations
- `"profile"` - User profile management
- `"discord"` - Discord integration
- `"slack"` - Slack integration
- `"emails"` - Email service
- `"sms"` - SMS service
- `"api_general:tasks"` - Celery tasks for general
- `"api_access:tasks"` - Celery tasks for access

### Log Level Configuration
Controlled by environment variables (uppercase with `MM_` prefix):
- `MM_LOG_LEVEL_ACCESS=INFO`
- `MM_LOG_LEVEL_BILLING=INFO`
- `MM_LOG_LEVEL_GENERAL=INFO`

### Logging Usage

```python
logger.info("User signed up: %s", user.email)
logger.warning(
    f"Tried to process log_access but profile with card ID {card_id} does not exist."
)
logger.error("Error receiving message from device: %s", e)
```

### Event Logging to Database

```python
from profile.models import log_event

# Simple event
log_event(
    description=f"Device connected.",
    event_type="generic",
    data="",
)

# Door event
log_event(
    description=f"{member_id} swiped door.",
    event_type="door",
    data="",
    door=door_object,
)

# Log types: "generic", "stripe", "memberbucks", "profile", "door", "interlock", "email", "admin", "error", "xero"
```

## Error Handling

### Try-Except Pattern

```python
logger = logging.getLogger("access")

try:
    profile = Profile.objects.get(rfid=card_id)
    self.device.log_access(profile.user.id, success=True)
except Profile.DoesNotExist:
    logger.warning(f"Profile with card ID {card_id} does not exist.")
    self.send_ack("log_access")
    return True
except ObjectDoesNotExist:
    self.send_json({"command": "error", "reason": "invalid_card_id"})
    return True
```

### Sentry Integration

```python
from sentry_sdk import capture_exception

try:
    stripe.api_key = config.STRIPE_SECRET_KEY
except OperationalError as error:
    capture_exception(error)
    # Continue gracefully
```

### Database Errors

```python
from django.db.utils import OperationalError

try:
    # Database operation
except OperationalError as error:
    capture_exception(error)
    # Handle gracefully or re-raise
```

## Testing Patterns

### Test File Organization

```python
#!/usr/bin/env python3
"""
Test script to verify feature X functionality
"""

import os
import sys
import django

# Setup path and Django
sys.path.insert(0, "/path/to/memberportal")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "membermatters.settings")
django.setup()


def test_helper_methods_exist():
    """Test that helper methods are defined."""
    from api_module.views import SomeClass
    
    method_names = ["method_one", "method_two"]
    
    for method_name in method_names:
        if hasattr(SomeClass, method_name):
            print(f"✅ Method {method_name} exists")
        else:
            print(f"❌ Method {method_name} missing")
            return False
    
    return True


def test_model_fields():
    """Test that model has expected fields."""
    from profile.models import SomeModel
    
    instance = SomeModel()
    if hasattr(instance, "field_name"):
        print("✅ field_name exists")
    else:
        print("⚠️  field_name missing (needs migration)")
    
    return True


if __name__ == "__main__":
    print("Testing feature...")
    
    try:
        test_helper_methods_exist()
        test_model_fields()
        print("✅ All tests passed!")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)
```

### Key Patterns
- Prefix test functions with `test_`
- Use print for output with emoji indicators (✅, ❌, ⚠️)
- Use try-except for model existence checks

---

# Vue 3/TypeScript Frontend Standards

## Code Formatting & Linting

### Prettier Configuration (`.prettierrc`)

```json
{
  "singleQuote": true,
  "semi": true
}
```

**Apply formatting**:
```bash
npm run format  # Prettier on all supported files
```

### ESLint Configuration (`.eslintrc.cjs`)

Key settings:
- **Parser**: `@typescript-eslint/parser`
- **Vue Rules**: `plugin:vue/vue3-essential` (Priority A)
- **TypeScript Rules**: `plugin:@typescript-eslint/recommended`
- **Prettier Integration**: Resolves conflicts between ESLint and Prettier

**Code styling rules**:
```javascript
quotes: ['warn', 'single', { avoidEscape: true }]  // Single quotes
'prefer-promise-reject-errors': 'off'              // Allow any rejection
'@typescript-eslint/explicit-function-return-type': 'off'  // No return types required
'no-debugger': process.env.NODE_ENV === 'production' ? 'error' : 'off'
```

**Run linting**:
```bash
npm run lint        # Format + ESLint fix
npm run lint:precommit  # Pre-commit version
```

## TypeScript Configuration

### tsconfig.json Path Aliases

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@components/*": ["src/components/*"],
      "@icons/*": ["src/icons/*"],
      "@store/*": ["src/store/*"],
      "@mixins/*": ["src/mixins/*"],
      "@assets/*": ["src/assets/*"],
      "types/*": ["src/types/*"],
      "boot/*": ["src/boot/*"]
    }
  }
}
```

**Usage in components**:
```typescript
import SavedNotification from '@components/SavedNotification.vue';
import formMixin from '@mixins/formMixin';
import { MemberProfile } from 'types/member';
```

## Component Structure

### Options API Pattern

```vue
<template>
  <div class="profile-form">
    <q-form ref="formRef">
      <q-input
        v-model="form.email"
        outlined
        :debounce="debounceLength"
        :label="$t('form.email')"
        :rules="[(val) => validateEmail(val) || $t('validation.invalidEmail')]"
        @update:model-value="saveChange('email')"
      >
        <template v-slot:append>
          <saved-notification
            :success="saved.email"
            show-text
            :error="saved.error"
          />
        </template>
      </q-input>
    </q-form>
  </div>
</template>

<script>
import { mapGetters, mapActions } from 'vuex';
import SavedNotification from '@components/SavedNotification.vue';
import formMixin from '@mixins/formMixin';

export default {
  name: 'ProfileForm',
  components: {
    SavedNotification,
  },
  mixins: [formMixin],
  props: {
    // Props if needed
  },
  data() {
    return {
      debounceLength: 500,
      form: {
        email: '',
        firstName: '',
        lastName: '',
      },
      saved: {
        error: false,
        email: false,
        firstName: false,
      },
    };
  },
  computed: {
    ...mapGetters('profile', ['getFullName']),
  },
  methods: {
    ...mapActions('profile', ['updateProfile']),
    saveChange(field) {
      // Implementation
    },
    validateEmail(val) {
      // Implementation
    },
  },
  mounted() {
    // Initialization
  },
};
</script>

<style scoped>
.profile-form {
  /* Styles */
}
</style>
```

### Key Component Patterns

1. **Component Registration**
   ```javascript
   import SavedNotification from '@components/SavedNotification.vue';
   
   export default {
     name: 'ComponentName',  // PascalCase
     components: { SavedNotification },
   }
   ```

2. **Props with Types**
   ```javascript
   props: {
     title: {
       type: String,
       required: true,
     },
     linkText: {
       type: String,
       required: false,
       default: null,
     },
     links: {
       type: Array,
       required: false,
       default: () => [],
     },
     routerLink: {
       type: [Object, Boolean],
       required: false,
       default: null,
     },
   }
   ```

3. **Data Structure**
   ```javascript
   data() {
     return {
       form: {
         email: '',
         firstName: '',
       },
       saved: {
         error: false,
         email: false,
       },
     };
   }
   ```

4. **Form Debounce Pattern**
   ```vue
   <q-input
     v-model="form.email"
     :debounce="debounceLength"
     @update:model-value="saveChange('email')"
   />
   ```

## Type Definitions with Zod

### Type Definition Pattern

```typescript
// src/types/member.ts
import { z } from 'zod';

export const MemberStateSchema = z.enum([
  'noob',
  'active',
  'inactive',
  'accountonly',
]);
export type MemberState = z.infer<typeof MemberStateSchema>;

export const MemberProfileSchema = z.object({
  id: z.number(),
  admin: z.boolean(),
  email: z.string(),
  screenName: z.string(),
  name: z.object({
    first: z.string(),
    last: z.string(),
    full: z.string(),
  }),
  phone: z.string(),
  state: MemberStateSchema,
  memberBucks: z.object({
    balance: z.number(),
    lastPurchase: z.string().nullable(),
  }),
});

export type MemberProfile = z.infer<typeof MemberProfileSchema>;
```

### Benefits of Zod Pattern
- Runtime validation of API responses
- TypeScript types inferred from schemas
- Single source of truth for both validation and types
- Type safety when working with API data

## Store (Vuex) Structure

### Module Pattern

```typescript
// src/store/modules/tools.ts
import { api } from 'boot/axios';
import { MetricsApi, MetricsApiSchema } from 'types/api/metrics';

export default {
  namespaced: true,
  
  state: {
    lastSeen: [],
    recentSwipes: [],
    memberList: [],
    statistics: {} as MetricsApi,
  },
  
  getters: {
    lastSeen: (state) => state.lastSeen,
    recentSwipes: (state) => state.recentSwipes,
    memberList: (state) => state.memberList,
    statistics: (state) => state.statistics,
  },
  
  mutations: {
    setLastSeen(state, payload) {
      state.lastSeen = payload;
    },
    setRecentSwipes(state, payload) {
      state.recentSwipes = payload;
    },
    setStatistics(state, payload) {
      state.statistics = payload;
    },
  },
  
  actions: {
    getLastSeen({ commit }) {
      return new Promise((resolve, reject) => {
        api
          .get('/api/tools/lastseen/')
          .then((result) => {
            commit('setLastSeen', result.data);
            resolve();
          })
          .catch((error) => {
            reject();
            throw error;
          });
      });
    },
  },
};
```

### Key Patterns

1. **Action Returns Promise** for async/await support
2. **Two-Step Update**: Action → Mutation → State
3. **Commit Naming**: `set{FieldName}` convention
4. **Error Handling**: Reject promise and re-throw error

## Component Naming & Organization

### Naming Conventions

| Item | Convention | Example |
|------|-----------|---------|
| Components | PascalCase | `ProfileForm.vue` |
| Methods/Functions | camelCase | `saveChange()` |
| Props | camelCase | `:enable-feature` |
| Event Handlers | camelCase | `@click="handleClick"` |
| Data Properties | camelCase | `form.firstName` |
| Store Mutations | camelCase prefixed | `setUserProfile` |
| Store Actions | camelCase | `fetchUser` |

### File Organization

```
src/
├── components/        # Reusable Vue components
│   ├── ProfileForm.vue
│   ├── DashboardCard.vue
│   └── SavedNotification.vue
├── pages/            # Page components (routes)
│   └── ProfilePage.vue
├── layouts/          # Layout components
│   └── MainLayout.vue
├── store/
│   ├── modules/      # Vuex modules
│   │   ├── profile.js
│   │   ├── auth.js
│   │   └── tools.ts
│   └── index.js
├── router/           # Vue Router config
│   └── routes.ts
├── types/            # TypeScript type definitions
│   ├── member.ts
│   ├── api/
│   │   └── metrics.ts
│   └── subscriptions.ts
├── i18n/             # Internationalization
│   ├── en-US/
│   ├── en-AU/
│   └── sv-SE/
├── mixins/           # Vue mixins
│   └── formMixin.js
├── boot/             # App initialization
│   └── axios.js
└── css/              # Global styles
```

## i18n (Internationalization) Patterns

### Message File Structure

```typescript
// src/i18n/en-US/index.ts
export default {
  form: {
    email: 'Email Address',
    firstName: 'First Name',
    lastName: 'Last Name',
    mobile: 'Mobile Number',
    screenName: 'Screen Name',
  },
  validation: {
    invalidEmail: 'Please enter a valid email address',
    cannotBeEmpty: 'This field cannot be empty',
    invalidPhone: 'Please enter a valid phone number',
  },
  error: {
    error: 'Error',
    contactUs: 'Please contact us for help if you continue to see this error.',
    loginFailed: 'Your username or password was incorrect.',
    requestFailed: 'Sorry, we\'re having trouble performing that action. Please try again later.',
    pageNotFound: 'Page not found',
    400: 'Sorry, there was an error with your request. (Error 400)',
    401: 'Sorry, you need to be logged in to access this page. (Error 401)',
    403: 'Sorry, you don\'t have permission to access this page. (Error 403)',
    500: 'Sorry, there was a server error. Please try again later. (Error 500)',
  },
};
```

### Usage in Templates

```vue
<template>
  <div>
    <q-input :label="$t('form.email')" />
    <div class="error">{{ $t('error.requestFailed') }}</div>
  </div>
</template>
```

### Usage in Scripts

```typescript
import { useI18n } from 'vue-i18n';

export default {
  setup() {
    const { t } = useI18n();
    
    const handleError = () => {
      console.error(t('error.error'));
    };
  },
};
```

## API Integration Patterns

### Axios Setup

```typescript
// src/boot/axios.ts
import axios from 'axios';

const api = axios.create({
  baseURL: process.env.API_BASE_URL || 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
});

export { api };
```

### Store Action with API Call

```typescript
actions: {
  getSiteConfig({ commit }) {
    return new Promise((resolve, reject) => {
      api
        .get('/api/config/')
        .then((result) => {
          commit('setSiteName', result.data.general.siteName);
          commit('setFeatures', result.data.features);
          resolve();
        })
        .catch((error) => {
          console.error('Failed to load config:', error);
          reject();
          throw error;
        });
    });
  },
}
```

## Error Handling & User Feedback

### User-Facing Error Messages

```vue
<template>
  <div v-if="error" class="error-message">
    {{ $t(`error.${errorCode}`) }}
  </div>
</template>

<script>
export default {
  data() {
    return {
      error: false,
      errorCode: 'requestFailed',
    };
  },
  methods: {
    async saveProfile() {
      try {
        await this.updateProfile(this.form);
        this.$q.notify({
          type: 'positive',
          message: this.$t('success.profileUpdated'),
        });
      } catch (error) {
        this.error = true;
        this.errorCode = error.response?.status || 'requestFailed';
      }
    },
  },
};
</script>
```

### Console Logging Pattern

```typescript
if (process.env.DEV) {
  console.error('Error during service worker registration:', err);
}
```

---

# General Project Standards

## Git Commit Messages

### Format
- Lower case start with imperative verb
- Short, concise description
- No strict conventional commits format

### Examples
```
shelf rental initial build out
extra error handling
aligning billing cycle to first of month
billing mismatch issues
fixed left nav not always displaying properly
added ability for member to leave billing group
```

### Multi-line Commits
```
fixed billing group subscription status

- Updated subscription state transitions
- Added proper error handling for edge cases
- Fixed race condition in state updates
```

## Documentation Standards

### README Structure
- Brief description at top
- Main Features list with dashes
- Getting Started section
- Compatibility info
- Updates/Releases link
- Hardware/Integration sections as needed

### Markdown Formatting
- Code blocks with language tags
- Bold for emphasis: **term**
- Italics for references: *variable*
- Link to sections: [Section Name](#section-name)

### Changelog Format (CHANGELOG.md)
```markdown
## [v3.7.0] - 2024-08-11

### Fixed
- specific bug that was fixed
- another specific issue resolved

### Changed
- what was modified
- behavior adjustments

### Added
- new feature description
- new capability
```

## Environment Variables

### Naming Convention
- All uppercase with `MM_` prefix
- Snake_case for compound names
- Example: `MM_LOG_LEVEL_ACCESS`, `MM_DB_LOCATION`

### Common Variables

**Database**:
```bash
MM_DB_LOCATION=db.sqlite3
MM_DB_ENGINE=mysql  # or postgresql
```

**Logging**:
```bash
MM_LOG_LOCATION=errors.log
MM_LOG_LEVEL_ACCESS=INFO
MM_LOG_LEVEL_BILLING=INFO
MM_LOG_LEVEL_GENERAL=INFO
```

**Stripe**:
```bash
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_API_VERSION=2025-06-30.basial
```

## Error Message Guidelines

### User-Facing Messages
✅ **Good**:
- "Sorry, we're having trouble performing that action. Please try again later."
- "Your username or password was incorrect."
- "Please contact us for help if you continue to see this error."

❌ **Bad**:
- "500 Internal Server Error"
- "Database connection failed"
- "TypeError: Cannot read property 'email' of undefined"

### Include Context
- Be friendly and helpful
- Suggest next steps when possible
- Include error codes for debugging: "(Error 404)"
- Provide contact info if user action needed

## Project Structure

```
MemberMatters/
├── memberportal/              # Django backend
│   ├── manage.py
│   ├── requirements.txt
│   ├── membermatters/         # Main settings
│   ├── profile/               # User profiles & auth
│   ├── access/                # Access control subsystem
│   ├── api_general/           # General API endpoints
│   ├── api_billing/           # Billing & Stripe
│   ├── api_access/            # Access API & WebSockets
│   ├── api_member_tools/      # Member tooling
│   ├── api_admin_tools/       # Admin interface
│   ├── services/              # Service integrations
│   ├── scripts/               # Utility scripts
│   ├── classes/               # Business logic classes
│   ├── fixtures/              # Initial data
│   └── db.sqlite3            # Dev database
├── src-frontend/              # Vue 3 frontend
│   ├── package.json
│   ├── tsconfig.json
│   ├── quasar.config.js
│   └── src/
│       ├── components/
│       ├── pages/
│       ├── store/
│       ├── types/
│       ├── router/
│       ├── i18n/
│       ├── boot/
│       └── css/
├── docker/                    # Docker configuration
├── docs/                      # Sphinx documentation
├── .github/workflows/         # CI/CD
└── .github/ISSUE_TEMPLATE/   # Issue templates
```

## CI/CD Workflows

### Python Linting (Black)
- File: `.github/workflows/black.yml`
- Trigger: On PRs
- Enforces code formatting consistency

### JavaScript Linting (ESLint)
- File: `.github/workflows/eslint.yml`
- Trigger: On PRs
- Runs: `npm run lint` in src-frontend

### Docker Builds
- Build images for PR/Release
- Multi-architecture (AMD64, ARM64)
- Pushes to Docker Hub

## Development Workflow

### Backend Development
```bash
cd memberportal
source venv/bin/activate
MM_LOG_LOCATION=errors.log MM_DB_LOCATION=db.sqlite3 python manage.py runserver
```

### Frontend Development
```bash
cd src-frontend
npm install
npm run dev
```

### Running Tests
```bash
# Backend tests
cd memberportal
python -m pytest tests/

# Frontend (if exists)
cd src-frontend
npm run test
```

### Code Formatting
```bash
# Format Python
black memberportal/

# Format Frontend
cd src-frontend && npm run format
```

---

## Summary Checklist for Contributors

### Before Committing
- [ ] Code follows Black style (Python)
- [ ] Code follows Prettier + ESLint rules (TypeScript/Vue)
- [ ] All imports organized properly
- [ ] Logger names match module purpose
- [ ] Error handling includes Sentry capture where appropriate
- [ ] User-facing errors use i18n strings
- [ ] Tests added for new functionality
- [ ] Commit message is lowercase, imperative verb

### For Python Code
- [ ] Models include `ExportModelOperationsMixin`
- [ ] Foreign keys specify `on_delete`
- [ ] `__str__` methods defined
- [ ] Docstrings use HTTP method format
- [ ] Module-level logger defined

### For Vue/TypeScript Code
- [ ] Components use PascalCase names
- [ ] Props have type definitions
- [ ] Type definitions use Zod schemas
- [ ] Error messages use i18n keys
- [ ] API calls return Promises
- [ ] Store mutations follow `set{Field}` pattern

---

Generated: March 2026
Based on: MemberMatters main branch standards and conventions
