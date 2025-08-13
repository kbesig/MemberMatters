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
    list_display = ['name', 'addon_type', 'cost', 'interval', 'visible', 'stripe_synced']
    list_filter = ['addon_type', 'visible', 'stripe_synced']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at', 'last_stripe_sync', 'stripe_synced']
    actions = ['create_stripe_objects', 'update_stripe_prices', 'sync_all_addons']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'addon_type', 'visible')
        }),
        ('Pricing', {
            'fields': ('currency', 'cost', 'interval_count', 'interval')
        }),
        ('Quantity Limits', {
            'fields': ('min_quantity', 'max_quantity')
        }),
        ('Stripe Integration', {
            'fields': ('stripe_product_id', 'stripe_price_id', 'stripe_synced', 'last_stripe_sync'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def create_stripe_objects(self, request, queryset):
        """Create Stripe products and prices for selected add-ons"""
        success_count = 0
        error_messages = []
        
        for addon in queryset:
            success, message = addon.create_stripe_product_and_price()
            if success:
                success_count += 1
            else:
                error_messages.append(f"{addon.name}: {message}")
        
        if success_count > 0:
            self.message_user(request, f"Successfully created Stripe objects for {success_count} add-on(s)")
        
        if error_messages:
            self.message_user(request, f"Errors: {'; '.join(error_messages)}", level='ERROR')
    
    create_stripe_objects.short_description = "Create Stripe products and prices"

    def update_stripe_prices(self, request, queryset):
        """Update Stripe prices for selected add-ons"""
        success_count = 0
        error_messages = []
        
        for addon in queryset:
            if addon.stripe_product_id:
                success, message = addon.update_stripe_price()
                if success:
                    success_count += 1
                else:
                    error_messages.append(f"{addon.name}: {message}")
            else:
                error_messages.append(f"{addon.name}: No Stripe product ID found")
        
        if success_count > 0:
            self.message_user(request, f"Successfully updated Stripe prices for {success_count} add-on(s)")
        
        if error_messages:
            self.message_user(request, f"Errors: {'; '.join(error_messages)}", level='ERROR')
    
    update_stripe_prices.short_description = "Update Stripe prices"

    def sync_all_addons(self, request, queryset):
        """Sync all add-ons with Stripe"""
        success_count = 0
        error_messages = []
        
        for addon in queryset:
            if addon.stripe_product_id:
                success, message = addon.update_stripe_price()
            else:
                success, message = addon.create_stripe_product_and_price()
            
            if success:
                success_count += 1
            else:
                error_messages.append(f"{addon.name}: {message}")
        
        if success_count > 0:
            self.message_user(request, f"Successfully synced {success_count} add-on(s) with Stripe")
        
        if error_messages:
            self.message_user(request, f"Errors: {'; '.join(error_messages)}", level='ERROR')
    
    sync_all_addons.short_description = "Sync all with Stripe"

    def save_model(self, request, obj, form, change):
        """Override save to automatically sync with Stripe if needed"""
        super().save_model(request, obj, form, change)
        
        # Auto-sync with Stripe if this is a new add-on or if Stripe fields changed
        if not change or form.changed_data:
            if not obj.stripe_product_id:
                # New add-on, create Stripe objects
                success, message = obj.create_stripe_product_and_price()
                if not success:
                    self.message_user(request, f"Warning: Could not create Stripe objects: {message}", level='WARNING')
            elif 'cost' in form.changed_data or 'interval' in form.changed_data or 'interval_count' in form.changed_data:
                # Pricing changed, update Stripe price
                success, message = obj.update_stripe_price()
                if not success:
                    self.message_user(request, f"Warning: Could not update Stripe price: {message}", level='WARNING')
