"""
Import members from legacy MySQL database into MemberMatters.

Usage:
    python import_legacy_members.py [--limit N] [--dry-run]

Options:
    --limit N     Import at most N members (default: 5)
    --dry-run     Print what would be imported without writing anything
    --all         Import all members (overrides --limit)

Deduplication: skips any member whose primary email already exists as a User.
Imported users get an unusable password — they must use "Forgot Password" to set one.

Status mapping:
    6 (Active)   → profile.state = "active"
    7 (Disabled) → profile.state = "inactive"
    other        → profile.state = "noob"
"""

import os
import sys
import re
import argparse
import django
from datetime import timezone as dt_tz

# --- Django setup ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "membermatters.settings")
os.environ.setdefault("MM_LOG_LOCATION", "errors.log")
os.environ.setdefault("MM_DB_LOCATION", "taketwo.sqlite3")
django.setup()

import pymysql
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from profile.models import Profile  # noqa: E402

User = get_user_model()

# NOTIFICATION SAFETY
# This script sets profile.state directly via profile.save() and never calls
# activate(), deactivate(), email_welcome(), email_enable_member(), or
# email_disable_member(). No emails or SMS will be sent to members during import.

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MYSQL_CONFIG = dict(
    host="192.168.7.75",
    port=3306,
    user="jim_dev",
    password="Stumble-Ducky-Armored-Sector-Baritone2-Apple",
    database="memberDB_PROD",
    cursorclass=pymysql.cursors.DictCursor,
    connect_timeout=10,
)

STATUS_MAP = {
    6: "active",
    7: "inactive",
}

PHONE_RE = re.compile(r"^\+?1?\d{9,15}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_phone(raw):
    """Strip non-numeric chars, validate against Profile regex, return or empty string."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if PHONE_RE.match(digits):
        return digits
    return ""


def clean_str(val, default=""):
    if val is None:
        return default
    return str(val).strip()


def fetch_members(limit):
    conn = pymysql.connect(**MYSQL_CONFIG)
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    m.MemberID,
                    m.FirstName,
                    m.LastName,
                    m.Suffix,
                    m.Birthdate,
                    m.Notes,
                    m.InitialJoinDate,
                    m.DisplayName,
                    m.MembersStatus,
                    h.Organization,
                    h.AddressLine1,
                    h.AddressLine2,
                    h.City,
                    h.State        AS AddrState,
                    h.Country,
                    h.PostalCode,
                    e.Email,
                    p.PhoneNum
                FROM members m
                LEFT JOIN households h  ON m.HouseID   = h.HouseID
                LEFT JOIN emails e      ON m.MemberID  = e.MemberID AND e.`Primary` = 1
                LEFT JOIN phones p      ON m.MemberID  = p.MemberID AND p.`Primary` = 1
                WHERE e.Email IS NOT NULL
                LIMIT %s;
            """, (limit,))
            return cur.fetchall()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_member(row, dry_run):
    email = clean_str(row["Email"]).lower()
    if not email:
        print(f"  SKIP MemberID={row['MemberID']} — no email")
        return "skip"

    if User.objects.filter(email__iexact=email).exists():
        print(f"  SKIP {email} — already exists")
        return "skip"

    first = clean_str(row["FirstName"]) or "Unknown"
    last  = clean_str(row["LastName"])  or "Unknown"

    # screen_name: use DisplayName if present, else First Last
    screen_name = clean_str(row["DisplayName"]) or f"{first} {last}"
    # Truncate to 30 chars (model limit)
    screen_name = screen_name[:30]

    state = STATUS_MAP.get(row["MembersStatus"], "noob")
    phone = clean_phone(row["PhoneNum"])

    print(f"  IMPORT {email} ({first} {last}) state={state}")

    if dry_run:
        return "dry"

    with transaction.atomic():
        user = User.objects.create_user(email=email, password=None)
        user.set_unusable_password()
        # Explicitly mark email as verified so login never triggers a
        # verification email to the member. The registration view normally
        # sets this to False and sends a verify email — we bypass that entirely.
        user.email_verified = True
        user.save()

        # Profile is not auto-created by User.save() — create it explicitly.
        # We call Profile.save() which sets created=now() on first save, then
        # use .update() below to backfill created from InitialJoinDate without
        # re-triggering the save() override.
        profile = Profile.objects.create(
            user=user,
            first_name=first[:30],
            last_name=last[:30],
            screen_name=screen_name,
            state=state,
            phone=phone,
            suffix=clean_str(row["Suffix"])[:45],
            birthdate=row["Birthdate"] or None,
            notes=clean_str(row["Notes"]),
            organization=clean_str(row["Organization"])[:255],
            address_line1=clean_str(row["AddressLine1"])[:100],
            address_line2=clean_str(row["AddressLine2"])[:100],
            city=clean_str(row["City"])[:100],
            address_state_province=clean_str(row["AddrState"])[:100],
            country=clean_str(row["Country"])[:100],
            postal_code=clean_str(row["PostalCode"])[:20],
        )

        # Backfill created from legacy InitialJoinDate if available.
        # Done via .update() to bypass the Profile.save() timestamp override.
        if row["InitialJoinDate"]:
            from django.utils.timezone import make_aware
            from datetime import datetime as dt
            legacy_created = make_aware(
                dt.combine(row["InitialJoinDate"], dt.min.time())
            )
            Profile.objects.filter(pk=profile.pk).update(created=legacy_created)

    return "imported"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Import legacy MySQL members into MemberMatters.")
    parser.add_argument("--limit", type=int, default=5, help="Max members to import (default: 5)")
    parser.add_argument("--all", action="store_true", help="Import all members")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    limit = 999999 if args.all else args.limit

    print(f"{'DRY RUN — ' if args.dry_run else ''}Fetching up to {limit} members from legacy DB...")
    rows = fetch_members(limit)
    print(f"Fetched {len(rows)} rows.\n")

    counts = {"imported": 0, "skip": 0, "dry": 0}
    for row in rows:
        result = import_member(row, dry_run=args.dry_run)
        counts[result] = counts.get(result, 0) + 1

    print(f"\nDone. imported={counts['imported']} skipped={counts['skip']} dry={counts['dry']}")


if __name__ == "__main__":
    main()
