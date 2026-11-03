from django import forms
from .models import Part, Company, Manufacturer, Category, Location, PartDocument, BOM, BOMItem


class PartForm(forms.ModelForm):
    class Meta:
        model = Part
        fields = [
            'part_number',
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
            'confirmed',
            'link',
            'notes',
        ]
        widgets = {
            'part_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 100-1234 (or enter 1234, or leave blank to auto-generate)'}),
            'supplier_part_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 296-1389-5-ND'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Component description or specs'}),
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
            'confirmed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
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
                    raw_pn = f"{prefix}-{raw_pn}"

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

        return cleaned_data


class CompanyForm(forms.ModelForm):
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


class ManufacturerForm(forms.ModelForm):
    class Meta:
        model = Manufacturer
        fields = ['name', 'website', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Texas Instruments, STMicroelectronics'}),
            'website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://www.ti.com'}),
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


class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name', 'code', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Main Warehouse, Shelf B, Bin 12'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. BIN-B12, W1-S02'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Location description or instructions'}),
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
        fields = ['name', 'description', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. String Assembly, Sensor Node, Base Station'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brief description of the assembly or device'}),
        }


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
            if self.bom:
                # Exclude parts that are already in this BOM assembly
                existing_part_ids = self.bom.items.values_list('part_id', flat=True)
                if self.instance and self.instance.pk and self.instance.part_id:
                    existing_part_ids = existing_part_ids.exclude(part_id=self.instance.part_id)
                self.fields['part'].queryset = Part.objects.exclude(id__in=existing_part_ids)

    def clean(self):
        cleaned_data = super().clean()
        part = cleaned_data.get('part')
        bom = self.bom or (self.instance.bom if self.instance and self.instance.pk else None)
        if bom and part:
            qs = BOMItem.objects.filter(bom=bom, part=part)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error(
                    'part',
                    f"Component '{part.part_number}' is already included in '{bom.name}'. Each component can only appear once per BOM assembly."
                )
        return cleaned_data
