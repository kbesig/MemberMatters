# Testing Guide: Flexible Billing Implementation

This guide will help you test the new flexible billing functionality to ensure multi-interval subscriptions work correctly.

## Prerequisites

- Stripe test account with API keys configured
- Access to Django admin panel
- Test payment method configured

## Test Scenarios

### Test 1: Create Subscription with Single Interval

**Objective:** Verify basic subscription creation still works

**Steps:**
1. Log in as a test user
2. Navigate to Billing → Plans
3. Select a monthly plan (e.g., $50/month)
4. Complete payment
5. Verify subscription is created in Stripe Dashboard

**Expected Result:**
- ✅ Subscription created successfully
- ✅ Shows `collection_method: "charge_automatically"`
- ✅ Single monthly charge

---

### Test 2: Add Same-Interval Add-on

**Objective:** Verify same-interval add-ons work (simplest case)

**Prerequisites:** Active monthly subscription

**Steps:**
1. Navigate to Billing → Add-ons
2. Select a monthly add-on (e.g., Storage Upgrade - $10/month)
3. Add to subscription
4. Check Stripe Dashboard

**Expected Result:**
- ✅ Add-on added successfully
- ✅ Both items show same billing interval
- ✅ Proration charge calculated for current period
- ✅ Next invoice includes both items

---

### Test 3: Add Different-Interval Add-on (KEY TEST)

**Objective:** Verify flexible billing with mixed intervals

**Prerequisites:** Active monthly subscription

**Steps:**
1. Navigate to Django Admin → Subscription Add-ons
2. Create a weekly add-on:
   - Name: "Equipment Rental"
   - Type: "Equipment Rental"
   - Cost: 500 (cents) = $5.00
   - Interval: "week"
   - Interval Count: 1
3. Save and ensure it syncs with Stripe
4. Navigate to member Billing page
5. Add the weekly add-on
6. Check application logs for validation warning
7. Check Stripe Dashboard

**Expected Result:**
- ✅ Warning logged: "Base uses 'month', addon uses 'week'"
- ✅ Add-on added successfully
- ✅ Stripe shows base plan: monthly, add-on: weekly
- ✅ Weekly add-on charges separately from monthly base

---

### Test 4: Billing Group with Mixed Intervals

**Objective:** Verify billing groups work with flexible billing

**Prerequisites:** 
- Primary member with monthly subscription
- Weekly "additional member" add-on configured

**Steps:**
1. As primary member, navigate to Billing → Billing Group
2. Invite a new member
3. New member accepts invitation
4. Check Stripe subscription for primary member

**Expected Result:**
- ✅ New subscription item added for additional member
- ✅ If weekly interval: charges weekly
- ✅ If monthly interval: charges monthly with base plan
- ✅ Proration applied correctly

---

### Test 5: Remove Add-on Mid-Cycle

**Objective:** Verify proration when removing items

**Prerequisites:** Subscription with monthly base + weekly add-on

**Steps:**
1. Note current date and next billing dates
2. Remove the weekly add-on
3. Check Stripe Dashboard → Billing → Upcoming Invoice

**Expected Result:**
- ✅ Add-on removed successfully
- ✅ Credit applied for unused time
- ✅ Next invoice shows only base plan
- ✅ No weekly charges after removal

---

### Test 6: Payment Failure with Mixed Intervals

**Objective:** Test failure handling with multiple billing frequencies

**Prerequisites:** Subscription with monthly + weekly items

**Steps:**
1. Use Stripe test card that will decline: `4000000000000002`
2. Update payment method in billing
3. Wait for next weekly charge attempt
4. Check payment status and user logs

**Expected Result:**
- ✅ Payment failure logged
- ✅ User notified of failure
- ✅ Retry logic applies correctly
- ✅ Monthly charges not affected by weekly failure

---

### Test 7: Proration Calculation

**Objective:** Verify proration math is correct

**Prerequisites:** Monthly subscription at $100/month

**Steps:**
1. On day 15 of billing cycle, add $20/month add-on
2. Check immediate charge amount
3. Expected: ~$10 (half of $20 for remaining days)
4. Check next full invoice
5. Expected: $120 ($100 + $20)

**Expected Result:**
- ✅ Proration charge = ~$10 (varies by days remaining)
- ✅ Next full charge = $120
- ✅ Math checks out for partial period

---

### Test 8: Complex Multi-Interval Scenario

**Objective:** Test subscription with 3+ different intervals

**Prerequisites:** Configure add-ons with different intervals

**Setup:**
- Monthly base: $50/month
- Weekly add-on: $10/week  
- Daily add-on: $2/day

**Steps:**
1. Create subscription with monthly base
2. Add weekly add-on
3. Add daily add-on
4. Monitor charges over 2 weeks

**Expected Result:**
- ✅ Daily charges: $2 × 7 = $14/week
- ✅ Weekly charges: $10/week
- ✅ Monthly charge: $50/month on billing date
- ✅ All charges process independently
- ✅ No conflicts or errors

---

## Validation Checklist

After running tests, verify:

- [ ] All subscription creations use `collection_method="charge_automatically"`
- [ ] All subscription modifications use `proration_behavior="create_prorations"`
- [ ] Validation warnings appear in logs for mixed intervals
- [ ] Stripe Dashboard shows correct billing intervals for each item
- [ ] Invoices are generated at correct frequencies
- [ ] Proration calculations are accurate
- [ ] No errors in application logs
- [ ] Email notifications sent for all charges

## Log Checks

Look for these entries in logs:

```bash
# Check for interval validation warnings
grep "Mixed interval subscription" memberportal/logs/errors.log

# Check for subscription creation
grep "collection_method" memberportal/logs/errors.log

# Check for proration events
grep "proration_behavior" memberportal/logs/errors.log
```

## Stripe Dashboard Checks

For each test subscription, verify in Stripe Dashboard:

1. **Subscription Details Page:**
   - Collection method: "Automatically charge"
   - Proration behavior: Shows proration adjustments

2. **Billing Tab:**
   - Multiple items visible
   - Each item shows correct interval
   - Upcoming invoices show all charges

3. **Events Tab:**
   - `invoice.created` events for each interval
   - `invoice.payment_succeeded` for each charge
   - `subscription.updated` when items added/removed

## Troubleshooting

### Issue: "Invalid request" error when creating subscription

**Solution:** Ensure these parameters are set:
```python
collection_method="charge_automatically"
proration_behavior="create_prorations"
```

### Issue: Mixed intervals not working

**Possible Causes:**
1. Not using flexible billing parameters
2. Stripe account doesn't support feature (check with Stripe)
3. Old subscription created before flexible billing enabled

**Solution:** Cancel old subscription and create new one with flexible billing

### Issue: Proration amounts seem wrong

**Check:**
1. Verify interval_count is correct (usually 1)
2. Check billing cycle anchor date
3. Confirm all items use proration_behavior="create_prorations"

### Issue: Weekly charges not happening

**Check:**
1. Verify add-on interval is set to "week"
2. Check Stripe subscription items list
3. Look for failed payment attempts
4. Verify customer has valid payment method

## Performance Testing

For production readiness:

1. **Load Test:** Create 100+ subscriptions with mixed intervals
2. **Monitor:** Check for rate limits or timeouts
3. **Billing Cycle:** Observe full month to ensure all intervals process
4. **Database:** Check for performance issues with complex queries

## Rollback Procedure

If issues are found:

1. **Immediate:** 
   - Stop creating new mixed-interval subscriptions
   - Remove mixed-interval add-ons from existing subscriptions

2. **Code Revert:**
   - Remove `collection_method` parameter
   - Standardize all add-ons to monthly interval

3. **Data Cleanup:**
   - Cancel problematic subscriptions
   - Recreate with standard billing

## Success Criteria

Before deploying to production:

- ✅ All 8 test scenarios pass
- ✅ No errors in logs
- ✅ Proration calculations verified accurate
- ✅ Stripe Dashboard shows correct data
- ✅ Email notifications working
- ✅ Performance acceptable under load
- ✅ Rollback procedure tested and documented

## Questions or Issues?

- Check `/memberportal/logs/errors.log` for detailed error messages
- Review `FLEXIBLE_BILLING_IMPLEMENTATION.md` for architecture details
- Check Stripe Dashboard Events for API call details
- Contact development team with test results
