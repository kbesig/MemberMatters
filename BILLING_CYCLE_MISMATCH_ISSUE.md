# Billing Cycle Mismatch Issue: Annual Subscription with Monthly Addons

## The Problem

You've discovered a critical issue with how Stripe handles subscription items with **different billing cycles** on the same subscription. Here's what's happening:

### Scenario
- **Primary member**: Has a yearly (annual) billing plan
- **Additional member addon**: Has a monthly billing cycle
- **Result**: The additional member addon charge is NOT showing up in the "upcoming invoice"

## Why This Happens

### Stripe's Billing Cycle Anchor

Stripe subscriptions have a **billing cycle anchor** - the date when the subscription renews. When you add subscription items with different billing intervals to the same subscription, Stripe handles them differently:

1. **Same Interval**: All items are billed together on the subscription's billing cycle
2. **Different Intervals**: Stripe has limitations and complex behavior

### The Issue with Mixed Intervals

When you have a **yearly subscription** and try to add a **monthly addon** as a subscription item:

```python
# Primary subscription
subscription = {
    "interval": "year",  # Bills once per year
    "billing_cycle_anchor": "2025-01-01"  # Renews annually
}

# Additional member addon (monthly)
subscription_item = {
    "price": {
        "interval": "month",  # Bills every month
        "interval_count": 1
    }
}
```

**Stripe's behavior:**
- The `upcoming_invoice` API primarily shows charges for the **next billing cycle anchor**
- For a yearly subscription, that's 12 months away
- Monthly addons need to be billed monthly, not yearly
- Stripe may prorate or handle this differently, but it's not ideal

## Stripe's Recommended Approaches

### Option 1: Use Same Billing Interval (RECOMMENDED)

**Convert monthly addons to match the primary subscription's interval:**

```python
# If primary subscription is yearly, make addon yearly too
if primary_subscription.interval == "year":
    addon_interval = "year"
    addon_cost = monthly_addon_cost * 12  # Convert monthly to yearly
else:
    addon_interval = "month"
    addon_cost = monthly_addon_cost
```

**Pros:**
- All items billed together
- Simpler invoicing
- Easier to predict costs
- Works perfectly with Stripe's billing cycle

**Cons:**
- Larger upfront cost for annual subscribers
- More complex pricing calculations

### Option 2: Use Subscription Schedules

Stripe Subscription Schedules allow more complex billing scenarios, but they're more complex to implement.

### Option 3: Separate Subscriptions

Create separate subscriptions for different billing intervals (not recommended for your use case).

## Current Code Analysis

Looking at your code in `/memberportal/api_billing/views.py`:

```python
# Line 1915-1940: Creating subscription item for additional member
stripe_price = stripe.Price.create(
    currency=locked_addon.locked_currency.lower(),
    unit_amount=locked_addon.locked_cost,  # This is monthly cost
    recurring={
        "interval": locked_addon.locked_interval,  # "month"
        "interval_count": locked_addon.locked_interval_count,  # 1
    },
    # ...
)

subscription_item = stripe.SubscriptionItem.create(
    subscription=primary_member.stripe_subscription_id,  # This has yearly interval!
    price=stripe_price.id,
    quantity=1,
    proration_behavior="create_prorations",
)
```

**The Issue**: You're creating a monthly price and attaching it to a yearly subscription.

## Recommended Solution

### Step 1: Detect Primary Member's Billing Interval

Before creating the addon subscription item, check the primary member's subscription interval:

```python
def _create_stripe_subscription_item_for_member(
    self, member_profile, billing_group, requesting_user
):
    """
    Create a Stripe subscription item for an additional member.
    Matches the billing interval to the primary member's subscription.
    """
    try:
        from profile.models import BillingGroupMemberAddon

        primary_member = billing_group.primary_member
        if not primary_member.stripe_subscription_id:
            return None

        # Get primary member's subscription to check billing interval
        primary_subscription = stripe.Subscription.retrieve(
            primary_member.stripe_subscription_id
        )
        
        # Get the primary plan's billing interval
        primary_plan_interval = primary_subscription.plan.interval
        primary_plan_interval_count = primary_subscription.plan.interval_count
        
        # Get locked addon pricing
        locked_addons = BillingGroupMemberAddon.objects.filter(
            billing_group=billing_group,
            member=member_profile,
            addon__addon_type="additional_member",
        )

        for locked_addon in locked_addons:
            # Calculate the appropriate cost based on primary subscription's interval
            addon_cost = locked_addon.locked_cost
            addon_interval = locked_addon.locked_interval
            addon_interval_count = locked_addon.locked_interval_count
            
            # Convert addon cost to match primary subscription's billing cycle
            if primary_plan_interval != addon_interval:
                if primary_plan_interval == "year" and addon_interval == "month":
                    # Convert monthly to yearly
                    addon_cost = addon_cost * 12
                    addon_interval = "year"
                    addon_interval_count = 1
                elif primary_plan_interval == "month" and addon_interval == "year":
                    # Convert yearly to monthly
                    addon_cost = addon_cost // 12
                    addon_interval = "month"
                    addon_interval_count = 1
                # Handle other interval conversions as needed
            
            # Create price with matching interval
            stripe_price = stripe.Price.create(
                currency=locked_addon.locked_currency.lower(),
                unit_amount=addon_cost,  # Adjusted cost
                recurring={
                    "interval": addon_interval,  # Matches primary subscription
                    "interval_count": addon_interval_count,
                },
                product_data={
                    "name": f"Additional Member: {member_profile.get_full_name()}",
                    "metadata": {
                        "billing_group_id": str(billing_group.id),
                        "member_id": str(member_profile.id),
                        "addon_id": str(locked_addon.addon.id),
                        "original_interval": locked_addon.locked_interval,
                        "adjusted_for_interval": addon_interval,
                    },
                },
            )

            # Rest of the code...
```

### Step 2: Update the Display Logic

Update the cost summary and display to show the adjusted pricing:

```python
# In the cost summary view, show both monthly equivalent and actual charge
if addon_interval == "year":
    monthly_equivalent = addon_cost // 12
    description = (
        f"Additional Member: {member_profile.get_full_name()} "
        f"(${monthly_equivalent/100:.2f}/month, billed ${addon_cost/100:.2f} annually)"
    )
```

### Step 3: Update Documentation

Add notes about billing interval matching in:
- Admin interface
- Member-facing displays
- Email notifications

## Testing Recommendations

1. **Test with yearly subscription + monthly addon**
   - Create a billing group with annual primary member
   - Add a member with monthly addon pricing
   - Verify the addon shows as yearly charge in upcoming invoice
   - Verify the cost is calculated correctly (monthly × 12)

2. **Test with monthly subscription + monthly addon**
   - Should work as-is (same interval)

3. **Test the upcoming invoice API**
   - Verify all subscription items appear
   - Verify costs are correct

4. **Test proration**
   - Add member mid-cycle
   - Verify proration is calculated correctly

## Why It's Not Showing Now

The addon is probably created in Stripe, but:
1. The upcoming invoice for a yearly subscription shows charges 12 months from now
2. The monthly addon might be trying to bill monthly, creating a conflict
3. Stripe's API might not show it properly due to interval mismatch

### Check in Stripe Dashboard

1. Go to your Stripe Dashboard
2. Find the primary member's subscription
3. Check the subscription items - you should see the additional member item
4. Check if there are any billing anomalies or warnings

## Immediate Fix

To see if the addon exists but isn't showing:

```python
# In MembershipPlanCostSummary view, add more detailed logging
subscription = stripe.Subscription.retrieve(
    profile.stripe_subscription_id,
    expand=["items"]
)

# Log all subscription items
for item in subscription.items.data:
    logger.info(f"Subscription item: {item.price.id}, interval: {item.price.recurring.interval}, cost: {item.price.unit_amount}")
```

## Long-term Solution

**Align all billing intervals to the primary member's subscription interval** when creating addon prices. This is the cleanest and most reliable approach for Stripe subscriptions.
