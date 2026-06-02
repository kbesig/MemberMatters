import stripe
import logging
from django.utils import timezone

from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from constance import config
from sentry_sdk import capture_exception

logger = logging.getLogger("billing")


class StripeAPIView(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not config.ENABLE_STRIPE:
            return
        try:
            stripe.api_key = config.STRIPE_SECRET_KEY
            stripe.api_version = "2025-06-30.basil"
        except Exception:
            pass


def _setup_shelf_billing(shelf, member, addon):
    """Create a Stripe subscription item for the member's shelf rental and save locked pricing."""
    from profile.models import MemberShelfAddon

    member_shelf_addon = MemberShelfAddon.objects.create(
        member=member,
        shelf=shelf,
        addon=addon,
        locked_cost=addon.cost,
        locked_currency=addon.currency,
        locked_interval=addon.interval,
        locked_interval_count=addon.interval_count,
    )

    if member.stripe_subscription_id:
        try:
            custom_price = stripe.Price.create(
                unit_amount=addon.cost,
                currency=addon.currency,
                recurring={
                    "interval": addon.interval,
                    "interval_count": addon.interval_count,
                },
                product_data={
                    "name": f"Shelf Rental #{shelf.number} - {member.get_full_name()}",
                    "metadata": {
                        "shelf_id": str(shelf.id),
                        "member_id": str(member.user.id),
                        "addon_id": str(addon.id),
                    },
                },
            )
            sub_item = stripe.SubscriptionItem.create(
                subscription=member.stripe_subscription_id,
                price=custom_price.id,
                proration_behavior="create_prorations",
            )
            member_shelf_addon.stripe_subscription_item_id = sub_item.id
            member_shelf_addon.stripe_price_id = custom_price.id
            member_shelf_addon.save()
        except stripe.error.StripeError as e:
            capture_exception(e)

    return member_shelf_addon


def _send_shelf_assignment_notification(shelf, member):
    """Send a shelf assignment email to the member using configurable templates."""
    try:
        available_date = (
            shelf.start_date.strftime("%B %d, %Y")
            if shelf.start_date
            else "immediately"
        )
        subject = config.SHELF_RENTAL_ASSIGNMENT_EMAIL_SUBJECT.format(
            shelf_number=shelf.number,
            available_date=available_date,
        )
        body = config.SHELF_RENTAL_ASSIGNMENT_EMAIL_BODY.format(
            shelf_number=shelf.number,
            available_date=available_date,
            member_name=member.get_full_name(),
        )
        member.user.email_notification(subject=subject, message=body)
    except Exception:
        pass


class MemberShelvesView(StripeAPIView):
    """
    get: returns the member's current shelves and pending requests.
    post: submits a shelf rental request.
    delete: cancels a pending shelf request.
    """

    def get(self, request):
        from profile.models import Shelf, ShelfRequest, MemberShelfAddon

        profile = request.user.profile
        shelves_data = []

        for shelf in Shelf.objects.filter(current_member=profile):
            pricing = None
            try:
                addon_record = shelf.addon
                pricing = {
                    "cost": addon_record.locked_cost,
                    "cost_display": f"${addon_record.locked_cost / 100:.2f}",
                    "interval": addon_record.locked_interval,
                }
            except MemberShelfAddon.DoesNotExist:
                pass

            shelves_data.append(
                {
                    "id": shelf.id,
                    "number": shelf.number,
                    "status": shelf.status,
                    "start_date": shelf.start_date,
                    "pricing": pricing,
                }
            )

        pending_requests = ShelfRequest.objects.filter(member=profile, status="pending")
        requests_data = [
            {
                "id": req.id,
                "quantity": req.quantity,
                "status": req.status,
                "requested_at": req.requested_at,
            }
            for req in pending_requests
        ]

        return Response({"shelves": shelves_data, "pending_requests": requests_data})

    def post(self, request):
        from profile.models import ShelfRequest

        profile = request.user.profile

        if not profile.has_active_subscription():
            return Response(
                {
                    "success": False,
                    "message": "An active subscription is required to request a shelf.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not config.CURRENT_SHELF_RENTAL_ADDON:
            return Response(
                {
                    "success": False,
                    "message": "Shelf rental is not currently available.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if ShelfRequest.objects.filter(member=profile, status="pending").exists():
            return Response(
                {
                    "success": False,
                    "message": "You already have a pending shelf request.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        quantity = request.data.get("quantity", 1)
        shelf_request = ShelfRequest.objects.create(member=profile, quantity=quantity)

        return Response(
            {
                "success": True,
                "request": {
                    "id": shelf_request.id,
                    "quantity": shelf_request.quantity,
                    "status": shelf_request.status,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request):
        from profile.models import ShelfRequest

        profile = request.user.profile
        request_id = request.data.get("request_id")

        if not request_id:
            return Response(
                {"success": False, "message": "request_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            shelf_request = ShelfRequest.objects.get(
                pk=request_id, member=profile, status="pending"
            )
        except ShelfRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Pending request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        shelf_request.status = "cancelled"
        shelf_request.cancelled_at = timezone.now()
        shelf_request.save()

        return Response({"success": True})


class AdminShelvesView(StripeAPIView):
    """
    get: list all shelves with stats and request queue.
    post: create a new shelf or assign a member to a shelf.
    delete: remove a member from a shelf.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        from profile.models import Shelf, ShelfRequest

        shelf_status_filter = request.query_params.get("status")
        sort = request.query_params.get("sort", "number")

        shelves_qs = Shelf.objects.all()
        if shelf_status_filter:
            shelves_qs = shelves_qs.filter(status=shelf_status_filter)
        shelves_qs = shelves_qs.order_by(sort)

        def format_member(profile):
            if not profile:
                return None
            return {
                "id": profile.user.id,
                "name": profile.get_full_name(),
                "email": profile.user.email,
            }

        shelves_data = [
            {
                "id": s.id,
                "number": s.number,
                "status": s.status,
                "current_member": format_member(s.current_member),
                "next_member": format_member(s.next_member),
                "start_date": s.start_date,
                "next_available_date": s.next_available_date,
            }
            for s in shelves_qs
        ]

        all_shelves = Shelf.objects.all()
        stats = {
            "total": all_shelves.count(),
            "occupied": all_shelves.filter(status="occupied").count(),
            "available": all_shelves.filter(status="available").count(),
            "cancelled": all_shelves.filter(status="cancelled").count(),
        }

        queue = ShelfRequest.objects.filter(status="pending").select_related(
            "member__user"
        )
        queue_data = [
            {
                "id": req.id,
                "member": format_member(req.member),
                "quantity": req.quantity,
                "requested_at": req.requested_at,
            }
            for req in queue
        ]

        return Response({"shelves": shelves_data, "stats": stats, "queue": queue_data})

    def post(self, request):
        from profile.models import Shelf, ShelfRequest, Profile

        action = request.data.get("action")

        if action == "create":
            number = request.data.get("number", "").strip()
            if not number:
                return Response(
                    {"error": "number is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if Shelf.objects.filter(number=number).exists():
                return Response(
                    {"error": f"Shelf '{number}' already exists."},
                    status=status.HTTP_409_CONFLICT,
                )
            shelf = Shelf.objects.create(number=number)
            return Response(
                {
                    "id": shelf.id,
                    "number": shelf.number,
                    "status": shelf.status,
                },
                status=status.HTTP_201_CREATED,
            )

        elif action == "assign":
            shelf_id = request.data.get("shelf_id")
            member_id = request.data.get("member_id")

            if not shelf_id or not member_id:
                return Response(
                    {"error": "shelf_id and member_id are required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                shelf = Shelf.objects.get(pk=shelf_id)
            except Shelf.DoesNotExist:
                return Response(
                    {"error": "Shelf not found."}, status=status.HTTP_404_NOT_FOUND
                )

            try:
                member = Profile.objects.get(user__id=member_id)
            except Profile.DoesNotExist:
                return Response(
                    {"error": "Member not found."}, status=status.HTTP_404_NOT_FOUND
                )

            if not member.has_active_subscription():
                return Response(
                    {"error": "Member does not have an active subscription."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            addon_id = config.CURRENT_SHELF_RENTAL_ADDON
            if not addon_id:
                return Response(
                    {"error": "No shelf rental addon configured."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            from api_admin_tools.models import SubscriptionAddon

            try:
                addon = SubscriptionAddon.objects.get(pk=int(addon_id))
            except (SubscriptionAddon.DoesNotExist, ValueError):
                return Response(
                    {"error": "Configured shelf rental addon not found."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            _setup_shelf_billing(shelf, member, addon)

            shelf.current_member = member
            shelf.status = "occupied"
            shelf.start_date = timezone.now().date()
            shelf.save()

            # Mark pending request as assigned if one exists
            pending = ShelfRequest.objects.filter(
                member=member, status="pending"
            ).first()
            if pending:
                pending.status = "assigned"
                pending.assigned_at = timezone.now()
                pending.save()

            _send_shelf_assignment_notification(shelf, member)

            request.user.log_event(
                f"Assigned shelf {shelf.number} to {member.get_full_name()}.",
                "admin",
            )

            return Response({"success": True, "shelfId": shelf.id})

        elif action == "set-next":
            shelf_id = request.data.get("shelf_id")
            member_id = request.data.get("member_id")

            if not shelf_id:
                return Response(
                    {"error": "shelf_id is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                shelf = Shelf.objects.get(pk=shelf_id)
            except Shelf.DoesNotExist:
                return Response(
                    {"error": "Shelf not found."}, status=status.HTTP_404_NOT_FOUND
                )

            if member_id:
                try:
                    next_member = Profile.objects.get(user__id=member_id)
                except Profile.DoesNotExist:
                    return Response(
                        {"error": "Member not found."}, status=status.HTTP_404_NOT_FOUND
                    )
                shelf.next_member = next_member
                shelf.status = "cancelled"
            else:
                # Clear next_member
                shelf.next_member = None
                if shelf.current_member:
                    shelf.status = "occupied"

            shelf.save()

            request.user.log_event(
                f"Set next member for shelf {shelf.number} to "
                f"{shelf.next_member.get_full_name() if shelf.next_member else 'none'}.",
                "admin",
            )

            def format_member(profile):
                if not profile:
                    return None
                return {
                    "id": profile.user.id,
                    "name": profile.get_full_name(),
                    "email": profile.user.email,
                }

            return Response(
                {
                    "success": True,
                    "shelf": {
                        "id": shelf.id,
                        "number": shelf.number,
                        "status": shelf.status,
                        "current_member": format_member(shelf.current_member),
                        "next_member": format_member(shelf.next_member),
                    },
                }
            )

        else:
            return Response(
                {"error": "action must be 'create', 'assign', or 'set-next'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def delete(self, request):
        from profile.models import Shelf, MemberShelfAddon, Profile

        shelf_id = request.data.get("shelf_id")
        member_id = request.data.get("member_id")

        if not shelf_id or not member_id:
            return Response(
                {"error": "shelf_id and member_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            shelf = Shelf.objects.get(pk=shelf_id)
        except Shelf.DoesNotExist:
            return Response(
                {"error": "Shelf not found."}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            member = Profile.objects.get(user__id=member_id)
        except Profile.DoesNotExist:
            return Response(
                {"error": "Member not found."}, status=status.HTTP_404_NOT_FOUND
            )

        # Remove Stripe subscription item
        try:
            shelf_addon = shelf.addon
            if shelf_addon.stripe_subscription_item_id:
                try:
                    stripe.SubscriptionItem.delete(
                        shelf_addon.stripe_subscription_item_id,
                        proration_behavior="create_prorations",
                    )
                except stripe.error.StripeError as e:
                    capture_exception(e)
            shelf_addon.delete()
        except MemberShelfAddon.DoesNotExist:
            pass

        # Next-occupant promotion
        if shelf.next_member:
            next_member = shelf.next_member
            addon_id = config.CURRENT_SHELF_RENTAL_ADDON
            if addon_id:
                from api_admin_tools.models import SubscriptionAddon

                try:
                    addon = SubscriptionAddon.objects.get(pk=int(addon_id))
                    _setup_shelf_billing(shelf, next_member, addon)
                except Exception as e:
                    capture_exception(e)

            shelf.current_member = next_member
            shelf.next_member = None
            shelf.status = "occupied"
            shelf.start_date = timezone.now().date()
            shelf.save()

            # Mark pending request for next_member as assigned
            from profile.models import ShelfRequest

            pending = ShelfRequest.objects.filter(
                member=next_member, status="pending"
            ).first()
            if pending:
                pending.status = "assigned"
                pending.assigned_at = timezone.now()
                pending.save()

            _send_shelf_assignment_notification(shelf, next_member)

            request.user.log_event(
                f"Removed {member.get_full_name()} from shelf {shelf.number}; promoted {next_member.get_full_name()}.",
                "admin",
            )
        else:
            shelf.current_member = None
            shelf.status = "available"
            shelf.start_date = None
            shelf.save()

            request.user.log_event(
                f"Removed {member.get_full_name()} from shelf {shelf.number}.",
                "admin",
            )

        return Response({"success": True})


class AdminMemberSearch(APIView):
    """
    get: search members by name or email for shelf assignment.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        from profile.models import Profile
        from django.db.models import Q

        query = request.query_params.get("q", "").strip()
        if len(query) < 2:
            return Response([])

        profiles = Profile.objects.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(user__email__icontains=query)
        ).select_related("user")[:20]

        return Response(
            [
                {
                    "id": p.user.id,
                    "name": p.get_full_name(),
                    "email": p.user.email,
                }
                for p in profiles
            ]
        )
