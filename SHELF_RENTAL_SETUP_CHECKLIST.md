# Shelf Rental Feature - Quick Setup Checklist

## ✅ Installation Complete

The shelf rental feature has been successfully installed in your MemberMatters instance. Follow these steps to activate and configure it.

## Setup Steps

### 1. ✅ Database Migrations (Already Done)
The following migrations have been applied:
- `api_admin_tools.0015_add_shelf_rental_models`
- `profile.0032_add_shelf_rental_models`

### 2. 📝 Create Shelf Rental Addon
1. Navigate to: **Django Admin** (http://localhost:8000/admin/)
2. Go to: **API Admin Tools → Subscription Add-ons**
3. Click: **Add Subscription Addon**
4. Configure:
   ```
   Name: Shelf Rental
   Description: Monthly shelf rental for members
   Addon Type: Shelf Rental (from dropdown)
   Visible: ✅ YES
   Currency: usd (or your currency)
   Cost: 2000 (for $20.00 per month)
   Interval Count: 1
   Interval: month
   Min Quantity: 1
   Max Quantity: 1
   ```
5. Click: **Save**
6. **Note the ID** of the created addon (shown in the URL or admin list)

### 3. 📝 Configure Constance Settings
1. Navigate to: **Django Admin → Constance → Config**
2. Scroll to: **"Shelf Rental"** section
3. Set values:
   ```
   CURRENT_SHELF_RENTAL_ADDON: [Enter addon ID from step 2]
   
   SHELF_RENTAL_ASSIGNMENT_EMAIL_SUBJECT:
   Shelf #{shelf_number} Assigned - Available {available_date}
   
   SHELF_RENTAL_ASSIGNMENT_EMAIL_BODY:
   Congratulations! You have been assigned Shelf #{shelf_number}.

   Your shelf will be available starting on {available_date}.

   Please note the shelf number for your records. If you have any questions,
   please contact us.
   ```
4. Click: **Save**

### 4. 📝 Sync Addon with Stripe (if using Stripe)
1. In Django Admin, go to your Shelf Rental addon
2. If `stripe_synced` is False:
   - Make sure Stripe is configured in Constance
   - The addon should auto-sync, or you can manually create a Product and Price in Stripe
   - Update the addon's `stripe_product_id` and `stripe_price_id` fields

### 5. 📝 Create Shelves
**Via Django Admin:**
1. Django Admin → Profile → Shelves
2. Click "Add Shelf"
3. Enter shelf number (e.g., "A1", "B2", "101")
4. Leave status as "available"
5. Save and repeat for all shelves

**OR Via Frontend (Recommended):**
1. Login as admin
2. Navigate to: **Admin Tools → Manage Shelves**
3. Click: **Create Shelf**
4. Enter shelf number
5. Click: **Create**
6. Repeat for all shelves

### 6. ✅ Test Member Flow
1. Login as a regular member
2. Navigate to: **Account → Membership Plan**
3. Scroll to: **"Add-ons & Rentals"** section
4. You should see:
   - Shelf rental addon information
   - Request form
5. Try requesting a shelf
6. Should appear in "Pending Requests"

### 7. ✅ Test Admin Flow
1. Login as admin
2. Navigate to: **Admin Tools → Manage Shelves**
3. You should see:
   - Statistics dashboard
   - List of shelves
   - Request queue (with your test request)
4. Try assigning the request:
   - Click the assignment icon in the queue
   - Select available date
   - Click "Assign"
5. Verify:
   - Shelf shows as "Occupied"
   - Member receives email notification
   - If member has active subscription, check Stripe for new subscription item

## Verification Checklist

- [ ] Addon created and ID noted
- [ ] Constance settings configured
- [ ] Stripe synced (if applicable)
- [ ] At least one shelf created
- [ ] Member can see addon info
- [ ] Member can request shelf
- [ ] Admin can see requests in queue
- [ ] Admin can assign shelf to member
- [ ] Email notification sent
- [ ] Stripe subscription item created (if applicable)

## Accessing the Features

### For Members:
- **URL**: `/account/membership-plan`
- **Navigation**: Account → Membership Plan → Scroll to "Add-ons & Rentals"

### For Admins:
- **URL**: `/manage/shelves`
- **Navigation**: Admin Tools → Manage Shelves

## Configuration Files

All configuration is done through:
1. **Django Admin** - Create addon and shelves
2. **Constance Config** - Email templates and addon ID

No code changes required for basic configuration!

## Common Issues

### "Shelf rental is not currently configured"
- **Cause**: `CURRENT_SHELF_RENTAL_ADDON` not set in Constance
- **Fix**: Set the addon ID in Constance Config

### "Addon not found"
- **Cause**: Addon ID is wrong or addon is not visible
- **Fix**: Verify addon exists and `visible=True`, check ID in Constance

### Member doesn't see addon price
- **Cause**: Addon not configured or not synced
- **Fix**: Check addon exists and is visible

### Stripe subscription item not created
- **Cause**: Member doesn't have active subscription, or Stripe not configured
- **Fix**: Ensure member has active subscription, check Stripe keys in Constance

### Email not sent
- **Cause**: Email configuration missing
- **Fix**: Configure email settings in Constance (EMAIL_DEFAULT_FROM, etc.)

## Support

For issues or questions:
1. Check the main documentation: `SHELF_RENTAL_FEATURE.md`
2. Review error logs: `memberportal/errors.log`
3. Check Django admin logs for user actions

## Next Steps

After setup is complete:
1. Train admin staff on shelf assignment process
2. Announce feature to members
3. Monitor the request queue regularly
4. Consider setting shelf naming conventions (e.g., "A1-A20", "B1-B20")

---

**Feature Version**: 1.0  
**Installation Date**: January 23, 2026  
**Status**: ✅ Installed and Ready for Configuration
