from django import forms
from .models import (
    Part, Company, Manufacturer, Customer, Category, Location, PartDocument,
    BOM, BOMItem, BOMDocument, Order, OrderItem, AssemblySale, AssemblySaleItem,
    Quote, QuoteItem, Tag, Article
)


class TagInputMixin(forms.ModelForm):
    """
    Mixin adding a comma-separated `tags_input` field to any ModelForm whose
    model has a `tags` ManyToManyField(Tag). Auto-creates missing tags by name.
    """
    tags_input = forms.CharField(
        required=False,
        label="Tags",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. esp32, datasheet, soldering, vendor-notes (comma-separated)'
        }),
        help_text="Enter comma-separated tags; new tags are created automatically."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and 'tags_input' in self.fields:
            self.fields['tags_input'].initial = ', '.join(
                self.instance.tags.filter(is_system=False).order_by('name').values_list('name', flat=True)
            )

    def _sync_tags(self, instance):
        raw = self.cleaned_data.get('tags_input', '') or ''
        names = []
        seen = set()
        for part in raw.split(','):
            name = part.strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                names.append(name)

        tag_objs = list(instance.tags.filter(is_system=True))
        for name in names:
            tag = Tag.objects.filter(name__iexact=name, is_system=False).first()
            if not tag:
                tag = Tag.objects.create(name=name, is_system=False)
            tag_objs.append(tag)
        instance.tags.set(tag_objs)

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            self._sync_tags(instance)
        else:
            old_save_m2m = self.save_m2m

            def save_m2m_with_tags():
                old_save_m2m()
                self._sync_tags(instance)

            self.save_m2m = save_m2m_with_tags
        return instance


class PartForm(TagInputMixin):
    adjustment_reason = forms.CharField(
        required=False,
        max_length=255,
        label="Adjustment Reason",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Required if changing On-Hand quantity (e.g. Cycle count, damaged, vendor return)'
        }),
        help_text="Required when modifying physical on-hand inventory count"
    )

    class Meta:
        model = Part
        fields = [
            'part_number',
            'name',
            'supplier_part_number',
            'description',
            'company',
            'manufacturer',
            'category',
            'location',
            'superseded_by',
            'quantity_on_hand',
            'quantity_on_order',
            'quantity_committed',
            'quantity_availible',
            'quantity',
            'price_per',
            'price',
            'sale_price',
            'confirmed',
            'link',
            'document',
            'notes',
        ]
        widgets = {
            'part_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 100-001 (or enter 001, or leave blank to auto-generate)'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Saft LS33600, Aircraft cable'}),
            'supplier_part_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 296-1389-5-ND'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Detailed specifications or package details'}),
            'company': forms.Select(attrs={'class': 'form-select'}),
            'manufacturer': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select', 'id': 'id_category'}),
            'location': forms.Select(attrs={'class': 'form-select'}),
            'superseded_by': forms.Select(attrs={'class': 'form-select'}),
            'quantity_on_hand': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'quantity_on_order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'quantity_committed': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'quantity_availible': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'price_per': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'sale_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00 (for 930+ assemblies)'}),
            'confirmed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'document': forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.png,.jpg,.jpeg,.webp,.doc,.docx,.xls,.xlsx,.txt,.csv'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'company' in self.fields:
            self.fields['company'].empty_label = "-- Select Company / Supplier --"
        if 'manufacturer' in self.fields:
            self.fields['manufacturer'].empty_label = "-- Select Manufacturer --"
        if 'category' in self.fields:
            self.fields['category'].empty_label = "-- Select Category --"
        if 'location' in self.fields:
            self.fields['location'].empty_label = "-- Select Storage Location --"
        if 'superseded_by' in self.fields:
            self.fields['superseded_by'].empty_label = "-- None (Not Superseded) --"
            # Exclude self from superseded_by options to avoid self-reference loops
            if self.instance and self.instance.pk:
                self.fields['superseded_by'].queryset = Part.objects.exclude(pk=self.instance.pk)

    def clean_quantity_on_hand(self):
        return self.cleaned_data.get('quantity_on_hand') or 0

    def clean_quantity_on_order(self):
        return self.cleaned_data.get('quantity_on_order') or 0

    def clean_quantity_committed(self):
        return self.cleaned_data.get('quantity_committed') or 0

    def clean_quantity_availible(self):
        return self.cleaned_data.get('quantity_availible') or 0

    def clean_quantity(self):
        return self.cleaned_data.get('quantity') or 0

    def clean(self):
        cleaned_data = super().clean()
        part_number = cleaned_data.get('part_number')
        category = cleaned_data.get('category')

        if part_number:
            raw_pn = part_number.strip()
            # If user entered digits only and category has prefix, resolve full target
            if category:
                prefix = category.get_prefix()
                if prefix and raw_pn.isdigit():
                    raw_pn = f"{prefix}-{int(raw_pn):03d}"

            # Case-insensitive uniqueness check
            qs = Part.objects.filter(part_number__iexact=raw_pn)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error(
                    'part_number',
                    f"A component with part number '{raw_pn}' already exists. Component numbers must be unique."
                )
            else:
                cleaned_data['part_number'] = raw_pn

        if self.instance and self.instance.pk:
            old_part = Part.objects.filter(pk=self.instance.pk).first()
            if old_part:
                old_on_hand = old_part.quantity_on_hand or 0
                new_on_hand = cleaned_data.get('quantity_on_hand')
                if new_on_hand is not None and new_on_hand != old_on_hand:
                    reason = (cleaned_data.get('adjustment_reason') or '').strip()
                    if not reason:
                        self.add_error(
                            'adjustment_reason',
                            f"A reason must be included when adjusting On-Hand quantity (from {old_on_hand} to {new_on_hand})."
                        )

        return cleaned_data


class CompanyForm(TagInputMixin):
    class Meta:
        model = Company
        fields = ['name', 'website', 'contact_name', 'email', 'phone', 'account_number', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. DigiKey, Mouser, McMaster-Carr'}),
            'website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://www.digikey.com'}),
            'contact_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Account Rep / Contact Person'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'sales@example.com'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '(555) 123-4567'}),
            'account_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Account or Customer #'}),
        }


class ManufacturerForm(TagInputMixin):
    class Meta:
        model = Manufacturer
        fields = ['name', 'website', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Texas Instruments, STMicroelectronics'}),
            'website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://www.ti.com'}),
        }


class CustomerForm(TagInputMixin):
    class Meta:
        model = Customer
        fields = ['name', 'contact_name', 'email', 'phone', 'address', 'website', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Acme Robotics, University Lab'}),
            'contact_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Primary Contact Person'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'billing@customer.com'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '(555) 123-4567'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Billing / Shipping Address'}),
            'website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://customer.com'}),
        }


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'prefix', 'parent', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Passives, Microcontrollers, Connectors'}),
            'prefix': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 100 (Passives), 200 (Actives), 300 (Connectors)'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brief category description'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'parent' in self.fields:
            self.fields['parent'].empty_label = "-- Top-Level Category (No Parent) --"
            if self.instance and self.instance.pk:
                self.fields['parent'].queryset = Category.objects.exclude(pk=self.instance.pk)

    def clean_prefix(self):
        prefix = self.cleaned_data.get('prefix', '')
        return prefix.strip() if prefix else ''


class LocationForm(TagInputMixin):
    class Meta:
        model = Location
        fields = ['name', 'code', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Main Warehouse, Shelf B, Bin 12'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. BIN-B12, W1-S02'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Location description or instructions'}),
        }


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ['name', 'color', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. esp32, datasheet, soldering'}),
            'color': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional description of when to use this tag'}),
        }


class ArticleForm(TagInputMixin):
    class Meta:
        model = Article
        fields = [
            'title', 'article_type', 'summary', 'content', 'file', 'external_url',
            'parts', 'manufacturers', 'companies', 'categories', 'customers', 'locations', 'orders',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Saft Li-SOCl2 Passivation & Storage Guide'}),
            'article_type': forms.Select(attrs={'class': 'form-select'}),
            'summary': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brief one-line summary of this article'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'external_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'parts': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
            'manufacturers': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
            'companies': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
            'categories': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
            'customers': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
            'locations': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
            'orders': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
        }


class PartDocumentForm(forms.ModelForm):
    class Meta:
        model = PartDocument
        fields = ['title', 'document_type', 'file', 'external_url', 'content']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'e.g. TI LM317 Datasheet Rev. C, TO-220 Pinout Diagram, Soldering Instructions'
            }),
            'document_type': forms.Select(attrs={'class': 'form-select'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'external_url': forms.URLInput(attrs={
                'class': 'form-control', 
                'placeholder': 'https://www.ti.com/lit/ds/symlink/lm317.pdf'
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        file = cleaned_data.get('file')
        external_url = cleaned_data.get('external_url')
        content = cleaned_data.get('content')

        if not file and not external_url and not content:
            raise forms.ValidationError(
                "Please provide at least one resource: an uploaded file/scan, an external URL, or article content."
            )
        return cleaned_data


class BOMForm(forms.ModelForm):
    class Meta:
        model = BOM
        fields = ['category', 'assembly_number', 'target_assembly_part', 'target_assembly_number', 'name', 'description', 'notes']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-select', 'id': 'id_bom_category'}),
            'assembly_number': forms.TextInput(attrs={
                'class': 'form-control font-monospace',
                'placeholder': 'e.g. 910-001 (leave blank to auto-assign next 910-series #)'
            }),
            'target_assembly_part': forms.Select(attrs={'class': 'form-select', 'id': 'id_target_assembly_part'}),
            'target_assembly_number': forms.TextInput(attrs={
                'class': 'form-control font-monospace',
                'placeholder': 'Auto-filled from Target Assembly Part (or auto-generated)'
            }),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. String BoM, Sensor Node BoM, Base Station BoM'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brief description of this BoM recipe'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'category' in self.fields:
            self.fields['category'].queryset = Category.objects.filter(prefix__startswith='91').order_by('prefix', 'name')
            self.fields['category'].empty_label = "-- Select 910-Series BoM Category --"
        if 'target_assembly_part' in self.fields:
            from django.db.models import Q
            self.fields['target_assembly_part'].queryset = (
                Part.objects.select_related('category')
                .filter(
                    Q(category__prefix__startswith='93') |
                    Q(category__prefix__startswith='94') |
                    Q(category__prefix__startswith='95')
                )
                .order_by('part_number')
            )
            self.fields['target_assembly_part'].empty_label = "-- Link to 930/940/950 Assembly Part (optional) --"


class BOMItemForm(forms.ModelForm):
    class Meta:
        model = BOMItem
        fields = ['part', 'reference', 'quantity', 'notes']
        widgets = {
            'part': forms.Select(attrs={'class': 'form-select'}),
            'reference': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. U1, C12, SW1'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional assembly notes or placement instructions'}),
        }

    def __init__(self, *args, bom=None, **kwargs):
        self.bom = bom
        super().__init__(*args, **kwargs)
        if 'part' in self.fields:
            self.fields['part'].empty_label = "-- Select Component Part --"
            existing_part_ids = []
            if self.bom:
                # Exclude parts that are already in this BOM assembly
                existing_part_ids = list(self.bom.items.values_list('part_id', flat=True))
                if self.instance and self.instance.pk and self.instance.part_id:
                    existing_part_ids = [pid for pid in existing_part_ids if pid != self.instance.part_id]
                # Exclude self-part to prevent circular self-reference
                if self.bom.part_id:
                    existing_part_ids.append(self.bom.part_id)

            from django.db.models.functions import Length
            parts = (
                Part.objects.select_related('category')
                .exclude(id__in=existing_part_ids)
                .annotate(part_num_len=Length('part_number'))
                .order_by('part_num_len', 'part_number')
            )
            self.fields['part'].queryset = parts
            self.fields['part'].label_from_instance = lambda obj: (
                f"{obj.part_number} - {obj.name or obj.description or 'Part'} (On-Hand: {obj.quantity_on_hand}{' — Sub-Assembly' if obj.category and obj.category.get_prefix() in ('900', '910', '920', '930', '940', '950') else ''})"
                + (f" [Superseded by {obj.superseded_by.part_number}]" if obj.superseded_by_id else "")
            )

    def clean(self):
        cleaned_data = super().clean()
        part = cleaned_data.get('part')
        if part and part.superseded_by_id:
            replacement = part.get_effective_replacement()
            if replacement:
                part = replacement
                cleaned_data['part'] = replacement

        bom = self.bom or (self.instance.bom if self.instance and self.instance.pk else None)
        if bom and part:
            if bom.part_id and part.pk == bom.part_id:
                self.add_error('part', "An assembly cannot contain itself as a sub-component.")
            qs = BOMItem.objects.filter(bom=bom, part=part)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error(
                    'part',
                    f"Component '{part.part_number}' is already included in '{bom.name}'. Each component can only appear once per BOM assembly."
                )
        return cleaned_data


class BOMDocumentForm(forms.ModelForm):
    class Meta:
        model = BOMDocument
        fields = ['title', 'document_type', 'file', 'external_url', 'notes']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Main Board Schematic Rev C, YouTube Build Walkthrough, Enclosure Assembly Guide'
            }),
            'document_type': forms.Select(attrs={'class': 'form-select'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'external_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://www.youtube.com/watch?v=... or https://...'
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        file = cleaned_data.get('file')
        external_url = cleaned_data.get('external_url')
        notes = cleaned_data.get('notes')

        if not file and not external_url and not notes:
            raise forms.ValidationError(
                "Please provide at least one resource: an uploaded file/schematic, an external URL / video link, or notes."
            )
        return cleaned_data


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            'supplier',
            'order_number',
            'order_date',
            'expected_delivery_date',
            'carrier',
            'tracking_number',
            'tracking_link',
            'status',
            'payment_method',
            'payment_reference',
            'payment_date',
            'payment_notes',
            'notes',
        ]
        widgets = {
            'supplier': forms.Select(attrs={'class': 'form-select', 'id': 'id_order_supplier'}),
            'order_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank to auto-generate (e.g. PO-20261103-001)'}),
            'order_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'expected_delivery_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'carrier': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. UPS, FedEx, DHL, USPS, Freight'}),
            'tracking_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tracking / Waybill #'}),
            'tracking_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://... (carrier tracking URL)'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'payment_reference': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Visa ending 4821, Check #1042, Wire Ref'}),
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional payment details or terms'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'supplier' in self.fields:
            self.fields['supplier'].empty_label = "-- Select Supplier / Vendor --"
            self.fields['supplier'].queryset = Company.objects.all().order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        if self.instance and self.instance.pk and self.instance.is_closed:
            raise forms.ValidationError(
                f"Order '{self.instance.order_number}' is closed ({self.instance.get_status_display()}) and locked. Closed orders cannot be edited."
            )
        return cleaned_data


class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = ['part', 'quantity', 'unit_price', 'notes']
        widgets = {
            'part': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'value': 1}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional item notes'}),
        }

    def __init__(self, *args, order=None, **kwargs):
        self.order = order
        super().__init__(*args, **kwargs)
        if 'part' in self.fields:
            self.fields['part'].empty_label = "-- Select Part --"
            # Format label to display part info
            parts = Part.objects.select_related('company').all().order_by('part_number')
            self.fields['part'].queryset = parts
            self.fields['part'].label_from_instance = lambda obj: (
                f"{obj.part_number} - {obj.name or obj.description or 'Part'} (On-Order: {obj.quantity_on_order}, On-Hand: {obj.quantity_on_hand})"
            )


class AssemblySaleForm(forms.ModelForm):
    status = forms.ChoiceField(
        choices=AssemblySale.STATUS_CHOICES,
        initial='UNPAID',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select fw-semibold'})
    )

    class Meta:
        model = AssemblySale
        fields = [
            'invoice_number',
            'invoice_date',
            'is_closeout',
            'status',
            'customer_name',
            'customer_address',
            'customer_phone',
            'customer_email',
            'payment_terms',
            'due_date',
            'payment_method',
            'payment_date',
            'shipping_status',
            'shipping_method',
            'tracking_number',
            'shipped_date',
            'notes',
        ]
        widgets = {
            'invoice_number': forms.TextInput(attrs={
                'class': 'form-control font-monospace',
                'placeholder': 'Leave blank to auto-generate (e.g. INV-0001)'
            }),
            'invoice_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_closeout': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_is_closeout'}),
            'customer_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Customer or Company Name'}),
            'customer_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Street, City, Province/State, Postal Code (optional for close-out)'}),
            'customer_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '780.901.9315'}),
            'customer_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'customer@example.com'}),
            'payment_terms': forms.Select(attrs={'class': 'form-select'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'shipping_status': forms.Select(attrs={'class': 'form-select'}),
            'shipping_method': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Canada Post, Purolator, Local Delivery'}),
            'tracking_number': forms.TextInput(attrs={'class': 'form-control font-monospace', 'placeholder': 'Tracking #'}),
            'shipped_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ('customer_address', 'payment_method', 'payment_terms', 'shipping_status'):
            if f in self.fields:
                self.fields[f].required = False

    def clean_status(self):
        return self.cleaned_data.get('status') or 'UNPAID'


class QuoteForm(forms.ModelForm):
    status = forms.ChoiceField(
        choices=Quote.STATUS_CHOICES,
        initial='DRAFT',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select fw-semibold'})
    )

    class Meta:
        model = Quote
        fields = [
            'quote_number',
            'quote_date',
            'valid_until',
            'status',
            'customer_name',
            'customer_address',
            'customer_phone',
            'customer_email',
            'notes',
        ]
        widgets = {
            'quote_number': forms.TextInput(attrs={
                'class': 'form-control font-monospace',
                'placeholder': 'Leave blank to auto-generate (e.g. QTE-0001)'
            }),
            'quote_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'valid_until': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'customer_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Customer or Company Name'}),
            'customer_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Street, City, Province/State, Postal Code'}),
            'customer_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '780.901.9315'}),
            'customer_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'customer@example.com'}),
        }

    def clean_status(self):
        return self.cleaned_data.get('status') or 'DRAFT'



