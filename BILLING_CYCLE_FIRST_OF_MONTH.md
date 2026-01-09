# Billing Cycle Changes - 1st of Month Anchor

## Overview

All billing cycles in MemberMatters now start on the **1st of each month**. This provides predictable billing dates for all members and simplifies subscription management.

## What Changed?

### 1. **All New Subscriptions Anchor to the 1st of the Month**

When someone signs up for membership:
- **Immediate charge**: They are charged a prorated amount for the remainder of the current month
- **Regular billing starts**: On the 1st of the following month, regular billing begins
- **Multi-month/yearly plans**: These also start billing on the 1st and continue every N months from that date

#### Example Scenarios:

**Scenario 1: Monthly Plan**
- Member signs up on January 15th for a $50/month plan
- **Day 1 (Jan 15)**: Charged ~$25 (prorated for Jan 15-31)
- **Day 17 (Feb 1)**: Charged $50 (first full month)
- **Day 45 (Mar 1)**: Charged $50
- **And so on...** every 1st of the month

**Scenario 2: 3-Month Plan**
- Member signs up on January 15th for a $120/3-month plan
- **Day 1 (Jan 15)**: Charged ~$20 (prorated for Jan 15-31, which is $120/3 months = $40/month → ~$20 for half month)
- **Day 17 (Feb 1)**: Charged $120 (first full 3-month period covering Feb 1 - Apr 30)
- **Day 107 (May 1)**: Charged $120 (next 3-month period covering May 1 - Jul 31)
- **And so on...** every 3 months from the 1st

**Scenario 3: Annual Plan**
- Member signs up on January 15th for a $500/year plan
- **Day 1 (Jan 15)**: Charged ~$20.83 (prorated for Jan 15-31, which is $500/12 months = $41.67/month → ~$20.83 for half month)
- **Day 17 (Feb 1)**: Charged $500 (first full year covering Feb 1, 2025 - Jan 31, 2026)
- **Day 382 (Feb 1, 2026)**: Charged $500 (next year covering Feb 1, 2026 - Jan 31, 2027)
- **And so on...** every year from Feb 1st

### 2. **Cancellations Continue Until Period End**

When a member cancels their subscription:
- Access continues until the **end of the current billing period**
- For monthly plans: Until the end of that month (midnight on the 1st of next month)
- For multi-month plans: Until the end of that multi-month period
- For annual plans: Until the end of that year period
- No refunds are issued (they've paid for the full period)

#### Example:
- Member has a monthly subscription that renews on the 1st
- They cancel on February 15th
- **Access continues**: Until February 28th/29th (end of period)
- **Final charge**: March 1st billing is **cancelled** - they won't be charged
- **Access ends**: March 1st at 00:00:00 UTC

### 3. **Billing Group Addons**

When members are added to billing groups:
- Addon charges are **prorated** to align with the primary member's billing cycle
- Since the primary member's subscription is anchored to the 1st, addons also bill on the 1st
- If a member is added mid-month, they are charged a prorated amount for the remainder of the month

## Technical Implementation

### Files Changed

1. **`memberportal/api_billing/views.py`**
   - `PaymentPlanSignup.create_subscription()`: Added `billing_cycle_anchor` parameter
   - `_create_stripe_subscription_item_for_member()`: Added documentation about billing cycle inheritance

2. **`memberportal/api_admin_tools/views.py`**
   - `_create_stripe_subscription_item_for_member()`: Added comment about billing cycle alignment
   - `_create_individual_subscription_for_removed_member()`: Added `billing_cycle_anchor` parameter

### Key Code Changes

#### Subscription Creation with Billing Cycle Anchor

```python
from datetime import datetime, timezone as dt_timezone
from dateutil.relativedelta import relativedelta

# Calculate billing cycle anchor for the 1st of next month
now = datetime.now(dt_timezone.utc)
next_month = now + relativedelta(months=1)
billing_anchor = datetime(next_month.year, next_month.month, 1, tzinfo=dt_timezone.utc)
billing_anchor_timestamp = int(billing_anchor.timestamp())

# Create subscription with billing cycle anchor
stripe.Subscription.create(
    customer=customer_id,
    items=items,
    collection_method="charge_automatically",
    proration_behavior="create_prorations",
    billing_mode={"type": "flexible"},
    billing_cycle_anchor=billing_anchor_timestamp,
)
```

#### How Stripe Handles This

1. **billing_cycle_anchor**: Sets when the subscription's billing period starts
2. **proration_behavior="create_prorations"**: Ensures proper prorated charges
3. Stripe automatically:
   - Charges the prorated amount immediately for the current partial period
   - Schedules the next billing for the anchor date (1st of next month)
   - Continues billing on the 1st for the specified interval

### Cancellation Behavior

The cancellation logic was already correctly implemented:

```python
# In PaymentPlanResumeCancel.post()
modified_subscription = stripe.Subscription.modify(
    subscription_id,
    cancel_at_period_end=True,  # Key parameter!
)
```

This ensures:
- Subscription continues until `current_period_end`
- No immediate cancellation
- No refunds needed
- Clean end-of-period cutoff

## Testing Recommendations

### 1. Test Mid-Month Signup (Monthly Plan)

```bash
# Use Stripe test mode
# 1. Sign up on the 15th of any month
# 2. Verify invoice shows:
#    - Prorated amount for remainder of month
#    - Next billing date is the 1st of next month
# 3. Check upcoming invoice on the 25th
# 4. Verify full charge on the 1st
```

### 2. Test Multi-Month Plan

```bash
# 1. Sign up for 3-month plan mid-month
# 2. Verify immediate prorated charge
# 3. Verify next charge is on the 1st
# 4. Verify subsequent charges are every 3 months from the 1st
```

### 3. Test Cancellation

```bash
# 1. Create a monthly subscription
# 2. Wait for first renewal (on the 1st)
# 3. Cancel mid-month (e.g., 15th)
# 4. Verify access continues until end of month
# 5. Verify no charge on next 1st
# 6. Verify access ends on the 1st
```

### 4. Test Billing Group Addons

```bash
# 1. Create primary member with monthly subscription
# 2. Add additional member mid-month
# 3. Verify prorated charge for additional member
# 4. Verify next billing includes both base + addon on the 1st
```

## Stripe Dashboard Verification

To verify in Stripe Dashboard:

1. Go to **Customers** → Select a customer
2. Click on their **Subscription**
3. Check **Billing cycle anchor**: Should show "1st of month"
4. Check **Current period**: Should show "1st of Month - End of Month" (or multi-month period)
5. Check **Upcoming invoice**: Should show next charge on the 1st

## Impact on Existing Subscriptions

### Existing Active Subscriptions
- **No change**: Existing subscriptions keep their current billing cycle
- They will **NOT** be automatically moved to the 1st of the month
- This prevents unexpected charges or billing disruptions

### New Subscriptions Only
- **Only new subscriptions** created after this deployment will use the 1st-of-month anchor
- This includes:
  - New member signups
  - Resumed subscriptions (if completely cancelled)
  - Members removed from billing groups who get new individual subscriptions

## Migration Notes

If you want to migrate existing subscriptions to the 1st-of-month cycle:

1. **Not recommended**: Migrating existing subscriptions is complex and can confuse members
2. **Better approach**: Let existing subscriptions naturally transition when they:
   - Cancel and rejoin
   - Switch to a different plan
   - Otherwise create a new subscription

## Configuration

No configuration changes are needed. The system will automatically:
- Apply the billing cycle anchor to all new subscriptions
- Continue cancelling subscriptions at period end
- Prorate all mid-period charges

## Support and Troubleshooting

### Issue: Member confused about prorated charge

**Explanation**: "When you joined mid-month, we only charged you for the days remaining in that month. Your regular monthly billing started on the 1st of the following month."

### Issue: Member wants refund after cancellation

**Explanation**: "Your subscription continues until the end of the billing period you've already paid for. This is standard practice and ensures you get the full value of your payment."

### Issue: Billing group addon not showing correct amount

**Check**: 
1. Verify primary member has active subscription
2. Check primary subscription's billing cycle anchor
3. Verify addon is prorated correctly for current period
4. Check next invoice to see full addon charge

## Benefits

1. **Predictable billing**: All members know their billing date is the 1st
2. **Simpler accounting**: All revenue arrives on the 1st of each month
3. **Easier support**: Single billing date to remember and explain
4. **Fair prorations**: Members only pay for what they use
5. **No surprise charges**: Clear communication about when charges occur
6. **Continued access**: Members get full value after cancellation

## Related Documentation

- [FLEXIBLE_BILLING_IMPLEMENTATION.md](FLEXIBLE_BILLING_IMPLEMENTATION.md)
- [BILLING_CYCLE_MISMATCH_ISSUE.md](BILLING_CYCLE_MISMATCH_ISSUE.md)
- [BILLING_GROUP_PRORATION_FEATURE.md](BILLING_GROUP_PRORATION_FEATURE.md)
