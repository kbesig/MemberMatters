from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from django.db.models import Q
from datetime import date, timedelta
from constance import config
from sentry_sdk import capture_exception
import logging
import stripe

from profile.models import Shelf, ShelfRequest, MemberShelfAddon, Profile
from api_admin_tools.models import SubscriptionAddon
from services.emails import send_single_email

logger = logging.getLogger("api_shelf_rental")


class MemberShelfRequestView(APIView):
    """
    Member endpoints for shelf rental requests
    get: retrieves the current user's shelf requests and rentals
    post: creates a new shelf rental request
    delete: cancels a pending shelf request
    """

    def get(self, request):
        """Get member's current shelf rentals and pending requests"""
        try:
            user_profile = request.user.profile

            # Get current rentals
            current_shelves = Shelf.objects.filter(
                Q(current_member=user_profile) | Q(next_member=user_profile)
            ).order_by("number")

            # Get pending requests
            pending_requests = ShelfRequest.objects.filter(
                member=user_profile, status="pending"
            ).order_by("requested_at")

            # Get addon configuration
            current_addon_id = getattr(config, "CURRENT_SHELF_RENTAL_ADDON", None)
            addon_info = None

            if current_addon_id and str(current_addon_id).strip():
                try:
                    addon = SubscriptionAddon.objects.get(
                        id=int(current_addon_id),
                        addon_type="shelf_rental",
                        visible=True,
                    )
                    addon_info = addon.get_object()
                except SubscriptionAddon.DoesNotExist:
                    pass

            return Response(
                {
                    "success": True,
                    "current_shelves": [
                        shelf.get_object() for shelf in current_shelves
                    ],
                    "pending_requests": [req.get_object() for req in pending_requests],
                    "addon_info": addon_info,
                }
            )

        except Exception as e:
            logger.error(f"Error fetching shelf requests: {str(e)}")
            capture_exception(e)
            return Response(
                {"success": False, "message": "Error fetching shelf information"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):
        """Create a new shelf rental request"""
        try:
            user_profile = request.user.profile
            quantity = request.data.get("quantity", 1)

            # Validate quantity
            if not isinstance(quantity, int) or quantity < 1 or quantity > 10:
                return Response(
                    {
                        "success": False,
                        "message": "Invalid quantity. Must be between 1 and 10.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check if addon is configured
            current_addon_id = getattr(config, "CURRENT_SHELF_RENTAL_ADDON", None)
            if not current_addon_id or not str(current_addon_id).strip():
                return Response(
                    {
                        "success": False,
                        "message": "Shelf rental is not currently configured.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Verify addon exists
            try:
                addon = SubscriptionAddon.objects.get(
                    id=int(current_addon_id),
                    addon_type="shelf_rental",
                    visible=True,
                )
            except SubscriptionAddon.DoesNotExist:
                return Response(
                    {"success": False, "message": "Shelf rental addon not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Create shelf requests (one per shelf)
            created_requests = []
            for i in range(quantity):
                shelf_request = ShelfRequest.objects.create(
                    member=user_profile,
                    quantity=1,
                    status="pending",
                )
                created_requests.append(shelf_request.get_object())

            request.user.log_event(
                f"Requested {quantity} shelf rental(s)",
                "shelf_rental",
            )

            return Response(
                {
                    "success": True,
                    "message": f"Successfully requested {quantity} shelf rental(s)",
                    "requests": created_requests,
                }
            )

        except Exception as e:
            logger.error(f"Error creating shelf request: {str(e)}")
            capture_exception(e)
            return Response(
                {"success": False, "message": "Error creating shelf request"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete(self, request):
        """Cancel a pending shelf request"""
        try:
            request_id = request.data.get("request_id")

            if not request_id:
                return Response(
                    {"success": False, "message": "Request ID is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            shelf_request = ShelfRequest.objects.get(
                id=request_id,
                member=request.user.profile,
                status="pending",
            )

            shelf_request.status = "cancelled"
            shelf_request.cancelled_at = timezone.now()
            shelf_request.save()

            request.user.log_event(
                f"Cancelled shelf request #{request_id}",
                "shelf_rental",
            )

            return Response(
                {
                    "success": True,
                    "message": "Shelf request cancelled successfully",
                }
            )

        except ShelfRequest.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "Shelf request not found or already processed",
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error(f"Error cancelling shelf request: {str(e)}")
            capture_exception(e)
            return Response(
                {"success": False, "message": "Error cancelling shelf request"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AdminShelfManagementView(APIView):
    """
    Admin endpoints for shelf management
    get: retrieves all shelves, queue, and statistics
    post: creates a new shelf or assigns a member to a shelf
    put: updates shelf information
    delete: removes a member from a shelf (cancels their rental)
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        """Get all shelves, queue, and statistics"""
        try:
            # Get filter and sort parameters
            search_filter = request.query_params.get("filter", "")
            sort_by = request.query_params.get(
                "sort", "number"
            )  # number, status, member

            # Get all shelves
            shelves_query = Shelf.objects.all()

            # Apply search filter
            if search_filter:
                shelves_query = shelves_query.filter(
                    Q(number__icontains=search_filter)
                    | Q(current_member__first_name__icontains=search_filter)
                    | Q(current_member__last_name__icontains=search_filter)
                    | Q(current_member__email__icontains=search_filter)
                    | Q(next_member__first_name__icontains=search_filter)
                    | Q(next_member__last_name__icontains=search_filter)
                    | Q(next_member__email__icontains=search_filter)
                )

            # Apply sorting
            if sort_by == "status":
                shelves_query = shelves_query.order_by("status", "number")
            elif sort_by == "member":
                shelves_query = shelves_query.order_by(
                    "current_member__first_name", "current_member__last_name", "number"
                )
            else:  # default to number
                shelves_query = shelves_query.order_by("number")

            shelves = [shelf.get_object() for shelf in shelves_query]

            # Get pending requests queue
            pending_queue = (
                ShelfRequest.objects.filter(status="pending")
                .select_related("member")
                .order_by("requested_at")
            )

            queue = [req.get_object() for req in pending_queue]

            # Get statistics
            stats = {
                "total_shelves": Shelf.objects.count(),
                "available": Shelf.objects.filter(status="available").count(),
                "occupied": Shelf.objects.filter(status="occupied").count(),
                "cancelled": Shelf.objects.filter(status="cancelled").count(),
                "pending_requests": pending_queue.count(),
            }

            return Response(
                {
                    "success": True,
                    "shelves": shelves,
                    "queue": queue,
                    "stats": stats,
                }
            )

        except Exception as e:
            logger.error(f"Error fetching shelf management data: {str(e)}")
            capture_exception(e)
            return Response(
                {"success": False, "message": "Error fetching shelf data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):
        """Create a new shelf or assign a member to a shelf"""
        action = request.data.get("action")  # "create_shelf" or "assign_member"

        if action == "create_shelf":
            return self._create_shelf(request)
        elif action == "assign_member":
            return self._assign_member_to_shelf(request)
        else:
            return Response(
                {"success": False, "message": "Invalid action"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _create_shelf(self, request):
        """Create a new shelf"""
        try:
            shelf_number = request.data.get("shelf_number")

            if not shelf_number:
                return Response(
                    {"success": False, "message": "Shelf number is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check if shelf already exists
            if Shelf.objects.filter(number=shelf_number).exists():
                return Response(
                    {
                        "success": False,
                        "message": "A shelf with this number already exists",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            shelf = Shelf.objects.create(
                number=shelf_number,
                status="available",
            )

            request.user.log_event(
                f"Created shelf {shelf_number}",
                "admin",
            )

            return Response(
                {
                    "success": True,
                    "message": f"Shelf {shelf_number} created successfully",
                    "shelf": shelf.get_object(),
                }
            )

        except Exception as e:
            logger.error(f"Error creating shelf: {str(e)}")
            capture_exception(e)
            return Response(
                {"success": False, "message": "Error creating shelf"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _assign_member_to_shelf(self, request):
        """Assign a member to a shelf"""
        try:
            shelf_id = request.data.get("shelf_id")
            member_id = request.data.get("member_id")
            request_id = request.data.get(
                "request_id"
            )  # Optional: links to a specific request
            available_date = request.data.get(
                "available_date"
            )  # Date when shelf becomes available
            is_next_occupant = request.data.get("is_next_occupant", False)

            if not shelf_id or not member_id:
                return Response(
                    {
                        "success": False,
                        "message": "Shelf ID and Member ID are required",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get shelf and member
            shelf = Shelf.objects.get(id=shelf_id)
            member = Profile.objects.get(id=member_id)

            # Parse available date
            if available_date:
                try:
                    available_date = date.fromisoformat(available_date)
                except (ValueError, TypeError):
                    available_date = date.today()
            else:
                available_date = date.today()

            # Determine if this is assigning as next occupant or current occupant
            if is_next_occupant or shelf.status == "cancelled":
                # Assign as next occupant
                shelf.next_member = member
                shelf.next_available_date = available_date
                if shelf.status != "cancelled":
                    shelf.status = "cancelled"
                shelf.save()

                # Don't create billing yet - that happens when they become current occupant
                message = f"Assigned {member.get_full_name()} as next occupant of Shelf {shelf.number}"

            else:
                # Assign as current occupant
                result = self._setup_shelf_billing(
                    shelf, member, available_date, request.user
                )

                if not result["success"]:
                    return Response(result, status=status.HTTP_400_BAD_REQUEST)

                message = f"Assigned {member.get_full_name()} to Shelf {shelf.number}"

            # Mark the request as assigned if provided
            if request_id:
                try:
                    shelf_request = ShelfRequest.objects.get(
                        id=request_id, member=member
                    )
                    shelf_request.status = "assigned"
                    shelf_request.assigned_at = timezone.now()
                    shelf_request.save()
                except ShelfRequest.DoesNotExist:
                    pass

            request.user.log_event(message, "admin")

            return Response(
                {
                    "success": True,
                    "message": message,
                    "shelf": shelf.get_object(),
                }
            )

        except Shelf.DoesNotExist:
            return Response(
                {"success": False, "message": "Shelf not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Profile.DoesNotExist:
            return Response(
                {"success": False, "message": "Member not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error(f"Error assigning member to shelf: {str(e)}")
            capture_exception(e)
            return Response(
                {"success": False, "message": "Error assigning member to shelf"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _setup_shelf_billing(self, shelf, member, available_date, admin_user):
        """Setup billing for a shelf rental"""
        try:
            # Get the addon configuration
            current_addon_id = getattr(config, "CURRENT_SHELF_RENTAL_ADDON", None)

            if not current_addon_id or not str(current_addon_id).strip():
                return {
                    "success": False,
                    "message": "CURRENT_SHELF_RENTAL_ADDON not configured",
                }

            addon = SubscriptionAddon.objects.get(
                id=int(current_addon_id),
                addon_type="shelf_rental",
                visible=True,
            )

            # Update shelf status
            shelf.current_member = member
            shelf.status = "occupied"
            shelf.start_date = available_date
            shelf.save()

            # Create the locked pricing record
            member_addon = MemberShelfAddon.objects.create(
                member=member,
                shelf=shelf,
                addon=addon,
                locked_cost=addon.cost,
                locked_currency=addon.currency,
                locked_interval=addon.interval,
                locked_interval_count=addon.interval_count,
            )

            # Create Stripe subscription item if member has an active subscription
            if member.stripe_subscription_id:
                stripe_result = self._create_stripe_subscription_item(
                    member, member_addon, admin_user
                )
                if not stripe_result["success"]:
                    logger.warning(
                        f"Failed to create Stripe item: {stripe_result['message']}"
                    )

            # Send notification email
            self._send_assignment_notification(member, shelf, available_date)

            return {"success": True}

        except SubscriptionAddon.DoesNotExist:
            return {
                "success": False,
                "message": "Shelf rental addon not found",
            }
        except Exception as e:
            logger.error(f"Error setting up shelf billing: {str(e)}")
            capture_exception(e)
            return {
                "success": False,
                "message": f"Error setting up billing: {str(e)}",
            }

    def _create_stripe_subscription_item(self, member, member_addon, admin_user):
        """Create a Stripe subscription item for the shelf rental"""
        try:
            stripe.api_key = config.STRIPE_SECRET_KEY

            # Get or create Stripe price
            if not member_addon.stripe_price_id:
                # Create a new price in Stripe for this locked pricing
                price = stripe.Price.create(
                    product=member_addon.addon.stripe_product_id,
                    unit_amount=member_addon.locked_cost,
                    currency=member_addon.locked_currency,
                    recurring={
                        "interval": member_addon.locked_interval,
                        "interval_count": member_addon.locked_interval_count,
                    },
                    metadata={
                        "member_id": member.id,
                        "shelf_id": member_addon.shelf.id,
                        "shelf_number": member_addon.shelf.number,
                    },
                )
                member_addon.stripe_price_id = price.id

            # Add the item to the member's subscription
            subscription_item = stripe.SubscriptionItem.create(
                subscription=member.stripe_subscription_id,
                price=member_addon.stripe_price_id,
                quantity=1,
                proration_behavior="create_prorations",
            )

            member_addon.stripe_subscription_item_id = subscription_item.id
            member_addon.save()

            admin_user.log_event(
                f"Created Stripe subscription item for {member.get_full_name()} - Shelf {member_addon.shelf.number}",
                "admin",
            )

            return {"success": True}

        except Exception as e:
            logger.error(f"Error creating Stripe subscription item: {str(e)}")
            capture_exception(e)
            return {"success": False, "message": str(e)}

    def _send_assignment_notification(self, member, shelf, available_date):
        """Send email notification to member about shelf assignment"""
        try:
            # Get email template from config
            subject_template = config.SHELF_RENTAL_ASSIGNMENT_EMAIL_SUBJECT
            body_template = config.SHELF_RENTAL_ASSIGNMENT_EMAIL_BODY

            # Format the templates
            subject = subject_template.format(
                shelf_number=shelf.number,
                available_date=available_date.strftime("%B %d, %Y"),
            )

            message = body_template.format(
                shelf_number=shelf.number,
                available_date=available_date.strftime("%B %d, %Y"),
                member_name=member.get_full_name(),
            )

            # Send email
            send_single_email(
                member.user,
                subject,
                message,
                "Shelf Rental Assigned",
            )

            logger.info(f"Sent shelf assignment notification to {member.email}")

        except Exception as e:
            logger.error(f"Error sending assignment notification: {str(e)}")
            capture_exception(e)

    def delete(self, request):
        """Remove a member from a shelf (cancel their rental)"""
        try:
            shelf_id = request.data.get("shelf_id")
            remove_type = request.data.get(
                "remove_type", "current"
            )  # "current" or "next"

            if not shelf_id:
                return Response(
                    {"success": False, "message": "Shelf ID is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            shelf = Shelf.objects.get(id=shelf_id)

            if remove_type == "next" and shelf.next_member:
                # Remove next occupant
                member_name = shelf.next_member.get_full_name()
                shelf.next_member = None
                shelf.next_available_date = None
                if shelf.current_member:
                    shelf.status = "occupied"
                else:
                    shelf.status = "available"
                shelf.save()

                message = f"Removed next occupant from Shelf {shelf.number}"

            elif shelf.current_member:
                # Remove current occupant
                member = shelf.current_member
                member_name = member.get_full_name()

                # Cancel Stripe subscription item
                try:
                    member_addon = MemberShelfAddon.objects.get(shelf=shelf)
                    if member_addon.stripe_subscription_item_id:
                        stripe.api_key = config.STRIPE_SECRET_KEY
                        stripe.SubscriptionItem.delete(
                            member_addon.stripe_subscription_item_id,
                            proration_behavior="create_prorations",
                        )
                    member_addon.delete()
                except MemberShelfAddon.DoesNotExist:
                    pass

                # If there's a next occupant, promote them
                if shelf.next_member:
                    next_member = shelf.next_member
                    next_date = shelf.next_available_date or date.today()

                    shelf.current_member = None
                    shelf.next_member = None
                    shelf.next_available_date = None
                    shelf.save()

                    # Setup billing for the next occupant
                    result = self._setup_shelf_billing(
                        shelf, next_member, next_date, request.user
                    )

                    message = f"Removed {member_name} from Shelf {shelf.number} and assigned to {next_member.get_full_name()}"
                else:
                    shelf.current_member = None
                    shelf.status = "available"
                    shelf.start_date = None
                    shelf.save()

                    message = f"Removed {member_name} from Shelf {shelf.number}"

            else:
                return Response(
                    {"success": False, "message": "No member assigned to this shelf"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            request.user.log_event(message, "admin")

            return Response(
                {
                    "success": True,
                    "message": message,
                    "shelf": shelf.get_object(),
                }
            )

        except Shelf.DoesNotExist:
            return Response(
                {"success": False, "message": "Shelf not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error(f"Error removing member from shelf: {str(e)}")
            capture_exception(e)
            return Response(
                {"success": False, "message": "Error removing member from shelf"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AdminShelfQueueView(APIView):
    """
    Admin endpoints for managing the shelf request queue
    get: get queue details
    post: reorder queue or manage requests
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        """Get the current queue with details"""
        try:
            pending_queue = (
                ShelfRequest.objects.filter(status="pending")
                .select_related("member")
                .order_by("requested_at")
            )

            return Response(
                {
                    "success": True,
                    "queue": [req.get_object() for req in pending_queue],
                }
            )

        except Exception as e:
            logger.error(f"Error fetching queue: {str(e)}")
            capture_exception(e)
            return Response(
                {"success": False, "message": "Error fetching queue"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MemberSearchView(APIView):
    """
    Search for members by name or email (for admin assignment)
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        """Search for members"""
        try:
            search_term = request.query_params.get("q", "")

            if len(search_term) < 2:
                return Response(
                    {
                        "success": True,
                        "members": [],
                    }
                )

            members = Profile.objects.filter(
                Q(first_name__icontains=search_term)
                | Q(last_name__icontains=search_term)
                | Q(user__email__icontains=search_term)
                | Q(screen_name__icontains=search_term)
            )[
                :20
            ]  # Limit to 20 results

            return Response(
                {
                    "success": True,
                    "members": [
                        {
                            "id": member.id,
                            "name": member.get_full_name(),
                            "email": member.user.email,
                            "screen_name": member.screen_name,
                        }
                        for member in members
                    ],
                }
            )

        except Exception as e:
            logger.error(f"Error searching members: {str(e)}")
            capture_exception(e)
            return Response(
                {"success": False, "message": "Error searching members"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
