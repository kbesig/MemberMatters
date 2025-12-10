# Flexible Billing Implementation

## Overview

MemberMatters now uses Stripe's **Flexible Billing** model, which allows subscriptions to have multiple items with different billing intervals on the same subscription.

## What Changed?

### Previous Setup (Standard Billing)
- All subscription items on a single subscription had to use the **same billing interval**
- Example limitation: Couldn't have a monthly base membership with a weekly equipment rental add-on

### New Setup (Flexible Billing)
- ✅ Supports **mixed billing intervals** on the same subscription
- ✅ Monthly base plan + weekly add-ons = ✅ Allowed
- ✅ Monthly base plan + daily add-ons = ✅ Allowed
- ✅ Complex proration handling for mid-cycle changes

## Technical Implementation

### 1. Subscription Creation
**Location:** `/memberportal/api_billing/views.py` - `PaymentPlanSignup.create_subscription()`

```python
stripe.Subscription.create(
    customer=request.user.profile.stripe_customer_id,
    items=items,
    collection_method="charge_automatically",  # Required for flexible billing
    proration_behavior="create_prorations",     # Handles prorations properly
)
```

**Key Parameters:**
- `collection_method="charge_automatically"`: Enables automatic charging (required for flexible billing)
- `proration_behavior="create_prorations"`: Creates prorations when items are added/removed mid-cycle

### 2. Interval Validation
**Location:** `/memberportal/api_billing/views.py` - `validate_subscription_intervals()`

A validation function that:
- Checks interval compatibility between base plan and add-ons
- Logs warnings when mixed intervals are used
- Returns helpful messages for unusual combinations

**Example:**
```python
is_valid, warning = validate_subscription_intervals("month", "week")
# Returns: (True, "Note: Base plan uses 'month' billing while add-on uses 'week' billing...")
```

### 3. Add-on Management
When adding/removing subscription items, the system now:
1. Validates interval compatibility
2. Logs warnings for mixed intervals
3. Uses `proration_behavior="create_prorations"` for fair billing

## How Billing Works with Mixed Intervals

### Example Scenario
- **Base Plan:** $50/month (billed monthly on the 1st)
- **Add-on:** $10/week (billed every Monday)

### Billing Timeline
```
Jan 1:  Charge $50 (monthly base)
Jan 8:  Charge $10 (weekly add-on - 1st week)
Jan 15: Charge $10 (weekly add-on - 2nd week)
Jan 22: Charge $10 (weekly add-on - 3rd week)
Jan 29: Charge $10 (weekly add-on - 4th week)
Feb 1:  Charge $50 (monthly base)
...and so on
```

### Prorations
When adding/removing items mid-cycle:
- **Adding:** Charges prorated amount for the remaining period
- **Removing:** Credits prorated amount for unused time
- Stripe handles all proration calculations automatically

## Use Cases

### 1. Billing Groups (Additional Members)
```python
# Primary member: $100/month
# Additional member addon: $75/month (same interval - simple)
# OR
# Additional member addon: $20/week (different interval - flexible billing)
```

### 2. Equipment Rentals
```python
# Base membership: $50/month
# Tool rental: $5/day (flexible billing allows this mix)
```

### 3. Seasonal Add-ons
```python
# Regular membership: $100/month
# Summer workshop access: $25/week during summer (flexible billing)
```

## Best Practices

### ✅ Recommended Approaches

1. **Same Interval Subscriptions (Simplest)**
   - Use the same interval for base + add-ons when possible
   - Example: $50/month base + $25/month add-on
   - Result: Single monthly invoice

2. **Complementary Intervals (Moderate)**
   - Use intervals that divide evenly
   - Example: Monthly base + weekly add-ons (4-5 weeks per month)
   - Result: Predictable billing patterns

3. **Clear Communication**
   - Inform members about mixed interval billing
   - Show upcoming charges in the member portal
   - Send email notifications before charges

### ⚠️ Things to Consider

1. **Invoice Complexity**
   - More frequent billing intervals = more invoices
   - Consider member confusion with multiple charges per month

2. **Payment Failures**
   - With weekly/daily intervals, failed payments occur more frequently
   - Implement robust retry logic and notifications

3. **Proration Complexity**
   - Mid-cycle changes with mixed intervals can be complex
   - Test thoroughly before rolling out to members

4. **Revenue Recognition**
   - Accounting becomes more complex with mixed intervals
   - Ensure your accounting system can handle it

## Configuration

### Current Add-on Types
In `api_admin_tools/models.py`:
```python
ADDON_TYPES = [
    ("additional_member", "Additional Member"),
    ("storage_upgrade", "Storage Upgrade"),
    ("priority_support", "Priority Support"),
    ("equipment_rental", "Equipment Rental"),
    ("custom", "Custom Add-on"),
]
```

### Billing Intervals Supported
```python
BILLING_PERIODS = [
    ("month", "month"),
    ("week", "week"),
    ("day", "day"),
]
```

## Monitoring & Logging

The system logs warnings when mixed intervals are used:

```python
logger.warning(f"Mixed interval subscription for user {user.id}: Base uses 'month', addon uses 'week'")
```

**Check logs for:**
- Mixed interval warnings
- Proration events
- Failed charges with frequent billing

## Migration Path

If you're migrating from standard billing:

### For Existing Subscriptions
1. ✅ Existing subscriptions continue to work
2. ✅ No changes required to existing subscriptions
3. ✅ New add-ons will use flexible billing automatically

### For New Features
1. Create add-ons with desired intervals in Django Admin
2. Set `CURRENT_ADDITIONAL_MEMBER_ADDON` config if using billing groups
3. Test with test Stripe keys before production

## Testing Checklist

- [ ] Create subscription with monthly base plan
- [ ] Add weekly add-on to subscription
- [ ] Verify both items bill on correct intervals
- [ ] Remove add-on mid-cycle and verify proration
- [ ] Add member to billing group with different interval
- [ ] Verify invoices show correct charges
- [ ] Test payment failure scenarios
- [ ] Check that logs show interval validation warnings

## Rollback Plan

If you need to disable flexible billing:

1. Remove `collection_method="charge_automatically"` from subscription creation
2. Standardize all add-ons to use same interval as base plans
3. Remove validation warnings from logs

**Note:** Cannot change existing subscriptions from flexible to standard billing. Would need to cancel and recreate.

## Support Resources

- [Stripe Flexible Billing Documentation](https://stripe.com/docs/billing/subscriptions/multiple-products)
- [Stripe Proration Documentation](https://stripe.com/docs/billing/subscriptions/prorations)
- [Stripe Multi-plan Subscriptions](https://stripe.com/docs/billing/subscriptions/multiplan)

## Questions?

Contact the development team or check:
- `/memberportal/api_billing/views.py` for implementation
- Stripe Dashboard for real-time subscription data
- Application logs for interval validation warnings
