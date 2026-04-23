# Spec 03: Subscription Status Enhancement

## Summary

Expand `Profile.subscription_status` from a simple active/inactive binary to five states that capture cancellation-in-progress and billing group membership. Add webhook-driven status cascading so billing group members' statuses update automatically when the primary member's subscription changes.

## Dependencies

- None (foundation spec, but informs Specs 04 and 05)

## Data Model Changes

### `Profile` model (modify in `profile/models.py`)

#### New/Modified Fields

```python
SUBSCRIPTION_STATES = (
    ("inactive", "Inactive"),
    ("active", "Active"),
    ("cancelling", "Cancelling"),
    ("group_active", "Group Member (Active)"),
    ("group_inactive", "Group Member (Inactive)"),
)

# Modify existing field to use new choices
subscription_status = models.CharField(
    max_length=20, default="inactive", choices=SUBSCRIPTION_STATES
)

# New field — set once on first paid invoice
subscription_first_created = models.DateTimeField(
    default=None, blank=True, null=True, editable=False
)
```

#### New Methods

```python
def has_active_subscription(self):
    """Returns True if member has active subscription (individual or group)."""
    return self.subscription_status in ["active", "group_active"]

def get_effective_subscription_status(self):
    """
    Returns effective status considering billing group membership.
    Primary members keep their own status; secondary members derive from primary.
    """
    if not self.billing_group or not self.billing_group.primary_member:
        return self.subscription_status

    if self.billing_group.primary_member == self:
        return self.subscription_status

    # Secondary member: derive from primary
    primary = self.billing_group.primary_member
    if primary.subscription_status == "active":
        return "group_active"
    elif primary.subscription_status in ["inactive", "cancelling"]:
        return "group_inactive"

    return self.subscription_status
```

## Status Transition Rules

```
                    signup/payment
  inactive ──────────────────────────> active
     ^                                    │
     │                                    │ cancel request
     │                                    v
     │         period ends           cancelling
     │<──────────────────────────────────┘
     │
     │          join group
     │──────────────────────────> group_active
     │                                │
     │     primary payment fails      v
     │                          group_inactive
     │<──────────────────────────────┘
                leave group
```

### Transition Triggers

| From | To | Trigger |
|------|----|---------|
| `inactive` | `active` | Stripe `invoice.paid` webhook (first paid invoice) |
| `active` | `cancelling` | Member requests cancellation (`cancel_at_period_end=true`) |
| `cancelling` | `inactive` | Stripe `customer.subscription.deleted` webhook (period ends) |
| `cancelling` | `active` | Member resumes subscription (un-cancel) |
| `inactive` | `group_active` | Member accepts billing group invitation |
| `group_active` | `group_inactive` | Primary member's payment fails / subscription cancelled |
| `group_inactive` | `group_active` | Primary member's payment succeeds again |
| `group_active` | `inactive` | Member leaves billing group |
| `group_inactive` | `inactive` | Member leaves billing group |

## Webhook Handler Changes

### `POST /api/billing/stripe-webhook/` — `StripeWebhook`

#### `invoice.paid` Event

```python
def handle_invoice_paid(event):
    invoice = event.data.object
    customer_id = invoice.customer
    subscription_id = invoice.subscription

    profile = Profile.objects.get(stripe_customer_id=customer_id)

    # Set subscription_first_created on first payment
    if not profile.subscription_first_created:
        profile.subscription_first_created = timezone.now()

    profile.subscription_status = "active"
    profile.save()

    # Log event
    profile.user.log_event(
        f"Stripe invoice paid for subscription {subscription_id}",
        "stripe"
    )

    # If primary member of billing group, cascade to all group members
    if hasattr(profile, 'billing_group_primary_member'):
        billing_group = profile.billing_group_primary_member
        for member in billing_group.get_members():
            if member != profile:
                member.subscription_status = "group_active"
                member.save()

    # Auto-activate member if requirements met
    if profile.state == "noob" and profile.can_signup()["success"]:
        profile.activate()
```

#### `invoice.payment_failed` Event

```python
def handle_payment_failed(event):
    invoice = event.data.object
    customer_id = invoice.customer

    profile = Profile.objects.get(stripe_customer_id=customer_id)

    profile.user.log_event(
        "Stripe payment failed",
        "stripe"
    )

    # If primary member of billing group, cascade failure to members
    if hasattr(profile, 'billing_group_primary_member'):
        billing_group = profile.billing_group_primary_member
        for member in billing_group.get_members():
            if member != profile:
                member.subscription_status = "group_inactive"
                member.save()
                member.user.log_event(
                    "Billing group primary member payment failed",
                    "stripe"
                )
```

#### `customer.subscription.deleted` Event

```python
def handle_subscription_deleted(event):
    subscription = event.data.object
    customer_id = subscription.customer

    profile = Profile.objects.get(stripe_customer_id=customer_id)

    profile.subscription_status = "inactive"
    profile.stripe_subscription_id = ""
    profile.membership_plan = None
    profile.save()

    # Cascade to billing group members
    if hasattr(profile, 'billing_group_primary_member'):
        billing_group = profile.billing_group_primary_member
        for member in billing_group.get_members():
            if member != profile:
                member.subscription_status = "group_inactive"
                member.save()

    # Deactivate member
    profile.deactivate()
```

### Cancel/Resume Subscription — `PaymentPlanResumeCancel`

```python
def post(self, request, resume):
    profile = request.user.profile

    if resume == "resume":
        # Un-cancel: revert from cancelling to active
        stripe.Subscription.modify(
            profile.stripe_subscription_id,
            cancel_at_period_end=False,
        )
        profile.subscription_status = "active"
        profile.save()

    elif resume == "cancel":
        # Set cancel at end of period
        stripe.Subscription.modify(
            profile.stripe_subscription_id,
            cancel_at_period_end=True,
        )
        profile.subscription_status = "cancelling"
        profile.save()
```

## API Response Changes

### `GET /api/billing/myplan/` — `SubscriptionInfo`

Include subscription status in response:

```json
{
  "subscriptionStatus": "active",
  "cancelAtPeriodEnd": false,
  "currentPeriodEnd": "2025-02-01T00:00:00Z",
  "subscriptionFirstCreated": "2024-06-15T10:30:00Z"
}
```

### Profile API (`get_basic_profile()`)

Already includes `subscriptionStatus` in the profile response:

```json
{
  "subscriptionStatus": "group_active",
  "billingGroup": {
    "name": "Smith Family",
    "head": "John Smith",
    "members": [...]
  }
}
```

## Frontend Changes

### Membership Plan Page

Display different UI based on status:

| Status | Display |
|--------|---------|
| `inactive` | "No active subscription" + signup prompt |
| `active` | Full subscription details, cancel button |
| `cancelling` | Subscription details + "Cancelling at end of period" warning + resume button |
| `group_active` | "Covered by billing group" + group name + primary member name |
| `group_inactive` | Warning banner: "Primary member's payment has been declined. Your access may be affected." |

### Dashboard

- Show subscription status badge
- Show warning banner if `group_inactive`

## Migrations

```python
# profile/migrations/0004_profile_subscription_status.py
# Add subscription_status field with choices

# profile/migrations/0027_add_group_subscription_states.py
# Add group_active, group_inactive to choices

# profile/migrations/0028_update_billing_group_subscription_status.py
# Data migration: update existing group members to correct status

# profile/migrations/0029_fix_billing_group_subscription_status.py
# Fix any inconsistent statuses
```

## Testing Checklist

- [ ] New member starts with `inactive` status
- [ ] `invoice.paid` webhook sets status to `active` and sets `subscription_first_created`
- [ ] Cancel request sets `cancel_at_period_end=true` and status to `cancelling`
- [ ] Resume request reverts to `active` and `cancel_at_period_end=false`
- [ ] `subscription.deleted` webhook sets status to `inactive`, clears subscription fields
- [ ] `has_active_subscription()` returns True for `active` and `group_active`
- [ ] `has_active_subscription()` returns False for `inactive`, `cancelling`, `group_inactive`
- [ ] Primary member payment failure cascades `group_inactive` to all secondary members
- [ ] Primary member payment success cascades `group_active` to all secondary members
- [ ] `get_effective_subscription_status()` correctly derives secondary member status from primary
- [ ] Frontend displays correct UI for each of the 5 statuses
- [ ] `group_inactive` shows prominent warning banner
