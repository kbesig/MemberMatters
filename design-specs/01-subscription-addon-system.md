# Spec 01: Subscription Addon System

## Summary

Introduce a configurable subscription add-on system that allows admins to define extra line items (e.g., additional member charges, storage upgrades, equipment rentals, shelf rentals) that can be attached to members' Stripe subscriptions.

## Dependencies

- None (foundation spec)

## Data Model

### `SubscriptionAddon` (new model in `api_admin_tools/models.py`)

Represents a purchasable add-on product/price in Stripe.

```python
class SubscriptionAddon(models.Model):
    ADDON_TYPES = [
        ("additional_member", "Additional Member"),
        ("storage_upgrade", "Storage Upgrade"),
        ("priority_support", "Priority Support"),
        ("equipment_rental", "Equipment Rental"),
        ("shelf_rental", "Shelf Rental"),
        ("custom", "Custom Add-on"),
    ]

    id = AutoField(primary_key=True)
    name = CharField(max_length=100)
    description = CharField(max_length=250, blank=True)
    stripe_price_id = CharField(max_length=100, unique=True, blank=True)
    stripe_product_id = CharField(max_length=100, blank=True)
    addon_type = CharField(max_length=50, choices=ADDON_TYPES)
    visible = BooleanField(default=True)
    currency = CharField(max_length=3, default="aud")
    cost = IntegerField()  # in cents
    interval_count = IntegerField(default=1)
    interval = CharField(max_length=10, choices=[("month","month"),("week","week"),("day","day")], default="month")
    max_quantity = IntegerField(default=10)
    min_quantity = IntegerField(default=1)
    stripe_synced = BooleanField(default=False)
    last_stripe_sync = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        unique_together = [["name", "addon_type"]]
```

### Stripe Sync Methods on `SubscriptionAddon`

| Method | Behavior |
|--------|----------|
| `create_stripe_product_and_price()` | Creates Stripe Product + Price. Sets `stripe_product_id`, `stripe_price_id`, `stripe_synced=True`. If product already exists, updates it. |
| `update_stripe_product()` | Updates Stripe Product name/description/metadata. |
| `update_stripe_price()` | Creates a **new** Stripe Price (Stripe doesn't allow modifying prices), archives the old one, updates `stripe_price_id`. |
| `delete_stripe_objects()` | Archives (deactivates) Stripe Product and Price. |
| `check_existing_stripe_product()` | Searches Stripe for a product matching by `django_id` metadata or name+type. |
| `clean()` | Validates no duplicate name+addon_type combinations. |
| `get_object()` | Returns serialized dict for API responses. |

### Stripe Product/Price Metadata

When creating Stripe objects, include this metadata:

```python
metadata = {
    "addon_type": self.addon_type,
    "django_id": str(self.id),
}
```

## Constance Configuration

Add to `membermatters/constance_config.py`:

```python
"CURRENT_ADDITIONAL_MEMBER_ADDON": (
    "",
    "The ID of the current additional member addon for billing group pricing locks. Leave empty if none configured.",
),
"CURRENT_SHELF_RENTAL_ADDON": (
    "",
    "The ID of the current shelf rental addon for shelf rental pricing. Leave empty if none configured.",
),
```

Add fieldsets:

```python
("Billing Groups", ("CURRENT_ADDITIONAL_MEMBER_ADDON",)),
("Shelf Rental", (
    "CURRENT_SHELF_RENTAL_ADDON",
    "SHELF_RENTAL_ASSIGNMENT_EMAIL_SUBJECT",
    "SHELF_RENTAL_ASSIGNMENT_EMAIL_BODY",
)),
```

## API Endpoints

### Admin Endpoints (requires staff permission)

#### `GET /api/admin/addons/`

List all subscription addons.

**Response:** `200 OK`
```json
[
  {
    "id": 1,
    "name": "Additional Member",
    "description": "Add a member to your billing group",
    "addon_type": "additional_member",
    "addon_type_display": "Additional Member",
    "visible": true,
    "currency": "aud",
    "cost": 5000,
    "cost_display": "$50.00",
    "interval_count": 1,
    "interval": "month",
    "max_quantity": 10,
    "min_quantity": 1,
    "stripe_synced": true
  }
]
```

#### `POST /api/admin/addons/`

Create a new subscription addon. Automatically creates Stripe Product + Price.

**Request Body:**
```json
{
  "name": "Additional Member",
  "description": "Add a member to your billing group",
  "addon_type": "additional_member",
  "currency": "aud",
  "cost": 5000,
  "interval": "month",
  "interval_count": 1,
  "visible": true
}
```

**Response:** `201 Created` — returns the addon object.

**Error cases:**
- `400` if duplicate name+type
- `500` if Stripe sync fails (addon still created locally, `stripe_synced=false`)

#### `GET /api/admin/addons/<id>/`

Get a single addon by ID.

#### `PUT /api/admin/addons/<id>/`

Update an addon. Updates Stripe Product metadata. If cost/interval changed, creates new Stripe Price and archives old one.

#### `DELETE /api/admin/addons/<id>/`

Delete an addon. Archives Stripe Product + Price first.

#### `GET/PUT /api/admin/addons/current-additional-member/`

Get or set the `CURRENT_ADDITIONAL_MEMBER_ADDON` constance config value. Used to designate which addon is used for billing group member charges.

**GET Response:**
```json
{
  "addon_id": "1",
  "addon": { /* full addon object */ }
}
```

**PUT Request:**
```json
{ "addon_id": "1" }
```

### User Endpoints (requires authentication)

#### `GET /api/billing/addons/`

List all visible subscription addons available to members.

**Response:** `200 OK` — array of addon objects (only where `visible=True`).

#### `POST /api/billing/addons/manage/`

Add or remove an addon from the member's active subscription.

**Request Body:**
```json
{
  "addon_id": 1,
  "action": "add",       // "add" or "remove"
  "quantity": 1
}
```

**Behavior:**
- Validates member has an active Stripe subscription
- For `add`: creates a new subscription item via `stripe.SubscriptionItem.create()` with `proration_behavior="create_prorations"`
- For `remove`: finds and deletes the subscription item via `stripe.SubscriptionItem.delete()`

**Response:** `200 OK`
```json
{
  "success": true,
  "message": "Add-on added/removed successfully"
}
```

## Migrations

- `api_admin_tools/migrations/0012_subscriptionaddon.py` — Create SubscriptionAddon table
- `api_admin_tools/migrations/0014_add_unique_constraint_to_subscription_addon.py` — Add unique_together constraint
- `api_admin_tools/migrations/0015_add_shelf_rental_models.py` — Add `shelf_rental` to ADDON_TYPES

## Frontend Changes

### Admin Addon Management

Add addon CRUD UI within the existing admin tools section:
- Table listing all addons with name, type, cost, interval, Stripe sync status
- Create/Edit dialog with all fields
- Delete confirmation
- "Set as current additional member addon" action
- Stripe sync status indicator

### User Addon Display

- Show available addons during plan signup flow
- Show active addons on the Membership Plan page
- Add/remove addon buttons with confirmation dialogs

## Testing Checklist

- [ ] Create addon via admin API, verify Stripe Product + Price created
- [ ] Update addon cost, verify new Stripe Price created and old one archived
- [ ] Delete addon, verify Stripe objects archived
- [ ] List addons as user, verify only visible addons returned
- [ ] Add addon to active subscription, verify subscription item created with proration
- [ ] Remove addon from subscription, verify subscription item deleted
- [ ] Verify unique constraint prevents duplicate name+type combinations
- [ ] Verify constance config `CURRENT_ADDITIONAL_MEMBER_ADDON` can be set/read
