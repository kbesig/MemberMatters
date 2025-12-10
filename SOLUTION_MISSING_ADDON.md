# SOLUTION: Missing "Billing Group Member" Addon

## Root Cause Found! ✅

The subscription item is never created because the **"Billing Group Member" addon doesn't exist** in your database.

### The Error
```
2025-12-03 17:35:28,171 general views.py:932  ERROR    Billing Group Member addon not found in database
2025-12-05 10:34:34,366 general views.py:932  ERROR    Billing Group Member addon not found in database
```

### What's Happening

When a member accepts a billing group invitation (during email verification), the code at `/memberportal/api_general/views.py:868` tries to find an addon:

```python
billing_group_addon = SubscriptionAddon.objects.get(
    name="Billing Group Member"  # This EXACT name must exist!
)
```

If this addon doesn't exist, the code logs an error and continues, but **NO Stripe subscription item is created**.

## How to Fix This

### Option 1: Create the Missing Addon (QUICK FIX)

1. **Go to Django Admin**: http://your-membermatters-url/admin/
2. **Navigate to**: API Admin Tools → Subscription Add-ons
3. **Click "Add Subscription Addon"**
4. **Fill in the form**:
   - **Name**: `Billing Group Member` (MUST be exactly this)
   - **Description**: Something like "Additional member in a billing group"
   - **Addon Type**: Select "Additional Member"
   - **Currency**: `usd` (or your currency)
   - **Cost**: Amount in cents (e.g., `1000` for $10.00)
   - **Interval Count**: `1`
   - **Interval**: `month` (or `year` depending on your preference)
   - **Visible**: ✅ Check this
   - **Min Quantity**: `1`
   - **Max Quantity**: `10` (or whatever makes sense)
5. **Save**
6. **Important**: Click the "Create Stripe Objects" button to sync with Stripe
7. **Also Set Configuration**:
   - Go to Django Admin → Constance → Config
   - Find `CURRENT_ADDITIONAL_MEMBER_ADDON`
   - Set it to the ID of the addon you just created

### Option 2: Update the Code to Use Configuration (BETTER LONG-TERM)

The issue is that this code path (email verification with billing group invite) uses hardcoded addon lookup, while other code paths use the `CURRENT_ADDITIONAL_MEMBER_ADDON` config setting.

**Update `/memberportal/api_general/views.py` around line 868:**

```python
# OLD CODE (HARDCODED):
try:
    billing_group_addon = SubscriptionAddon.objects.get(
        name="Billing Group Member"
    )

# NEW CODE (USE CONFIG):
try:
    from constance import config
    
    current_addon_id = getattr(config, "CURRENT_ADDITIONAL_MEMBER_ADDON", None)
    
    if not current_addon_id or not str(current_addon_id).strip():
        logger.error(
            "CURRENT_ADDITIONAL_MEMBER_ADDON not configured - cannot add member to billing group subscription"
        )
        # Continue anyway - user still gets added to group
    else:
        billing_group_addon = SubscriptionAddon.objects.get(
            id=int(current_addon_id),
            addon_type="additional_member",
            visible=True,
        )
```

This makes it consistent with how other parts of the code work (like in `api_billing/views.py`).

## After Creating the Addon

### For New Members

Once the addon exists, new members who accept invitations will:
1. Get added to the billing group ✅
2. Have their pricing locked ✅
3. Get a Stripe subscription item created ✅
4. Show up in upcoming invoices ✅

### For Existing Members (Already Added)

Members who were already added while the addon was missing need manual intervention:

**Option A: Re-invite them**
1. Remove the member from the billing group
2. Re-invite them
3. Have them accept the invitation again

**Option B: Manually create subscription items** (via Django shell)
```python
from profile.models import BillingGroup, Profile, BillingGroupMemberAddon
from api_admin_tools.models import SubscriptionAddon
from api_billing.views import MemberBillingGroupInviteResponse
import stripe
from constance import config

stripe.api_key = config.STRIPE_SECRET_KEY

# Get the billing group
billing_group = BillingGroup.objects.get(name="Besig Family")  # Update name
primary = billing_group.primary_member

# Get all members (excluding primary)
members = billing_group.members.exclude(id=primary.id)

# Get the addon
addon = SubscriptionAddon.objects.get(name="Billing Group Member")

# Create subscription items for each member
view = MemberBillingGroupInviteResponse()
for member in members:
    print(f"Processing {member.get_full_name()}...")
    
    # Check if they already have a locked addon
    locked_addon = BillingGroupMemberAddon.objects.filter(
        billing_group=billing_group,
        member=member
    ).first()
    
    if not locked_addon:
        # Create locked pricing
        locked_addon = BillingGroupMemberAddon.objects.create(
            billing_group=billing_group,
            member=member,
            addon=addon,
            locked_cost=addon.cost,
            locked_currency=addon.currency,
            locked_interval=addon.interval,
            locked_interval_count=addon.interval_count,
        )
        print(f"  Created locked pricing")
    
    if not locked_addon.stripe_subscription_item_id:
        # Create Stripe subscription item
        result = view._create_stripe_subscription_item_for_member(
            member,
            billing_group,
            primary.user
        )
        if result:
            print(f"  ✅ Created Stripe subscription item: {result}")
        else:
            print(f"  ❌ Failed to create Stripe subscription item")
    else:
        print(f"  Already has subscription item: {locked_addon.stripe_subscription_item_id}")
```

## Important: The Billing Cycle Issue

Once you create the addon and subscription items start working, you'll still face the billing cycle mismatch issue I described earlier. 

**Remember**: If your primary member has a yearly subscription, you should create the addon with a **yearly** interval and cost (monthly cost × 12), NOT a monthly interval.

Otherwise, you'll have the same display problem where monthly addons on a yearly subscription don't show up properly in upcoming invoices.

## Verification Steps

After fixing:

1. Create the addon in Django Admin
2. Sync it with Stripe
3. Set `CURRENT_ADDITIONAL_MEMBER_ADDON` config
4. Invite a test member to a billing group
5. Have them accept the invitation
6. Check the logs - should see no errors
7. Check Stripe dashboard - should see the subscription item
8. Check upcoming invoice - should see the additional member charge

## Summary

**The Problem**: Missing database record for "Billing Group Member" addon  
**The Fix**: Create the addon in Django Admin with exact name "Billing Group Member"  
**Better Fix**: Update code to use `CURRENT_ADDITIONAL_MEMBER_ADDON` config instead of hardcoded name  
**Result**: Subscription items will be created successfully for new members
