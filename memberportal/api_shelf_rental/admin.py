from django.contrib import admin
from profile.models import Shelf, ShelfRequest, MemberShelfAddon


@admin.register(Shelf)
class ShelfAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "status",
        "current_member",
        "next_member",
        "start_date",
        "next_available_date",
    )
    list_filter = ("status",)
    search_fields = (
        "number",
        "current_member__first_name",
        "current_member__last_name",
        "current_member__email",
    )
    ordering = ("number",)


@admin.register(ShelfRequest)
class ShelfRequestAdmin(admin.ModelAdmin):
    list_display = ("member", "quantity", "status", "requested_at", "assigned_at")
    list_filter = ("status", "requested_at")
    search_fields = ("member__first_name", "member__last_name", "member__email")
    ordering = ("-requested_at",)


@admin.register(MemberShelfAddon)
class MemberShelfAddonAdmin(admin.ModelAdmin):
    list_display = ("member", "shelf", "locked_cost", "locked_interval", "date_locked")
    list_filter = ("locked_interval", "date_locked")
    search_fields = (
        "member__first_name",
        "member__last_name",
        "member__email",
        "shelf__number",
    )
    ordering = ("-date_locked",)
