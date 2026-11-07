import os
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
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
        ordering = ['prefix', 'name']

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
    name = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Part Name",
        help_text="Short component name or title"
    )
    description = models.CharField(max_length=255, blank=True, verbose_name="Description")
    
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
    document = models.FileField(
        upload_to='parts/documents/%Y/%m/',
        blank=True,
        null=True,
        verbose_name="Document / Datasheet",
        help_text="Upload component datasheet, drawing, schematic, or PDF manual"
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
        ordering = ['part_number', 'name']

    def clean(self):
        super().clean()
        if self.part_number:
            raw_pn = self.part_number.strip()
            # If user entered digits only and category has prefix, resolve full target
            if self.category:
                prefix = self.category.get_prefix()
                if prefix and raw_pn.isdigit():
                    raw_pn = f"{prefix}-{int(raw_pn):03d}"

            # Case-insensitive uniqueness check across all parts
            existing = Part.objects.filter(part_number__iexact=raw_pn)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError({
                    'part_number': f"A component with part number '{raw_pn}' already exists. Component numbers must be unique."
                })

    def __str__(self):
        label = self.name or self.description
        if self.part_number:
            return f"{self.part_number} - {label}"
        return label

    @classmethod
    def generate_next_part_number(cls, category):
        """
        Generates the next sequential part number for the given category prefix.
        Uses 3-digit zero-padded format (e.g. 100-001, 100-002, 210-001).
        """
        prefix = category.get_prefix() if hasattr(category, 'get_prefix') else str(category).strip()
        if not prefix:
            prefix = "PART"

        prefix_pattern = f"{prefix}-"
        matching_parts = cls.objects.filter(part_number__startswith=prefix_pattern).values_list('part_number', flat=True)

        highest_num = 0
        for pn in matching_parts:
            suffix = pn[len(prefix_pattern):]
            if suffix.isdigit():
                num = int(suffix)
                if num > highest_num:
                    highest_num = num

        next_num = highest_num + 1
        candidate = f"{prefix}-{next_num:03d}"
        while cls.objects.filter(part_number=candidate).exists():
            next_num += 1
            candidate = f"{prefix}-{next_num:03d}"
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
                        # User entered digits (e.g. '1' or '001') -> auto-format to '100-001'
                        self.part_number = f"{prefix}-{int(cleaned):03d}"
                    else:
                        self.part_number = cleaned
            elif not self.part_number or not self.part_number.strip():
                self.part_number = self.generate_next_part_number(self.category)
            else:
                self.part_number = self.part_number.strip()
        elif not self.part_number or not self.part_number.strip():
            # If no category and no part_number provided, fallback to PART-001
            matching_parts = Part.objects.filter(part_number__startswith="PART-").values_list('part_number', flat=True)
            highest_num = 0
            for pn in matching_parts:
                suffix = pn[len("PART-"):]
                if suffix.isdigit():
                    num = int(suffix)
                    if num > highest_num:
                        highest_num = num
            self.part_number = f"PART-{highest_num + 1:03d}"
        else:
            self.part_number = self.part_number.strip()

        # 2. Auto-compute total price if price_per and quantity are set but price is empty
        if self.price_per is not None and self.quantity and not self.price:
            self.price = round(self.price_per * self.quantity, 2)
        # Or auto-compute price_per if total price and quantity are set
        elif self.price is not None and self.quantity and not self.price_per and self.quantity > 0:
            self.price_per = round(self.price / self.quantity, 2)

        super().save(*args, **kwargs)

        # If this part represents a finished assembly, keep BOM.quantity_on_hand in sync
        try:
            if hasattr(self, 'assembly_bom') and self.assembly_bom:
                bom = self.assembly_bom
                if bom.quantity_on_hand != self.quantity_on_hand:
                    bom.quantity_on_hand = self.quantity_on_hand or 0
                    BOM.objects.filter(pk=bom.pk).update(
                        quantity_on_hand=bom.quantity_on_hand,
                        updated_at=timezone.now()
                    )
        except Exception:
            pass

    @property
    def document_filename(self):
        if self.document and self.document.name:
            return os.path.basename(self.document.name)
        return ""

    @property
    def document_extension(self):
        if self.document and self.document.name:
            _, ext = os.path.splitext(self.document.name)
            return ext.lstrip('.').lower()
        return ""

    @property
    def is_document_pdf(self):
        return self.document_extension == 'pdf'

    @property
    def is_document_image(self):
        return self.document_extension in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg']

    @property
    def document_size_display(self):
        try:
            if self.document and hasattr(self.document, 'size') and self.document.size:
                size = self.document.size
                if size < 1024:
                    return f"{size} B"
                elif size < 1024 * 1024:
                    return f"{size / 1024:.1f} KB"
                else:
                    return f"{size / (1024 * 1024):.1f} MB"
        except Exception:
            pass
        return ""


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


class InventoryAdjustment(models.Model):
    """
    Audit record tracking physical inventory and stock adjustments for a Part,
    including mandatory reason, previous quantity, new quantity, delta, and user.
    """
    part = models.ForeignKey(
        Part,
        on_delete=models.CASCADE,
        related_name='adjustments',
        verbose_name="Part"
    )
    old_quantity = models.IntegerField(
        verbose_name="Previous On-Hand"
    )
    new_quantity = models.IntegerField(
        verbose_name="New On-Hand"
    )
    delta = models.IntegerField(
        verbose_name="Adjustment Delta"
    )
    reason = models.CharField(
        max_length=255,
        verbose_name="Reason for Adjustment",
        help_text="Required explanation for why inventory was adjusted"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_adjustments',
        verbose_name="Adjusted By"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Adjustment Date"
    )

    class Meta:
        verbose_name = "Inventory Adjustment"
        verbose_name_plural = "Inventory Adjustments"
        ordering = ['-created_at']

    def __str__(self):
        sign = f"+{self.delta}" if self.delta > 0 else str(self.delta)
        return f"{self.part.part_number} ({sign}): {self.reason}"


class BOM(models.Model):
    """
    Bill of Materials (BOM) / Product Assembly.
    Represents an assembled device or sub-assembly (e.g. String, Node, Base Station, Tipups).
    Assemblies use the 1000 series numbering (e.g. 1000-001, 1000-002).
    """
    assembly_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        verbose_name="Assembly Number (1000 Series)",
        help_text="1000-series assembly number (e.g. 1000-001). Leave blank to auto-assign."
    )
    name = models.CharField(max_length=150, unique=True, verbose_name="BOM / Assembly Name")
    description = models.CharField(max_length=255, blank=True, verbose_name="Description")
    quantity_on_hand = models.PositiveIntegerField(
        default=0,
        blank=True,
        verbose_name="Built Assemblies On Hand",
        help_text="Number of completed assemblies currently in finished goods inventory"
    )
    sale_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Sale Price ($)",
        help_text="Default unit selling price when this assembly is sold"
    )
    part = models.OneToOneField(
        'Part',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assembly_bom',
        verbose_name="Associated Part (1000 Series)",
        help_text="The 1000-series Part representing this finished assembly in the parts catalog and inventory."
    )
    notes = CKEditor5Field('Assembly Instructions & Notes', config_name='notes', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Bill of Materials (BOM)"
        verbose_name_plural = "Bills of Materials (BOMs)"
        ordering = ['assembly_number', 'name']

    def __str__(self):
        if self.assembly_number:
            return f"{self.assembly_number} - {self.name}"
        return self.name

    @classmethod
    def generate_next_assembly_number(cls):
        """
        Generates the next sequential 1000-series assembly number (e.g. 1000-001, 1000-002).
        """
        prefix = "1000-"
        existing = cls.objects.filter(assembly_number__startswith=prefix).values_list('assembly_number', flat=True)
        highest = 0
        for an in existing:
            if not an:
                continue
            suffix = an[len(prefix):]
            if suffix.isdigit():
                num = int(suffix)
                if num > highest:
                    highest = num
        next_num = highest + 1
        candidate = f"{prefix}{next_num:03d}"
        while cls.objects.filter(assembly_number=candidate).exists():
            next_num += 1
            candidate = f"{prefix}{next_num:03d}"
        return candidate

    def sync_part(self):
        """
        Ensures a corresponding 1000-series Part exists in the Parts Catalog under
        the 'Assemblies' category (prefix 1000), kept in sync with this BOM.
        """
        category, _ = Category.objects.get_or_create(
            prefix='1000',
            defaults={
                'name': 'Assemblies',
                'description': 'Completed / built 1000-series product assemblies',
            }
        )
        if not self.assembly_number:
            self.assembly_number = self.generate_next_assembly_number()

        part = self.part
        if not part and self.assembly_number:
            part = Part.objects.filter(part_number=self.assembly_number).first()

        target_on_hand = self.quantity_on_hand or 0
        price_to_set = self.effective_sale_price

        if not part:
            part = Part.objects.create(
                part_number=self.assembly_number,
                name=self.name,
                description=self.description or f"Built 1000-series assembly for {self.name}",
                category=category,
                quantity_on_hand=target_on_hand,
                quantity_availible=target_on_hand,
                price_per=price_to_set,
                confirmed=True,
            )
            if self.part_id != part.pk:
                self.part = part
                BOM.objects.filter(pk=self.pk).update(part=part)
        else:
            update_fields = []
            if part.part_number != self.assembly_number:
                part.part_number = self.assembly_number
                update_fields.append('part_number')
            if part.name != self.name:
                part.name = self.name
                update_fields.append('name')
            if self.description and part.description != self.description:
                part.description = self.description
                update_fields.append('description')
            if part.category_id != category.pk:
                part.category = category
                update_fields.append('category')
            if part.quantity_on_hand != target_on_hand:
                part.quantity_on_hand = target_on_hand
                part.quantity_availible = max(0, target_on_hand - (part.quantity_committed or 0))
                update_fields.extend(['quantity_on_hand', 'quantity_availible'])
            if price_to_set and part.price_per != price_to_set:
                part.price_per = price_to_set
                update_fields.append('price_per')
            if update_fields:
                update_fields.append('updated_at')
                part.save(update_fields=update_fields)
            if self.part_id != part.pk:
                self.part = part
                BOM.objects.filter(pk=self.pk).update(part=part)

        return part

    def save(self, *args, **kwargs):
        if self.assembly_number:
            cleaned = self.assembly_number.strip()
            if cleaned.isdigit():
                num = int(cleaned)
                if num >= 1000:
                    self.assembly_number = f"1000-{num - 1000 if num > 1000 else 1:03d}" if num > 1000 else "1000-001"
                else:
                    self.assembly_number = f"1000-{num:03d}"
            else:
                self.assembly_number = cleaned
        else:
            self.assembly_number = self.generate_next_assembly_number()
        super().save(*args, **kwargs)
        try:
            self.sync_part()
        except Exception:
            pass

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

    @property
    def effective_sale_price(self):
        if self.sale_price is not None and self.sale_price > 0:
            return self.sale_price
        return self.total_cost


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
        constraints = [
            models.UniqueConstraint(
                fields=['bom', 'part'],
                name='unique_bom_component'
            )
        ]

    def clean(self):
        super().clean()
        if hasattr(self, 'bom') and hasattr(self, 'part') and self.bom_id and self.part_id:
            qs = BOMItem.objects.filter(bom=self.bom, part=self.part)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({
                    'part': f"Component '{self.part.part_number}' is already in '{self.bom.name}'. Each component can only appear once per BOM assembly."
                })

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


class Order(models.Model):
    """
    Purchase Order (PO) placed with a supplier/vendor.
    Tracks supplier, expected delivery date, carrier tracking number, status, and part items.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Pending / Draft'),
        ('ORDERED', 'Ordered / Placed'),
        ('PARTIALLY_RECEIVED', 'Partially Received'),
        ('RECEIVED', 'Completed / Received'),
        ('CANCELLED', 'Cancelled'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('CREDIT_CARD', 'Credit Card'),
        ('COMPANY_CARD', 'Company Card'),
        ('DEBIT_CARD', 'Debit Card'),
        ('E_TRANSFER', 'E-Transfer'),
        ('NET_30', 'Account / Net 30'),
        ('WIRE', 'Wire / ACH Transfer'),
        ('CHEQUE', 'Cheque'),
        ('CASH', 'Cash'),
        ('PAYPAL', 'PayPal'),
        ('OTHER', 'Other'),
    ]

    order_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        verbose_name="Order # / PO Number",
        help_text="Custom PO number, or leave blank to auto-generate (e.g. PO-YYYYMMDD-001)"
    )
    supplier = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='orders',
        verbose_name="Supplier / Vendor",
        help_text="Company supplying this order"
    )
    order_date = models.DateField(
        default=timezone.now,
        verbose_name="Order Date"
    )
    expected_delivery_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Expected Delivery Date",
        help_text="Estimated date of arrival"
    )
    tracking_number = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Tracking Number",
        help_text="Shipping carrier tracking or waybill number"
    )
    carrier = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Shipping Carrier",
        help_text="e.g. FedEx, UPS, USPS, DHL, Freight"
    )
    status = models.CharField(
        max_length=25,
        choices=STATUS_CHOICES,
        default='ORDERED',
        verbose_name="Status"
    )
    payment_method = models.CharField(
        max_length=50,
        choices=PAYMENT_METHOD_CHOICES,
        default='CREDIT_CARD',
        blank=True,
        null=True,
        verbose_name="Payment Method",
        help_text="Method used to pay for this purchase order"
    )
    payment_reference = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Payment Reference / Receipt #",
        help_text="Receipt number, last 4 digits of card, transaction ID, or check number"
    )
    payment_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Payment Date",
        help_text="Date payment was made or scheduled"
    )
    payment_notes = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Payment Notes",
        help_text="Additional payment notes or terms"
    )
    notes = CKEditor5Field(
        'Order Notes & Instructions',
        config_name='notes',
        blank=True,
        null=True,
        help_text="Special instructions, delivery terms, or supplier contact notes"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Purchase Order"
        verbose_name_plural = "Purchase Orders"
        ordering = ['-order_date', '-created_at']

    def __str__(self):
        supplier_name = self.supplier.name if self.supplier else 'No Supplier'
        return f"{self.order_number} ({supplier_name})"

    def save(self, *args, **kwargs):
        if not self.order_number:
            today_str = timezone.now().strftime("%Y%m%d")
            prefix = f"PO-{today_str}-"
            last_order = Order.objects.filter(order_number__startswith=prefix).order_by('order_number').last()
            if last_order:
                try:
                    last_seq = int(last_order.order_number.split('-')[-1])
                    next_seq = last_seq + 1
                except (ValueError, IndexError):
                    next_seq = 1
            else:
                next_seq = 1
            self.order_number = f"{prefix}{next_seq:03d}"
        super().save(*args, **kwargs)

    @property
    def total_items_count(self):
        return self.items.count()

    @property
    def total_units_ordered(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def total_units_received(self):
        return sum(item.quantity_received for item in self.items.all())

    @property
    def total_cost(self):
        total = Decimal('0.00')
        for item in self.items.all():
            total += item.subtotal
        return total

    @property
    def is_fully_received(self):
        items = list(self.items.all())
        return len(items) > 0 and all(item.quantity_received >= item.quantity for item in items)

    @property
    def is_closed(self):
        """
        An order is closed once it has been fully received or cancelled.
        Closed orders are locked from further editing.
        """
        return self.status in ['RECEIVED', 'CANCELLED']

    @property
    def can_edit(self):
        return not self.is_closed


class OrderItem(models.Model):
    """
    Line item for a purchase order linking a component Part with quantity and tracking.
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Order"
    )
    part = models.ForeignKey(
        Part,
        on_delete=models.CASCADE,
        related_name='order_items',
        verbose_name="Part"
    )
    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name="Quantity Ordered",
        help_text="Number of units ordered"
    )
    quantity_received = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantity Received",
        help_text="Number of units already received"
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Unit Price",
        help_text="Cost per unit for this order"
    )
    notes = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Item Notes"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"
        ordering = ['part__part_number']

    def __str__(self):
        return f"{self.part.part_number} x {self.quantity} on {self.order.order_number}"

    @property
    def subtotal(self):
        if (
            self.part
            and self.part.price is not None
            and self.part.quantity
            and self.part.quantity > 1
            and self.quantity % self.part.quantity == 0
            and (self.unit_price is None or self.unit_price == self.part.price_per)
        ):
            pkgs = self.quantity // self.part.quantity
            return (Decimal(str(self.part.price)) * Decimal(str(pkgs))).quantize(Decimal('0.01'))
        price = self.unit_price if self.unit_price is not None else (self.part.price_per or Decimal('0.00'))
        return (Decimal(str(price)) * Decimal(str(self.quantity))).quantize(Decimal('0.01'))

    @property
    def remaining_to_receive(self):
        return max(0, self.quantity - self.quantity_received)


class AssemblySale(models.Model):
    """
    Sales Order / Invoice for selling built 1000-series assemblies (and/or items) to a customer.
    """
    DEFAULT_COMPANY_NAME = "Granary Watch"
    DEFAULT_COMPANY_ADDRESS = "11940 52 St NW, Edmonton, AB T5J 3J6"
    DEFAULT_COMPANY_PHONE = "780.901.9315"
    DEFAULT_COMPANY_EMAIL = "michael@granarywatch.com"

    STATUS_CHOICES = [
        ('UNPAID', 'Unpaid (Open)'),
        ('PAID', 'Paid & Closed'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('E-Transfer', 'Interac e-Transfer'),
        ('Credit Card', 'Credit Card'),
        ('Wire / ACH', 'Bank Wire / EFT'),
        ('Cheque', 'Cheque'),
        ('Cash', 'Cash'),
        ('Net 30', 'Net 30 Terms'),
        ('Other', 'Other'),
    ]

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='UNPAID',
        verbose_name="Invoice Status",
        help_text="Unpaid (assembly not built yet / pending payment) or Paid & Closed (assembly built and sold)."
    )
    stock_deducted = models.BooleanField(
        default=False,
        verbose_name="Stock Deducted",
        help_text="Whether finished assembly inventory has been deducted for this invoice."
    )
    pdf_file = models.FileField(
        upload_to='invoices/',
        null=True,
        blank=True,
        verbose_name="Saved Invoice PDF",
        help_text="Saved print-ready PDF invoice file."
    )

    invoice_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        verbose_name="Invoice Number",
        help_text="Sequential invoice number (e.g. INV-0001). Leave blank to auto-generate."
    )
    invoice_date = models.DateField(
        default=timezone.now,
        verbose_name="Invoice Date (Date of Sale)"
    )
    customer_name = models.CharField(
        max_length=150,
        default="Granary Watch",
        verbose_name="Customer / Company Name"
    )
    customer_address = models.CharField(
        max_length=255,
        default="11940 52 St NW, Edmonton, AB T5J 3J6",
        blank=True,
        verbose_name="Customer Address"
    )
    customer_phone = models.CharField(
        max_length=50,
        default="780.901.9315",
        blank=True,
        verbose_name="Customer Phone"
    )
    customer_email = models.EmailField(
        default="michael@granarywatch.com",
        blank=True,
        verbose_name="Customer Email"
    )
    payment_method = models.CharField(
        max_length=50,
        choices=PAYMENT_METHOD_CHOICES,
        default='E-Transfer',
        blank=True,
        verbose_name="Payment Method"
    )
    payment_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Payment Date"
    )
    notes = CKEditor5Field(
        'Invoice Notes',
        config_name='notes',
        blank=True,
        null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Assembly Sale / Invoice"
        verbose_name_plural = "Assembly Sales / Invoices"
        ordering = ['-invoice_date', '-id']

    def __str__(self):
        return f"{self.invoice_number} - {self.customer_name}"

    @classmethod
    def generate_next_invoice_number(cls):
        """
        Generates a strictly sequential invoice number (e.g. INV-0001, INV-0002).
        """
        prefix = "INV-"
        existing = cls.objects.filter(invoice_number__startswith=prefix).values_list('invoice_number', flat=True)
        highest = 0
        for inv in existing:
            if not inv:
                continue
            suffix = inv[len(prefix):]
            if suffix.isdigit():
                num = int(suffix)
                if num > highest:
                    highest = num
        next_num = highest + 1
        candidate = f"{prefix}{next_num:04d}"
        while cls.objects.filter(invoice_number=candidate).exists():
            next_num += 1
            candidate = f"{prefix}{next_num:04d}"
        return candidate

    def save(self, *args, **kwargs):
        if not self.invoice_number or not self.invoice_number.strip():
            self.invoice_number = self.generate_next_invoice_number()
        else:
            self.invoice_number = self.invoice_number.strip()
        super().save(*args, **kwargs)

    @property
    def is_paid(self):
        return self.status == 'PAID' or bool(self.payment_date and self.status != 'UNPAID')

    @property
    def total_amount(self):
        total = Decimal('0.00')
        for item in self.items.all():
            total += item.subtotal
        return total

    @property
    def total_quantity(self):
        return sum(item.quantity for item in self.items.all())


class AssemblySaleItem(models.Model):
    """
    Line item on an AssemblySale / Invoice representing a sold 1000-series Assembly.
    """
    sale = models.ForeignKey(
        AssemblySale,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Sale / Invoice"
    )
    bom = models.ForeignKey(
        BOM,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sale_items',
        verbose_name="Assembly (BoM)"
    )
    item_number = models.CharField(
        max_length=50,
        verbose_name="Item / Assembly Number",
        help_text="e.g. 1000-001"
    )
    description = models.CharField(
        max_length=255,
        verbose_name="Item Description"
    )
    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name="Quantity Sold"
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Unit Price ($)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Invoice Line Item"
        verbose_name_plural = "Invoice Line Items"
        ordering = ['id']

    def __str__(self):
        return f"{self.item_number} - {self.description} x {self.quantity}"

    @property
    def subtotal(self):
        return (Decimal(str(self.unit_price or 0)) * Decimal(str(self.quantity or 0))).quantize(Decimal('0.01'))


