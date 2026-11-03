from django.db import models
from django_ckeditor_5.fields import CKEditor5Field


class Company(models.Model):
    """
    Suppliers, distributors, and vendors (e.g. DigiKey, Mouser, McMaster-Carr).
    Has a one-to-many relationship with Part.
    """
    name = models.CharField(max_length=150, unique=True, verbose_name="Company Name")
    website = models.URLField(max_length=300, blank=True, verbose_name="Website")
    contact_name = models.CharField(max_length=100, blank=True, verbose_name="Contact Person")
    email = models.EmailField(blank=True, verbose_name="Email")
    phone = models.CharField(max_length=30, blank=True, verbose_name="Phone")
    account_number = models.CharField(
        max_length=100, 
        blank=True, 
        verbose_name="Account Number", 
        help_text="Customer or account ID with this supplier"
    )
    notes = CKEditor5Field('Notes', config_name='notes', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Company"
        verbose_name_plural = "Companies"
        ordering = ['name']

    def __str__(self):
        return self.name


class Manufacturer(models.Model):
    """
    Component brand or original maker (e.g. Texas Instruments, STMicroelectronics, Molex).
    """
    name = models.CharField(max_length=150, unique=True, verbose_name="Manufacturer Name")
    website = models.URLField(max_length=300, blank=True, verbose_name="Website")
    notes = CKEditor5Field('Notes', config_name='notes', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Manufacturer"
        verbose_name_plural = "Manufacturers"
        ordering = ['name']

    def __str__(self):
        return self.name


class Category(models.Model):
    """
    Component taxonomy/category (e.g. Microcontrollers, Passives, Connectors, Fasteners).
    Supports hierarchical nesting via parent.
    """
    name = models.CharField(max_length=100, unique=True, verbose_name="Category Name")
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='subcategories',
        verbose_name="Parent Category"
    )
    description = models.CharField(max_length=255, blank=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        if self.parent:
            return f"{self.parent} > {self.name}"
        return self.name


class Location(models.Model):
    """
    Physical storage location (e.g. Bin B-04, Shelf 2, Warehouse 1).
    """
    name = models.CharField(max_length=100, unique=True, verbose_name="Location Name")
    description = models.CharField(max_length=255, blank=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Storage Location"
        verbose_name_plural = "Storage Locations"
        ordering = ['name']

    def __str__(self):
        if self.code:
            return f"{self.name} ({self.code})"
        return self.name


class Part(models.Model):
    """
    Model representing a part/component in the bill of materials.
    """
    part_number = models.CharField(
        max_length=100,
        blank=True,
        unique=True,
        verbose_name="Part Number",
        help_text="Manufacturer/vendor part #, or leave blank to auto-generate"
    )
    description = models.CharField(max_length=255, verbose_name="Description")
    
    # Relationships (One-to-Many)
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='parts',
        verbose_name="Company / Supplier",
        help_text="Supplier or distributor providing this part"
    )
    manufacturer = models.ForeignKey(
        Manufacturer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='parts',
        verbose_name="Manufacturer",
        help_text="Original component manufacturer/brand"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='parts',
        verbose_name="Category",
        help_text="Component classification (e.g. Resistors, Microcontrollers)"
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='parts',
        verbose_name="Storage Location",
        help_text="Physical bin, drawer, or warehouse location"
    )
    supplier_part_number = models.CharField(
        max_length=150, 
        blank=True, 
        verbose_name="Supplier Part Number",
        help_text="Suppliers' part number"
    )
    superseded_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supersedes',
        verbose_name="Superseded By",
        help_text="The replacement part if this part has been superseded"
    )
    quantity_on_hand = models.IntegerField(
        default=0, 
        verbose_name="On hand"
    )
    quantity_on_order = models.IntegerField(
        default=0, 
        verbose_name="On order"
    )
    quantity_committed = models.IntegerField(
        default=0, 
        verbose_name="Committed"
    )
    quantity_availible = models.IntegerField(
        default=0, 
        verbose_name="Available"
    )
    quantity = models.PositiveIntegerField(
        default=0, 
        verbose_name="Quantity",
        help_text="Purchased in quanity"
    )
    price_per = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True, 
        verbose_name="Price Per",
        help_text="Unit price per item"
    )
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True, 
        verbose_name="Price",
        help_text="Total price (quantity × price per)"
    )
    confirmed = models.BooleanField(
        default=False, 
        verbose_name="Confirmed",
        help_text="Has this part order/spec been confirmed?"
    )
    link = models.URLField(
        max_length=500, 
        blank=True, 
        verbose_name="Link",
        help_text="Direct product page or datasheet URL"
    )
    notes = CKEditor5Field(
        'Notes',
        config_name='notes',
        blank=True,
        null=True,
        help_text="Additional notes, alternate parts, or lead time details"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Part"
        verbose_name_plural = "Parts"
        ordering = ['part_number', 'description']

    def __str__(self):
        if self.part_number:
            return f"{self.part_number} - {self.description}"
        return self.description

    def save(self, *args, **kwargs):
        # Auto-compute total price if price_per and quantity are set but price is empty
        if self.price_per is not None and self.quantity and not self.price:
            self.price = round(self.price_per * self.quantity, 2)
        # Or auto-compute price_per if total price and quantity are set
        elif self.price is not None and self.quantity and not self.price_per and self.quantity > 0:
            self.price_per = round(self.price / self.quantity, 2)
        super().save(*args, **kwargs)
