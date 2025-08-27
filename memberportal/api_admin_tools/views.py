import json

import stripe
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
            filtered.append(member.profile.get_basic_profile())

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
                )

            # if we got subscription details
            if s:
                billing_info["subscription"] = {
                    "status": member.profile.subscription_status,
                    "billingCycleAnchor": s.billing_cycle_anchor,
                    "currentPeriodEnd": s.current_period_end,
                    "cancelAt": s.cancel_at,
                    "cancelAtPeriodEnd": s.cancel_at_period_end,
                    "startDate": s.start_date,
                    "membershipTier": member.profile.membership_plan.member_tier.get_object(),
                    "membershipPlan": member.profile.membership_plan.get_object(),
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


class BillingGroupManagement(APIView):
    """
    get: retrieves a list of all billing groups.
    post: creates a new billing group.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        from profile.models import BillingGroup

        billing_groups = BillingGroup.objects.all()

        def get_billing_group(billing_group):
            return {
                "id": billing_group.id,
                "name": billing_group.name,
                "primary_member": (
                    {
                        "id": billing_group.primary_member.user.id,
                        "name": billing_group.primary_member.get_full_name(),
                    }
                    if billing_group.primary_member
                    else None
                ),
                "member_count": billing_group.members.count(),
                "invite_count": billing_group.members_invites.count(),
            }

        return Response(list(map(get_billing_group, billing_groups)))

    def post(self, request):
        from profile.models import BillingGroup, Profile

        body = request.data

        # Validate required fields
        if not body.get("name"):
            return Response(
                {"success": False, "message": "Billing group name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if billing group name already exists
        if BillingGroup.objects.filter(name=body["name"]).exists():
            return Response(
                {
                    "success": False,
                    "message": "A billing group with this name already exists.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Create the billing group
        billing_group = BillingGroup.objects.create(
            name=body["name"],
            primary_member_id=body.get("primary_member_id"),
        )

        # If a primary member was specified, add them to the billing group
        if body.get("primary_member_id"):
            try:
                primary_member = Profile.objects.get(user_id=body["primary_member_id"])
                primary_member.billing_group = billing_group
                primary_member.save()
            except Profile.DoesNotExist:
                pass

        request.user.log_event(
            f"Created billing group '{billing_group.name}'",
            "admin",
        )

        return Response({"success": True, "billing_group_id": billing_group.id})


class BillingGroupDetail(APIView):
    """
    get: retrieves details of a specific billing group.
    put: updates a billing group.
    delete: deletes a billing group.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request, billing_group_id):
        from profile.models import BillingGroup

        try:
            billing_group = BillingGroup.objects.get(id=billing_group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"success": False, "message": "Billing group not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        def get_member(member):
            return {
                "id": member.user.id,
                "name": member.get_full_name(),
                "email": member.user.email,
                "state": member.state,
            }

        def get_invite(invite):
            return {
                "id": invite.user.id,
                "name": invite.get_full_name(),
                "email": invite.user.email,
                "state": invite.state,
            }

        return Response(
            {
                "id": billing_group.id,
                "name": billing_group.name,
                "primary_member": (
                    get_member(billing_group.primary_member)
                    if billing_group.primary_member
                    else None
                ),
                "members": list(map(get_member, billing_group.members.all())),
                "invites": list(map(get_invite, billing_group.members_invites.all())),
            }
        )

    def put(self, request, billing_group_id):
        from profile.models import BillingGroup, Profile

        try:
            billing_group = BillingGroup.objects.get(id=billing_group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"success": False, "message": "Billing group not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        body = request.data

        # Update name if provided
        if body.get("name") and body["name"] != billing_group.name:
            # Check if new name already exists
            if (
                BillingGroup.objects.filter(name=body["name"])
                .exclude(id=billing_group_id)
                .exists()
            ):
                return Response(
                    {
                        "success": False,
                        "message": "A billing group with this name already exists.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            billing_group.name = body["name"]

        # Update primary member if provided
        if "primary_member_id" in body:
            if body["primary_member_id"]:
                try:
                    primary_member = Profile.objects.get(
                        user_id=body["primary_member_id"]
                    )
                    billing_group.primary_member = primary_member
                except Profile.DoesNotExist:
                    return Response(
                        {"success": False, "message": "Primary member not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                billing_group.primary_member = None

        billing_group.save()

        request.user.log_event(
            f"Updated billing group '{billing_group.name}'",
            "admin",
        )

        return Response({"success": True})

    def delete(self, request, billing_group_id):
        from profile.models import BillingGroup

        try:
            billing_group = BillingGroup.objects.get(id=billing_group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"success": False, "message": "Billing group not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Remove all members from the billing group
        for member in billing_group.members.all():
            member.billing_group = None
            member.save()

        # Remove all invites from the billing group
        for invite in billing_group.members_invites.all():
            invite.billing_group_invite = None
            invite.save()

        billing_group_name = billing_group.name
        billing_group.delete()

        request.user.log_event(
            f"Deleted billing group '{billing_group_name}'",
            "admin",
        )

        return Response({"success": True})


class BillingGroupMemberManagement(APIView):
    """
    post: adds or removes members from a billing group.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, billing_group_id):
        from profile.models import BillingGroup, Profile

        try:
            billing_group = BillingGroup.objects.get(id=billing_group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"success": False, "message": "Billing group not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        body = request.data
        action = body.get("action")  # "add" or "remove"
        member_id = body.get("member_id")

        if not action or not member_id:
            return Response(
                {"success": False, "message": "Action and member_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            member = Profile.objects.get(user_id=member_id)
        except Profile.DoesNotExist:
            return Response(
                {"success": False, "message": "Member not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if action == "add":
            # Remove from any existing billing group first
            if member.billing_group:
                member.billing_group = None
                member.save()

            # Add to this billing group
            member.billing_group = billing_group
            member.save()

            request.user.log_event(
                f"Added {member.get_full_name()} to billing group '{billing_group.name}'",
                "admin",
            )

        elif action == "remove":
            if member.billing_group == billing_group:
                member.billing_group = None
                member.save()

                request.user.log_event(
                    f"Removed {member.get_full_name()} from billing group '{billing_group.name}'",
                    "admin",
                )
            else:
                return Response(
                    {
                        "success": False,
                        "message": "Member is not in this billing group.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        else:
            return Response(
                {"success": False, "message": "Invalid action. Use 'add' or 'remove'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"success": True})


class BillingGroupInviteManagement(APIView):
    """
    post: sends or cancels billing group invites.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, billing_group_id):
        from profile.models import BillingGroup, Profile

        try:
            billing_group = BillingGroup.objects.get(id=billing_group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"success": False, "message": "Billing group not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        body = request.data
        action = body.get("action")  # "invite" or "cancel"
        member_id = body.get("member_id")

        if not action or not member_id:
            return Response(
                {"success": False, "message": "Action and member_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            member = Profile.objects.get(user_id=member_id)
        except Profile.DoesNotExist:
            return Response(
                {"success": False, "message": "Member not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if action == "invite":
            # Remove from any existing billing group invite first
            if member.billing_group_invite:
                member.billing_group_invite = None
                member.save()

            # Send invite to this billing group
            member.billing_group_invite = billing_group
            member.save()

            # Send email notification
            subject = (
                f"You've been invited to join billing group '{billing_group.name}'"
            )
            message = f"You have been invited to join the billing group '{billing_group.name}'. Please log into your account to accept or decline this invitation."
            member.user.email_notification(subject, message)

            request.user.log_event(
                f"Invited {member.get_full_name()} to billing group '{billing_group.name}'",
                "admin",
            )

        elif action == "cancel":
            if member.billing_group_invite == billing_group:
                member.billing_group_invite = None
                member.save()

                request.user.log_event(
                    f"Cancelled invite for {member.get_full_name()} to billing group '{billing_group.name}'",
                    "admin",
                )
            else:
                return Response(
                    {
                        "success": False,
                        "message": "Member is not invited to this billing group.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        else:
            return Response(
                {
                    "success": False,
                    "message": "Invalid action. Use 'invite' or 'cancel'.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"success": True})
