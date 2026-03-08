# Shelf Rental Management Feature

## Overview
This feature allows members to request and rent physical shelves (storage spaces) from the organization. It includes a queue system for managing requests, admin tools for assigning shelves, and automatic billing integration with Stripe.

## Feature Flow

### Member Experience
1. **View Current Rentals**: Members can see their currently rented shelves and any future shelf assignments
2. **Request Shelves**: Members can request one or more shelves through the UI
3. **Queue Status**: Pending requests show in a queue with "under review" status
4. **Assignment Notification**: When assigned, members receive an email with shelf number and availability date
5. **Billing**: Shelf rental charges are automatically added to the member's subscription

### Admin Experience
1. **Dashboard View**: Shows all shelves with occupancy status, current/next members, and statistics
2. **Queue Management**: View all pending requests in order of request date
3. **Shelf Assignment**: Assign members to shelves from the queue or by search
4. **Next Occupant**: Assign a "next occupant" when current member cancels
5. **Filtering & Sorting**: Search/filter shelves by number or member name, sort by various criteria

## Technical Implementation

### Backend Components

#### Models (`memberportal/profile/models.py`)
- **Shelf**: Represents a physical shelf with number, status, current/next member, dates
- **ShelfRequest**: Queue entry for shelf rental requests
- **MemberShelfAddon**: Tracks locked pricing and Stripe subscription item for member's shelf rental

#### API Endpoints (`memberportal/api_shelf_rental/`)
##### Member Endpoints:
- `GET /api/shelf-rental/my-shelves/` - Get member's shelves and requests
- `POST /api/shelf-rental/my-shelves/` - Request new shelf rental
- `DELETE /api/shelf-rental/my-shelves/` - Cancel pending request

##### Admin Endpoints:
- `GET /api/shelf-rental/admin/shelves/` - Get all shelves, queue, and stats
- `POST /api/shelf-rental/admin/shelves/` - Create shelf or assign member
- `DELETE /api/shelf-rental/admin/shelves/` - Remove member from shelf
- `GET /api/shelf-rental/admin/members/search/` - Search for members by name/email

#### Configuration (`memberportal/membermatters/constance_config.py`)
- `CURRENT_SHELF_RENTAL_ADDON` - ID of the addon to use for shelf rental pricing
- `SHELF_RENTAL_ASSIGNMENT_EMAIL_SUBJECT` - Email subject template
- `SHELF_RENTAL_ASSIGNMENT_EMAIL_BODY` - Email body template

### Frontend Components

#### Member Interface
**Component**: `src-frontend/src/components/ShelfRental/ShelfRentalManager.vue`
- Displays current shelves with status
- Shows pending requests with cancel option
- Request form for new shelf rentals
- Integrated into Membership Plan page under "Add-ons & Rentals"

#### Admin Interface
**Component**: `src-frontend/src/components/AdminTools/AdminShelfManagement.vue`
- Statistics dashboard (total, available, occupied, pending)
- Shelves table with search, sort, and filter
- Request queue sidebar
- Assignment dialog with member search
- Create new shelf dialog
- Accessible via Admin Tools → Manage Shelves

### Database Schema

#### Shelf Table
```
- id (PK)
- number (unique, indexed)
- current_member (FK to Profile)
- next_member (FK to Profile)
- status (available/occupied/cancelled)
- start_date
- next_available_date
- created_at
- updated_at
```

#### ShelfRequest Table
```
- id (PK)
- member (FK to Profile)
- quantity (int)
- status (pending/assigned/cancelled)
- requested_at
- assigned_at
- cancelled_at
- notes (text)
```

#### MemberShelfAddon Table
```
- id (PK)
- member (FK to Profile)
- shelf (OneToOne FK to Shelf)
- addon (FK to SubscriptionAddon)
- locked_cost (int, cents)
- locked_currency (str)
- locked_interval (str)
- locked_interval_count (int)
- date_locked
- stripe_subscription_item_id (str)
- stripe_price_id (str)
```

## Setup Instructions

### 1. Create Shelf Rental Addon
1. Go to Django Admin → API Admin Tools → Subscription Add-ons
2. Click "Add Subscription Addon"
3. Fill in:
   - Name: "Shelf Rental" (or your choice)
   - Description: Description of the shelf rental service
   - Addon Type: Select "Shelf Rental"
   - Currency: Your currency (e.g., "usd")
   - Cost: Price in cents (e.g., 2000 for $20.00)
   - Interval Count: 1
   - Interval: "month"
   - Visible: ✅ Check this
4. Save the addon
5. Note the ID of the created addon

### 2. Configure Constance Settings
1. Go to Django Admin → Constance → Config
2. Find the "Shelf Rental" section
3. Set:
   - `CURRENT_SHELF_RENTAL_ADDON`: Enter the addon ID from step 1
   - `SHELF_RENTAL_ASSIGNMENT_EMAIL_SUBJECT`: Customize if desired (default: "Shelf #{shelf_number} Assigned - Available {available_date}")
   - `SHELF_RENTAL_ASSIGNMENT_EMAIL_BODY`: Customize the email body
4. Save changes

### 3. Create Shelves
1. Go to Admin Tools → Manage Shelves in the frontend
2. Click "Create Shelf"
3. Enter shelf numbers (e.g., "A1", "B2", "101", etc.)
4. Create as many shelves as you have available

### 4. Sync Stripe (if using Stripe)
The addon needs to be synced with Stripe:
1. Go to Django Admin → API Admin Tools → Subscription Add-ons
2. Find your Shelf Rental addon
3. Ensure it has been synced to Stripe (or manually create product/price in Stripe)

## Usage Workflows

### Member Requests Shelf
1. Member goes to Account → Membership Plan
2. Scrolls to "Add-ons & Rentals" section
3. Sees addon pricing information
4. Enters number of shelves desired
5. Clicks "Request Shelf Rental"
6. Request appears in "Pending Requests" section

### Admin Assigns Shelf
**From Queue:**
1. Admin goes to Admin Tools → Manage Shelves
2. Views the Request Queue on the right side
3. Clicks the assignment icon next to a request
4. Shelf assignment dialog opens with member pre-selected
5. Sets available date
6. Clicks "Assign"

**From Shelf:**
1. In the Shelves table, finds an available shelf
2. Clicks "Actions" → "Assign Member"
3. Searches for member by name/email
4. Sets available date
5. Clicks "Assign"

**Result:**
- Shelf status changes to "Occupied"
- Member's request marked as "Assigned"
- Stripe subscription item created (if member has active subscription)
- Email sent to member with shelf number and availability date

### Member Cancels Rental (Admin Process)
1. Admin goes to shelf in table
2. Clicks "Actions" → "Remove Current Member"
3. Confirms removal
4. Stripe subscription item is cancelled with proration
5. If next occupant exists, they are automatically promoted
6. Otherwise, shelf becomes "Available"

### Assigning Next Occupant
1. When shelf is occupied, admin can click "Actions" → "Assign Next Occupant"
2. Shelf status becomes "Cancelled"
3. Current member continues until their end date
4. Next occupant's start date is set
5. On the assignment date, next occupant becomes current occupant automatically

## Email Notifications

When a member is assigned a shelf, they receive an email with:
- Shelf number
- Availability/start date
- Customizable message body

Email templates use placeholders:
- `{shelf_number}` - The shelf number
- `{available_date}` - The date when shelf is available
- `{member_name}` - The member's full name

## Billing Integration

### How It Works
1. When admin assigns a member to a shelf, a `MemberShelfAddon` record is created
2. The current addon pricing is "locked" to protect against future price changes
3. If member has an active Stripe subscription:
   - A new Price is created in Stripe with locked pricing
   - A Subscription Item is added to member's subscription
   - Proration is automatically calculated
4. Member is billed monthly according to their billing cycle

### Proration
- Charges are prorated to align with member's billing cycle anchor (1st of month)
- If assigned mid-month, member pays prorated amount for remainder of month

### Cancellation
- When member is removed from shelf, subscription item is deleted from Stripe
- Credit/proration is automatically applied

## Admin Tools Features

### Statistics Dashboard
- Total Shelves: Count of all shelves
- Available: Shelves ready for assignment
- Occupied: Shelves currently rented
- Pending Requests: Queue count

### Search & Filter
- Search by shelf number
- Search by member name or email
- Filter applies to both current and next members

### Sorting Options
- By Shelf Number (default)
- By Status (available/occupied/cancelled)
- By Member Name (alphabetical)

### Request Queue
- Shows all pending requests
- Ordered by request date (oldest first)
- Displays member name, email, request date
- Quick assignment button

## Future Enhancements (Not Implemented)
- Bulk shelf creation
- Shelf categories/sizes
- Waitlist notifications
- Automatic assignment from queue
- Member-initiated cancellation
- Photo upload for shelf contents
- QR code generation for shelves
- Shelf availability calendar

## Troubleshooting

### Member Can't Request Shelf
- Check `CURRENT_SHELF_RENTAL_ADDON` is configured
- Verify addon exists and is visible
- Check addon type is "shelf_rental"

### Stripe Item Not Created
- Verify member has active subscription
- Check addon has Stripe product/price IDs
- Review error logs in `memberportal/errors.log`
- Ensure `STRIPE_SECRET_KEY` is configured

### Email Not Sent
- Check email configuration in Constance
- Verify `EMAIL_DEFAULT_FROM` is set
- Review error logs for email sending errors

## Files Modified/Created

### Backend
- `memberportal/profile/models.py` - Added Shelf, ShelfRequest, MemberShelfAddon models
- `memberportal/api_admin_tools/models.py` - Added "shelf_rental" addon type
- `memberportal/api_shelf_rental/` - New API app
  - `__init__.py`
  - `views.py`
  - `urls.py`
  - `admin.py`
- `memberportal/membermatters/settings.py` - Added api_shelf_rental to INSTALLED_APPS
- `memberportal/membermatters/urls.py` - Added api_shelf_rental URLs
- `memberportal/membermatters/constance_config.py` - Added shelf rental configuration
- `memberportal/api_admin_tools/migrations/0015_add_shelf_rental_models.py` - Migration
- `memberportal/profile/migrations/0032_add_shelf_rental_models.py` - Migration

### Frontend
- `src-frontend/src/components/ShelfRental/ShelfRentalManager.vue` - Member component
- `src-frontend/src/components/AdminTools/AdminShelfManagement.vue` - Admin component
- `src-frontend/src/pages/AdminTools/ManageShelves.vue` - Admin page
- `src-frontend/src/pages/MembershipPlan.vue` - Modified to include shelf rental
- `src-frontend/src/pages/pageAndRouteConfig.ts` - Added route for admin shelf management

## API Reference

### Member API

#### GET /api/shelf-rental/my-shelves/
Returns member's current shelves and pending requests.

**Response:**
```json
{
  "success": true,
  "current_shelves": [
    {
      "id": 1,
      "number": "A1",
      "status": "occupied",
      "status_display": "Occupied",
      "current_member": { ... },
      "start_date": "2026-01-15"
    }
  ],
  "pending_requests": [
    {
      "id": 5,
      "member": { ... },
      "quantity": 1,
      "status": "pending",
      "requested_at": "2026-01-20T10:30:00Z"
    }
  ],
  "addon_info": {
    "id": 3,
    "name": "Shelf Rental",
    "cost_display": "$20.00",
    "interval": "month"
  }
}
```

#### POST /api/shelf-rental/my-shelves/
Request new shelf rental(s).

**Request:**
```json
{
  "quantity": 2
}
```

**Response:**
```json
{
  "success": true,
  "message": "Successfully requested 2 shelf rental(s)",
  "requests": [ ... ]
}
```

#### DELETE /api/shelf-rental/my-shelves/
Cancel a pending request.

**Request:**
```json
{
  "request_id": 5
}
```

### Admin API

#### GET /api/shelf-rental/admin/shelves/
Get all shelves, queue, and statistics.

**Query Parameters:**
- `filter` - Search string for shelf number or member name
- `sort` - Sort by: "number", "status", or "member"

#### POST /api/shelf-rental/admin/shelves/
Create shelf or assign member.

**Create Shelf:**
```json
{
  "action": "create_shelf",
  "shelf_number": "A1"
}
```

**Assign Member:**
```json
{
  "action": "assign_member",
  "shelf_id": 1,
  "member_id": 42,
  "request_id": 5,  // optional
  "available_date": "2026-02-01",
  "is_next_occupant": false
}
```

#### DELETE /api/shelf-rental/admin/shelves/
Remove member from shelf.

**Request:**
```json
{
  "shelf_id": 1,
  "remove_type": "current"  // or "next"
}
```

## Notes

- Shelf numbers are unique and can be any string (letters, numbers, or combination)
- One request per shelf is created when quantity > 1 (e.g., requesting 3 shelves creates 3 separate requests)
- Billing integration is automatic but only works if member has an active subscription
- Email notifications use the templates configured in Constance
- Admin logs are created for all shelf assignments and removals
