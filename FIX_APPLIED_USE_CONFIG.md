# Fix Applied: Use CURRENT_ADDITIONAL_MEMBER_ADDON Configuration

## What Was Changed

Updated `/memberportal/api_general/views.py` (the email verification endpoint) to use the `CURRENT_ADDITIONAL_MEMBER_ADDON` configuration setting instead of hardcoding the addon lookup by name.

### Before (Problematic Code)
```python
# Line 868 - HARDCODED LOOKUP
billing_group_addon = SubscriptionAddon.objects.get(
    name="Billing Group Member"  # ❌ Required exact name match
)
```

### After (Fixed Code)
```python
# Line 868-886 - USE CONFIGURATION
current_addon_id = getattr(
    config, "CURRENT_ADDITIONAL_MEMBER_ADDON", None
)

if not current_addon_id or not str(current_addon_id).strip():
    logger.error(
        "CURRENT_ADDITIONAL_MEMBER_ADDON not configured - cannot create Stripe subscription item"
    )
    raise SubscriptionAddon.DoesNotExist

billing_group_addon = SubscriptionAddon.objects.get(
    id=int(current_addon_id),  # ✅ Uses configured ID
    addon_type="additional_member",
    visible=True,
)
```

## Benefits

1. **Consistency**: Now matches the approach used in `api_billing/views.py` and `api_admin_tools/views.py`
2. **Flexibility**: No longer requires a specific addon name
3. **Better Error Messages**: Clearer error logging when configuration is missing
4. **Type Safety**: Validates addon type and visibility

## What You Need To Do Now

### Step 1: Create the Additional Member Addon

1. **Go to Django Admin**: `http://your-site/admin/`
2. **Navigate to**: API Admin Tools → Subscription Add-ons
3. **Click**: "Add Subscription Addon"
4. **Fill in** (IMPORTANT - use yearly interval since your primary plan is yearly):
   ```
   Name: Additional Member (or any name you want)
   Description: Additional member in a billing group
   Addon Type: Additional Member
   Currency: usd
   Cost: 12000 (for $120/year - or monthly cost × 12)
   Interval Count: 1
   Interval: year ⚠️ MUST match primary member's billing interval!
   Visible: ✅ Checked
   Min Quantity: 1
   Max Quantity: 10
   ```
5. **Save**
6. **Click**: "Create Stripe Objects" button to sync with Stripe
7. **Note the addon ID** (you'll see it in the URL or on the page)

### Step 2: Configure the System

1. **Go to Django Admin**: Constance → Config
2. **Find**: `CURRENT_ADDITIONAL_MEMBER_ADDON`
3. **Set it to**: The ID of the addon you just created (e.g., `1` or `2`)
4. **Save**

### Step 3: Test with a New Invitation

1. Invite a new test member to a billing group
2. Have them register with the invitation link
3. Have them verify their email
4. Check the logs - should see no errors
5. Check Stripe subscription - should see the new subscription item
6. Check upcoming invoice - should show the additional member charge

## Why Yearly Interval is Important

Your primary member has a **yearly** subscription (`$550/year`). When you add subscription items to Stripe, they should have the **same billing interval** as the main subscription.

**Wrong** (Monthly addon on yearly subscription):
```
Primary Plan: $550/year
Additional Member: $10/month  ❌ MISMATCH!
Result: Won't show properly in invoices
```

**Correct** (Yearly addon on yearly subscription):
```
Primary Plan: $550/year  
Additional Member: $120/year  ✅ MATCHES!
Result: Shows correctly in upcoming invoice
```

## For Your Existing Members

Members who already accepted invitations before this fix will need manual intervention:

### Option 1: Re-invite (Easiest)
1. Remove them from the billing group
2. Re-invite them
3. Have them accept again

### Option 2: Manual Fix via Django Shell
See the script in `SOLUTION_MISSING_ADDON.md`

## Verification

After completing all steps, you should be able to:
- ✅ Invite members to billing groups
- ✅ Have them register and verify email successfully  
- ✅ See Stripe subscription items created automatically
- ✅ See additional member charges in upcoming invoices
- ✅ See proper logging with no errors

## Summary of the Root Issues

1. **Missing addon** - No SubscriptionAddon existed at all ✅ FIXED - You create it
2. **Hardcoded lookup** - Code used hardcoded name instead of config ✅ FIXED - Code updated
3. **Billing cycle mismatch** - Monthly addons on yearly subscriptions ⚠️ FIX BY USING YEARLY INTERVAL

All three issues are now addressed! 🎉
