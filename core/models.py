import os
from decimal import Decimal
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
    prefix = models.CharField(
        max_length=20, 
        blank=True, 
        verbose_name="Category Prefix",
        help_text="Prefix code for part numbers (e.g. 100 for Passives, 200 for Actives)"
    )
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

    def get_prefix(self):
        """
        Returns this category's prefix, or inherits from parent if not explicitly set.
        """
        if self.prefix and self.prefix.strip():
            return self.prefix.strip()
        if self.parent:
            return self.parent.get_prefix()
        return ""

    def get_full_path(self):
        names = [self.name]
        curr = self.parent
        while curr:
            names.append(curr.name)
            curr = curr.parent
        return " > ".join(reversed(names))

    def __str__(self):
        prefix = self.get_prefix()
        prefix_str = f"[{prefix}] " if prefix else ""
        return f"{prefix_str}{self.get_full_path()}"


class Location(models.Model):
    """
    Physical storage location (e.g. Bin B-04, Shelf 2, Warehouse 1).
    """
    name = models.CharField(max_length=100, unique=True, verbose_name="Location Name")
    code = models.CharField(max_length=50, blank=True, verbose_name="Location Code", help_text="Bin barcode / identifier")
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
        blank=True,
        verbose_name="On hand"
    )
    quantity_on_order = models.IntegerField(
        default=0, 
        blank=True,
        verbose_name="On order"
    )
    quantity_committed = models.IntegerField(
        default=0, 
        blank=True,
        verbose_name="Committed"
    )
    quantity_availible = models.IntegerField(
        default=0, 
        blank=True,
        verbose_name="Available"
    )
    quantity = models.PositiveIntegerField(
        default=0, 
        blank=True,
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

    @classmethod
    def generate_next_part_number(cls, category):
        """
        Generates the next sequential part number for the given category prefix.
        Starts at 1001 (e.g. 100-1001, 100-1002, ..., matching 100-1234).
        """
        prefix = category.get_prefix() if hasattr(category, 'get_prefix') else str(category).strip()
        if not prefix:
            prefix = "PART"

        prefix_pattern = f"{prefix}-"
        matching_parts = cls.objects.filter(part_number__startswith=prefix_pattern).values_list('part_number', flat=True)

        highest_num = 1000
        for pn in matching_parts:
            suffix = pn[len(prefix_pattern):]
            if suffix.isdigit():
                num = int(suffix)
                if num > highest_num:
                    highest_num = num

        next_num = highest_num + 1
        candidate = f"{prefix}-{next_num}"
        while cls.objects.filter(part_number=candidate).exists():
            next_num += 1
            candidate = f"{prefix}-{next_num}"
        return candidate

    def save(self, *args, **kwargs):
        # 1. Part Number auto-generation / formatting based on Category prefix
        if self.category:
            prefix = self.category.get_prefix()
            if prefix:
                if not self.part_number or not self.part_number.strip():
                    self.part_number = self.generate_next_part_number(self.category)
                else:
                    cleaned = self.part_number.strip()
                    if cleaned.isdigit():
                        # User entered only digits (e.g. '1234') -> auto-format to '100-1234'
                        self.part_number = f"{prefix}-{cleaned}"
                    else:
                        self.part_number = cleaned
            elif not self.part_number or not self.part_number.strip():
                self.part_number = self.generate_next_part_number(self.category)
            else:
                self.part_number = self.part_number.strip()
        elif not self.part_number or not self.part_number.strip():
            # If no category and no part_number provided, fallback to PART-1001
            matching_parts = Part.objects.filter(part_number__startswith="PART-").values_list('part_number', flat=True)
            highest_num = 1000
            for pn in matching_parts:
                suffix = pn[len("PART-"):]
                if suffix.isdigit():
                    num = int(suffix)
                    if num > highest_num:
                        highest_num = num
            self.part_number = f"PART-{highest_num + 1}"
        else:
            self.part_number = self.part_number.strip()

        # 2. Auto-compute total price if price_per and quantity are set but price is empty
        if self.price_per is not None and self.quantity and not self.price:
            self.price = round(self.price_per * self.quantity, 2)
        # Or auto-compute price_per if total price and quantity are set
        elif self.price is not None and self.quantity and not self.price_per and self.quantity > 0:
            self.price_per = round(self.price / self.quantity, 2)

        super().save(*args, **kwargs)


class PartDocument(models.Model):
    """
    Associated documentation, datasheets, scans, pinouts, and technical articles for a Part.
    """
    DOCUMENT_TYPES = [
        ('datasheet', 'Datasheet (PDF)'),
        ('pinout', 'Pinout Diagram / Schematic'),
        ('scan', 'Document Scan / Drawing'),
        ('instructions', 'Instructions / Manual'),
        ('article', 'Technical Article / Notes'),
        ('other', 'Other Document'),
    ]

    part = models.ForeignKey(
        Part,
        on_delete=models.CASCADE,
        related_name='documents',
        verbose_name="Part"
    )
    title = models.CharField(
        max_length=200,
        verbose_name="Title / Description",
        help_text="e.g. TI LM317 Datasheet Rev. C, TO-220 Pinout Diagram, Soldering Instructions"
    )
    document_type = models.CharField(
        max_length=50,
        choices=DOCUMENT_TYPES,
        default='datasheet',
        verbose_name="Document Type"
    )
    file = models.FileField(
        upload_to='parts/documents/%Y/%m/',
        blank=True,
        null=True,
        verbose_name="Uploaded File / Scan",
        help_text="Upload PDF, Image (PNG, JPG, WEBP), or document file"
    )
    external_url = models.URLField(
        max_length=500,
        blank=True,
        verbose_name="External URL",
        help_text="Direct web link to datasheet or online reference (if not uploaded)"
    )
    content = CKEditor5Field(
        'Article / Notes Content',
        config_name='notes',
        blank=True,
        null=True,
        help_text="Rich text article body, pinout description, or assembly instructions"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Part Document / Scan"
        verbose_name_plural = "Part Documents & Scans"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_document_type_display()}) - {self.part.part_number}"

    @property
    def file_extension(self):
        if self.file and self.file.name:
            _, ext = os.path.splitext(self.file.name)
            return ext.lstrip('.').lower()
        return ""

    @property
    def is_image(self):
        return self.file_extension in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg']

    @property
    def is_pdf(self):
        return self.file_extension == 'pdf'

    @property
    def file_size_display(self):
        try:
            if self.file and hasattr(self.file, 'size') and self.file.size:
                size = self.file.size
                if size < 1024:
                    return f"{size} B"
                elif size < 1024 * 1024:
                    return f"{size / 1024:.1f} KB"
                else:
                    return f"{size / (1024 * 1024):.1f} MB"
        except Exception:
            pass
        return ""


class BOM(models.Model):
    """
    Bill of Materials (BOM) / Product Assembly.
    Represents an assembled device or sub-assembly (e.g. String, Node, Base Station, Tipups).
    """
    name = models.CharField(max_length=150, unique=True, verbose_name="BOM / Assembly Name")
    description = models.CharField(max_length=255, blank=True, verbose_name="Description")
    notes = CKEditor5Field('Assembly Instructions & Notes', config_name='notes', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Bill of Materials (BOM)"
        verbose_name_plural = "Bills of Materials (BOMs)"
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def total_items_count(self):
        return self.items.count()

    @property
    def total_parts_quantity(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def total_cost(self):
        total = Decimal('0.00')
        for item in self.items.select_related('part'):
            if item.part and item.part.price_per:
                total += Decimal(str(item.part.price_per)) * Decimal(str(item.quantity))
        return total


class BOMItem(models.Model):
    """
    Line item inside a Bill of Materials, linking a specific component Part with quantity and reference.
    """
    bom = models.ForeignKey(
        BOM,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="BOM Assembly"
    )
    part = models.ForeignKey(
        Part,
        on_delete=models.CASCADE,
        related_name='bom_items',
        verbose_name="Component Part"
    )
    reference = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Reference Designator",
        help_text="e.g. U1, R1, C12, SW1"
    )
    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name="Quantity Required"
    )
    notes = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Notes"
    )

    class Meta:
        verbose_name = "BOM Item"
        verbose_name_plural = "BOM Items"
        ordering = ['reference', 'part__part_number']

    def __str__(self):
        ref_str = f"[{self.reference}] " if self.reference else ""
        return f"{ref_str}{self.part.part_number} x {self.quantity} in {self.bom.name}"

    @property
    def unit_price(self):
        return self.part.price_per or Decimal('0.00')

    @property
    def subtotal(self):
        if self.part and self.part.price_per:
            return Decimal(str(self.part.price_per)) * Decimal(str(self.quantity))
        return Decimal('0.00')
