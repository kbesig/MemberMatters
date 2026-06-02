# Spec 02: Flexible Billing & Billing Cycle Anchoring

## Summary

Enable Stripe's flexible billing mode to support mixed billing intervals on a single subscription (e.g., yearly base plan + monthly addon). Anchor all new subscriptions to the 1st of the month with automatic proration for mid-month signups.

## Dependencies

- **Spec 01**: Subscription Addon System (addon model and Stripe integration)

## Stripe API Requirements

- **Stripe API version**: `2025-06-30.basil` (or later, with flexible billing support)
- Set in `StripeAPIView.__init__()`:
  ```python
  stripe.api_version = "2025-06-30.basil"
  ```

## Billing Cycle Anchoring

All new subscriptions are anchored to the **1st of the next month**. Members who sign up mid-month pay a prorated amount for the remainder of the current month, then full billing starts on the 1st.

### Implementation in `PaymentPlanSignup.post()`

```python
from datetime import datetime
from dateutil.relativedelta import relativedelta

# Calculate the 1st of the next month
now = datetime.now()
first_of_next_month = (now + relativedelta(months=1)).replace(
    day=1, hour=0, minute=0, second=0, microsecond=0
)
billing_cycle_anchor = int(first_of_next_month.timestamp())
```

Use when creating the subscription:

```python
subscription = stripe.Subscription.create(
    customer=profile.stripe_customer_id,
    items=subscription_items,
    default_payment_method=profile.stripe_payment_method_id,
    billing_cycle_anchor=billing_cycle_anchor,
    proration_behavior="create_prorations",
    # ... other params
)
```

## Flexible Billing Mode

When a subscription includes items with different billing intervals (e.g., monthly base + weekly addon), use Stripe's flexible billing mode:

### Detection Logic

```python
def needs_flexible_billing(base_plan, addon_items):
    """Check if subscription items have mixed intervals requiring flexible billing."""
    intervals = {base_plan.interval}
    for addon in addon_items:
        intervals.add(addon.interval)
    return len(intervals) > 1
```

### Subscription Creation with Flexible Billing

```python
subscription_params = {
    "customer": profile.stripe_customer_id,
    "items": subscription_items,
    "default_payment_method": profile.stripe_payment_method_id,
    "billing_cycle_anchor": billing_cycle_anchor,
    "proration_behavior": "create_prorations",
}

# Add flexible billing mode if items have mixed intervals
if needs_flexible_billing(plan, selected_addons):
    subscription_params["billing_mode"] = {"type": "flexible"}

subscription = stripe.Subscription.create(**subscription_params)
```

### Interval Validation Helper

```python
def validate_subscription_intervals(base_interval, addon_interval):
    """
    With flexible billing, all interval combinations are valid.
    Returns (is_valid, warning_message).
    """
    if base_interval == addon_interval:
        return True, None

    warning = (
        f"Note: Base plan uses '{base_interval}' billing while add-on uses "
        f"'{addon_interval}' billing. This is supported with flexible billing "
        f"but may result in complex billing cycles."
    )
    return True, warning
```

## Modified Endpoints

### `POST /api/billing/plans/<plan_id>/signup/` — `PaymentPlanSignup`

**Changes:**
1. Accept optional `addons` array in request body
2. Calculate `billing_cycle_anchor` as 1st of next month
3. Build subscription items list (base plan + addons)
4. Detect if flexible billing is needed
5. Create subscription with appropriate params

**Request Body (updated):**
```json
{
  "paymentPlan": 1,
  "addons": [
    { "addon_id": 1, "quantity": 1 }
  ]
}
```

**Subscription Creation Flow:**
1. Validate payment plan exists and is visible
2. Validate member has Stripe customer + payment method
3. Build base item: `{"price": plan.stripe_id}`
4. For each addon: validate exists, build item `{"price": addon.stripe_price_id, "quantity": qty}`
5. Detect mixed intervals → set `billing_mode`
6. Set `billing_cycle_anchor` to 1st of next month
7. Create Stripe subscription
8. Save `stripe_subscription_id` and `subscription_status="active"` on profile
9. Save `membership_plan` FK on profile

### `GET /api/billing/myplan/` — `SubscriptionInfo`

**Changes:**
Return addon items with their individual intervals in the response.

**Response (updated):**
```json
{
  "id": "sub_xxx",
  "plan": { "name": "Monthly", "cost": 5000, "interval": "month" },
  "billingCycleAnchor": "2025-01-01T00:00:00Z",
  "currentPeriodEnd": "2025-02-01T00:00:00Z",
  "cancelAtPeriodEnd": false,
  "addons": [
    {
      "id": "si_xxx",
      "name": "Storage Upgrade",
      "cost": 1000,
      "interval": "month",
      "quantity": 1
    }
  ]
}
```

### `POST /api/billing/addons/manage/` — `SubscriptionAddonManagement`

**Changes:**
When adding an addon with a different interval than the base plan, the subscription automatically uses flexible billing. All modifications use `proration_behavior="create_prorations"`.

### `GET /api/billing/membership-plan-cost-summary/` — `MembershipPlanCostSummary`

**Changes:**
Use Stripe's upcoming invoice API to show accurate upcoming charges:

```python
upcoming = stripe.Invoice.upcoming(
    customer=profile.stripe_customer_id,
    subscription=profile.stripe_subscription_id,
)
```

**Response:**
```json
{
  "upcoming": {
    "amount_due": 6000,
    "currency": "aud",
    "period_start": "2025-01-01",
    "period_end": "2025-02-01",
    "lines": [
      { "description": "Monthly Plan", "amount": 5000 },
      { "description": "Storage Upgrade", "amount": 1000 }
    ]
  }
}
```

## Known Limitation

**Annual subscriptions with monthly addons**: When a member has a yearly base plan with monthly addons, the Stripe upcoming invoice API may not show the next monthly addon charge because it's on a different billing cycle. The upcoming invoice only shows charges for the next billing event of the primary item.

**Recommendation**: Match addon intervals to the primary subscription interval when possible. Document this clearly in admin UI.

## Frontend Changes

### Cost Summary Display

On the Membership Plan page, display:
- Base plan cost and interval
- Each addon with its own cost and interval
- Upcoming charge amount from Stripe upcoming invoice
- Proration amount for mid-month signups (shown during signup)

### Signup Flow

During plan selection, if addons are available:
1. Show addon selection after plan selection
2. Display combined cost estimate
3. If mixed intervals, show a note explaining billing cycle differences
4. Show prorated first charge amount

## Testing Checklist

- [ ] Create subscription anchored to 1st of next month — verify proration for remainder of current month
- [ ] Create subscription with same-interval addon — verify single billing cycle
- [ ] Create subscription with mixed-interval addon — verify `billing_mode=flexible` is set
- [ ] Retrieve subscription info — verify addon items returned with intervals
- [ ] Add addon to existing subscription — verify proration created
- [ ] Remove addon from subscription — verify subscription item deleted
- [ ] Get upcoming invoice — verify all line items displayed
- [ ] Test edge case: signup on the 1st of a month — verify no proration
- [ ] Test cancellation — verify cancel_at_period_end behavior preserved
