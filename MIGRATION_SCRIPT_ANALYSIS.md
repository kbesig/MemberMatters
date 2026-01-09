# Migration Script Analysis: Billing Cycle & Flexible Billing Upgrade

## Question
Do we need a script to:
1. Upgrade all subscriptions to mixed billing period support (flexible billing)?
2. Realign periods to start on the 1st of the month?

## Short Answer

**NO migration script is needed, and it's RECOMMENDED to NOT migrate existing subscriptions.**

Here's why:

## Detailed Analysis

### 1. Flexible Billing (Mixed Intervals)

**Already Supported for New Subscriptions:**
- The code changes we made add `billing_mode={"type": "flexible"}` to new subscription creation
- This is a **Stripe account-level feature** that's already enabled
- Existing subscriptions continue to work normally

**Why NOT migrate existing subscriptions:**
- Flexible billing is **opt-in per subscription**
- Existing subscriptions without `billing_mode: flexible` still work fine
- You can't easily "convert" an existing subscription to flexible billing
- You'd have to **cancel and recreate** subscriptions (very disruptive!)

**When it matters:**
- Only matters when you add subscription items with **different intervals**
- Example: Monthly base plan + weekly addon
- If all items have the **same interval**, flexible billing isn't needed

### 2. Billing Cycle Realignment (1st of Month)

**Already Implemented for New Subscriptions:**
- All **new subscriptions** will automatically use the 1st-of-month anchor
- This happens automatically with the code changes

**Why NOT migrate existing subscriptions:**

#### **Major Disruption to Members**
- Members are already on their current billing cycles
- Changing billing dates mid-cycle is confusing and frustrating
- Example: Member bills on the 15th → suddenly bills on the 1st
- They'd get a prorated charge, then a new charge soon after

#### **Complex Stripe Operations Required**
- Can't simply update `billing_cycle_anchor` on existing subscriptions
- Would need to:
  1. Cancel existing subscription
  2. Create new subscription with new anchor
  3. Prorate the charges
  4. Handle payment failures
  5. Update all database records
  6. Handle billing group members
  7. Deal with failed webhooks

#### **Financial Complexity**
- Prorations would create confusing charges
- Potential for double-billing if timing is wrong
- Refunds might be needed
- Accounting becomes messy

#### **Risk of Breaking Things**
- Subscription webhooks might fail
- Payment methods might fail on new subscription
- Database consistency issues if something fails mid-migration
- Billing group relationships could break

## Recommendation: Natural Transition

### Let Subscriptions Naturally Migrate

**When existing subscriptions WILL get the new billing cycle:**
1. **New members** - Get 1st-of-month billing automatically ✅
2. **Plan changes** - If member switches plans, new subscription created ✅
3. **Cancellation & Rejoining** - If member cancels and rejoins ✅
4. **Billing group changes** - If removed and create new individual subscription ✅

**Timeline:**
- Over 6-12 months, most subscriptions will naturally transition
- Annual subscriptions will take longer (up to a year)
- No forced migration needed

### Benefits of Natural Transition

1. **No member confusion** - They chose to make a change
2. **No sudden charges** - Everything is expected
3. **No technical risk** - Each transition is a normal operation
4. **Clean accounting** - No mass proration adjustments
5. **Members keep their current value** - They paid for a full period

## What About Edge Cases?

### Issue: Member with Annual Plan + Monthly Addons

**Current State:**
- Member has annual plan billing on Jan 10
- Wants to add monthly addon
- Monthly addon won't align with annual billing

**Solutions:**

**Option A: Wait for Natural Renewal**
- Let member keep annual cycle until next renewal (Jan 10, 2026)
- When they renew, new subscription gets 1st-of-month billing
- Any addons added after renewal align automatically

**Option B: Offer Plan Change**
- Offer member to switch plans (cancel and recreate)
- Explain they'll get prorated credit for unused time
- New subscription starts on 1st of next month
- This is **voluntary** and explained to the member

**Option C: Use Same Interval for Addons**
- If member has annual plan, addons should also be annual
- Convert monthly addon cost → annual: `monthly_cost * 12`
- This aligns everything to the same billing cycle

### Issue: Billing Groups with Old Primary Member

**Scenario:**
- Primary member has old subscription (not 1st-of-month)
- New members join billing group
- New member addons inherit primary's billing cycle

**Solution:**
- Addons automatically align with primary's billing cycle ✅
- This already works with current code
- When primary eventually renews, everything moves to 1st-of-month

## Script for OPTIONAL Voluntary Migration

If you want to offer members the option to migrate, here's a script:

### Migration Script Template

```python
from profile.models import Profile
from api_admin_tools.models import PaymentPlan
import stripe
from datetime import datetime, timezone as dt_timezone
from dateutil.relativedelta import relativedelta

def offer_billing_cycle_migration(profile_id, notify_only=True):
    """
    Optionally migrate a member's subscription to 1st-of-month billing.
    
    Args:
        profile_id: The profile ID to migrate
        notify_only: If True, only send notification. If False, perform migration.
    """
    from constance import config
    
    stripe.api_key = config.STRIPE_SECRET_KEY
    profile = Profile.objects.get(id=profile_id)
    
    # Check if they have an active subscription
    if not profile.stripe_subscription_id:
        print(f"❌ {profile.get_full_name()} has no active subscription")
        return False
    
    # Get current subscription
    current_sub = stripe.Subscription.retrieve(profile.stripe_subscription_id)
    
    # Check billing cycle anchor
    current_anchor = current_sub.billing_cycle_anchor
    anchor_date = datetime.fromtimestamp(current_anchor, tz=dt_timezone.utc)
    
    # Check if already on 1st of month
    if anchor_date.day == 1:
        print(f"✅ {profile.get_full_name()} already bills on the 1st")
        return True
    
    print(f"📅 {profile.get_full_name()} currently bills on day {anchor_date.day}")
    
    if notify_only:
        # Just notify the member
        subject = "Voluntary Billing Cycle Migration Available"
        message = f"""
        Hi {profile.get_full_name()},
        
        We've updated our billing system to standardize all billing cycles to the 1st of each month.
        
        Your current billing date: {anchor_date.strftime('%B %d')}
        New billing date: 1st of each month
        
        Benefits:
        - Predictable billing date
        - Easier to budget
        - Aligned with other members
        
        If you'd like to migrate, please contact us. We'll:
        1. Cancel your current subscription with prorated credit
        2. Create a new subscription starting on the 1st
        3. Ensure no interruption in service
        
        This is completely voluntary!
        """
        
        profile.user.email_notification(subject, message)
        print(f"📧 Notification sent to {profile.user.email}")
        return True
    
    else:
        # Perform actual migration (DANGEROUS - use with caution!)
        print(f"⚠️  WARNING: About to migrate {profile.get_full_name()}")
        print("This will cancel their current subscription and create a new one")
        
        # Get confirmation
        confirmation = input("Type 'MIGRATE' to confirm: ")
        if confirmation != "MIGRATE":
            print("❌ Migration cancelled")
            return False
        
        try:
            # Cancel old subscription with proration
            old_sub = stripe.Subscription.modify(
                profile.stripe_subscription_id,
                cancel_at_period_end=False,
                proration_behavior="create_prorations"
            )
            
            # Calculate new billing anchor
            now = datetime.now(dt_timezone.utc)
            next_month = now + relativedelta(months=1)
            billing_anchor = datetime(next_month.year, next_month.month, 1, tzinfo=dt_timezone.utc)
            billing_anchor_timestamp = int(billing_anchor.timestamp())
            
            # Create new subscription
            new_sub = stripe.Subscription.create(
                customer=profile.stripe_customer_id,
                items=[{"price": profile.membership_plan.stripe_id}],
                collection_method="charge_automatically",
                proration_behavior="create_prorations",
                billing_mode={"type": "flexible"},
                billing_cycle_anchor=billing_anchor_timestamp,
            )
            
            # Update profile
            profile.stripe_subscription_id = new_sub.id
            profile.save()
            
            # Notify member
            subject = "Your Billing Cycle Has Been Updated"
            message = f"""
            Hi {profile.get_full_name()},
            
            Your billing cycle has been successfully updated to the 1st of each month.
            
            - You received a prorated credit for your previous subscription
            - Your next billing date: {billing_anchor.strftime('%B 1, %Y')}
            - Your membership continues without interruption
            
            Thank you!
            """
            profile.user.email_notification(subject, message)
            
            print(f"✅ Successfully migrated {profile.get_full_name()}")
            return True
            
        except Exception as e:
            print(f"❌ Migration failed: {str(e)}")
            # Try to restore if possible
            return False


# Usage Examples:

# 1. Notify all members with non-1st billing (safe)
def notify_all_eligible_members():
    profiles = Profile.objects.filter(
        stripe_subscription_id__isnull=False,
        subscription_status='active'
    )
    
    for profile in profiles:
        try:
            offer_billing_cycle_migration(profile.id, notify_only=True)
        except Exception as e:
            print(f"Error processing {profile.id}: {str(e)}")


# 2. Migrate specific member (dangerous - manual only)
# offer_billing_cycle_migration(123, notify_only=False)
```

## When Would You NEED a Migration Script?

You would only need a migration script if:

1. **Regulatory Requirement** - If regulations require standardized billing dates
2. **Accounting Software** - If your accounting system can't handle variable billing dates
3. **Business Decision** - If management decides all subscriptions MUST align
4. **Contract Change** - If you're changing terms and members must agree

**Even then**, consider:
- Notify members first
- Make it voluntary when possible
- Do it in batches over several months
- Have excellent rollback plan
- Test extensively in staging first

## Summary & Recommendation

### ✅ What We Have Now (Good!)

1. **New subscriptions** → 1st-of-month billing automatically
2. **Flexible billing** → Enabled for new subscriptions
3. **Cancellations** → Continue until period end
4. **Natural migration** → Will happen over time

### ❌ What We Should NOT Do

1. **Force migrate existing subscriptions** → Too disruptive
2. **Mass billing cycle changes** → Too risky
3. **Immediate conversion** → Not necessary

### 🎯 Best Approach

1. **Deploy the code changes** ✅ (Already done!)
2. **New members get new system** ✅ (Automatic)
3. **Let existing subscriptions transition naturally** ✅ (Over time)
4. **Optionally notify members** ⚠️ (If desired)
5. **Offer voluntary migration** ⚠️ (For members who want it)

## Conclusion

**You do NOT need a migration script for existing subscriptions.**

The code changes ensure all **new subscriptions** use the improved billing system. Existing subscriptions will naturally transition over time as members renew, change plans, or make other subscription modifications.

This approach:
- ✅ Minimizes disruption
- ✅ Reduces technical risk
- ✅ Avoids member confusion
- ✅ Maintains financial consistency
- ✅ Provides smooth transition

**If** you decide you absolutely need to migrate existing subscriptions, use the optional script template above, but do so very carefully, in small batches, with extensive testing, and with clear member communication.
