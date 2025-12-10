#!/usr/bin/env python
"""
Check the current billing group addon configuration
"""
import os
import sys
import django

# Setup Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "membermatters.settings")
django.setup()

from constance import config
from api_admin_tools.models import SubscriptionAddon


def main():
    print("=" * 70)
    print("BILLING GROUP ADDON CONFIGURATION CHECK")
    print("=" * 70)

    # Get the configured addon ID
    current_addon_id = getattr(config, "CURRENT_ADDITIONAL_MEMBER_ADDON", None)
    print(f"\nCURRENT_ADDITIONAL_MEMBER_ADDON configuration: {current_addon_id}")

    if not current_addon_id or not str(current_addon_id).strip():
        print("\n❌ ERROR: CURRENT_ADDITIONAL_MEMBER_ADDON is not configured!")
        print("Please set this value in Django Admin > Constance > Config")
        return

    # Try to get the addon
    try:
        addon_id = int(current_addon_id)
        addon = SubscriptionAddon.objects.get(id=addon_id)

        print(f"\n✅ Found addon with ID {addon_id}")
        print("-" * 70)
        print(f"Name: {addon.name}")
        print(f"Addon Type: {addon.addon_type}")
        print(f"Visible: {addon.visible}")
        print(f"Cost: ${addon.cost / 100:.2f}")
        print(f"Currency: {addon.currency}")
        print(f"Interval: {addon.interval}")
        print(f"Interval Count: {addon.interval_count}")
        print(f"Stripe Product ID: {addon.stripe_product_id}")
        print(f"Description: {addon.description}")
        print("-" * 70)

        # Validation checks
        print("\nVALIDATION CHECKS:")
        issues = []

        if addon.addon_type != "additional_member":
            issues.append(
                f"❌ Addon type should be 'additional_member', but is '{addon.addon_type}'"
            )
        else:
            print("✅ Addon type is correct: 'additional_member'")

        if not addon.visible:
            issues.append("❌ Addon should be visible (visible=True)")
        else:
            print("✅ Addon is visible")

        if addon.interval == "month":
            issues.append(
                f"⚠️  WARNING: Addon interval is 'month' - this may cause issues with yearly subscriptions!"
            )
            print(
                f"   Recommended: Change interval to 'year' and cost to yearly amount"
            )
        elif addon.interval == "year":
            print("✅ Addon interval is 'year' - matches yearly subscriptions")
        else:
            print(f"⚠️  Addon interval is '{addon.interval}'")

        if addon.interval_count != 1:
            print(f"⚠️  Interval count is {addon.interval_count} (usually should be 1)")
        else:
            print("✅ Interval count is 1")

        if issues:
            print("\n" + "=" * 70)
            print("ISSUES FOUND:")
            for issue in issues:
                print(issue)
            print("=" * 70)
        else:
            print("\n" + "=" * 70)
            print("✅ ALL CHECKS PASSED - Configuration looks good!")
            print("=" * 70)

    except SubscriptionAddon.DoesNotExist:
        print(f"\n❌ ERROR: No SubscriptionAddon found with ID {addon_id}")
        print("\nAvailable SubscriptionAddons:")
        all_addons = SubscriptionAddon.objects.filter(addon_type="additional_member")
        if all_addons.exists():
            for addon in all_addons:
                print(
                    f"  - ID {addon.id}: {addon.name} ({addon.interval}, visible={addon.visible})"
                )
        else:
            print("  No additional_member addons found in database")
    except ValueError:
        print(
            f"\n❌ ERROR: Invalid CURRENT_ADDITIONAL_MEMBER_ADDON value: '{current_addon_id}'"
        )
        print("Value must be a valid integer ID")


if __name__ == "__main__":
    main()
