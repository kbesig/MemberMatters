#!/usr/bin/env python
import os
import sys
import django

# Add project directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "membermatters.settings")
django.setup()

# Test constance config
try:
    from constance import config
    from membermatters.constance_config import CONSTANCE_CONFIG

    print("Testing constance configuration...")

    # Check if our new setting is in the config
    if "CURRENT_ADDITIONAL_MEMBER_ADDON" in CONSTANCE_CONFIG:
        print("✓ CURRENT_ADDITIONAL_MEMBER_ADDON found in CONSTANCE_CONFIG")
        default_value = CONSTANCE_CONFIG["CURRENT_ADDITIONAL_MEMBER_ADDON"][0]
        print(f"✓ Default value: '{default_value}' (type: {type(default_value)})")
    else:
        print("✗ CURRENT_ADDITIONAL_MEMBER_ADDON not found in CONSTANCE_CONFIG")

    # Try to access the setting
    try:
        current_value = getattr(config, "CURRENT_ADDITIONAL_MEMBER_ADDON", "NOT_FOUND")
        print(f"✓ Current value: '{current_value}' (type: {type(current_value)})")
    except Exception as e:
        print(f"✗ Error accessing setting: {e}")

    print("Constance configuration test completed successfully!")

except Exception as e:
    print(f"Error testing constance: {e}")
    sys.exit(1)
