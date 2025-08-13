# Subscription Add-ons

This document explains how to use the new subscription add-on functionality in MemberMatters.

## Overview

The add-on system allows you to add additional items to member subscriptions, such as:
- Additional members
- Storage upgrades
- Priority support
- Equipment rentals
- Custom add-ons

## Admin Setup

### Enhanced Django Admin Interface

The subscription add-on system includes a comprehensive admin interface with:

- **Stripe Integration**: Automatic creation and management of Stripe products and prices
- **Sync Status**: Visual indicators showing which add-ons are synced with Stripe
- **Bulk Operations**: Admin actions for managing multiple add-ons at once
- **Auto-sync**: Automatic Stripe sync when pricing or intervals change

#### Admin Features:
- **List View**: Shows name, type, cost, interval, visibility, and sync status
- **Filters**: Filter by add-on type, visibility, and sync status
- **Search**: Search by name and description
- **Actions**: Bulk operations for Stripe management
- **Auto-save**: Automatically syncs with Stripe when saving changes

### 1. Create Add-ons in Django Admin

1. Go to Django Admin → API Admin Tools → Subscription Add-ons
2. Click "Add Subscription Add-on"
3. Fill in the details:
   - **Name**: Display name for the add-on
   - **Description**: Optional description
   - **Add-on Type**: Choose from predefined types
   - **Visible**: Whether members can see this add-on
   - **Currency**: Currency code (e.g., "aud")
   - **Cost**: Cost in cents (e.g., 1000 for $10.00)
   - **Interval Count**: Billing frequency (e.g., 1)
   - **Interval**: Billing period (month, week, day)
   - **Min/Max Quantity**: Quantity limits

4. **Stripe Integration**: The system will automatically create Stripe products and prices when you save the add-on.

### 2. Automatic Stripe Management

The system now automatically handles Stripe integration:

- **New Add-ons**: Automatically creates Stripe products and prices
- **Price Changes**: Automatically updates Stripe prices (creates new ones and archives old ones)
- **Sync Status**: Shows whether add-ons are synced with Stripe
- **Bulk Operations**: Use admin actions to sync multiple add-ons at once

### 3. Manual Stripe Management

You can also manually manage Stripe integration:

#### Admin Actions
- **Create Stripe products and prices**: For add-ons that don't have Stripe objects yet
- **Update Stripe prices**: For add-ons with existing Stripe products
- **Sync all with Stripe**: Sync all selected add-ons

#### Command Line
```bash
# Sync all add-ons
python manage.py sync_addons_stripe

# Only create new Stripe objects
python manage.py sync_addons_stripe --create-only

# Only update existing Stripe objects
python manage.py sync_addons_stripe --update-only

# Sync specific add-ons
python manage.py sync_addons_stripe --addon-ids 1 2 3
```

## API Endpoints

### Get Available Add-ons
```
GET /api/billing/addons/
```

Returns a list of all visible add-ons that can be added to subscriptions.

### Add Add-on to Subscription
```
POST /api/billing/addons/manage/
{
  "action": "add",
  "addon_id": 1,
  "quantity": 2
}
```

### Remove Add-on from Subscription
```
POST /api/billing/addons/manage/
{
  "action": "remove",
  "addon_id": 1
}
```

### Create Subscription with Add-ons
```
POST /api/billing/plans/{plan_id}/signup/
{
  "addons": [
    {
      "stripe_price_id": "price_xxxxxxxxxxxxx",
      "quantity": 1
    }
  ]
}
```

### Get Subscription Info (includes add-ons)
```
GET /api/billing/myplan/
```

Returns subscription details including any active add-ons.

## Frontend Integration

### Example: Display Available Add-ons

```javascript
// Get available add-ons
const response = await fetch('/api/billing/addons/');
const addons = await response.json();

// Display add-ons to user
addons.forEach(addon => {
  console.log(`${addon.name}: ${addon.cost_display}/${addon.interval}`);
});
```

### Example: Add Add-on to Subscription

```javascript
// Add an add-on to existing subscription
const response = await fetch('/api/billing/addons/manage/', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    action: 'add',
    addon_id: 1,
    quantity: 2
  })
});
```

## Common Use Cases

### 1. Additional Members
- Create an add-on with type "additional_member"
- Set appropriate pricing per additional member
- Members can add multiple quantities

### 2. Storage Upgrades
- Create add-ons for different storage tiers
- Set usage limits if needed
- Members can upgrade/downgrade as needed

### 3. Equipment Rentals
- Create add-ons for different equipment types
- Set monthly rental rates
- Track equipment availability separately

## Best Practices

1. **Test in Stripe Test Mode**: Always test add-ons in Stripe test mode first
2. **Clear Pricing**: Make sure add-on costs are clearly communicated to members
3. **Quantity Limits**: Set appropriate min/max quantities to prevent abuse
4. **Documentation**: Keep add-on descriptions clear and informative
5. **Monitoring**: Monitor add-on usage and revenue in Stripe dashboard

## Troubleshooting

### Add-on Not Appearing
- Check if the add-on is marked as "visible"
- Verify the Stripe Price ID is correct
- Ensure the Stripe Price is active

### Subscription Creation Fails
- Verify all Stripe Price IDs exist and are active
- Check that quantities are within min/max limits
- Ensure the customer has a valid payment method

### Add-on Management Fails
- Verify the subscription is active
- Check that the add-on exists and is visible
- Ensure proper permissions for the user 