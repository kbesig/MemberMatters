import json
import logging
import stripe

logger = logging.getLogger("billing")
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from constance import config
from constance.backends.database.models import Constance as ConstanceSetting
from django.db.models import F, Sum, Value, CharField, Count, Max
from django.db.models.functions import Concat
from django.db.utils import OperationalError
from rest_framework import permissions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey
from sentry_sdk import capture_exception
from sentry_sdk import capture_message

from access import models
from access.models import DoorLog, InterlockLog
from memberbucks.models import (
    MemberBucks,
    MemberbucksProductPurchaseLog,
)
from profile.models import User, UserEventLog
from services import sms
from services.emails import send_email_to_admin
from .models import MemberTier, PaymentPlan


class StripeAPIView(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not config.ENABLE_STRIPE:
            return

        try:
            stripe.api_key = config.STRIPE_SECRET_KEY
        except OperationalError as error:
            capture_exception(error)


class GetMembers(APIView):
    """
    get: This method returns a list of members.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request):
        filtered = []

        members_queryset = User.objects.select_related("profile")

        screenName = request.GET.get("screenName")
        if screenName is not None:
            members_queryset = members_queryset.filter(profile__screen_name=screenName)

        members = members_queryset.all()

        for member in members:
            filtered.append(member.profile.get_admin_profile())

        return Response(filtered)


class MemberState(APIView):
    """
    get: This method gets a member's state.
    post: This method sets a member's state.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request, member_id, state=None):
        member = User.objects.get(id=member_id)

        return Response({"state": member.profile.state})

    def post(self, request, member_id, state):
        member = User.objects.get(id=member_id)
        if state == "active":
            member.profile.activate(request)
        elif state == "inactive":
            member.profile.deactivate(request)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        return Response()


class MakeMember(APIView):
    """
    post: This activates a new member.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        user = User.objects.get(id=member_id)

        # if they're a new member or account only
        if user.profile.state == "noob" or user.profile.state == "accountonly":
            # give default door access
            for door in models.Doors.objects.filter(all_members=True):
                user.profile.doors.add(door)

            # give default interlock access
            for interlock in models.Interlock.objects.filter(all_members=True):
                user.profile.interlocks.add(interlock)

            # send the welcome email
            email = user.email_welcome()

            # mark them as "active"
            user.profile.activate()

            subject = f"{user.profile.get_full_name()} just got turned into a member!"
            send_email_to_admin(
                subject=subject,
                template_vars={"title": subject, "message": subject},
                user=request.user,
            )

            if email:
                return Response(
                    {
                        "success": True,
                        "message": "adminTools.makeMemberSuccess",
                    }
                )

            # if there was an error sending the welcome email
            elif email is False:
                return Response(
                    {"success": False, "message": "adminTools.makeMemberErrorEmail"}
                )

            # otherwise some other error happened
            else:
                capture_message("Unknown error occurred when running makemember.")
                return Response(
                    {
                        "success": False,
                        "message": "adminTools.makeMemberError",
                    }
                )
        else:
            return Response(
                {
                    "success": False,
                    "message": "adminTools.makeMemberErrorExists",
                }
            )


class Doors(APIView):
    """
    get: returns a list of doors.
    put: updates a specific door.
    delete: deletes a specific door.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        doors = models.Doors.objects.all()

        def get_door(door):
            logs = models.DoorLog.objects.filter(door_id=door.id)

            # Query to get the statistics
            stats = (
                logs.select_related("user__profile")
                .values("door_id")
                .annotate(
                    screen_name=F("user__profile__screen_name"),
                    full_name=Concat(
                        F("user__profile__first_name"),
                        Value(" "),
                        F("user__profile__last_name"),
                        output_field=CharField(),
                    ),
                    total_swipes=Count("door_id"),
                    last_swipe=Max("date"),
                )
                .order_by("-total_swipes")
            )

            return {
                "id": door.id,
                "name": door.name,
                "description": door.description,
                "ipAddress": door.ip_address,
                "serialNumber": door.serial_number,
                "lastSeen": door.last_seen,
                "offline": door.get_unavailable(),
                "defaultAccess": door.all_members,
                "maintenanceLockout": door.locked_out,
                "playThemeOnSwipe": door.play_theme,
                "postDiscordOnSwipe": door.post_to_discord,
                "postSlackOnSwipe": door.post_to_slack,
                "exemptFromSignin": door.exempt_signin,
                "hiddenToMembers": door.hidden,
                "totalSwipes": logs.count(),
                "userStats": stats,
            }

        return Response(map(get_door, doors))

    def put(self, request, door_id):
        door = models.Doors.objects.get(pk=door_id)
        data = request.data
        all_members_added = False
        all_members_removed = False
        locked_out_changed = False

        if door.all_members != data.get("defaultAccess"):
            if data.get("defaultAccess"):
                all_members_added = True
            else:
                all_members_removed = True

        if door.locked_out != data.get("maintenanceLockout"):
            locked_out_changed = True

        door.name = data.get("name")
        door.description = data.get("description")
        door.ip_address = data.get("ipAddress")
        door.serial_number = data.get("serialNumber")
        door.all_members = data.get("defaultAccess")
        door.locked_out = data.get("maintenanceLockout")
        door.play_theme = data.get("playThemeOnSwipe")
        door.post_to_discord = data.get("postDiscordOnSwipe")
        door.post_to_slack = data.get("postSlackOnSwipe")
        door.exempt_signin = data.get("exemptFromSignin")
        door.hidden = data.get("hiddenToMembers")
        door.save()

        if locked_out_changed:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                door.serial_number, {"type": "update_device_locked_out"}
            )

        if all_members_added or all_members_removed:
            members = User.objects.all()

            for member in members:
                if all_members_added:
                    member.profile.doors.add(door)
                else:
                    member.profile.doors.remove(door)

                member.profile.save()

        if (
            all_members_added
            or all_members_removed
            or locked_out_changed
            or door.exempt_signin != data.get("exemptFromSignin")
        ):
            # once we're done, sync changes to the device
            door.sync()

            # update the door object on the websocket consumer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                door.serial_number, {"type": "update_device_object"}
            )

        return Response()

    def delete(self, request, door_id):
        door = models.Doors.objects.get(pk=door_id)
        door.delete()

        return Response()


class Interlocks(APIView):
    """
    get: returns a list of interlocks.
    put: update a specific interlock.
    delete: delete a specific interlock.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        interlocks = models.Interlock.objects.all()

        def get_interlock(interlock):
            # Calculate total on time
            logs = InterlockLog.objects.filter(interlock_id=interlock.id)
            total_time = logs.aggregate(total_time=Sum("total_time")).get("total_time")
            total_time_seconds = total_time.total_seconds() if total_time else 0

            # Retrieve stats
            stats = (
                logs.select_related("user_started__profile")
                .values("interlock_id")
                .annotate(
                    screen_name=F("user_started__profile__screen_name"),
                    full_name=Concat(
                        F("user_started__profile__first_name"),
                        Value(" "),
                        F("user_started__profile__last_name"),
                        output_field=CharField(),
                    ),
                    total_swipes=Count("total_time"),
                    total_seconds=Sum("total_time"),
                )
                .order_by("-total_seconds", "-total_swipes")
            )

            return {
                "id": interlock.id,
                "authorised": interlock.authorised,
                "name": interlock.name,
                "description": interlock.description,
                "ipAddress": interlock.ip_address,
                "lastSeen": interlock.last_seen,
                "offline": interlock.get_unavailable(),
                "defaultAccess": interlock.all_members,
                "maintenanceLockout": interlock.locked_out,
                "playThemeOnSwipe": interlock.play_theme,
                "exemptFromSignin": interlock.exempt_signin,
                "hiddenToMembers": interlock.hidden,
                "totalTimeSeconds": total_time_seconds,
                "userStats": list(stats),
            }

        return Response(map(get_interlock, interlocks))

    def put(self, request, interlock_id):
        interlock = models.Interlock.objects.get(pk=interlock_id)
        data = request.data
        all_members_added = False
        all_members_removed = False
        locked_out_changed = False

        if interlock.all_members != data.get("defaultAccess"):
            if data.get("defaultAccess"):
                all_members_added = True
            else:
                all_members_removed = True

        if interlock.locked_out != data.get("maintenanceLockout"):
            locked_out_changed = True

        interlock.name = data.get("name")
        interlock.description = data.get("description")
        interlock.ip_address = data.get("ipAddress")
        interlock.all_members = data.get("defaultAccess")
        interlock.locked_out = data.get("maintenanceLockout")
        interlock.play_theme = data.get("playThemeOnSwipe")
        interlock.exempt_signin = data.get("exemptFromSignin")
        interlock.hidden = data.get("hiddenToMembers")
        interlock.save()

        if locked_out_changed:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                interlock.serial_number, {"type": "update_device_locked_out"}
            )

        if all_members_added or all_members_removed:
            members = User.objects.all()

            for member in members:
                if all_members_added:
                    member.profile.interlocks.add(interlock)
                else:
                    member.profile.interlocks.remove(interlock)

                member.profile.save()

        if (
            all_members_added
            or all_members_removed
            or locked_out_changed
            or interlock.exempt_signin != data.get("exemptFromSignin")
        ):
            # once we're done, sync changes to the device
            interlock.sync()

            # update the door object on the websocket consumer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                interlock.serial_number, {"type": "update_device_object"}
            )

        return Response()

    def delete(self, request, interlock_id):
        interlock = models.Interlock.objects.get(pk=interlock_id)
        interlock.delete()

        return Response()


class MemberbucksDevices(APIView):
    """
    get: returns a list of memberbucks devices.
    put: update a specific memberbucks device.
    delete: delete a specific memberbucks device.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        devices = models.MemberbucksDevice.objects.all()

        def get_device(device):
            # Calculate total transaction volume
            purchases = MemberbucksProductPurchaseLog.objects.filter(
                memberbucks_device_id=device.id, success=True
            )
            total_count = purchases.count()
            total_volume = (
                purchases.aggregate(total_volume=Sum("price")).get("total_volume") or 0
            ) / 100

            # Retrieve stats
            stats = (
                purchases.select_related("user__profile")
                .values("memberbucks_device_id")
                .annotate(
                    screen_name=F("user__profile__screen_name"),
                    full_name=Concat(
                        F("user__profile__first_name"),
                        Value(" "),
                        F("user__profile__last_name"),
                        output_field=CharField(),
                    ),
                    total_purchases=Count("price"),
                    total_volume=(Sum("price") or 0) / 100,
                )
                .order_by("-total_purchases", "-total_volume")
            )

            return {
                "id": device.id,
                "authorised": device.authorised,
                "name": device.name,
                "description": device.description,
                "ipAddress": device.ip_address,
                "lastSeen": device.last_seen,
                "offline": device.get_unavailable(),
                "defaultAccess": device.all_members,
                "maintenanceLockout": device.locked_out,
                "playThemeOnSwipe": device.play_theme,
                "exemptFromSignin": device.exempt_signin,
                "hiddenToMembers": device.hidden,
                "totalPurchases": total_count,
                "totalVolume": total_volume,
                "userStats": list(stats),
            }

        return Response(map(get_device, devices))

    def put(self, request, device_id):
        device = models.MemberbucksDevice.objects.get(pk=device_id)

        data = request.data

        device.name = data.get("name")
        device.description = data.get("description")
        device.ip_address = data.get("ipAddress")

        device.all_members = data.get("defaultAccess")
        device.locked_out = data.get("maintenanceLockout")
        device.play_theme = data.get("playThemeOnSwipe")
        device.exempt_signin = data.get("exemptFromSignin")
        device.hidden = data.get("hiddenToMembers")

        device.save()

        return Response()

    def delete(self, request, device_id):
        device = models.MemberbucksDevice.objects.get(pk=device_id)
        device.delete()

        return Response()


class MemberAccess(APIView):
    """
    get: This method gets a member's access permissions.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request, member_id):
        member = User.objects.get(id=member_id)

        return Response(member.profile.get_access_permissions(ignore_user_state=True))


class MemberWelcomeEmail(APIView):
    """
    post: This method sends a welcome email to the specified member.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        member = User.objects.get(id=member_id)
        member.email_welcome()

        return Response()


class MemberSendSms(APIView):
    """
    post: This method sends a custom sms alert to the specified member.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        member = User.objects.get(id=member_id)
        sms_body = request.data["smsBody"]

        if not config.SMS_ENABLE:
            return Response(
                {"success": False, "message": "SMS functionality not enabled."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not member.profile.phone:
            return Response(
                {"success": False, "message": "Member does not have a phone number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # check if the sms body exists, is at least 1 character, and isn't more than 320 characters
        if not sms_body or len(sms_body) < 1 or len(sms_body) > 320:
            return Response(
                {"success": False, "message": "SMS body is invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sms_message = sms.SMS()
        sms_message.send_custom_notification(
            to_number=member.profile.phone,
            message=sms_body,
            portal_user_sender=request.user,
            portal_user_recipient=member,
        )

        return Response()


class MemberProfile(APIView):
    """
    put: This method updates a member's profile.
    """

    permission_classes = (permissions.IsAdminUser,)

    def put(self, request, member_id):
        if not member_id:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        body = json.loads(request.body)
        member = User.objects.get(id=member_id)
        rfid_changed = False

        if member.profile.rfid != body.get("rfidCard"):
            rfid_changed = True

        member.email = body.get("email")
        member.profile.first_name = body.get("firstName")
        member.profile.last_name = body.get("lastName")
        member.profile.rfid = body.get("rfidCard")
        member.profile.phone = body.get("phone")
        member.profile.screen_name = body.get("screenName")
        member.profile.vehicle_registration_plate = body.get("vehicleRegistrationPlate")
        member.profile.exclude_from_email_export = body.get("excludeFromEmailExport")
        member.profile.suffix = body.get("suffix", "")
        member.profile.birthdate = body.get("birthdate") or None
        member.profile.notes = body.get("notes", "")
        member.profile.additional_contacts = body.get("additionalContacts", "")
        member.profile.organization = body.get("organization", "")
        member.profile.address_line1 = body.get("addressLine1", "")
        member.profile.address_line2 = body.get("addressLine2", "")
        member.profile.city = body.get("city", "")
        member.profile.address_state_province = body.get("addressStateProvince", "")
        member.profile.country = body.get("country", "")
        member.profile.postal_code = body.get("postalCode", "")

        member.save()
        member.profile.save()

        if rfid_changed:
            for door in member.profile.doors.all():
                door.sync()

        return Response()


class ManageMembershipTier(StripeAPIView):
    """
    get: gets a membership tier.
    post: creates a new membership tier.
    put: updates a membership tier.
    delete: deletes a membership tier.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get_tier(self, tier: MemberTier):
        return {
            "id": tier.id,
            "name": tier.name,
            "description": tier.description,
            "visible": tier.visible,
            "featured": tier.featured,
            "stripeId": tier.stripe_id,
        }

    def get(self, request, tier_id=None):
        if tier_id:
            try:
                tier = MemberTier.objects.get(pk=tier_id)
                return Response(self.get_tier(tier))

            except MemberTier.DoesNotExist as e:
                return Response(status=status.HTTP_404_NOT_FOUND)

        else:
            formatted_tiers = []

            for tier in MemberTier.objects.all():
                formatted_tiers.append(self.get_tier(tier))

            return Response(formatted_tiers)

    def post(self, request):
        body = request.data

        try:
            product = stripe.Product.create(
                name=body["name"], description=body["description"]
            )
            tier = MemberTier.objects.create(
                name=body["name"],
                description=body["description"],
                visible=body["visible"],
                featured=body["featured"],
                stripe_id=product.id,
            )

            return Response(self.get_tier(tier))

        except stripe.error.AuthenticationError:
            return Response(
                {"success": False, "message": "error.stripeNotConfigured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def put(self, request, tier_id):
        body = request.data

        tier = MemberTier.objects.get(pk=tier_id)

        tier.name = body["name"]
        tier.description = body["description"]
        tier.visible = body["visible"]
        tier.featured = body["featured"]
        tier.save()

        return Response(self.get_tier(tier))

    def delete(self, request, tier_id):
        tier = MemberTier.objects.get(pk=tier_id)
        tier.delete()

        return Response()


class ManageMembershipTierPlan(StripeAPIView):
    """
    get: gets an individual or a list of payment plans.
    post: creates a new payment plan.

    """

    permission_classes = (permissions.IsAdminUser,)

    def get_plan(self, plan: PaymentPlan):
        return {
            "id": plan.id,
            "name": plan.name,
            "stripeId": plan.stripe_id,
            "memberTier": plan.member_tier.id,
            "visible": plan.visible,
            "currency": plan.currency,
            "cost": plan.cost / 100,  # convert to dollars
            "intervalCount": plan.interval_count,
            "interval": plan.interval,
        }

    def get(self, request, plan_id=None, tier_id=None):
        if plan_id:
            try:
                plan = PaymentPlan.objects.get(pk=plan_id)
                return Response(self.get_plan(plan))

            except PaymentPlan.DoesNotExist as e:
                return Response(status=status.HTTP_404_NOT_FOUND)

        if tier_id:
            try:
                formatted_plans = []

                for plan in PaymentPlan.objects.filter(member_tier=tier_id):
                    formatted_plans.append(self.get_plan(plan))

                return Response(formatted_plans)

            except PaymentPlan.DoesNotExist as e:
                return Response(status=status.HTTP_404_NOT_FOUND)

        else:
            formatted_plans = []

            for plan in PaymentPlan.objects.all():
                formatted_plans.append(self.get_plan(plan))

            return Response(formatted_plans)

    def post(self, request, tier_id=None):
        if tier_id is not None:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        body = request.data

        member_tier = MemberTier.objects.get(pk=body["memberTier"])

        stripe_plan = stripe.Price.create(
            unit_amount=round(body["cost"]),
            currency=str(body["currency"]).lower(),
            recurring={
                "interval": body["interval"],
                "interval_count": body["intervalCount"],
            },
            product=member_tier.stripe_id,
        )

        plan = PaymentPlan.objects.create(
            name=body["name"],
            stripe_id=stripe_plan.id,
            member_tier_id=body["memberTier"],
            visible=body["visible"],
            currency=str(body["currency"]).lower(),
            cost=round(body["cost"]),
            interval_count=body["intervalCount"],
            interval=body["interval"],
        )

        return Response(self.get_plan(plan))

    def put(self, request, plan_id):
        body = request.data

        plan = PaymentPlan.objects.get(pk=plan_id)

        plan.name = body["name"]
        plan.visible = body["visible"]
        plan.cost = body["cost"]
        plan.save()

        return Response(self.get_plan(plan))

    def delete(self, request, plan_id):
        plan = PaymentPlan.objects.get(pk=plan_id)
        plan.delete()

        return Response()


class MemberBillingInfo(StripeAPIView):
    """
    get: This method gets a member's billing info.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request, member_id):
        member = User.objects.get(id=member_id)
        current_plan = member.profile.membership_plan

        billing_info = {}

        if current_plan:
            s = None

            # if we have a subscription id, fetch the details
            if member.profile.stripe_subscription_id:
                s = stripe.Subscription.retrieve(
                    member.profile.stripe_subscription_id,
                    expand=["items.data.price"],
                )

            # if we got subscription details
            if s:
                from profile.models import BillingGroupMemberAddon
                from api_admin_tools.models import SubscriptionAddon as SubscriptionAddonModel

                # If this member is a billing group primary, collect member addon data
                billing_group_data = None
                billing_group_price_ids = set()
                billing_group_item_ids = set()
                billing_group = getattr(
                    member.profile, "billing_group_primary_member", None
                )
                if billing_group:
                    addon_records = list(
                        BillingGroupMemberAddon.objects.filter(
                            billing_group=billing_group
                        ).select_related("member", "addon")
                    )
                    for ma in addon_records:
                        if ma.stripe_price_id:
                            billing_group_price_ids.add(ma.stripe_price_id)
                        if ma.stripe_subscription_item_id:
                            billing_group_item_ids.add(ma.stripe_subscription_item_id)

                    # Build per-member rows from actual group members
                    member_rows = []
                    for profile in billing_group.members.all():
                        member_addons = [r for r in addon_records if r.member_id == profile.id]
                        if member_addons:
                            for ma in member_addons:
                                member_rows.append({
                                    "memberName": profile.get_full_name(),
                                    "memberEmail": profile.user.email,
                                    "addonName": ma.addon.name,
                                    "cost": ma.locked_cost,
                                    "currency": ma.locked_currency,
                                    "interval": ma.locked_interval,
                                    "intervalCount": ma.locked_interval_count,
                                })
                        else:
                            member_rows.append({
                                "memberName": profile.get_full_name(),
                                "memberEmail": profile.user.email,
                                "addonName": None,
                                "cost": None,
                                "currency": None,
                                "interval": None,
                                "intervalCount": None,
                            })

                    billing_group_data = {
                        "id": billing_group.id,
                        "name": billing_group.name,
                        "memberAddons": member_rows,
                    }

                # Build a name lookup from local SubscriptionAddon records (price_id → name)
                addon_name_lookup = {
                    a.stripe_price_id: a.name
                    for a in SubscriptionAddonModel.objects.exclude(stripe_price_id=None)
                }

                # Standalone addons: Stripe items that are not the base plan or billing group items
                base_plan_price_id = current_plan.stripe_id
                addon_items = []
                for item in s.get("items", {}).get("data", []):
                    price_id = item.get("price", {}).get("id")
                    item_id = item.get("id")
                    if price_id == base_plan_price_id:
                        continue
                    if price_id in billing_group_price_ids:
                        continue
                    if item_id in billing_group_item_ids:
                        continue
                    recurring = item.get("price", {}).get("recurring") or {}
                    addon_items.append(
                        {
                            "id": item_id,
                            "name": (
                                item.get("price", {}).get("nickname")
                                or addon_name_lookup.get(price_id)
                                or item.get("price", {}).get("product")
                                or price_id
                            ),
                            "cost": item.get("price", {}).get("unit_amount"),
                            "currency": item.get("price", {}).get("currency"),
                            "interval": recurring.get("interval"),
                            "intervalCount": recurring.get("interval_count"),
                            "quantity": item.get("quantity"),
                        }
                    )

                # Stripe API 2024-09-30+ moved period fields to subscription items
                first_item = s.get("items", {}).get("data", [None])[0] or {}
                current_period_end = s.get("current_period_end") or first_item.get("current_period_end")
                billing_cycle_anchor = s.get("billing_cycle_anchor") or first_item.get("billing_cycle_anchor")

                billing_info["subscription"] = {
                    "status": member.profile.subscription_status,
                    "billingCycleAnchor": billing_cycle_anchor,
                    "currentPeriodEnd": current_period_end,
                    "cancelAt": s.get("cancel_at"),
                    "cancelAtPeriodEnd": s.get("cancel_at_period_end"),
                    "startDate": s.get("start_date"),
                    "membershipTier": member.profile.membership_plan.member_tier.get_object(),
                    "membershipPlan": member.profile.membership_plan.get_object(),
                    "addons": addon_items,
                    "billingGroup": billing_group_data,
                }
            else:
                billing_info["subscription"] = None

        # get the most recent memberbucks transactions and order them by date
        recent_transactions = MemberBucks.objects.filter(user=member).order_by("date")[
            ::-1
        ][:100]

        def get_transaction(transaction):
            return transaction.get_transaction_display()

        billing_info["memberbucks"] = {
            "balance": member.profile.memberbucks_balance,
            "stripe_card_last_digits": member.profile.stripe_card_last_digits,
            "stripe_card_expiry": member.profile.stripe_card_expiry,
            "transactions": map(get_transaction, recent_transactions),
            "lastPurchase": member.profile.last_memberbucks_purchase,
        }

        return Response(billing_info)


class AdminMemberAddonManage(StripeAPIView):
    """
    post: removes a subscription addon item from a member's active Stripe subscription.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        subscription_item_id = request.data.get("subscription_item_id")
        action = request.data.get("action")

        if not subscription_item_id or action != "remove":
            return Response(
                {"error": "subscription_item_id and action='remove' are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            member = User.objects.get(id=member_id)
        except User.DoesNotExist:
            return Response(
                {"error": "Member not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if not member.profile.stripe_subscription_id:
            return Response(
                {"error": "Member has no active Stripe subscription."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            subscription = stripe.Subscription.retrieve(
                member.profile.stripe_subscription_id,
                expand=["items.data.price"],
            )
            item_ids = [item["id"] for item in subscription["items"]["data"]]
            if subscription_item_id not in item_ids:
                return Response(
                    {"error": "Subscription item not found on member's subscription."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            stripe.SubscriptionItem.delete(
                subscription_item_id,
                proration_behavior="create_prorations",
            )
            member.log_event(
                f"Admin removed subscription item '{subscription_item_id}' from subscription.",
                "stripe",
            )
            return Response({"success": True, "message": "Add-on removed successfully."})

        except stripe.error.StripeError as e:
            capture_exception(e)
            return Response(
                {"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )


class MemberLogs(APIView):
    """
    get: This method gets a member's logs.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request, member_id):
        user = User.objects.get(id=member_id)

        user_event_logs = []
        door_logs = []
        interlock_logs = []

        for user_event_log in UserEventLog.objects.order_by("-date").filter(user=user)[
            :1000
        ]:
            user_event_logs.append(
                {
                    "date": user_event_log.date,
                    "description": user_event_log.description,
                    "logtype": user_event_log.get_logtype_display(),
                }
            )

        for door_log in DoorLog.objects.order_by("-date").filter(user=user)[:500]:
            door_logs.append(
                {
                    "date": door_log.date,
                    "door": door_log.door.name,
                    "success": door_log.success,
                }
            )

        for interlock_log in InterlockLog.objects.filter(user_started=user)[:1000]:
            status = None

            if not interlock_log.success:
                status = -1
            else:
                status = 1 if interlock_log.date_ended else 0

            interlock_logs.append(
                {
                    "interlockName": interlock_log.interlock.name,
                    "dateStarted": interlock_log.date_started,
                    "totalTime": interlock_log.total_time,
                    "totalCost": (interlock_log.total_cost or 0) / 100,
                    "status": status,
                    "userEnded": (
                        interlock_log.user_ended.get_full_name()
                        if interlock_log.user_ended
                        else None
                    ),
                }
            )

        logs = {
            "userEventLogs": user_event_logs,
            "doorLogs": door_logs,
            "interlockLogs": interlock_logs,
        }

        return Response(logs)


class ManageSettings(APIView):
    """
    get: This method gets a constance setting value or values.
    put: This method updates a constance setting value.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get_setting(self, setting):
        return {
            "key": setting.key,
            "value": setting.value,
        }

    def get(self, request, setting_key=None):
        if setting_key:
            try:
                setting = ConstanceSetting.objects.get(key=setting_key)
                return Response(self.get_setting(setting))

            except ConstanceSetting.DoesNotExist as e:
                return Response(status=status.HTTP_404_NOT_FOUND)

        else:
            settings = []

            for setting in ConstanceSetting.objects.all():
                settings.append(self.get_setting(setting))

            return Response(settings)

    def put(self, request, setting_key=None):
        if not setting_key:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        body = request.data

        try:
            setting = ConstanceSetting.objects.get(key=setting_key)
            setting.value = body["value"]
            setting.save()

            return Response(self.get_setting(setting))

        except ConstanceSetting.DoesNotExist as e:
            return Response(status=status.HTTP_404_NOT_FOUND)


class AdminAddonList(StripeAPIView):
    """
    get: returns all subscription addons.
    post: creates a new subscription addon and syncs to Stripe.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        from .models import SubscriptionAddon

        addons = SubscriptionAddon.objects.all()
        return Response([a.get_object() for a in addons])

    def post(self, request):
        from .models import SubscriptionAddon

        data = request.data
        required = ["name", "addon_type", "cost", "interval"]
        for field in required:
            if field not in data:
                return Response(
                    {"error": f"Missing required field: {field}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        addon = SubscriptionAddon(
            name=data["name"],
            description=data.get("description", ""),
            addon_type=data["addon_type"],
            visible=data.get("visible", True),
            currency=data.get("currency", "aud"),
            cost=data["cost"],
            interval=data["interval"],
            interval_count=data.get("interval_count", 1),
            max_quantity=data.get("max_quantity", 10),
            min_quantity=data.get("min_quantity", 1),
        )

        try:
            addon.save()
        except Exception as e:
            capture_exception(e)
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            addon.create_stripe_product_and_price()
        except stripe.error.StripeError as e:
            capture_exception(e)
            logger.warning(f"Stripe sync failed for addon {addon.id}: {e}")

        return Response(addon.get_object(), status=status.HTTP_201_CREATED)


class AdminAddonDetail(StripeAPIView):
    """
    get: returns a single subscription addon.
    put: updates an addon. Updates Stripe product/price as needed.
    delete: deletes an addon and archives Stripe objects.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request, addon_id):
        from .models import SubscriptionAddon

        try:
            addon = SubscriptionAddon.objects.get(pk=addon_id)
        except SubscriptionAddon.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        return Response(addon.get_object())

    def put(self, request, addon_id):
        from .models import SubscriptionAddon

        try:
            addon = SubscriptionAddon.objects.get(pk=addon_id)
        except SubscriptionAddon.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        data = request.data
        price_changed = (
            data.get("cost", addon.cost) != addon.cost
            or data.get("interval", addon.interval) != addon.interval
            or data.get("interval_count", addon.interval_count) != addon.interval_count
            or data.get("currency", addon.currency) != addon.currency
        )
        product_changed = (
            data.get("name", addon.name) != addon.name
            or data.get("description", addon.description) != addon.description
        )

        addon.name = data.get("name", addon.name)
        addon.description = data.get("description", addon.description)
        addon.visible = data.get("visible", addon.visible)
        addon.currency = data.get("currency", addon.currency)
        addon.cost = data.get("cost", addon.cost)
        addon.interval = data.get("interval", addon.interval)
        addon.interval_count = data.get("interval_count", addon.interval_count)
        addon.max_quantity = data.get("max_quantity", addon.max_quantity)
        addon.min_quantity = data.get("min_quantity", addon.min_quantity)
        addon.save()

        try:
            if price_changed:
                addon.update_stripe_price()
            elif product_changed:
                addon.update_stripe_product()
        except stripe.error.StripeError as e:
            capture_exception(e)
            logger.warning(f"Stripe update failed for addon {addon.id}: {e}")

        return Response(addon.get_object())

    def delete(self, request, addon_id):
        from .models import SubscriptionAddon

        try:
            addon = SubscriptionAddon.objects.get(pk=addon_id)
        except SubscriptionAddon.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            addon.delete_stripe_objects()
        except stripe.error.StripeError as e:
            capture_exception(e)
            logger.warning(f"Stripe archive failed for addon {addon.id}: {e}")

        addon.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminCurrentAdditionalMemberAddon(StripeAPIView):
    """
    get: returns the current additional member addon configured in constance.
    put: sets the CURRENT_ADDITIONAL_MEMBER_ADDON constance config value.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        from .models import SubscriptionAddon

        addon_id = config.CURRENT_ADDITIONAL_MEMBER_ADDON
        addon_obj = None

        if addon_id:
            try:
                addon = SubscriptionAddon.objects.get(pk=int(addon_id))
                addon_obj = addon.get_object()
            except (SubscriptionAddon.DoesNotExist, ValueError):
                pass

        return Response({"addon_id": addon_id, "addon": addon_obj})

    def put(self, request):
        addon_id = request.data.get("addon_id", "")

        if addon_id:
            from .models import SubscriptionAddon

            try:
                SubscriptionAddon.objects.get(pk=int(addon_id))
            except (SubscriptionAddon.DoesNotExist, ValueError):
                return Response(
                    {"error": "Addon not found"}, status=status.HTTP_404_NOT_FOUND
                )

        try:
            setting = ConstanceSetting.objects.get(
                key="CURRENT_ADDITIONAL_MEMBER_ADDON"
            )
            setting.value = str(addon_id)
            setting.save()
        except ConstanceSetting.DoesNotExist:
            ConstanceSetting.objects.create(
                key="CURRENT_ADDITIONAL_MEMBER_ADDON", value=str(addon_id)
            )

        return Response({"addon_id": str(addon_id)})


class AdminBillingGroupList(StripeAPIView):
    """
    get: list all billing groups.
    post: create a billing group with a primary member.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        from profile.models import BillingGroup

        groups = BillingGroup.objects.all()
        data = []
        for group in groups:
            obj = group.get_object()
            obj["memberCount"] = group.get_members().count()
            data.append(obj)
        return Response(data)

    def post(self, request):
        from profile.models import BillingGroup, Profile

        name = request.data.get("name", "").strip()
        primary_member_id = request.data.get("primary_member_id")

        if not name or not primary_member_id:
            return Response(
                {"error": "name and primary_member_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            primary_profile = Profile.objects.get(user__id=primary_member_id)
        except Profile.DoesNotExist:
            return Response(
                {"error": "Member not found."}, status=status.HTTP_404_NOT_FOUND
            )

        group = BillingGroup.objects.create(name=name, primary_member=primary_profile)
        primary_profile.billing_group = group
        primary_profile.save()

        request.user.log_event(
            f"Admin created billing group '{name}' for {primary_profile.get_full_name()}.",
            "admin",
        )

        return Response(group.get_object(), status=status.HTTP_201_CREATED)


class AdminBillingGroupDetail(StripeAPIView):
    """
    get: get billing group details.
    put: update billing group name or primary member.
    delete: delete the billing group and clean up members.
    """

    import stripe as stripe_module

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request, group_id):
        from profile.models import (
            BillingGroup,
            BillingGroupMemberAddon,
            BillingGroupInvite,
        )

        try:
            group = BillingGroup.objects.get(pk=group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"error": "Billing group not found."}, status=status.HTTP_404_NOT_FOUND
            )

        obj = group.get_object()
        obj["memberAddons"] = [
            {
                "id": ma.id,
                "member": ma.member.get_full_name(),
                "addon": ma.addon.name,
                "lockedCost": ma.locked_cost,
                "lockedInterval": ma.locked_interval,
                "stripeSubscriptionItemId": ma.stripe_subscription_item_id,
            }
            for ma in BillingGroupMemberAddon.objects.filter(billing_group=group)
        ]
        obj["invitations"] = [
            {
                "id": inv.id,
                "email": inv.email,
                "accepted": inv.accepted,
                "invalidated": inv.invalidated,
                "createdDate": inv.created_date,
                "expiresDate": inv.expires_date,
            }
            for inv in BillingGroupInvite.objects.filter(billing_group=group)
        ]
        return Response(obj)

    def put(self, request, group_id):
        from profile.models import BillingGroup, Profile

        try:
            group = BillingGroup.objects.get(pk=group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"error": "Billing group not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if "name" in request.data:
            group.name = request.data["name"].strip()

        if "primary_member_id" in request.data:
            try:
                new_primary = Profile.objects.get(
                    user__id=request.data["primary_member_id"]
                )
            except Profile.DoesNotExist:
                return Response(
                    {"error": "Member not found."}, status=status.HTTP_404_NOT_FOUND
                )
            group.primary_member = new_primary

        group.save()
        request.user.log_event(f"Admin updated billing group {group.id}.", "admin")
        return Response(group.get_object())

    def delete(self, request, group_id):
        from profile.models import BillingGroup, BillingGroupMemberAddon

        try:
            group = BillingGroup.objects.get(pk=group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"error": "Billing group not found."}, status=status.HTTP_404_NOT_FOUND
            )

        for member in group.get_members():
            member_addons = BillingGroupMemberAddon.objects.filter(
                billing_group=group, member=member
            )
            for ma in member_addons:
                if ma.stripe_subscription_item_id:
                    try:
                        import stripe as stripe_module

                        stripe_module.SubscriptionItem.delete(
                            ma.stripe_subscription_item_id,
                            proration_behavior="create_prorations",
                        )
                    except Exception as e:
                        from sentry_sdk import capture_exception

                        capture_exception(e)
                ma.delete()
            member.billing_group = None
            member.subscription_status = "inactive"
            member.save()

        group.delete()
        request.user.log_event(f"Admin deleted billing group {group_id}.", "admin")
        return Response({"success": True})


class AdminBillingGroupMembers(StripeAPIView):
    """
    post: add or remove a member from a billing group (admin).
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, group_id):
        from profile.models import BillingGroup, Profile, BillingGroupMemberAddon

        try:
            group = BillingGroup.objects.get(pk=group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"error": "Billing group not found."}, status=status.HTTP_404_NOT_FOUND
            )

        action = request.data.get("action")
        member_id = request.data.get("member_id")

        if action not in ("add", "remove") or not member_id:
            return Response(
                {"error": "action ('add' or 'remove') and member_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            target_profile = Profile.objects.get(user__id=member_id)
        except Profile.DoesNotExist:
            return Response(
                {"error": "Member not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if action == "add":
            target_profile.billing_group = group
            target_profile.subscription_status = "group_active"
            target_profile.save()
            request.user.log_event(
                f"Admin added {target_profile.get_full_name()} to billing group {group.name}.",
                "admin",
            )

        elif action == "remove":
            member_addons = BillingGroupMemberAddon.objects.filter(
                billing_group=group, member=target_profile
            )
            for ma in member_addons:
                if ma.stripe_subscription_item_id:
                    try:
                        import stripe as stripe_module

                        stripe_module.SubscriptionItem.delete(
                            ma.stripe_subscription_item_id,
                            proration_behavior="create_prorations",
                        )
                    except Exception as e:
                        from sentry_sdk import capture_exception

                        capture_exception(e)
                ma.delete()
            target_profile.billing_group = None
            target_profile.subscription_status = "inactive"
            target_profile.save()
            request.user.log_event(
                f"Admin removed {target_profile.get_full_name()} from billing group {group.name}.",
                "admin",
            )

        return Response({"success": True, "billingGroup": group.get_object()})


class AdminBillingGroupInvites(StripeAPIView):
    """
    post: admin send/resend/cancel invitations for a billing group.
    Supports actions: "send", "resend", "cancel".
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, group_id):
        from profile.models import BillingGroup, BillingGroupInvite
        from django.utils import timezone

        try:
            group = BillingGroup.objects.get(pk=group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"error": "Billing group not found."}, status=status.HTTP_404_NOT_FOUND
            )

        action = request.data.get("action")

        if action == "send":
            email = request.data.get("email", "").strip().lower()
            if not email:
                return Response(
                    {"error": "email is required."}, status=status.HTTP_400_BAD_REQUEST
                )

            # Invalidate any previous pending invites for this email+group
            for old in BillingGroupInvite.objects.filter(
                billing_group=group, email=email, accepted=False, invalidated=False
            ):
                old.invalidate()

            invite = BillingGroupInvite.objects.create(
                email=email,
                billing_group=group,
                invited_by=request.user,
            )

            from services.emails import send_single_email

            invite_url = f"{config.SITE_URL}/signup?billing_group_invite={invite.invitation_token}"
            try:
                send_single_email(
                    to_email=email,
                    subject=f"You've been invited to join {group.name}",
                    template_vars={
                        "title": f"Join {group.name}",
                        "message": (
                            f"An admin has invited you to join the billing group '{group.name}'.~br~~br~"
                            f"Click below to create your account and join the group."
                        ),
                        "link": invite_url,
                        "btn_text": "Create Account & Join",
                    },
                    template_name="email_with_button.html",
                    user=request.user,
                )
            except Exception:
                pass
            request.user.log_event(
                f"Admin sent billing group invite to {email} for group {group.name}.",
                "admin",
            )
            return Response(
                {
                    "success": True,
                    "invite": {
                        "id": invite.id,
                        "email": invite.email,
                        "expiresDate": invite.expires_date,
                        "token": str(invite.invitation_token),
                    },
                },
                status=status.HTTP_201_CREATED,
            )

        elif action == "resend":
            invite_id = request.data.get("invite_id")
            if not invite_id:
                return Response(
                    {"error": "invite_id is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                old_invite = BillingGroupInvite.objects.get(
                    pk=invite_id, billing_group=group
                )
            except BillingGroupInvite.DoesNotExist:
                return Response(
                    {"error": "Invitation not found."}, status=status.HTTP_404_NOT_FOUND
                )

            old_invite.invalidate()

            new_invite = BillingGroupInvite.objects.create(
                email=old_invite.email,
                billing_group=group,
                invited_by=request.user,
            )

            from services.emails import send_single_email

            invite_url = f"{config.SITE_URL}/signup?billing_group_invite={new_invite.invitation_token}"
            try:
                send_single_email(
                    to_email=new_invite.email,
                    subject=f"You've been invited to join {group.name}",
                    template_vars={
                        "title": f"Join {group.name}",
                        "message": (
                            f"An admin has re-sent your invitation to join the billing group '{group.name}'.~br~~br~"
                            f"Click below to create your account and join the group."
                        ),
                        "link": invite_url,
                        "btn_text": "Create Account & Join",
                    },
                    template_name="email_with_button.html",
                    user=request.user,
                )
            except Exception:
                pass
            request.user.log_event(
                f"Admin resent billing group invite to {new_invite.email} for group {group.name}.",
                "admin",
            )
            return Response(
                {
                    "success": True,
                    "invite": {
                        "id": new_invite.id,
                        "email": new_invite.email,
                        "expiresDate": new_invite.expires_date,
                        "token": str(new_invite.invitation_token),
                    },
                }
            )

        elif action == "cancel":
            invite_id = request.data.get("invite_id")
            if not invite_id:
                return Response(
                    {"error": "invite_id is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                invite = BillingGroupInvite.objects.get(
                    pk=invite_id, billing_group=group
                )
            except BillingGroupInvite.DoesNotExist:
                return Response(
                    {"error": "Invitation not found."}, status=status.HTTP_404_NOT_FOUND
                )

            invite.invalidate()
            request.user.log_event(
                f"Admin cancelled billing group invite {invite_id} for group {group.name}.",
                "admin",
            )
            return Response({"success": True})

        else:
            return Response(
                {"error": "action must be 'send', 'resend', or 'cancel'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
