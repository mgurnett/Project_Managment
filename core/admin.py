from django.contrib import admin
from django.utils.html import format_html
from .models import Company, Manufacturer, Category, Location, Part


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_name', 'email', 'phone', 'account_number', 'parts_count', 'website_button')
    search_fields = ('name', 'contact_name', 'email', 'account_number', 'notes')
    list_per_page = 25

    def parts_count(self, obj):
        return obj.parts.count()
    parts_count.short_description = "Parts Count"

    def website_button(self, obj):
        if obj.website:
            return format_html('<a href="{}" target="_blank" rel="noopener" class="button" style="padding: 2px 8px; font-size: 11px;">Visit ↗</a>', obj.website)
        return "-"
    website_button.short_description = "Website"


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ('name', 'parts_count', 'website_button')
    search_fields = ('name', 'notes')
    list_per_page = 25

    def parts_count(self, obj):
        return obj.parts.count()
    parts_count.short_description = "Parts Count"

    def website_button(self, obj):
        if obj.website:
            return format_html('<a href="{}" target="_blank" rel="noopener" class="button" style="padding: 2px 8px; font-size: 11px;">Visit ↗</a>', obj.website)
        return "-"
    website_button.short_description = "Website"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'parts_count')
    list_filter = ('parent',)
    search_fields = ('name', 'description')
    autocomplete_fields = ('parent',)
    list_per_page = 25

    def parts_count(self, obj):
        return obj.parts.count()
    parts_count.short_description = "Parts Count"


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'parts_count')
    search_fields = ('name', 'code', 'description')
    list_per_page = 25

    def parts_count(self, obj):
        return obj.parts.count()
    parts_count.short_description = "Parts Stored"


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = (
        'part_number',
        'description',
        'company',
        'category',
        'quantity_on_hand',
        'price_per',
        'price',
        'confirmed',
        'link_button',
    )
    list_filter = ('confirmed', 'company', 'manufacturer', 'category', 'location')
    search_fields = ('part_number', 'supplier_part_number', 'description', 'notes')
    list_editable = ('confirmed', 'price_per', 'price')
    autocomplete_fields = ('company', 'manufacturer', 'category', 'location', 'superseded_by')
    list_per_page = 25

    fieldsets = (
        ('Part Identification', {
            'fields': (
                ('part_number', 'supplier_part_number'),
                'description',
                ('company', 'manufacturer'),
                ('category', 'location'),
                'superseded_by',
            )
        }),
        ('Inventory Quantities', {
            'fields': (
                ('quantity_on_hand', 'quantity_on_order'),
                ('quantity_committed', 'quantity_availible'),
            )
        }),
        ('Pricing & Order', {
            'fields': (
                ('quantity', 'price_per', 'price'),
                'confirmed',
            )
        }),
        ('Documentation & Notes', {
            'fields': ('link', 'notes')
        }),
    )

    def link_button(self, obj):
        if obj.link:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener" class="button" style="padding: 2px 8px; font-size: 11px;">Open Link ↗</a>',
                obj.link
            )
        return "-"
    link_button.short_description = "Link"
