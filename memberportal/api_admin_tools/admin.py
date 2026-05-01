from django.contrib import admin
from .models import *


@admin.register(MemberTier)
class AdminLogAdmin(admin.ModelAdmin):
    pass


@admin.register(PaymentPlan)
class AdminLogAdmin(admin.ModelAdmin):
    pass


@admin.register(SubscriptionAddon)
class SubscriptionAddonAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "addon_type",
        "cost",
        "interval",
        "visible",
    ]
    list_filter = ["addon_type", "visible"]
    search_fields = ["name", "description"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("name", "description", "addon_type", "visible")},
        ),
        ("Pricing", {"fields": ("currency", "cost", "interval_count", "interval")}),
        ("Quantity Limits", {"fields": ("min_quantity", "max_quantity")}),
        (
            "Stripe Integration",
            {
                "fields": (
                    "stripe_product_id",
                    "stripe_price_id",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
