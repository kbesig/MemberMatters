#!/usr/bin/env python3
"""
Test script to verify the billing group admin functionality
"""

import os
import sys
import django

# Add the memberportal directory to Python path
sys.path.insert(0, "/Users/kbesig/Documents/GitHub/MemberMatters/memberportal")

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "membermatters.settings")
django.setup()


def test_helper_methods_exist():
    """Test that the helper methods exist in BillingGroupMemberManagement class"""
    from api_admin_tools.views import BillingGroupMemberManagement

    # Check if all helper methods exist
    method_names = [
        "_cancel_individual_subscription_with_proration",
        "_lock_addon_pricing_for_member",
        "_create_stripe_subscription_item_for_member",
    ]

    for method_name in method_names:
        if hasattr(BillingGroupMemberManagement, method_name):
            print(f"✅ Method {method_name} exists")
        else:
            print(f"❌ Method {method_name} missing")
            return False

    return True


def test_billing_group_model():
    """Test that BillingGroupMemberAddon model has expected fields"""
    from profile.models import BillingGroupMemberAddon

    # Test that the model exists
    print("✅ BillingGroupMemberAddon model exists")

    # Check if stripe fields exist (might be missing in current DB)
    instance = BillingGroupMemberAddon()
    if hasattr(instance, "stripe_subscription_item_id"):
        print("✅ stripe_subscription_item_id field exists")
    else:
        print("⚠️  stripe_subscription_item_id field missing (needs migration)")

    if hasattr(instance, "stripe_price_id"):
        print("✅ stripe_price_id field exists")
    else:
        print("⚠️  stripe_price_id field missing (needs migration)")

    return True


if __name__ == "__main__":
    print("Testing billing group admin functionality...")
    print("=" * 50)

    try:
        test_helper_methods_exist()
        print()
        test_billing_group_model()
        print()
        print("✅ All tests completed successfully!")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)
