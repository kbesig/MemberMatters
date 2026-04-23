# Spec 05: Shelf Rental System

## Summary

Allow members to request and rent physical shelves with automatic Stripe billing integration. Includes a member self-service request queue, admin assignment workflow, next-occupant promotion, and per-shelf locked pricing via subscription addons.

## Dependencies

- **Spec 01**: Subscription Addon System (SubscriptionAddon model with `shelf_rental` type)
- **Spec 02**: Flexible Billing (proration support for adding subscription items)
- **Spec 03**: Subscription Status Enhancement (active subscription check)

## Data Models

All models added to `profile/models.py`.

### `Shelf`

Represents a physical shelf that can be rented.

```python
class Shelf(models.Model):
    STATUS_CHOICES = [
        ("available", "Available"),
        ("occupied", "Occupied"),
        ("cancelled", "Cancelled - Next Occupant Assigned"),
    ]

    id = AutoField(primary_key=True)
    number = CharField(max_length=50, unique=True)  # shelf identifier/label
    current_member = ForeignKey("Profile", on_delete=SET_NULL, null=True, blank=True,
                                 related_name="current_shelves")
    next_member = ForeignKey("Profile", on_delete=SET_NULL, null=True, blank=True,
                              related_name="next_shelves")
    status = CharField(max_length=20, choices=STATUS_CHOICES, default="available")
    start_date = DateField(null=True, blank=True)
    next_available_date = DateField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ["number"]
```

### `ShelfRequest`

Member request queue for shelf rentals.

```python
class ShelfRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("assigned", "Assigned"),
        ("cancelled", "Cancelled"),
    ]

    id = AutoField(primary_key=True)
    member = ForeignKey("Profile", on_delete=CASCADE, related_name="shelf_requests")
    quantity = IntegerField(default=1)
    status = CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    requested_at = DateTimeField(auto_now_add=True)
    assigned_at = DateTimeField(null=True, blank=True)
    cancelled_at = DateTimeField(null=True, blank=True)
    notes = TextField(blank=True)

    class Meta:
        ordering = ["requested_at"]
```

### `MemberShelfAddon`

Locks shelf rental addon pricing at time of assignment. One record per shelf per member.

```python
class MemberShelfAddon(models.Model):
    id = AutoField(primary_key=True)
    member = ForeignKey("Profile", on_delete=CASCADE, related_name="shelf_addons")
    shelf = OneToOneField(Shelf, on_delete=CASCADE, related_name="addon")
    addon = ForeignKey("api_admin_tools.SubscriptionAddon", on_delete=CASCADE,
                        related_name="shelf_rentals")
    locked_cost = IntegerField()  # cents at time of assignment
    locked_currency = CharField(max_length=3, default="aud")
    locked_interval = CharField(max_length=10)
    locked_interval_count = IntegerField(default=1)
    date_locked = DateTimeField(auto_now_add=True)
    stripe_subscription_item_id = CharField(max_length=255, blank=True, null=True)
    stripe_price_id = CharField(max_length=255, blank=True, null=True)
```

## New Django App

Create `memberportal/api_shelf_rental/` with:
- `__init__.py`
- `views.py`
- `urls.py`
- (Models live in `profile/models.py` to keep all billing-related models together)

Register in `INSTALLED_APPS` and include URLs in project `urls.py`.

## User API Endpoints

Base path: `/api/shelf-rental/`

### `GET /api/shelf-rental/my-shelves/`

Get the member's current shelves and pending requests.

**Response:**
```json
{
  "shelves": [
    {
      "id": 1,
      "number": "A-01",
      "status": "occupied",
      "start_date": "2025-01-15",
      "pricing": {
        "cost": 2000,
        "cost_display": "$20.00",
        "interval": "month"
      }
    }
  ],
  "pending_requests": [
    {
      "id": 3,
      "quantity": 1,
      "status": "pending",
      "requested_at": "2025-01-20T10:00:00Z"
    }
  ]
}
```

### `POST /api/shelf-rental/my-shelves/`

Submit a shelf rental request.

**Request:**
```json
{ "quantity": 1 }
```

**Validation:**
- Member must have an active subscription (individual or group)
- `CURRENT_SHELF_RENTAL_ADDON` must be configured
- No duplicate pending requests

**Behavior:**
1. Create `ShelfRequest` with `status="pending"`
2. Notify admin (optional)

**Response:** `201 Created`
```json
{
  "success": true,
  "request": { "id": 3, "quantity": 1, "status": "pending" }
}
```

### `DELETE /api/shelf-rental/my-shelves/`

Cancel a pending shelf request.

**Request:**
```json
{ "request_id": 3 }
```

**Behavior:**
1. Verify request belongs to user and status is `pending`
2. Set `status="cancelled"`, `cancelled_at=now()`

## Admin API Endpoints

Base path: `/api/shelf-rental/admin/`

### `GET /api/shelf-rental/admin/shelves/`

List all shelves with filtering, sorting, and aggregate stats.

**Query params:** `?status=available&sort=number`

**Response:**
```json
{
  "shelves": [
    {
      "id": 1,
      "number": "A-01",
      "status": "occupied",
      "current_member": { "id": 5, "name": "John Smith", "email": "john@example.com" },
      "next_member": null,
      "start_date": "2025-01-15",
      "next_available_date": null
    }
  ],
  "stats": {
    "total": 20,
    "occupied": 15,
    "available": 3,
    "cancelled": 2
  },
  "queue": [
    {
      "id": 3,
      "member": { "id": 8, "name": "Jane Smith" },
      "quantity": 1,
      "requested_at": "2025-01-20T10:00:00Z"
    }
  ]
}
```

### `POST /api/shelf-rental/admin/shelves/`

Create a new shelf **or** assign a member to an existing shelf.

#### Create Shelf

**Request:**
```json
{
  "action": "create",
  "number": "A-05"
}
```

#### Assign Member to Shelf

**Request:**
```json
{
  "action": "assign",
  "shelf_id": 1,
  "member_id": 8
}
```

**Assign Behavior (`_setup_shelf_billing`):**
1. Verify member has active subscription
2. Get `CURRENT_SHELF_RENTAL_ADDON` addon
3. Create `MemberShelfAddon` with locked pricing
4. Create Stripe Price for this member's locked rate:
   ```python
   price = stripe.Price.create(
       unit_amount=addon.cost,
       currency=addon.currency,
       recurring={
           "interval": addon.interval,
           "interval_count": addon.interval_count,
       },
       product_data={
           "name": f"Shelf Rental #{shelf.number} - {member.get_full_name()}",
           "metadata": {
               "shelf_id": str(shelf.id),
               "member_id": str(member.user.id),
               "addon_id": str(addon.id),
           },
       },
   )
   ```
5. Add subscription item to member's subscription:
   ```python
   sub_item = stripe.SubscriptionItem.create(
       subscription=member.stripe_subscription_id,
       price=price.id,
       proration_behavior="create_prorations",
   )
   ```
6. Save Stripe IDs on `MemberShelfAddon`
7. Update shelf: `current_member=member`, `status="occupied"`, `start_date=today`
8. If member had a pending `ShelfRequest`, mark it `status="assigned"`, `assigned_at=now()`
9. Send assignment notification email

### `DELETE /api/shelf-rental/admin/shelves/`

Remove a member from a shelf.

**Request:**
```json
{
  "shelf_id": 1,
  "member_id": 5
}
```

**Behavior:**
1. Find `MemberShelfAddon` for this shelf
2. Remove Stripe subscription item: `stripe.SubscriptionItem.delete(sub_item_id, proration_behavior="create_prorations")`
3. Delete `MemberShelfAddon`
4. **Next-occupant promotion**: if `shelf.next_member` exists:
   - Promote: set `current_member = next_member`, clear `next_member`
   - Run `_setup_shelf_billing()` for the promoted member
   - Status remains `"occupied"`
5. Else: set `current_member=None`, `status="available"`, clear dates

### `GET /api/shelf-rental/admin/members/search/`

Search members by name or email for assignment UI.

**Query params:** `?q=john` (minimum 2 characters)

**Response:** `200 OK`
```json
[
  { "id": 5, "name": "John Smith", "email": "john@example.com" }
]
```

Maximum 20 results returned.

## Constance Configuration

```python
"CURRENT_SHELF_RENTAL_ADDON": (
    "",
    "The ID of the current shelf rental addon for shelf rental pricing. Leave empty if none configured.",
),
"SHELF_RENTAL_ASSIGNMENT_EMAIL_SUBJECT": (
    "Shelf #{shelf_number} Assigned - Available {available_date}",
    "Subject line for shelf assignment emails. Placeholders: {shelf_number}, {available_date}.",
),
"SHELF_RENTAL_ASSIGNMENT_EMAIL_BODY": (
    "Congratulations! You have been assigned Shelf #{shelf_number}.\n\n"
    "Your shelf will be available starting on {available_date}.\n\n"
    "Please note the shelf number for your records.",
    "Body for shelf assignment emails. Placeholders: {shelf_number}, {available_date}, {member_name}.",
),
```

## Frontend Components

### `ShelfRentalManager.vue`

Member-facing component shown on the Membership Plan page:
- List of currently rented shelves with number, status, locked pricing
- "Request Shelf" button with quantity selector
- List of pending requests with "Cancel" button
- Only shown when `CURRENT_SHELF_RENTAL_ADDON` is configured

### `AdminShelfManagement.vue`

Admin component for shelf management:
- **Shelves table**: sortable/filterable by status, shows current member, next member
- **Statistics bar**: total, occupied, available, cancelled counts
- **Create shelf** button (number input)
- **Assign member** action per shelf (opens member search dialog)
- **Remove member** action per occupied shelf (confirmation dialog)
- **Request queue** panel: pending requests sorted by date, with "Assign" action

### `ManageShelves.vue`

Admin page wrapping `AdminShelfManagement.vue`:
- Route: `/manage/shelves`
- Added to admin menu in `pageAndRouteConfig.ts`

### Route Configuration

In `pageAndRouteConfig.ts`:
```typescript
{
  path: "/manage/shelves",
  name: "manageShelves",
  component: () => import("pages/AdminTools/ManageShelves.vue"),
  meta: { requiresAuth: true, requiresStaff: true },
}
```

## Migrations

```python
# profile/migrations/0032_add_shelf_rental_models.py
# Create Shelf, ShelfRequest, MemberShelfAddon tables

# api_admin_tools/migrations/0015_add_shelf_rental_models.py
# Add "shelf_rental" to SubscriptionAddon.ADDON_TYPES choices
```

## Testing Checklist

### Member Self-Service
- [ ] Request shelf rental — creates pending ShelfRequest
- [ ] Cancel pending request — status set to cancelled
- [ ] View current shelves — shows shelf number, status, pricing
- [ ] Request rejected without active subscription

### Admin Assignment
- [ ] Create new shelf — shelf created with available status
- [ ] Assign member to shelf — MemberShelfAddon created, Stripe subscription item added, email sent
- [ ] Assign fulfills pending request — ShelfRequest marked as assigned
- [ ] Remove member from shelf — Stripe item removed, MemberShelfAddon deleted

### Next-Occupant Promotion
- [ ] Set next_member on occupied shelf
- [ ] Remove current member — next_member auto-promoted to current
- [ ] Promoted member gets Stripe subscription item + email notification

### Stripe Integration
- [ ] Assignment creates custom Price with shelf metadata
- [ ] Assignment adds subscription item with proration
- [ ] Removal deletes subscription item with proration
- [ ] Locked pricing preserved in MemberShelfAddon

### Admin Search
- [ ] Search members by name (min 2 chars)
- [ ] Search members by email
- [ ] Max 20 results returned
