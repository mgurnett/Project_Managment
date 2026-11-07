import csv
import os
import re
from pathlib import Path
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.core.mail import EmailMessage
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.utils import timezone
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView
from django.db import transaction
from django.db.models import Q, Count, Sum, Case, When, Value, IntegerField, F
from django.db.models.functions import Length
from .models import (
    Part, Company, Manufacturer, Category, Location, PartDocument,
    InventoryAdjustment,
    BOM, BOMItem, Order, OrderItem, AssemblySale, AssemblySaleItem
)
from .forms import (
    PartForm, CompanyForm, ManufacturerForm, CategoryForm, LocationForm,
    PartDocumentForm, BOMForm, BOMItemForm, OrderForm, OrderItemForm, AssemblySaleForm
)


def home(request):
    """
    Landing / Dashboard view for Inventory Manager.
    """
    total_parts = Part.objects.count()
    total_companies = Company.objects.count()
    total_manufacturers = Manufacturer.objects.count()
    total_categories = Category.objects.count()
    total_locations = Location.objects.count()
    total_boms = BOM.objects.count()
    total_orders = Order.objects.count()
    active_orders_qs = Order.objects.filter(status__in=['PENDING', 'ORDERED', 'PARTIALLY_RECEIVED'])
    active_orders = active_orders_qs.count()
    active_order_items_qs = OrderItem.objects.filter(order__status__in=['PENDING', 'ORDERED', 'PARTIALLY_RECEIVED'])
    active_order_parts = active_order_items_qs.count()
    total_on_hand = Part.objects.aggregate(total=Sum('quantity_on_hand'))['total'] or 0
    total_on_order = active_order_items_qs.aggregate(total=Sum('quantity'))['total'] or 0
    total_committed = Part.objects.aggregate(total=Sum('quantity_committed'))['total'] or 0
    total_assemblies_on_hand = BOM.objects.aggregate(total=Sum('quantity_on_hand'))['total'] or 0
    total_sales = AssemblySale.objects.count()

    context = {
        'page_title': 'Dashboard Overview',
        'metrics': {
            'total_parts': total_parts,
            'total_companies': total_companies,
            'total_manufacturers': total_manufacturers,
            'total_categories': total_categories,
            'total_locations': total_locations,
            'total_boms': total_boms,
            'total_assemblies_on_hand': total_assemblies_on_hand,
            'total_sales': total_sales,
            'total_orders': total_orders,
            'active_orders': active_orders,
            'active_order_parts': active_order_parts,
            'total_on_hand': total_on_hand,
            'total_on_order': total_on_order,
            'total_committed': total_committed,
        },
        'recent_orders': Order.objects.select_related('supplier').order_by('-order_date', '-created_at')[:5],
        'recent_sales': AssemblySale.objects.prefetch_related('items').order_by('-invoice_date', '-created_at')[:5],
        'recent_boms': BOM.objects.annotate(item_count=Count('items')).order_by('-created_at')[:5],
        'recent_parts': Part.objects.select_related('company', 'category', 'location').order_by('-created_at')[:8],
        'recent_companies': Company.objects.annotate(part_count=Count('parts')).order_by('-created_at')[:5],
    }
    return render(request, 'home.html', context)


# ==============================================================================
# PERSISTENT FILTER HELPER
# ==============================================================================

def resolve_persistent_filters(request, session_key, filter_keys):
    """
    Persists filter parameters in `request.session[session_key]` until explicitly
    cleared via `?clear=1` (or `?reset=1`).
    Returns a dict of `{key: str_value}` for all `filter_keys`.
    """
    saved = dict(request.session.get(session_key, {}))

    if request.GET.get('clear') or request.GET.get('reset'):
        request.session.pop(session_key, None)
        return {k: '' for k in filter_keys}

    has_filter_in_get = any(k in request.GET for k in filter_keys)
    if has_filter_in_get:
        for k in filter_keys:
            if k in request.GET:
                saved[k] = (request.GET.get(k) or '').strip()
        request.session[session_key] = saved

    return {k: saved.get(k, '') for k in filter_keys}


# ==============================================================================
# PART CRUD VIEWS & CSV EXPORT
# ==============================================================================

PART_FILTER_KEYS = ['q', 'company', 'category', 'location', 'confirmed']
COUNT_SHEET_FILTER_KEYS = ['q', 'category', 'location', 'stock']
ORDER_FILTER_KEYS = ['q', 'status', 'supplier']


def get_parts_filtered_queryset(request):
    """
    Applies search query, supplier, category, location, and confirmed status filters to the Part queryset.
    Persists filters in session until cleared.
    """
    filters = resolve_persistent_filters(request, 'part_list_filters', PART_FILTER_KEYS)
    qs = Part.objects.select_related('company', 'manufacturer', 'category', 'location', 'superseded_by').all()
    q = filters['q']
    company_id = filters['company']
    category_id = filters['category']
    location_id = filters['location']
    confirmed = filters['confirmed']

    if q:
        qs = qs.filter(
            Q(part_number__icontains=q) |
            Q(name__icontains=q) |
            Q(supplier_part_number__icontains=q) |
            Q(description__icontains=q) |
            Q(company__name__icontains=q)
        )
    if company_id:
        qs = qs.filter(company_id=company_id)
    if category_id:
        qs = qs.filter(category_id=category_id)
    if location_id:
        qs = qs.filter(location_id=location_id)
    if confirmed in ['true', '1']:
        qs = qs.filter(confirmed=True)
    elif confirmed in ['false', '0']:
        qs = qs.filter(confirmed=False)

    from django.db.models.functions import Length
    return qs.annotate(part_num_len=Length('part_number')).order_by('part_num_len', 'part_number', '-created_at')


def generate_parts_csv(queryset):
    """
    Generates an HTTP streaming CSV response from a Part queryset.
    """
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    response['Content-Disposition'] = f'attachment; filename="parts_catalog_{timestamp}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Part Number',
        'Name',
        'Description',
        'Supplier Part Number',
        'Company / Supplier',
        'Manufacturer',
        'Category',
        'Category Prefix',
        'Storage Location',
        'Quantity On Hand',
        'Quantity On Order',
        'Quantity Committed',
        'Quantity Available',
        'Purchased Quantity',
        'Unit Price ($)',
        'Total Price ($)',
        'Confirmed',
        'Superseded By',
        'Product URL',
        'Document URL',
        'Notes',
    ])

    for part in queryset:
        notes_text = ''
        if part.notes:
            notes_text = re.sub(r'<[^>]+>', ' ', str(part.notes)).strip()

        writer.writerow([
            part.part_number,
            part.name or '',
            part.description or '',
            part.supplier_part_number or '',
            part.company.name if part.company else '',
            part.manufacturer.name if part.manufacturer else '',
            part.category.name if part.category else '',
            part.category.get_prefix() if part.category else '',
            part.location.name if part.location else '',
            part.quantity_on_hand,
            part.quantity_on_order,
            part.quantity_committed,
            part.quantity_availible,
            part.quantity,
            f"{part.price_per:.2f}" if part.price_per is not None else '',
            f"{part.price:.2f}" if part.price is not None else '',
            'Yes' if part.confirmed else 'No',
            part.superseded_by.part_number if part.superseded_by else '',
            part.link or '',
            part.document.url if part.document else '',
            notes_text,
        ])

    return response


def part_export_csv(request):
    """
    Standalone endpoint to export parts filtered by active query parameters.
    """
    queryset = get_parts_filtered_queryset(request)
    return generate_parts_csv(queryset)


class PartListView(ListView):
    model = Part
    template_name = 'core/part_list.html'
    context_object_name = 'parts'
    paginate_by = 25

    def get_queryset(self):
        return get_parts_filtered_queryset(self.request)

    def get(self, request, *args, **kwargs):
        if request.GET.get('clear') or request.GET.get('reset'):
            request.session.pop('part_list_filters', None)
            return redirect('part_list')
        if request.GET.get('export') == 'csv':
            return generate_parts_csv(self.get_queryset())
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = resolve_persistent_filters(self.request, 'part_list_filters', PART_FILTER_KEYS)
        ctx['current_q'] = filters['q']
        ctx['current_company'] = filters['company']
        ctx['current_category'] = filters['category']
        ctx['current_location'] = filters['location']
        ctx['current_confirmed'] = filters['confirmed']
        ctx['companies'] = Company.objects.all()
        ctx['categories'] = Category.objects.all().annotate(prefix_len=Length('prefix')).order_by('prefix_len', 'prefix', 'name')
        ctx['locations'] = Location.objects.all()
        ctx['total_count'] = self.get_queryset().count()
        return ctx


class PartDetailView(DetailView):
    model = Part
    template_name = 'core/part_detail.html'
    context_object_name = 'part'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['documents'] = self.object.documents.all()
        ctx['document_form'] = PartDocumentForm()
        ctx['order_items'] = (
            self.object.order_items
            .select_related('order', 'order__supplier')
            .order_by('-order__order_date', '-created_at')
        )

        # Build Transaction & Movement Journal from easyaudit CRUDEvent
        journal_entries = []
        try:
            import json
            from django.contrib.contenttypes.models import ContentType
            from easyaudit.models import CRUDEvent

            part_ct = ContentType.objects.get_for_model(Part)
            events = (
                CRUDEvent.objects.filter(content_type=part_ct, object_id=str(self.object.pk))
                .select_related('user')
                .order_by('-datetime', '-id')[:50]
            )
            field_labels = {
                'quantity_on_hand': 'On Hand',
                'quantity_on_order': 'On Order',
                'quantity_committed': 'Committed (Kit)',
                'quantity_availible': 'Available',
                'price_per': 'Unit Price ($)',
                'price': 'Package Price ($)',
                'quantity': 'Pkg Qty',
            }
            for ev in events:
                if ev.event_type == CRUDEvent.CREATE:
                    journal_entries.append({
                        'datetime': ev.datetime,
                        'action': 'Part Created',
                        'badge_class': 'bg-success-subtle text-success border-success-subtle',
                        'changes': [f"Initial catalog record created (On Hand: {self.object.quantity_on_hand})"],
                        'user': ev.user.username if ev.user else 'System',
                    })
                elif ev.event_type == CRUDEvent.UPDATE and ev.changed_fields:
                    try:
                        changed = json.loads(ev.changed_fields)
                    except Exception:
                        changed = {}
                    if not isinstance(changed, dict):
                        continue

                    change_descriptions = []
                    for f_key, label in field_labels.items():
                        if f_key in changed and isinstance(changed[f_key], list) and len(changed[f_key]) == 2:
                            old_v, new_v = changed[f_key][0], changed[f_key][1]
                            if old_v != new_v:
                                change_descriptions.append(f"{label}: {old_v} → {new_v}")

                    if not change_descriptions:
                        other_keys = [k for k in changed.keys() if k != 'updated_at']
                        if other_keys:
                            change_descriptions.append(f"Updated {', '.join(other_keys)}")

                    if change_descriptions:
                        # Infer high-level movement type from the fields that changed
                        if 'quantity_on_order' in changed and 'quantity_on_hand' in changed:
                            action_label = 'Order Received'
                            badge_class = 'bg-success-subtle text-success border-success-subtle'
                        elif 'quantity_on_order' in changed:
                            action_label = 'Purchase Order'
                            badge_class = 'bg-primary-subtle text-primary border-primary-subtle'
                        elif 'quantity_committed' in changed and 'quantity_on_hand' in changed:
                            action_label = 'Kit Closed / Built'
                            badge_class = 'bg-warning-subtle text-warning-emphasis border-warning-subtle'
                        elif 'quantity_committed' in changed:
                            action_label = 'Kit Picked'
                            badge_class = 'bg-info-subtle text-info border-info-subtle'
                        elif 'quantity_on_hand' in changed:
                            action_label = 'Inventory Adjustment'
                            badge_class = 'bg-secondary-subtle text-secondary border-secondary-subtle'
                        else:
                            action_label = 'Part Updated'
                            badge_class = 'bg-light text-dark border'

                        journal_entries.append({
                            'datetime': ev.datetime,
                            'action': action_label,
                            'badge_class': badge_class,
                            'changes': change_descriptions,
                            'user': ev.user.username if ev.user else 'System',
                        })
        except Exception:
            pass

        # Incorporate dedicated InventoryAdjustment records with their mandatory reasons
        try:
            adjustments = list(self.object.adjustments.select_related('user').all())
            ctx['adjustments'] = adjustments
            for adj in adjustments:
                sign = f"+{adj.delta}" if adj.delta > 0 else str(adj.delta)
                journal_entries.append({
                    'datetime': adj.created_at,
                    'action': 'Inventory Adjustment',
                    'badge_class': 'bg-secondary-subtle text-secondary border-secondary-subtle',
                    'changes': [
                        f"On Hand: {adj.old_quantity} → {adj.new_quantity} ({sign})",
                        f"Reason: {adj.reason}"
                    ],
                    'user': adj.user.username if adj.user else 'System',
                })
        except Exception:
            ctx['adjustments'] = []

        journal_entries.sort(key=lambda x: x.get('datetime') or timezone.now(), reverse=True)
        ctx['journal_entries'] = journal_entries
        return ctx


class PartCreateView(CreateView):
    model = Part
    form_class = PartForm
    template_name = 'core/part_form.html'
    success_url = reverse_lazy('part_list')

    def get_initial(self):
        initial = super().get_initial()
        duplicate_id = self.request.GET.get('duplicate') or self.request.GET.get('from')
        if duplicate_id:
            try:
                source = Part.objects.get(pk=duplicate_id)
                next_pn = Part.generate_next_part_number(source.category) if source.category else Part.generate_next_part_number('PART')
                initial.update({
                    'part_number': next_pn,
                    'name': source.name,
                    'description': source.description,
                    'company': source.company_id,
                    'manufacturer': source.manufacturer_id,
                    'category': source.category_id,
                    'location': source.location_id,
                    'supplier_part_number': source.supplier_part_number,
                    'superseded_by': source.superseded_by_id,
                    'quantity_on_hand': 0,
                    'quantity_on_order': 0,
                    'quantity_committed': 0,
                    'quantity_availible': 0,
                    'quantity': source.quantity,
                    'price_per': source.price_per,
                    'price': source.price,
                    'confirmed': source.confirmed,
                    'link': source.link,
                    'notes': source.notes,
                })
            except (Part.DoesNotExist, ValueError):
                pass
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Part '{self.object}' was created successfully!")
        return response


class PartDuplicateView(CreateView):
    """
    Creates a new part pre-filled with all specifications and details
    from an existing part, with a newly generated part number ready to save.
    """
    model = Part
    form_class = PartForm
    template_name = 'core/part_form.html'
    success_url = reverse_lazy('part_list')

    def get_source_part(self):
        return get_object_or_404(Part, pk=self.kwargs['pk'])

    def get_initial(self):
        initial = super().get_initial()
        source = self.get_source_part()
        next_pn = Part.generate_next_part_number(source.category) if source.category else Part.generate_next_part_number('PART')
        initial.update({
            'part_number': next_pn,
            'name': source.name,
            'description': source.description,
            'company': source.company_id,
            'manufacturer': source.manufacturer_id,
            'category': source.category_id,
            'location': source.location_id,
            'supplier_part_number': source.supplier_part_number,
            'superseded_by': source.superseded_by_id,
            'quantity_on_hand': 0,
            'quantity_on_order': 0,
            'quantity_committed': 0,
            'quantity_availible': 0,
            'quantity': source.quantity,
            'price_per': source.price_per,
            'price': source.price,
            'confirmed': source.confirmed,
            'link': source.link,
            'notes': source.notes,
        })
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['source_part'] = self.get_source_part()
        ctx['is_duplicate'] = True
        return ctx

    def form_valid(self, form):
        source = self.get_source_part()
        self.object = form.save(commit=False)
        # If no new document uploaded, inherit document from source part if available
        if not form.cleaned_data.get('document') and source.document:
            self.object.document = source.document
        self.object.save()
        form.save_m2m()

        # Clone associated PartDocuments if any
        for doc in source.documents.all():
            PartDocument.objects.create(
                part=self.object,
                title=doc.title,
                document_type=doc.document_type,
                file=doc.file,
                external_url=doc.external_url,
                notes=doc.notes,
            )

        messages.success(self.request, f"Part '{self.object}' was successfully duplicated from '{source}'!")
        return HttpResponseRedirect(self.get_success_url())


class PartUpdateView(UpdateView):
    model = Part
    form_class = PartForm
    template_name = 'core/part_form.html'
    success_url = reverse_lazy('part_list')

    def form_valid(self, form):
        old_part = Part.objects.get(pk=self.get_object().pk)
        old_on_hand = old_part.quantity_on_hand or 0
        response = super().form_valid(form)
        new_on_hand = self.object.quantity_on_hand or 0
        if new_on_hand != old_on_hand:
            reason = (form.cleaned_data.get('adjustment_reason') or '').strip()
            InventoryAdjustment.objects.create(
                part=self.object,
                old_quantity=old_on_hand,
                new_quantity=new_on_hand,
                delta=new_on_hand - old_on_hand,
                reason=reason or "Manual stock adjustment via part edit",
                user=self.request.user if self.request.user.is_authenticated else None,
            )
        messages.success(self.request, f"Part '{self.object}' was updated successfully!")
        return response


class PartDeleteView(DeleteView):
    model = Part
    template_name = 'core/confirm_delete.html'
    success_url = reverse_lazy('part_list')

    def delete(self, request, *args, **kwargs):
        part = self.get_object()
        messages.success(request, f"Part '{part}' was deleted successfully.")
        return super().delete(request, *args, **kwargs)


# ==============================================================================
# COMPANY CRUD VIEWS
# ==============================================================================

class CompanyListView(ListView):
    model = Company
    template_name = 'core/company_list.html'
    context_object_name = 'companies'
    paginate_by = 20

    def get(self, request, *args, **kwargs):
        if request.GET.get('clear') or request.GET.get('reset'):
            request.session.pop('company_list_filters', None)
            return redirect('company_list')
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        filters = resolve_persistent_filters(self.request, 'company_list_filters', ['q'])
        qs = Company.objects.annotate(parts_count=Count('parts')).all()
        q = filters['q']
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(contact_name__icontains=q) |
                Q(email__icontains=q) |
                Q(account_number__icontains=q)
            )
        return qs.order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = resolve_persistent_filters(self.request, 'company_list_filters', ['q'])
        ctx['current_q'] = filters['q']
        ctx['total_count'] = self.get_queryset().count()
        return ctx


class CompanyDetailView(DetailView):
    model = Company
    template_name = 'core/company_detail.html'
    context_object_name = 'company'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['parts'] = self.object.parts.select_related('category', 'location').all()
        return ctx


class CompanyCreateView(CreateView):
    model = Company
    form_class = CompanyForm
    template_name = 'core/company_form.html'
    success_url = reverse_lazy('company_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Company '{self.object.name}' was created successfully!")
        return response


class CompanyUpdateView(UpdateView):
    model = Company
    form_class = CompanyForm
    template_name = 'core/company_form.html'
    success_url = reverse_lazy('company_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Company '{self.object.name}' was updated successfully!")
        return response


class CompanyDeleteView(DeleteView):
    model = Company
    template_name = 'core/confirm_delete.html'
    success_url = reverse_lazy('company_list')

    def delete(self, request, *args, **kwargs):
        company = self.get_object()
        messages.success(request, f"Company '{company.name}' was deleted successfully.")
        return super().delete(request, *args, **kwargs)


# ==============================================================================
# MANUFACTURER CRUD VIEWS
# ==============================================================================

class ManufacturerListView(ListView):
    model = Manufacturer
    template_name = 'core/manufacturer_list.html'
    context_object_name = 'manufacturers'
    paginate_by = 25

    def get(self, request, *args, **kwargs):
        if request.GET.get('clear') or request.GET.get('reset'):
            request.session.pop('manufacturer_list_filters', None)
            return redirect('manufacturer_list')
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        filters = resolve_persistent_filters(self.request, 'manufacturer_list_filters', ['q'])
        qs = Manufacturer.objects.annotate(parts_count=Count('parts')).all()
        q = filters['q']
        if q:
            qs = qs.filter(name__icontains=q)
        return qs.order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = resolve_persistent_filters(self.request, 'manufacturer_list_filters', ['q'])
        ctx['current_q'] = filters['q']
        return ctx


class ManufacturerDetailView(DetailView):
    model = Manufacturer
    template_name = 'core/manufacturer_detail.html'
    context_object_name = 'manufacturer'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['parts'] = self.object.parts.select_related('company', 'category', 'location').all()
        return ctx


class ManufacturerCreateView(CreateView):
    model = Manufacturer
    form_class = ManufacturerForm
    template_name = 'core/manufacturer_form.html'
    success_url = reverse_lazy('manufacturer_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Manufacturer '{self.object.name}' was created successfully!")
        return response


class ManufacturerUpdateView(UpdateView):
    model = Manufacturer
    form_class = ManufacturerForm
    template_name = 'core/manufacturer_form.html'
    success_url = reverse_lazy('manufacturer_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Manufacturer '{self.object.name}' was updated successfully!")
        return response


class ManufacturerDeleteView(DeleteView):
    model = Manufacturer
    template_name = 'core/confirm_delete.html'
    success_url = reverse_lazy('manufacturer_list')

    def delete(self, request, *args, **kwargs):
        mfg = self.get_object()
        messages.success(request, f"Manufacturer '{mfg.name}' was deleted successfully.")
        return super().delete(request, *args, **kwargs)


# ==============================================================================
# CATEGORY CRUD VIEWS
# ==============================================================================

class CategoryListView(ListView):
    model = Category
    template_name = 'core/category_list.html'
    context_object_name = 'categories'
    paginate_by = 25

    def get(self, request, *args, **kwargs):
        if request.GET.get('clear') or request.GET.get('reset'):
            request.session.pop('category_list_filters', None)
            return redirect('category_list')
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        filters = resolve_persistent_filters(self.request, 'category_list_filters', ['q'])
        qs = Category.objects.select_related('parent').annotate(
            parts_count=Count('parts'),
            empty_prefix=Case(
                When(prefix='', then=Value(1)),
                When(prefix__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            )
        ).all()
        q = filters['q']
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(prefix__icontains=q) | Q(description__icontains=q))
        return qs.order_by('empty_prefix', 'prefix', 'name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = resolve_persistent_filters(self.request, 'category_list_filters', ['q'])
        ctx['current_q'] = filters['q']
        return ctx


class CategoryDetailView(DetailView):
    model = Category
    template_name = 'core/category_detail.html'
    context_object_name = 'category'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['parts'] = self.object.parts.select_related('company', 'location').all()
        return ctx


class CategoryCreateView(CreateView):
    model = Category
    form_class = CategoryForm
    template_name = 'core/category_form.html'
    success_url = reverse_lazy('category_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Category '{self.object.name}' was created successfully!")
        return response


class CategoryUpdateView(UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = 'core/category_form.html'
    success_url = reverse_lazy('category_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Category '{self.object.name}' was updated successfully!")
        return response


class CategoryDeleteView(DeleteView):
    model = Category
    template_name = 'core/confirm_delete.html'
    success_url = reverse_lazy('category_list')

    def delete(self, request, *args, **kwargs):
        cat = self.get_object()
        messages.success(request, f"Category '{cat.name}' was deleted successfully.")
        return super().delete(request, *args, **kwargs)


# ==============================================================================
# LOCATION CRUD VIEWS
# ==============================================================================

class LocationListView(ListView):
    model = Location
    template_name = 'core/location_list.html'
    context_object_name = 'locations'
    paginate_by = 25

    def get(self, request, *args, **kwargs):
        if request.GET.get('clear') or request.GET.get('reset'):
            request.session.pop('location_list_filters', None)
            return redirect('location_list')
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        filters = resolve_persistent_filters(self.request, 'location_list_filters', ['q'])
        qs = Location.objects.annotate(parts_count=Count('parts')).all()
        q = filters['q']
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))
        return qs.order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = resolve_persistent_filters(self.request, 'location_list_filters', ['q'])
        ctx['current_q'] = filters['q']
        return ctx


class LocationDetailView(DetailView):
    model = Location
    template_name = 'core/location_detail.html'
    context_object_name = 'location'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['parts'] = self.object.parts.select_related('company', 'category').all()
        return ctx


class LocationCreateView(CreateView):
    model = Location
    form_class = LocationForm
    template_name = 'core/location_form.html'
    success_url = reverse_lazy('location_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Location '{self.object.name}' was created successfully!")
        return response


class LocationUpdateView(UpdateView):
    model = Location
    form_class = LocationForm
    template_name = 'core/location_form.html'
    success_url = reverse_lazy('location_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Location '{self.object.name}' was updated successfully!")
        return response


class LocationDeleteView(DeleteView):
    model = Location
    template_name = 'core/confirm_delete.html'
    success_url = reverse_lazy('location_list')

    def delete(self, request, *args, **kwargs):
        loc = self.get_object()
        messages.success(request, f"Location '{loc.name}' was deleted successfully.")
        return super().delete(request, *args, **kwargs)


# ==============================================================================
# PART DOCUMENT / SCAN / ARTICLE VIEWS
# ==============================================================================

class PartDocumentCreateView(CreateView):
    model = PartDocument
    form_class = PartDocumentForm
    template_name = 'core/part_document_form.html'

    def get_part(self):
        return get_object_or_404(Part, pk=self.kwargs['part_pk'])

    def form_valid(self, form):
        form.instance.part = self.get_part()
        response = super().form_valid(form)
        messages.success(self.request, f"Document '{self.object.title}' added to Part {self.object.part.part_number}!")
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['part'] = self.get_part()
        return ctx

    def get_success_url(self):
        return reverse('part_detail', kwargs={'pk': self.kwargs['part_pk']})


class PartDocumentDetailView(DetailView):
    model = PartDocument
    template_name = 'core/part_document_detail.html'
    context_object_name = 'document'


class PartDocumentUpdateView(UpdateView):
    model = PartDocument
    form_class = PartDocumentForm
    template_name = 'core/part_document_form.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['part'] = self.object.part
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Document '{self.object.title}' updated successfully!")
        return response

    def get_success_url(self):
        return reverse('part_detail', kwargs={'pk': self.object.part.pk})


class PartDocumentDeleteView(DeleteView):
    model = PartDocument
    template_name = 'core/confirm_delete.html'

    def form_valid(self, form):
        messages.success(self.request, f"Document '{self.object.title}' was deleted.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('part_detail', kwargs={'pk': self.object.part.pk})


# ==============================================================================
# BILL OF MATERIALS (BOM) VIEWS
# ==============================================================================

class BOMListView(ListView):
    model = BOM
    template_name = 'core/bom_list.html'
    context_object_name = 'boms'
    paginate_by = 20

    def get(self, request, *args, **kwargs):
        if request.GET.get('clear') or request.GET.get('reset'):
            request.session.pop('bom_list_filters', None)
            return redirect('bom_list')
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        filters = resolve_persistent_filters(self.request, 'bom_list_filters', ['q'])
        qs = BOM.objects.annotate(items_count=Count('items')).all()
        q = filters['q']
        if q:
            qs = qs.filter(
                Q(assembly_number__icontains=q) |
                Q(name__icontains=q) |
                Q(description__icontains=q)
            )
        return qs.order_by('assembly_number', 'name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = resolve_persistent_filters(self.request, 'bom_list_filters', ['q'])
        ctx['current_q'] = filters['q']
        ctx['total_count'] = self.get_queryset().count()
        ctx['total_built_on_hand'] = BOM.objects.aggregate(total=Sum('quantity_on_hand'))['total'] or 0
        return ctx


class BOMDetailView(DetailView):
    model = BOM
    template_name = 'core/bom_detail.html'
    context_object_name = 'bom'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        items = list(self.object.items.select_related('part', 'part__company', 'part__location').all())
        ctx['items'] = items
        ctx['item_form'] = BOMItemForm(bom=self.object)
        if items:
            max_kits = []
            max_builds = []
            kitted_sets = []
            for item in items:
                req = item.quantity or 1
                on_hand = item.part.quantity_on_hand or 0
                committed = item.part.quantity_committed or 0
                uncommitted = max(0, on_hand - committed)
                max_kits.append(uncommitted // req)
                max_builds.append(on_hand // req)
                kitted_sets.append(committed // req)
            ctx['max_kits_available'] = min(max_kits)
            ctx['max_builds_possible'] = min(max_builds)
            ctx['kitted_sets'] = min(kitted_sets)
        else:
            ctx['max_kits_available'] = 0
            ctx['max_builds_possible'] = 0
            ctx['kitted_sets'] = 0
        return ctx


class BOMCreateView(CreateView):
    model = BOM
    form_class = BOMForm
    template_name = 'core/bom_form.html'

    def get_initial(self):
        initial = super().get_initial()
        initial['assembly_number'] = BOM.generate_next_assembly_number()
        initial['quantity_on_hand'] = 0
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['all_parts'] = Part.objects.select_related('company', 'category').all().order_by('part_number')
        ctx['next_assembly_number'] = BOM.generate_next_assembly_number()
        return ctx

    def form_valid(self, form):
        with transaction.atomic():
            bom = form.save()
            self.object = bom

            part_ids = self.request.POST.getlist('item_part[]') or self.request.POST.getlist('item_part')
            quantities = self.request.POST.getlist('item_quantity[]') or self.request.POST.getlist('item_quantity')
            references = self.request.POST.getlist('item_reference[]') or self.request.POST.getlist('item_reference')
            notes_list = self.request.POST.getlist('item_notes[]') or self.request.POST.getlist('item_notes')

            added_count = 0
            for i, p_id in enumerate(part_ids):
                p_str = str(p_id).strip() if p_id else ''
                if not p_str or not p_str.isdigit():
                    continue
                part = Part.objects.filter(pk=int(p_str)).first()
                if not part:
                    continue

                try:
                    qty = int(quantities[i]) if i < len(quantities) and str(quantities[i]).strip() else 1
                    if qty <= 0:
                        qty = 1
                except (ValueError, TypeError):
                    qty = 1

                ref = references[i].strip() if i < len(references) and references[i] else ''
                item_note = notes_list[i].strip() if i < len(notes_list) and notes_list[i] else ''

                existing_item = BOMItem.objects.filter(bom=bom, part=part).first()
                if existing_item:
                    existing_item.quantity += qty
                    if ref and not existing_item.reference:
                        existing_item.reference = ref
                    if item_note and not existing_item.notes:
                        existing_item.notes = item_note
                    existing_item.save()
                else:
                    BOMItem.objects.create(
                        bom=bom,
                        part=part,
                        quantity=qty,
                        reference=ref,
                        notes=item_note,
                    )
                    added_count += 1

            if added_count > 0:
                messages.success(
                    self.request,
                    f"BOM Assembly '{bom.name}' was created with {added_count} component(s)!"
                )
            else:
                messages.success(self.request, f"BOM Assembly '{bom.name}' was created successfully!")
            return redirect('bom_detail', pk=bom.pk)


class BOMUpdateView(UpdateView):
    model = BOM
    form_class = BOMForm
    template_name = 'core/bom_form.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['all_parts'] = Part.objects.select_related('company', 'category').all().order_by('part_number')
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"BOM Assembly '{self.object.name}' was updated successfully!")
        return response

    def get_success_url(self):
        return reverse('bom_detail', kwargs={'pk': self.object.pk})


class BOMDeleteView(DeleteView):
    model = BOM
    template_name = 'core/confirm_delete.html'
    success_url = reverse_lazy('bom_list')

    def form_valid(self, form):
        messages.success(self.request, f"BOM Assembly '{self.object.name}' was deleted.")
        return super().form_valid(form)


class BOMItemCreateView(CreateView):
    model = BOMItem
    form_class = BOMItemForm

    def get_bom(self):
        return get_object_or_404(BOM, pk=self.kwargs['bom_pk'])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['bom'] = self.get_bom()
        return kwargs

    def form_valid(self, form):
        bom = self.get_bom()
        form.instance.bom = bom

        # Check how many active kits this BoM already had before adding the new component
        existing_items = list(bom.items.select_related('part').all())
        if existing_items:
            active_kits = min(
                (i.part.quantity_committed or 0) // max(1, i.quantity)
                for i in existing_items
            )
        else:
            active_kits = 0

        with transaction.atomic():
            response = super().form_valid(form)
            part = self.object.part
            if active_kits > 0:
                commit_qty = (self.object.quantity or 1) * active_kits
                part.quantity_committed = (part.quantity_committed or 0) + commit_qty
                part.quantity_availible = max(0, (part.quantity_on_hand or 0) - part.quantity_committed)
                part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
                messages.success(
                    self.request,
                    f"Added {part.part_number} to {bom.name} and committed {commit_qty} unit(s) for {active_kits} active kit(s)!"
                )
            else:
                messages.success(self.request, f"Added {part.part_number} to {bom.name}!")
        return response

    def form_invalid(self, form):
        for field, errs in form.errors.items():
            for err in errs:
                messages.error(self.request, f"{err}")
        return redirect('bom_detail', pk=self.kwargs['bom_pk'])

    def get_success_url(self):
        return reverse('bom_detail', kwargs={'pk': self.kwargs['bom_pk']})


def _get_bom_active_kit_count(bom, exclude_item_pk=None):
    """
    Returns the number of active kits currently committed for `bom`.
    """
    items = [
        i for i in bom.items.select_related('part').all()
        if exclude_item_pk is None or i.pk != exclude_item_pk
    ]
    if not items:
        return 0
    return min((i.part.quantity_committed or 0) // max(1, i.quantity) for i in items)


def bom_item_update_action(request, pk):
    """
    POST action to adjust a BOMItem's required quantity (or reference/notes),
    supporting mode='add', 'subtract', 'set', or 'delete'.
    Also syncs the component part's `quantity_committed` if the BoM has active kits.
    """
    if request.method != 'POST':
        return redirect('bom_list')

    item = get_object_or_404(BOMItem.objects.select_related('bom', 'part'), pk=pk)
    bom = item.bom
    part = item.part
    bom_pk = bom.pk
    next_url = request.POST.get('next') or reverse('bom_detail', kwargs={'pk': bom_pk})
    mode = (request.POST.get('mode') or 'set').strip().lower()

    active_kits = _get_bom_active_kit_count(bom)
    old_qty = item.quantity or 1

    def _release_item_committed(qty_per_kit):
        if active_kits > 0:
            release_units = qty_per_kit * active_kits
            old_c = part.quantity_committed or 0
            part.quantity_committed = max(0, old_c - min(old_c, release_units))
            part.quantity_availible = max(0, (part.quantity_on_hand or 0) - part.quantity_committed)
            part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])

    if mode == 'delete':
        with transaction.atomic():
            _release_item_committed(old_qty)
            part_num = part.part_number
            bom_name = bom.name
            item.delete()
        messages.success(request, f"Removed {part_num} from {bom_name}.")
        return redirect(next_url)

    if mode == 'add':
        new_qty = old_qty + 1
    elif mode == 'subtract':
        if old_qty <= 1:
            with transaction.atomic():
                _release_item_committed(old_qty)
                part_num = part.part_number
                bom_name = bom.name
                item.delete()
            messages.success(request, f"Removed {part_num} from {bom_name} (quantity reached 0).")
            return redirect(next_url)
        new_qty = old_qty - 1
    else:
        try:
            new_qty = int(request.POST.get('quantity', old_qty))
        except (ValueError, TypeError):
            new_qty = old_qty
        if new_qty <= 0:
            with transaction.atomic():
                _release_item_committed(old_qty)
                part_num = part.part_number
                bom_name = bom.name
                item.delete()
            messages.success(request, f"Removed {part_num} from {bom_name} (quantity set to 0).")
            return redirect(next_url)

    with transaction.atomic():
        item.quantity = new_qty
        if 'reference' in request.POST:
            item.reference = request.POST.get('reference', '').strip()
        if 'notes' in request.POST:
            item.notes = request.POST.get('notes', '').strip()
        item.save()

        if active_kits > 0 and new_qty != old_qty:
            delta_units = (new_qty - old_qty) * active_kits
            part.quantity_committed = max(0, (part.quantity_committed or 0) + delta_units)
            part.quantity_availible = max(0, (part.quantity_on_hand or 0) - part.quantity_committed)
            part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])

    messages.success(
        request,
        f"Updated {part.part_number} in {bom.name}: Qty {old_qty} → {item.quantity}."
    )
    return redirect(next_url)


class BOMItemDeleteView(DeleteView):
    model = BOMItem
    template_name = 'core/confirm_delete.html'

    def form_valid(self, form):
        item = self.get_object()
        bom = item.bom
        part = item.part
        active_kits = _get_bom_active_kit_count(bom)
        with transaction.atomic():
            if active_kits > 0:
                release_units = (item.quantity or 1) * active_kits
                old_c = part.quantity_committed or 0
                part.quantity_committed = max(0, old_c - min(old_c, release_units))
                part.quantity_availible = max(0, (part.quantity_on_hand or 0) - part.quantity_committed)
                part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
            messages.success(self.request, f"Removed {part.part_number} from {bom.name}.")
            return super().form_valid(form)

    def get_success_url(self):
        return reverse('bom_detail', kwargs={'pk': self.object.bom.pk})


# ==============================================================================
# INVENTORY COUNT SHEET & AUDIT VIEWS
# ==============================================================================

def get_count_sheet_queryset(request, session_key='count_sheet_filters'):
    """
    Returns filtered Part queryset for the Inventory Count Sheet / Take Inventory:
    Grouped by Category (by category prefix/name) and sorted by part_number.
    """
    from django.db.models.functions import Length
    filters = resolve_persistent_filters(request, session_key, COUNT_SHEET_FILTER_KEYS)
    qs = Part.objects.select_related('category', 'location', 'company', 'manufacturer').annotate(
        cat_prefix_len=Length('category__prefix'),
        part_num_len=Length('part_number')
    ).order_by(
        'cat_prefix_len', 'category__prefix', 'category__name', 'part_num_len', 'part_number'
    )

    q = filters['q']
    if q:
        qs = qs.filter(
            Q(part_number__icontains=q) |
            Q(name__icontains=q) |
            Q(description__icontains=q) |
            Q(supplier_part_number__icontains=q)
        )

    category_id = filters['category']
    if category_id:
        if category_id == 'none':
            qs = qs.filter(category__isnull=True)
        else:
            qs = qs.filter(category_id=category_id)

    location_id = filters['location']
    if location_id:
        if location_id == 'none':
            qs = qs.filter(location__isnull=True)
        else:
            qs = qs.filter(location_id=location_id)

    stock = filters['stock']
    if stock == 'in_stock':
        qs = qs.filter(quantity_on_hand__gt=0)
    elif stock == 'zero_stock':
        qs = qs.filter(quantity_on_hand=0)
    elif stock == 'negative':
        qs = qs.filter(quantity_on_hand__lt=0)

    return qs


class InventoryCountSheetView(TemplateView):
    template_name = 'core/inventory_count_sheet.html'

    def get(self, request, *args, **kwargs):
        if request.GET.get('clear') or request.GET.get('reset'):
            request.session.pop('count_sheet_filters', None)
            return redirect('inventory_count_sheet')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = resolve_persistent_filters(self.request, 'count_sheet_filters', COUNT_SHEET_FILTER_KEYS)
        qs = get_count_sheet_queryset(self.request, session_key='count_sheet_filters')

        # Group parts by category while maintaining sort order
        category_map = {}
        for part in qs:
            cat = part.category
            cat_id = cat.pk if cat else 'none'
            if cat_id not in category_map:
                category_map[cat_id] = {
                    'category': cat,
                    'category_name': cat.name if cat else 'Uncategorized / General Components',
                    'prefix': cat.get_prefix() if cat else '',
                    'parts': [],
                    'total_on_hand': 0,
                    'total_items': 0,
                }
            category_map[cat_id]['parts'].append(part)
            category_map[cat_id]['total_on_hand'] += (part.quantity_on_hand or 0)
            category_map[cat_id]['total_items'] += 1

        groups = list(category_map.values())
        groups.sort(key=lambda g: (len(g['prefix']), g['prefix'], g['category_name']))

        ctx['groups'] = groups
        ctx['total_parts'] = qs.count()
        ctx['total_categories'] = len(groups)
        ctx['total_on_hand'] = sum(g['total_on_hand'] for g in groups)
        ctx['categories'] = Category.objects.all().annotate(prefix_len=Length('prefix')).order_by('prefix_len', 'prefix', 'name')
        ctx['locations'] = Location.objects.all().order_by('name')
        ctx['current_category'] = filters['category']
        ctx['current_location'] = filters['location']
        ctx['current_stock'] = filters['stock']
        ctx['current_q'] = filters['q']
        ctx['generated_at'] = timezone.now()
        return ctx


def inventory_count_sheet_export_csv(request):
    """
    Exports the inventory count sheet to CSV, grouped by category and sorted by part number.
    """
    qs = get_count_sheet_queryset(request)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    response['Content-Disposition'] = f'attachment; filename="inventory_count_sheet_{timestamp}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Category Prefix',
        'Category Name',
        'Part Number',
        'Component Name',
        'Description',
        'Location Name',
        'Location Code',
        'System On Hand',
        'Physical Count',
        'Discrepancy (+/-)',
        'Auditor Notes',
    ])

    for part in qs:
        cat_prefix = part.category.get_prefix() if part.category else ''
        cat_name = part.category.name if part.category else 'Uncategorized'
        loc_name = part.location.name if part.location else ''
        loc_code = part.location.code if part.location else ''

        writer.writerow([
            cat_prefix,
            cat_name,
            part.part_number,
            part.name or '',
            part.description or '',
            loc_name,
            loc_code,
            part.quantity_on_hand,
            '',  # Physical Count
            '',  # Discrepancy
            '',  # Notes
        ])

    return response


def inventory_count_sheet_pdf(request):
    """
    Renders and streams a high-resolution print-ready PDF version of the Inventory Count Sheet.
    Uses WeasyPrint to produce standard Letter portrait reference sheets.
    Supports ?download=1 to force attachment download vs inline browser tab view.
    """
    import weasyprint

    qs = get_count_sheet_queryset(request)

    category_map = {}
    for part in qs:
        cat = part.category
        cat_id = cat.pk if cat else 'none'
        if cat_id not in category_map:
            category_map[cat_id] = {
                'category': cat,
                'category_name': cat.name if cat else 'Uncategorized / General Components',
                'prefix': cat.get_prefix() if cat else '',
                'parts': [],
                'total_on_hand': 0,
                'total_items': 0,
            }
        category_map[cat_id]['parts'].append(part)
        category_map[cat_id]['total_on_hand'] += (part.quantity_on_hand or 0)
        category_map[cat_id]['total_items'] += 1

    groups = list(category_map.values())

    context = {
        'groups': groups,
        'total_parts': qs.count(),
        'total_categories': len(groups),
        'total_on_hand': sum(g['total_on_hand'] for g in groups),
        'generated_at': timezone.now(),
        'request': request,
    }

    html_content = render_to_string('core/inventory_count_sheet_pdf.html', context)
    pdf_bytes = weasyprint.HTML(
        string=html_content,
        base_url=request.build_absolute_uri('/')
    ).write_pdf()

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    disposition = 'attachment' if request.GET.get('download') == '1' else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="inventory_count_sheet_{timestamp}.pdf"'
    return response


# ==============================================================================
# PURCHASE ORDERS & ORDER ACTION VIEWS
# ==============================================================================

class OrderListView(ListView):
    model = Order
    template_name = 'core/order_list.html'
    context_object_name = 'orders'
    paginate_by = 20

    def get(self, request, *args, **kwargs):
        if request.GET.get('clear') or request.GET.get('reset'):
            request.session.pop('order_list_filters', None)
            return redirect('order_list')
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        filters = resolve_persistent_filters(self.request, 'order_list_filters', ORDER_FILTER_KEYS)
        qs = Order.objects.select_related('supplier').annotate(
            items_count=Count('items'),
            total_ordered=Sum('items__quantity'),
            total_received=Sum('items__quantity_received')
        )
        q = filters['q']
        if q:
            qs = qs.filter(
                Q(order_number__icontains=q) |
                Q(tracking_number__icontains=q) |
                Q(carrier__icontains=q) |
                Q(supplier__name__icontains=q) |
                Q(items__part__part_number__icontains=q) |
                Q(items__part__name__icontains=q)
            ).distinct()

        status_filter = filters['status']
        if status_filter:
            qs = qs.filter(status=status_filter)

        supplier_filter = filters['supplier']
        if supplier_filter.isdigit():
            qs = qs.filter(supplier_id=int(supplier_filter))

        return qs.order_by('-order_date', '-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = resolve_persistent_filters(self.request, 'order_list_filters', ORDER_FILTER_KEYS)
        all_orders = Order.objects.all()
        ctx['total_orders_count'] = all_orders.count()
        ctx['active_orders_count'] = all_orders.filter(status__in=['PENDING', 'ORDERED', 'PARTIALLY_RECEIVED']).count()
        ctx['received_orders_count'] = all_orders.filter(status='RECEIVED').count()
        active_items_qs = OrderItem.objects.filter(
            order__status__in=['PENDING', 'ORDERED', 'PARTIALLY_RECEIVED']
        )
        ctx['active_order_parts_count'] = active_items_qs.count()
        ctx['total_on_order_units'] = active_items_qs.aggregate(total=Sum('quantity'))['total'] or 0

        ctx['current_q'] = filters['q']
        ctx['current_status'] = filters['status']
        ctx['current_supplier'] = filters['supplier']
        ctx['suppliers'] = Company.objects.filter(orders__isnull=False).distinct().order_by('name')
        ctx['status_choices'] = Order.STATUS_CHOICES
        return ctx


class OrderDetailView(DetailView):
    model = Order
    template_name = 'core/order_detail.html'
    context_object_name = 'order'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['items'] = self.object.items.select_related('part', 'part__company', 'part__location').all()
        ctx['item_form'] = OrderItemForm(order=self.object)
        ctx['categories'] = Category.objects.all().order_by('prefix', 'name')
        ctx['locations'] = Location.objects.all().order_by('name')
        ctx['all_parts'] = Part.objects.select_related('company', 'category').all().order_by('part_number')
        return ctx


def order_quick_create_part(request):
    """
    AJAX/POST endpoint to quickly create a new Part while placing or editing an order.
    Supports setting package quantity (the quantity they come in, e.g. box of 50),
    package price, and unit price.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'error': 'POST required'}, status=405)

    name = (request.POST.get('name') or '').strip()
    part_number = (request.POST.get('part_number') or '').strip()
    description = (request.POST.get('description') or '').strip()
    supplier_part_number = (request.POST.get('supplier_part_number') or '').strip()
    category_id = (request.POST.get('category') or '').strip()
    location_id = (request.POST.get('location') or '').strip()
    supplier_id = (request.POST.get('supplier') or '').strip()

    if not name and not description and not part_number:
        return JsonResponse({'status': 'error', 'error': 'Please provide a Part Name or Description.'}, status=400)

    try:
        pkg_qty = int(request.POST.get('package_quantity') or request.POST.get('quantity') or 1)
        if pkg_qty <= 0:
            pkg_qty = 1
    except (ValueError, TypeError):
        pkg_qty = 1

    pkg_price = None
    raw_pkg_price = (request.POST.get('package_price') or request.POST.get('price') or '').strip()
    if raw_pkg_price:
        try:
            pkg_price = Decimal(raw_pkg_price)
        except (InvalidOperation, ValueError):
            pkg_price = None

    u_price = None
    raw_u_price = (request.POST.get('unit_price') or request.POST.get('price_per') or '').strip()
    if raw_u_price:
        try:
            u_price = Decimal(raw_u_price)
        except (InvalidOperation, ValueError):
            u_price = None

    if pkg_price is not None and pkg_qty > 0 and u_price is None:
        u_price = (pkg_price / Decimal(str(pkg_qty))).quantize(Decimal('0.01'))
    elif u_price is not None and pkg_qty > 0 and pkg_price is None:
        pkg_price = (u_price * Decimal(str(pkg_qty))).quantize(Decimal('0.01'))

    category = Category.objects.filter(pk=int(category_id)).first() if category_id.isdigit() else None
    location = Location.objects.filter(pk=int(location_id)).first() if location_id.isdigit() else None
    company = Company.objects.filter(pk=int(supplier_id)).first() if supplier_id.isdigit() else None

    part = Part(
        part_number=part_number,
        name=name or description or part_number,
        description=description or name,
        supplier_part_number=supplier_part_number,
        company=company,
        category=category,
        location=location,
        quantity=pkg_qty,
        price_per=u_price,
        price=pkg_price,
    )
    try:
        part.clean()
        part.save()
    except Exception as exc:
        err_msg = getattr(exc, 'messages', [str(exc)])
        return JsonResponse({'status': 'error', 'error': '; '.join(err_msg)}, status=400)

    return JsonResponse({
        'status': 'ok',
        'part': {
            'id': str(part.pk),
            'part_number': part.part_number,
            'name': part.name or part.description or 'Part',
            'description': part.description or '',
            'quantity': part.quantity or 1,
            'price': f"{part.price:.2f}" if part.price is not None else '',
            'price_per': f"{part.price_per:.2f}" if part.price_per is not None else '0.00',
            'on_hand': part.quantity_on_hand or 0,
            'on_order': part.quantity_on_order or 0,
        }
    })


class OrderCreateView(CreateView):
    """
    Action that allows us to make an order.
    The order has a supplier, expected delivery date, tracking number, and part numbers.
    The part numbers have their on-order number increased by the amount ordered.
    Also allows creating a new part inline and changing the price and package quantity
    (e.g. box of 50) that the part comes in.
    """
    model = Order
    form_class = OrderForm
    template_name = 'core/order_form.html'

    def get_initial(self):
        initial = super().get_initial()
        supplier_id = self.request.GET.get('supplier')
        if supplier_id and supplier_id.isdigit():
            initial['supplier'] = supplier_id
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['all_parts'] = Part.objects.select_related('company', 'category').all().order_by('part_number')
        ctx['categories'] = Category.objects.all().order_by('prefix', 'name')
        ctx['locations'] = Location.objects.all().order_by('name')
        ctx['preselected_part_id'] = self.request.GET.get('part')
        return ctx

    def form_valid(self, form):
        with transaction.atomic():
            order = form.save()

            # Process line items submitted dynamically
            part_ids = self.request.POST.getlist('item_part[]') or self.request.POST.getlist('item_part')
            quantities = self.request.POST.getlist('item_quantity[]') or self.request.POST.getlist('item_quantity')
            package_quantities = (
                self.request.POST.getlist('item_package_quantity[]')
                or self.request.POST.getlist('item_package_quantity')
            )
            package_prices = (
                self.request.POST.getlist('item_package_price[]')
                or self.request.POST.getlist('item_package_price')
            )
            unit_prices = self.request.POST.getlist('item_unit_price[]') or self.request.POST.getlist('item_unit_price')
            notes_list = self.request.POST.getlist('item_notes[]') or self.request.POST.getlist('item_notes')

            # Inline new-part creation fields (when item_part is '__new__' or 'new')
            new_names = self.request.POST.getlist('item_new_name[]') or self.request.POST.getlist('item_new_name')
            new_part_numbers = (
                self.request.POST.getlist('item_new_part_number[]')
                or self.request.POST.getlist('item_new_part_number')
            )
            new_categories = (
                self.request.POST.getlist('item_new_category[]')
                or self.request.POST.getlist('item_new_category')
            )
            new_descriptions = (
                self.request.POST.getlist('item_new_description[]')
                or self.request.POST.getlist('item_new_description')
            )
            new_supplier_pns = (
                self.request.POST.getlist('item_new_supplier_pn[]')
                or self.request.POST.getlist('item_new_supplier_pn')
            )

            items_created = 0
            for i, p_id in enumerate(part_ids):
                p_id_str = str(p_id).strip() if p_id else ''
                if not p_id_str:
                    continue

                try:
                    qty = int(quantities[i]) if i < len(quantities) and str(quantities[i]).strip() else 1
                    if qty <= 0:
                        continue
                except (ValueError, TypeError):
                    qty = 1

                pkg_qty = None
                if i < len(package_quantities) and str(package_quantities[i]).strip():
                    try:
                        parsed_pkg_qty = int(package_quantities[i])
                        if parsed_pkg_qty > 0:
                            pkg_qty = parsed_pkg_qty
                    except (ValueError, TypeError):
                        pkg_qty = None

                pkg_price = None
                if i < len(package_prices) and str(package_prices[i]).strip():
                    try:
                        pkg_price = Decimal(str(package_prices[i]).strip())
                    except (InvalidOperation, ValueError):
                        pkg_price = None

                u_price = None
                if i < len(unit_prices) and str(unit_prices[i]).strip():
                    try:
                        u_price = Decimal(str(unit_prices[i]).strip())
                    except (InvalidOperation, ValueError):
                        u_price = None

                # Compute unit_price from package_price / package_quantity or vice versa
                effective_pkg_qty_for_calc = pkg_qty if (pkg_qty and pkg_qty > 0) else 1
                if pkg_price is not None and u_price is None:
                    u_price = (pkg_price / Decimal(str(effective_pkg_qty_for_calc))).quantize(Decimal('0.01'))
                elif u_price is not None and pkg_price is None and pkg_qty and pkg_qty > 0:
                    pkg_price = (u_price * Decimal(str(pkg_qty))).quantize(Decimal('0.01'))

                item_notes = notes_list[i].strip() if i < len(notes_list) and notes_list[i] else ''

                if p_id_str in ['__new__', 'new']:
                    new_name = new_names[i].strip() if i < len(new_names) and new_names[i] else ''
                    new_pn = new_part_numbers[i].strip() if i < len(new_part_numbers) and new_part_numbers[i] else ''
                    new_cat_id = new_categories[i].strip() if i < len(new_categories) and new_categories[i] else ''
                    new_desc = new_descriptions[i].strip() if i < len(new_descriptions) and new_descriptions[i] else ''
                    new_sku = new_supplier_pns[i].strip() if i < len(new_supplier_pns) and new_supplier_pns[i] else ''

                    if not new_name and not new_desc and not new_pn:
                        continue

                    cat_obj = Category.objects.filter(pk=int(new_cat_id)).first() if new_cat_id.isdigit() else None
                    part = Part.objects.create(
                        part_number=new_pn,
                        name=new_name or new_desc or new_pn,
                        description=new_desc or new_name,
                        supplier_part_number=new_sku,
                        company=order.supplier,
                        category=cat_obj,
                        quantity=pkg_qty if (pkg_qty and pkg_qty > 0) else 1,
                        price_per=u_price,
                        price=pkg_price,
                    )
                elif p_id_str.isdigit():
                    part = get_object_or_404(Part, pk=int(p_id_str))
                    part_updated_fields = []

                    # If package quantity ("quantity that they come in", e.g. box of 50) was set/changed
                    if pkg_qty is not None and pkg_qty > 0 and part.quantity != pkg_qty:
                        part.quantity = pkg_qty
                        part_updated_fields.append('quantity')
                        # Recalculate package price if part already has a price_per
                        if pkg_price is not None:
                            part.price = pkg_price
                            part_updated_fields.append('price')
                        elif part.price_per is not None:
                            part.price = (Decimal(str(part.price_per)) * Decimal(str(pkg_qty))).quantize(Decimal('0.01'))
                            part_updated_fields.append('price')
                    elif pkg_price is not None and part.price != pkg_price:
                        part.price = pkg_price
                        part_updated_fields.append('price')

                    # If pkg_price was explicitly provided without u_price, derive u_price using part.quantity
                    if u_price is None and pkg_price is not None:
                        denom = pkg_qty or part.quantity or 1
                        u_price = (pkg_price / Decimal(str(denom))).quantize(Decimal('0.01'))

                    if u_price is None and part.price_per is not None:
                        u_price = part.price_per

                    if part_updated_fields:
                        part_updated_fields.append('updated_at')
                        part.save(update_fields=part_updated_fields)
                else:
                    continue

                # If part comes in a package (e.g. pkg_qty=50) and the user entered package count (e.g. qty=1 box of 50),
                # convert to total individual units ordered (1 * 50 = 50 units) so inventory & subtotal match $20.20
                effective_pkg_size = pkg_qty if (pkg_qty and pkg_qty > 0) else (part.quantity if (part.quantity and part.quantity > 0) else 1)
                if effective_pkg_size > 1 and qty < effective_pkg_size:
                    total_units_qty = qty * effective_pkg_size
                else:
                    total_units_qty = qty

                OrderItem.objects.create(
                    order=order,
                    part=part,
                    quantity=total_units_qty,
                    unit_price=u_price,
                    notes=item_notes
                )

                # Increase the part's on order number
                part.quantity_on_order = (part.quantity_on_order or 0) + total_units_qty
                part.save(update_fields=['quantity_on_order', 'updated_at'])
                items_created += 1

            messages.success(
                self.request,
                f"Order '{order.order_number}' successfully created with {items_created} part item(s)! On-order quantities have been increased."
            )
            return redirect('order_detail', pk=order.pk)


class OrderUpdateView(UpdateView):
    model = Order
    form_class = OrderForm
    template_name = 'core/order_form.html'

    def dispatch(self, request, *args, **kwargs):
        order = self.get_object()
        if order.is_closed:
            messages.error(
                request,
                f"Order '{order.order_number}' is closed ({order.get_status_display()}) and locked. Closed orders cannot be edited."
            )
            return redirect('order_detail', pk=order.pk)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Order '{self.object.order_number}' was updated.")
        return response

    def get_success_url(self):
        return reverse('order_detail', kwargs={'pk': self.object.pk})


class OrderDeleteView(DeleteView):
    model = Order
    template_name = 'core/confirm_delete.html'
    success_url = reverse_lazy('order_list')

    def dispatch(self, request, *args, **kwargs):
        order = self.get_object()
        if order.is_closed:
            messages.error(
                request,
                f"Order '{order.order_number}' is closed ({order.get_status_display()}) and locked. Closed orders cannot be deleted."
            )
            return redirect('order_detail', pk=order.pk)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            order = self.get_object()
            # Restore on-order quantities for remaining unreceived quantities before deleting
            for item in order.items.select_related('part').all():
                remaining = max(0, item.quantity - item.quantity_received)
                if remaining > 0 and order.status not in ['CANCELLED', 'RECEIVED']:
                    part = item.part
                    part.quantity_on_order = max(0, (part.quantity_on_order or 0) - remaining)
                    part.save(update_fields=['quantity_on_order', 'updated_at'])
            messages.success(self.request, f"Order '{order.order_number}' was deleted and on-order quantities adjusted.")
            return super().form_valid(form)


class OrderItemCreateView(CreateView):
    """
    Adds a line item to an existing order and increments the part's quantity_on_order.
    Supports selecting an existing part OR creating a new part inline, as well as
    changing the price and package quantity (e.g. box of 50).
    """
    model = OrderItem
    form_class = OrderItemForm

    def get_order(self):
        return get_object_or_404(Order, pk=self.kwargs['order_pk'])

    def post(self, request, *args, **kwargs):
        order = self.get_order()
        if order.is_closed:
            messages.error(
                request,
                f"Cannot add items to Order '{order.order_number}' because it is closed ({order.get_status_display()})."
            )
            return redirect('order_detail', pk=order.pk)
        part_val = (request.POST.get('part') or '').strip()

        try:
            qty = int(request.POST.get('quantity') or 1)
            if qty <= 0:
                qty = 1
        except (ValueError, TypeError):
            qty = 1

        pkg_qty = None
        raw_pkg_qty = (request.POST.get('package_quantity') or '').strip()
        if raw_pkg_qty:
            try:
                parsed_pkg = int(raw_pkg_qty)
                if parsed_pkg > 0:
                    pkg_qty = parsed_pkg
            except (ValueError, TypeError):
                pkg_qty = None

        pkg_price = None
        raw_pkg_price = (request.POST.get('package_price') or '').strip()
        if raw_pkg_price:
            try:
                pkg_price = Decimal(raw_pkg_price)
            except (InvalidOperation, ValueError):
                pkg_price = None

        u_price = None
        raw_u_price = (request.POST.get('unit_price') or '').strip()
        if raw_u_price:
            try:
                u_price = Decimal(raw_u_price)
            except (InvalidOperation, ValueError):
                u_price = None

        notes = (request.POST.get('notes') or '').strip()

        with transaction.atomic():
            if part_val in ['__new__', 'new']:
                new_name = (request.POST.get('new_name') or '').strip()
                new_pn = (request.POST.get('new_part_number') or '').strip()
                new_cat_id = (request.POST.get('new_category') or '').strip()
                new_desc = (request.POST.get('new_description') or '').strip()
                new_sku = (request.POST.get('new_supplier_part_number') or '').strip()

                if not new_name and not new_desc and not new_pn:
                    messages.error(request, "Please provide a Part Name or Description for the new part.")
                    return redirect('order_detail', pk=order.pk)

                effective_pkg = pkg_qty if (pkg_qty and pkg_qty > 0) else 1
                if pkg_price is not None and u_price is None:
                    u_price = (pkg_price / Decimal(str(effective_pkg))).quantize(Decimal('0.01'))
                elif u_price is not None and pkg_price is None:
                    pkg_price = (u_price * Decimal(str(effective_pkg))).quantize(Decimal('0.01'))

                cat_obj = Category.objects.filter(pk=int(new_cat_id)).first() if new_cat_id.isdigit() else None
                part = Part.objects.create(
                    part_number=new_pn,
                    name=new_name or new_desc or new_pn,
                    description=new_desc or new_name,
                    supplier_part_number=new_sku,
                    company=order.supplier,
                    category=cat_obj,
                    quantity=effective_pkg,
                    price_per=u_price,
                    price=pkg_price,
                )
            elif part_val.isdigit():
                part = get_object_or_404(Part, pk=int(part_val))
                part_updated_fields = []
                if pkg_qty is not None and pkg_qty > 0 and part.quantity != pkg_qty:
                    part.quantity = pkg_qty
                    part_updated_fields.append('quantity')
                    if part.price_per is not None:
                        part.price = (Decimal(str(part.price_per)) * Decimal(str(pkg_qty))).quantize(Decimal('0.01'))
                        part_updated_fields.append('price')

                effective_pkg = pkg_qty or part.quantity or 1
                if pkg_price is not None and u_price is None:
                    u_price = (pkg_price / Decimal(str(effective_pkg))).quantize(Decimal('0.01'))

                if u_price is None and part.price_per is not None:
                    u_price = part.price_per

                if part_updated_fields:
                    part_updated_fields.append('updated_at')
                    part.save(update_fields=part_updated_fields)
            else:
                messages.error(request, "Please select a valid part or create a new part.")
                return redirect('order_detail', pk=order.pk)

            effective_pkg_size = pkg_qty if (pkg_qty and pkg_qty > 0) else (part.quantity if (part.quantity and part.quantity > 0) else 1)
            if effective_pkg_size > 1 and qty < effective_pkg_size:
                total_units_qty = qty * effective_pkg_size
            else:
                total_units_qty = qty

            item = OrderItem.objects.create(
                order=order,
                part=part,
                quantity=total_units_qty,
                unit_price=u_price,
                notes=notes,
            )
            part.quantity_on_order = (part.quantity_on_order or 0) + item.quantity
            part.save(update_fields=['quantity_on_order', 'updated_at'])
            messages.success(
                request,
                f"Added {item.part.part_number} (Qty: {item.quantity}) to Order {order.order_number}. On-order quantity increased."
            )
            return redirect('order_detail', pk=order.pk)


class OrderItemDeleteView(DeleteView):
    """
    Deletes a line item and decrements the part's quantity_on_order.
    """
    model = OrderItem
    template_name = 'core/confirm_delete.html'

    def dispatch(self, request, *args, **kwargs):
        item = self.get_object()
        if item.order.is_closed:
            messages.error(
                request,
                f"Cannot remove items from Order '{item.order.order_number}' because it is closed ({item.order.get_status_display()})."
            )
            return redirect('order_detail', pk=item.order.pk)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        item = self.get_object()
        order_pk = item.order.pk
        with transaction.atomic():
            remaining = max(0, item.quantity - item.quantity_received)
            if remaining > 0 and item.order.status not in ['CANCELLED', 'RECEIVED']:
                part = item.part
                part.quantity_on_order = max(0, (part.quantity_on_order or 0) - remaining)
                part.save(update_fields=['quantity_on_order', 'updated_at'])
            messages.success(
                self.request,
                f"Removed {item.part.part_number} from order. On-order quantity adjusted."
            )
            return super().form_valid(form)

    def get_success_url(self):
        return reverse('order_detail', kwargs={'pk': self.object.order.pk})


def order_receive_item(request, order_pk, item_pk):
    """
    Action to receive units for a specific order line item.
    Increases on_hand, decreases on_order, and updates the Part's price model
    (price_per, price, and package quantity if provided) to the ordered/received price.
    """
    if request.method != 'POST':
        return redirect('order_detail', pk=order_pk)

    order = get_object_or_404(Order, pk=order_pk)
    item = get_object_or_404(OrderItem, pk=item_pk, order=order)

    try:
        qty_to_receive = int(request.POST.get('quantity_received', item.remaining_to_receive))
    except (ValueError, TypeError):
        qty_to_receive = item.remaining_to_receive

    if qty_to_receive <= 0:
        messages.warning(request, "Receive quantity must be at least 1.")
        return redirect('order_detail', pk=order_pk)

    qty_to_receive = min(qty_to_receive, item.remaining_to_receive)

    with transaction.atomic():
        part = item.part

        # Check if package quantity ("quantity that they come in", e.g. box of 50) was provided/updated
        raw_pkg_qty = (request.POST.get('package_quantity') or '').strip()
        if raw_pkg_qty:
            try:
                parsed_pkg_qty = int(raw_pkg_qty)
                if parsed_pkg_qty > 0:
                    part.quantity = parsed_pkg_qty
            except (ValueError, TypeError):
                pass

        # Check if unit_price or package_price was provided/overridden during receipt, else use item.unit_price
        raw_unit_price = (request.POST.get('unit_price') or '').strip()
        raw_pkg_price = (request.POST.get('package_price') or '').strip()

        received_pkg_price = None
        if raw_pkg_price:
            try:
                received_pkg_price = Decimal(raw_pkg_price)
            except (InvalidOperation, ValueError):
                received_pkg_price = None

        received_unit_price = None
        if raw_unit_price:
            try:
                received_unit_price = Decimal(raw_unit_price)
            except (InvalidOperation, ValueError):
                received_unit_price = None

        if received_unit_price is None and received_pkg_price is not None:
            denom = part.quantity if (part.quantity and part.quantity > 0) else 1
            received_unit_price = (received_pkg_price / Decimal(str(denom))).quantize(Decimal('0.01'))

        if received_unit_price is not None:
            item.unit_price = received_unit_price
        else:
            received_unit_price = item.unit_price

        item.quantity_received += qty_to_receive
        item.save(update_fields=['quantity_received', 'unit_price', 'updated_at'])

        # Decrease on order, increase on hand
        part.quantity_on_order = max(0, (part.quantity_on_order or 0) - qty_to_receive)
        part.quantity_on_hand = (part.quantity_on_hand or 0) + qty_to_receive
        part.quantity_availible = max(0, part.quantity_on_hand - (part.quantity_committed or 0))

        # Update the price in the Part model when ordered at a price and received
        part_update_fields = ['quantity_on_order', 'quantity_on_hand', 'quantity_availible', 'quantity', 'updated_at']
        if received_unit_price is not None:
            old_price_per = part.price_per
            part.price_per = received_unit_price
            if received_pkg_price is not None:
                part.price = received_pkg_price
            elif part.price is not None and old_price_per == received_unit_price:
                pass
            elif part.quantity and part.quantity > 0:
                part.price = (received_unit_price * Decimal(str(part.quantity))).quantize(Decimal('0.01'))
            else:
                part.price = received_unit_price
            part_update_fields.extend(['price_per', 'price'])

        part.save(update_fields=part_update_fields)

        # Update order status
        if order.is_fully_received:
            order.status = 'RECEIVED'
        else:
            order.status = 'PARTIALLY_RECEIVED'
        order.save(update_fields=['status', 'updated_at'])

        price_msg = f" Price updated to ${part.price_per:.2f}/unit." if received_unit_price is not None else ""
        messages.success(
            request,
            f"Received {qty_to_receive} units of {part.part_number}! On-hand is now {part.quantity_on_hand}, On-order is {part.quantity_on_order}.{price_msg}"
        )

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('order_detail', pk=order_pk)


def _receive_all_items_for_order(order):
    """
    Receives all remaining unreceived items on the given Order.
    Returns (items_received_count, total_units_received).
    """
    items_received_count = 0
    total_units_received = 0

    for item in order.items.select_related('part').all():
        remaining = item.remaining_to_receive
        if remaining <= 0:
            continue

        part = item.part
        item.quantity_received += remaining
        item.save(update_fields=['quantity_received', 'updated_at'])

        part.quantity_on_order = max(0, (part.quantity_on_order or 0) - remaining)
        part.quantity_on_hand = (part.quantity_on_hand or 0) + remaining
        part.quantity_availible = max(0, part.quantity_on_hand - (part.quantity_committed or 0))

        part_update_fields = ['quantity_on_order', 'quantity_on_hand', 'quantity_availible', 'updated_at']
        if item.unit_price is not None:
            old_price_per = part.price_per
            part.price_per = item.unit_price
            if part.price is not None and old_price_per == item.unit_price:
                pass
            elif part.quantity and part.quantity > 0:
                part.price = (item.unit_price * Decimal(str(part.quantity))).quantize(Decimal('0.01'))
            else:
                part.price = item.unit_price
            part_update_fields.extend(['price_per', 'price'])

        part.save(update_fields=part_update_fields)
        items_received_count += 1
        total_units_received += remaining

    if order.items.exists():
        order.status = 'RECEIVED'
        order.save(update_fields=['status', 'updated_at'])

    return items_received_count, total_units_received


def order_receive_all(request, pk):
    """
    Action to receive all remaining items on a specific Purchase Order at once.
    """
    if request.method != 'POST':
        return redirect('order_detail', pk=pk)

    order = get_object_or_404(Order, pk=pk)
    with transaction.atomic():
        items_count, units_count = _receive_all_items_for_order(order)

    if units_count > 0:
        messages.success(
            request,
            f"Received all remaining items on Order {order.order_number} ({items_count} line item(s), {units_count} total units)! Inventory on-hand and part prices updated."
        )
    else:
        messages.info(request, f"Order {order.order_number} has no remaining unreceived items.")

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('order_detail', pk=order.pk)


def orders_receive_everything(request):
    """
    Action to receive everything currently on order across all active Purchase Orders
    (and any standalone on-order quantities on parts).
    """
    if request.method != 'POST':
        return redirect('order_receive_action')

    orders_updated = 0
    total_items = 0
    total_units = 0

    with transaction.atomic():
        active_orders = Order.objects.filter(
            status__in=['PENDING', 'ORDERED', 'PARTIALLY_RECEIVED']
        ).prefetch_related('items__part')

        for order in active_orders:
            i_count, u_count = _receive_all_items_for_order(order)
            if u_count > 0:
                orders_updated += 1
                total_items += i_count
                total_units += u_count

        # Also handle any parts that had standalone quantity_on_order > 0 not tied to an active Order
        standalone_parts = Part.objects.filter(quantity_on_order__gt=0)
        for part in standalone_parts:
            rem = part.quantity_on_order
            part.quantity_on_hand = (part.quantity_on_hand or 0) + rem
            part.quantity_on_order = 0
            part.quantity_availible = max(0, part.quantity_on_hand - (part.quantity_committed or 0))
            part.save(update_fields=['quantity_on_hand', 'quantity_on_order', 'quantity_availible', 'updated_at'])
            total_units += rem
            total_items += 1

    if total_units > 0:
        messages.success(
            request,
            f"Received everything on order! Processed {orders_updated} purchase order(s) and moved {total_units} total unit(s) across {total_items} item(s) into on-hand inventory."
        )
    else:
        messages.info(request, "There are currently no outstanding items on order to receive.")

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('order_receive_action')


class OrderReceiveActionView(TemplateView):
    """
    Dedicated 'Receive Orders' action center where users can see all pending/open orders
    and unreceived line items, and either receive individual items, receive an entire PO,
    or receive everything that was on order with one click.
    """
    template_name = 'core/order_receive_action.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        active_orders = list(
            Order.objects.filter(status__in=['PENDING', 'ORDERED', 'PARTIALLY_RECEIVED'])
            .select_related('supplier')
            .prefetch_related('items__part', 'items__part__location', 'items__part__category')
            .order_by('expected_delivery_date', '-order_date')
        )

        orders_with_pending = []
        total_pending_units = 0
        total_pending_items = 0

        for order in active_orders:
            pending_items = [item for item in order.items.all() if item.remaining_to_receive > 0]
            if pending_items:
                order.pending_items = pending_items
                order.pending_units = sum(item.remaining_to_receive for item in pending_items)
                orders_with_pending.append(order)
                total_pending_units += order.pending_units
                total_pending_items += len(pending_items)

        ctx['active_orders'] = orders_with_pending
        ctx['total_pending_orders'] = len(orders_with_pending)
        ctx['total_pending_items'] = total_pending_items
        ctx['total_pending_units'] = total_pending_units
        ctx['recently_received_orders'] = (
            Order.objects.filter(status='RECEIVED')
            .select_related('supplier')
            .order_by('-updated_at')[:5]
        )
        return ctx


# ==============================================================================
# KIT ACTION & BUILD ACTION VIEWS
# ==============================================================================

def _execute_bom_kit(bom, kits_count=1):
    """
    Moves all components for `kits_count` units of `bom` into a kit by increasing
    each part's `quantity_committed` and updating `quantity_availible`.
    Returns (components_count, total_units_kitted, shortages_list).
    """
    items = list(bom.items.select_related('part').all())
    shortages = []
    for item in items:
        part = item.part
        req_qty = item.quantity * kits_count
        on_hand = part.quantity_on_hand or 0
        committed = part.quantity_committed or 0
        uncommitted = max(0, on_hand - committed)
        if uncommitted < req_qty:
            shortages.append(f"{part.part_number} (need {req_qty}, uncommitted available {uncommitted})")

    total_units_kitted = 0
    for item in items:
        part = item.part
        req_qty = item.quantity * kits_count
        part.quantity_committed = (part.quantity_committed or 0) + req_qty
        part.quantity_availible = max(0, (part.quantity_on_hand or 0) - part.quantity_committed)
        part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
        total_units_kitted += req_qty

    return len(items), total_units_kitted, shortages


def bom_kit_action(request, pk):
    """
    POST action to move everything from a BoM into a Kit (increases committed quantity).
    """
    if request.method != 'POST':
        return redirect('bom_detail', pk=pk)

    bom = get_object_or_404(BOM, pk=pk)
    try:
        kits_count = int(request.POST.get('quantity', 1))
        if kits_count <= 0:
            kits_count = 1
    except (ValueError, TypeError):
        kits_count = 1

    if not bom.items.exists():
        messages.warning(request, f"BOM '{bom.name}' has no components to kit.")
        return redirect('bom_detail', pk=bom.pk)

    with transaction.atomic():
        comp_count, total_kitted, shortages = _execute_bom_kit(bom, kits_count=kits_count)

    msg = (
        f"Moved {kits_count} kit(s) of '{bom.name}' ({comp_count} unique component(s), "
        f"{total_kitted} total parts) to Committed Kit inventory!"
    )
    if shortages:
        messages.warning(
            request,
            f"{msg} Note: Shortages detected on {', '.join(shortages)}."
        )
    else:
        messages.success(request, msg)

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('bom_detail', pk=bom.pk)


def _execute_bom_build(bom, build_count=1, consume_committed=True, assembly_number=None, sale_price=None):
    """
    Takes all required parts for `build_count` units of `bom` out of inventory AND adds the
    built assembly (`build_count` units) to `bom.quantity_on_hand`, assigning a 1000-series
    `assembly_number` if not already set (or if overridden by `assembly_number`):
    - Decreases each component `part.quantity_on_hand` by required quantity (floored at 0)
    - If `consume_committed` is True, also decreases `part.quantity_committed` up to the required quantity
    - Recalculates `part.quantity_availible`
    - Assigns 1000-series `bom.assembly_number` and increases `bom.quantity_on_hand` by `build_count`
    Returns (components_count, total_units_consumed, shortages_list).
    """
    items = list(bom.items.select_related('part').all())
    shortages = []
    for item in items:
        part = item.part
        req_qty = item.quantity * build_count
        on_hand = part.quantity_on_hand or 0
        if on_hand < req_qty:
            shortages.append(f"{part.part_number} (need {req_qty}, on hand {on_hand})")

    total_consumed = 0
    for item in items:
        part = item.part
        req_qty = item.quantity * build_count
        old_on_hand = part.quantity_on_hand or 0
        old_committed = part.quantity_committed or 0

        part.quantity_on_hand = max(0, old_on_hand - req_qty)
        if consume_committed and old_committed > 0:
            part.quantity_committed = max(0, old_committed - min(old_committed, req_qty))
        part.quantity_availible = max(0, part.quantity_on_hand - (part.quantity_committed or 0))
        part.save(update_fields=['quantity_on_hand', 'quantity_committed', 'quantity_availible', 'updated_at'])
        total_consumed += req_qty

    # Assign 1000-series assembly number and add built assembly units to finished inventory
    bom_update_fields = ['quantity_on_hand', 'updated_at']
    if assembly_number and str(assembly_number).strip():
        desired_asm_num = str(assembly_number).strip()
        # Only set if not conflicting with another BOM
        if not BOM.objects.filter(assembly_number=desired_asm_num).exclude(pk=bom.pk).exists():
            bom.assembly_number = desired_asm_num
            bom_update_fields.append('assembly_number')

    if not bom.assembly_number:
        bom.assembly_number = BOM.generate_next_assembly_number(exclude_pk=bom.pk)
        if 'assembly_number' not in bom_update_fields:
            bom_update_fields.append('assembly_number')

    if sale_price is not None and str(sale_price).strip() != '':
        try:
            bom.sale_price = Decimal(str(sale_price).strip())
            bom_update_fields.append('sale_price')
        except (InvalidOperation, ValueError):
            pass

    bom.quantity_on_hand = (bom.quantity_on_hand or 0) + build_count
    bom.save(update_fields=bom_update_fields)
    try:
        bom.sync_part()
    except Exception:
        pass

    return len(items), total_consumed, shortages


def bom_build_action(request, pk):
    """
    POST action to build an assembly from a BoM, taking all required parts out of inventory,
    assigning a 1000-series assembly number, and adding the built assembly to inventory.
    """
    if request.method != 'POST':
        return redirect('bom_detail', pk=pk)

    bom = get_object_or_404(BOM, pk=pk)
    try:
        build_count = int(request.POST.get('quantity', 1))
        if build_count <= 0:
            build_count = 1
    except (ValueError, TypeError):
        build_count = 1

    consume_committed = request.POST.get('consume_committed', '1') != '0'
    assembly_number = request.POST.get('assembly_number')
    sale_price = request.POST.get('sale_price')

    if not bom.items.exists():
        messages.warning(request, f"BOM '{bom.name}' has no components to build.")
        return redirect('bom_detail', pk=bom.pk)

    with transaction.atomic():
        comp_count, total_consumed, shortages = _execute_bom_build(
            bom,
            build_count=build_count,
            consume_committed=consume_committed,
            assembly_number=assembly_number,
            sale_price=sale_price,
        )

    msg = (
        f"Built {build_count} unit(s) of Assembly {bom.assembly_number} — '{bom.name}'! "
        f"Removed {total_consumed} component(s) from parts inventory and added {build_count} built assembly unit(s) "
        f"(Assemblies On-Hand: {bom.quantity_on_hand})."
    )
    if shortages:
        messages.warning(
            request,
            f"{msg} Note: Insufficient on-hand stock for {', '.join(shortages)} (floored at 0)."
        )
    else:
        messages.success(request, msg)

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('bom_detail', pk=bom.pk)


def bom_close_kit_action(request, pk):
    """
    POST action to close/complete a Kit for a BoM (consumes the committed kit parts out of
    inventory and adds the built 1000-series assembly to inventory, or if action_type == 'return'
    returns them to uncommitted available stock).
    """
    if request.method != 'POST':
        return redirect('bom_detail', pk=pk)

    bom = get_object_or_404(BOM, pk=pk)
    try:
        kits_count = int(request.POST.get('quantity', 1))
        if kits_count <= 0:
            kits_count = 1
    except (ValueError, TypeError):
        kits_count = 1

    action_type = request.POST.get('action_type', 'build').strip().lower()
    assembly_number = request.POST.get('assembly_number')
    sale_price = request.POST.get('sale_price')

    if not bom.items.exists():
        messages.warning(request, f"BOM '{bom.name}' has no components.")
        return redirect('bom_detail', pk=bom.pk)

    with transaction.atomic():
        if action_type == 'return':
            items = list(bom.items.select_related('part').all())
            total_returned = 0
            for item in items:
                part = item.part
                req_qty = item.quantity * kits_count
                old_committed = part.quantity_committed or 0
                released = min(old_committed, req_qty)
                part.quantity_committed = max(0, old_committed - released)
                part.quantity_availible = max(0, (part.quantity_on_hand or 0) - part.quantity_committed)
                part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
                total_returned += released
            messages.success(
                request,
                f"Closed {kits_count} kit(s) of '{bom.name}' and returned {total_returned} committed part(s) back to available stock."
            )
        else:
            comp_count, total_consumed, shortages = _execute_bom_build(
                bom,
                build_count=kits_count,
                consume_committed=True,
                assembly_number=assembly_number,
                sale_price=sale_price,
            )
            msg = (
                f"Closed {kits_count} kit(s) into Assembly {bom.assembly_number} — '{bom.name}'! "
                f"Consumed {total_consumed} committed part(s) out of inventory and added {kits_count} built assembly unit(s) "
                f"(Assemblies On-Hand: {bom.quantity_on_hand})."
            )
            if shortages:
                messages.warning(request, f"{msg} Note: Shortages on {', '.join(shortages)}.")
            else:
                messages.success(request, msg)

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('bom_detail', pk=bom.pk)


def _compute_bom_kit_metrics(bom):
    """
    Computes `max_kits`, `kitted_sets`, `max_builds`, and `total_committed_parts` for a BoM.
    """
    items = list(bom.items.all())
    if items:
        bom.max_kits = min(
            max(0, (i.part.quantity_on_hand or 0) - (i.part.quantity_committed or 0)) // max(1, i.quantity)
            for i in items
        )
        bom.kitted_sets = min(
            (i.part.quantity_committed or 0) // max(1, i.quantity)
            for i in items
        )
        bom.max_builds = min(
            max(0, i.part.quantity_on_hand or 0) // max(1, i.quantity)
            for i in items
        )
        bom.total_committed_parts = sum((i.part.quantity_committed or 0) for i in items)
    else:
        bom.max_kits = 0
        bom.kitted_sets = 0
        bom.max_builds = 0
        bom.total_committed_parts = 0
    return bom


def bom_adjust_kit_action(request, pk):
    """
    POST action to adjust a BoM's kit quantity:
    - mode='add': add `quantity` kits (commits components)
    - mode='subtract' / 'return': subtract `quantity` kits and return components to available stock
    - mode='set': set kitted sets to exact target `target_kits` (adds or returns the difference)
    - mode='delete' / 'clear': delete/clear all kitted sets for this BoM and return committed parts to stock
    - mode='build' / 'close': close & build `quantity` (or all) kitted sets, deducting from on-hand and committed
    """
    if request.method != 'POST':
        return redirect('kit_action')

    bom = get_object_or_404(BOM.objects.prefetch_related('items__part'), pk=pk)
    next_url = request.POST.get('next') or reverse('kit_action')

    if not bom.items.exists():
        messages.warning(request, f"BOM '{bom.name}' has no components.")
        return redirect(next_url)

    _compute_bom_kit_metrics(bom)
    current_kits = bom.kitted_sets
    mode = (request.POST.get('mode') or 'set').strip().lower()

    try:
        qty = int(request.POST.get('quantity', 1))
    except (ValueError, TypeError):
        qty = 1

    try:
        target_kits = int(request.POST.get('target_kits', current_kits))
        if target_kits < 0:
            target_kits = 0
    except (ValueError, TypeError):
        target_kits = current_kits

    if mode == 'add':
        qty = max(1, qty)
        with transaction.atomic():
            comp_count, total_kitted, shortages = _execute_bom_kit(bom, kits_count=qty)
        msg = f"Added {qty} kit(s) of '{bom.name}' ({total_kitted} total component parts committed)."
        if shortages:
            messages.warning(request, f"{msg} Note: Shortages on {', '.join(shortages)}.")
        else:
            messages.success(request, msg)
        return redirect(next_url)

    elif mode in ('subtract', 'return'):
        qty = max(1, qty)
        with transaction.atomic():
            items = list(bom.items.select_related('part').all())
            total_returned = 0
            for item in items:
                part = item.part
                req_qty = item.quantity * qty
                old_committed = part.quantity_committed or 0
                released = min(old_committed, req_qty)
                if released > 0:
                    part.quantity_committed = max(0, old_committed - released)
                    part.quantity_availible = max(0, (part.quantity_on_hand or 0) - part.quantity_committed)
                    part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
                    total_returned += released
        messages.success(
            request,
            f"Subtracted {qty} kit(s) from '{bom.name}' and returned {total_returned} committed part(s) to available stock."
        )
        return redirect(next_url)

    elif mode in ('delete', 'clear'):
        kits_to_clear = max(1, current_kits)
        with transaction.atomic():
            items = list(bom.items.select_related('part').all())
            total_returned = 0
            for item in items:
                part = item.part
                old_committed = part.quantity_committed or 0
                req_qty = item.quantity * kits_to_clear
                released = min(old_committed, req_qty) if current_kits > 0 else old_committed
                if released > 0:
                    part.quantity_committed = max(0, old_committed - released)
                    part.quantity_availible = max(0, (part.quantity_on_hand or 0) - part.quantity_committed)
                    part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
                    total_returned += released
        messages.success(
            request,
            f"Deleted active kit(s) for '{bom.name}' and returned {total_returned} committed part(s) back to available inventory."
        )
        return redirect(next_url)

    elif mode in ('build', 'close'):
        kits_to_build = max(1, qty if 'quantity' in request.POST else current_kits)
        assembly_number = request.POST.get('assembly_number')
        sale_price = request.POST.get('sale_price')
        with transaction.atomic():
            comp_count, total_consumed, shortages = _execute_bom_build(
                bom,
                build_count=kits_to_build,
                consume_committed=True,
                assembly_number=assembly_number,
                sale_price=sale_price,
            )
        msg = (
            f"Closed & built {kits_to_build} kit(s) into Assembly {bom.assembly_number} — '{bom.name}' "
            f"({total_consumed} parts deducted from inventory, {kits_to_build} assembly unit(s) added; "
            f"Assemblies On-Hand: {bom.quantity_on_hand})."
        )
        if shortages:
            messages.warning(request, f"{msg} Note: Shortages on {', '.join(shortages)}.")
        else:
            messages.success(request, msg)
        return redirect(next_url)

    else:
        # mode == 'set': adjust from current_kits to target_kits
        delta = target_kits - current_kits
        if delta > 0:
            with transaction.atomic():
                comp_count, total_kitted, shortages = _execute_bom_kit(bom, kits_count=delta)
            msg = f"Adjusted '{bom.name}' kits from {current_kits} to {target_kits} (+{delta} kit(s), {total_kitted} parts committed)."
            if shortages:
                messages.warning(request, f"{msg} Note: Shortages on {', '.join(shortages)}.")
            else:
                messages.success(request, msg)
        elif delta < 0:
            remove_kits = abs(delta)
            with transaction.atomic():
                items = list(bom.items.select_related('part').all())
                total_returned = 0
                for item in items:
                    part = item.part
                    req_qty = item.quantity * remove_kits
                    old_committed = part.quantity_committed or 0
                    released = min(old_committed, req_qty)
                    if released > 0:
                        part.quantity_committed = max(0, old_committed - released)
                        part.quantity_availible = max(0, (part.quantity_on_hand or 0) - part.quantity_committed)
                        part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
                        total_returned += released
            messages.success(
                request,
                f"Adjusted '{bom.name}' kits from {current_kits} to {target_kits} (-{remove_kits} kit(s), {total_returned} parts returned to stock)."
            )
        else:
            # Even when target_kits == current_kits, ensure any newly added component
            # whose quantity_committed is below (item.quantity * target_kits) gets synced up
            synced_units = 0
            if target_kits > 0:
                with transaction.atomic():
                    for item in bom.items.select_related('part').all():
                        part = item.part
                        expected_c = (item.quantity or 1) * target_kits
                        old_c = part.quantity_committed or 0
                        if old_c < expected_c:
                            diff_c = expected_c - old_c
                            part.quantity_committed = expected_c
                            part.quantity_availible = max(0, (part.quantity_on_hand or 0) - part.quantity_committed)
                            part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
                            synced_units += diff_c
            if synced_units > 0:
                messages.success(
                    request,
                    f"Synced '{bom.name}' to {target_kits} kit(s) and committed {synced_units} missing component unit(s)."
                )
            else:
                messages.info(request, f"Kit quantity for '{bom.name}' is already {target_kits}.")
        return redirect(next_url)


def part_adjust_committed_action(request, pk):
    """
    POST action to directly adjust, add, subtract, or clear/delete a specific Part's
    `quantity_committed` (kitted quantity), or consume it from on-hand inventory.
    """
    if request.method != 'POST':
        return redirect('kit_action')

    part = get_object_or_404(Part, pk=pk)
    next_url = request.POST.get('next') or reverse('kit_action')
    mode = (request.POST.get('mode') or 'set').strip().lower()
    old_committed = part.quantity_committed or 0
    old_on_hand = part.quantity_on_hand or 0

    try:
        qty = int(request.POST.get('quantity', 1))
    except (ValueError, TypeError):
        qty = 1

    try:
        target_committed = int(request.POST.get('target_committed', old_committed))
        if target_committed < 0:
            target_committed = 0
    except (ValueError, TypeError):
        target_committed = old_committed

    with transaction.atomic():
        if mode == 'add':
            qty = max(1, qty)
            part.quantity_committed = old_committed + qty
            part.quantity_availible = max(0, old_on_hand - part.quantity_committed)
            part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
            messages.success(
                request,
                f"Added {qty} to committed kit count for {part.part_number} (Committed: {old_committed} → {part.quantity_committed})."
            )
        elif mode in ('subtract', 'return'):
            qty = max(1, qty)
            part.quantity_committed = max(0, old_committed - qty)
            part.quantity_availible = max(0, old_on_hand - part.quantity_committed)
            part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
            messages.success(
                request,
                f"Returned {min(old_committed, qty)} committed unit(s) of {part.part_number} to available stock (Committed: {old_committed} → {part.quantity_committed})."
            )
        elif mode in ('delete', 'clear'):
            part.quantity_committed = 0
            part.quantity_availible = max(0, old_on_hand)
            part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
            messages.success(
                request,
                f"Cleared committed kit allocation for {part.part_number} ({old_committed} unit(s) returned to available stock)."
            )
        elif mode in ('consume', 'build'):
            consume_qty = max(1, qty if 'quantity' in request.POST else old_committed)
            part.quantity_on_hand = max(0, old_on_hand - consume_qty)
            part.quantity_committed = max(0, old_committed - consume_qty)
            part.quantity_availible = max(0, part.quantity_on_hand - part.quantity_committed)
            part.save(update_fields=['quantity_on_hand', 'quantity_committed', 'quantity_availible', 'updated_at'])
            messages.success(
                request,
                f"Consumed {consume_qty} kitted unit(s) of {part.part_number} from inventory (On-Hand: {old_on_hand} → {part.quantity_on_hand}, Committed: {old_committed} → {part.quantity_committed})."
            )
        else:
            # mode == 'set'
            if target_committed != old_committed:
                part.quantity_committed = target_committed
                part.quantity_availible = max(0, old_on_hand - part.quantity_committed)
                part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])
                messages.success(
                    request,
                    f"Updated committed kit quantity for {part.part_number}: {old_committed} → {part.quantity_committed}."
                )
            else:
                messages.info(request, f"Committed quantity for {part.part_number} is already {old_committed}.")

    return redirect(next_url)


class KitActionView(TemplateView):
    """
    Dedicated 'Kits Management & Pick/Adjust Kits' page where users can:
    - View all active Kits and all BoM Assemblies with their kitted counts
    - Add (+), subtract (-), set exact kit quantities, close/build kits, or delete/uncommit kits
    - View and directly adjust, add, subtract, or clear every individual kitted/committed component part
    """
    template_name = 'core/kit_action.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        boms = list(BOM.objects.prefetch_related('items__part', 'items__part__location').order_by('name'))
        active_kits_count = 0
        total_kitted_sets = 0
        for bom in boms:
            _compute_bom_kit_metrics(bom)
            if bom.kitted_sets > 0:
                active_kits_count += 1
                total_kitted_sets += bom.kitted_sets

        committed_parts = list(
            Part.objects.filter(quantity_committed__gt=0)
            .select_related('category', 'location', 'company')
            .prefetch_related('bom_items__bom')
            .order_by('part_number')
        )
        total_committed_units = sum((p.quantity_committed or 0) for p in committed_parts)

        ctx['boms'] = boms
        ctx['active_kits'] = [b for b in boms if b.kitted_sets > 0 or b.total_committed_parts > 0]
        ctx['active_kits_count'] = active_kits_count
        ctx['total_kitted_sets'] = total_kitted_sets
        ctx['total_built_assemblies'] = sum((b.quantity_on_hand or 0) for b in boms)
        ctx['next_assembly_number'] = BOM.generate_next_assembly_number()
        ctx['committed_parts'] = committed_parts
        ctx['committed_parts_count'] = len(committed_parts)
        ctx['total_committed_units'] = total_committed_units
        ctx['all_parts'] = Part.objects.select_related('category', 'location').order_by('part_number')

        selected_id = self.request.GET.get('bom')
        if selected_id and selected_id.isdigit():
            ctx['selected_bom'] = next((b for b in boms if b.pk == int(selected_id)), None)
        elif boms:
            ctx['selected_bom'] = boms[0]
        else:
            ctx['selected_bom'] = None
        return ctx

    def post(self, request, *args, **kwargs):
        action = (request.POST.get('action') or '').strip()
        if action == 'adjust_part':
            part_id = request.POST.get('part_id')
            if part_id and str(part_id).isdigit():
                return part_adjust_committed_action(request, pk=int(part_id))
            messages.error(request, "Please select a valid component part to adjust.")
            return redirect('kit_action')

        if action == 'adjust_bom':
            bom_id = request.POST.get('bom')
            if bom_id and str(bom_id).isdigit():
                return bom_adjust_kit_action(request, pk=int(bom_id))
            messages.error(request, "Please select a valid Bill of Materials (BoM) to adjust.")
            return redirect('kit_action')

        bom_id = request.POST.get('bom')
        if not bom_id or not str(bom_id).isdigit():
            messages.error(request, "Please select a valid Bill of Materials (BoM) to kit.")
            return redirect('kit_action')
        if request.POST.get('close_kit') == '1':
            return bom_close_kit_action(request, pk=int(bom_id))
        return bom_kit_action(request, pk=int(bom_id))


class BuildActionView(TemplateView):
    """
    Dedicated 'Build Assembly' action page where users select a BoM Assembly, specify build
    quantity, and deduct all required parts from on-hand (and committed kit) inventory.
    """
    template_name = 'core/build_action.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        boms = list(BOM.objects.prefetch_related('items__part', 'items__part__location').order_by('name'))
        for bom in boms:
            items = list(bom.items.all())
            if items:
                bom.max_builds = min(
                    max(0, i.part.quantity_on_hand or 0) // max(1, i.quantity)
                    for i in items
                )
                bom.kitted_sets = min(
                    (i.part.quantity_committed or 0) // max(1, i.quantity)
                    for i in items
                )
            else:
                bom.max_builds = 0
                bom.kitted_sets = 0
        ctx['boms'] = boms
        ctx['total_built_assemblies'] = sum((b.quantity_on_hand or 0) for b in boms)
        ctx['next_assembly_number'] = BOM.generate_next_assembly_number()
        selected_id = self.request.GET.get('bom')
        if selected_id and selected_id.isdigit():
            ctx['selected_bom'] = next((b for b in boms if b.pk == int(selected_id)), None)
        elif boms:
            ctx['selected_bom'] = boms[0]
        else:
            ctx['selected_bom'] = None
        return ctx

    def post(self, request, *args, **kwargs):
        bom_id = request.POST.get('bom')
        if not bom_id or not str(bom_id).isdigit():
            messages.error(request, "Please select a valid Bill of Materials (BoM) to build.")
            return redirect('build_action')
        return bom_build_action(request, pk=int(bom_id))


# ==============================================================================
# TAKE INVENTORY SHEET (INTERACTIVE ADJUSTMENTS)
# ==============================================================================

class TakeInventoryView(TemplateView):
    """
    Interactive Take Inventory Sheet that shows what should be there (System On-Hand,
    Committed, Available, On-Order, Storage Location) grouped by Category and allows
    auditors to enter actual physical counts and commit inventory adjustments.
    """
    template_name = 'core/take_inventory.html'

    def get(self, request, *args, **kwargs):
        if request.GET.get('clear') or request.GET.get('reset'):
            request.session.pop('take_inventory_filters', None)
            return redirect('take_inventory')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = resolve_persistent_filters(self.request, 'take_inventory_filters', COUNT_SHEET_FILTER_KEYS)
        qs = get_count_sheet_queryset(self.request, session_key='take_inventory_filters')

        category_map = {}
        for part in qs:
            cat = part.category
            cat_id = cat.pk if cat else 'none'
            if cat_id not in category_map:
                category_map[cat_id] = {
                    'category': cat,
                    'category_name': cat.name if cat else 'Uncategorized / General Components',
                    'prefix': cat.get_prefix() if cat else '',
                    'parts': [],
                    'total_on_hand': 0,
                    'total_items': 0,
                }
            category_map[cat_id]['parts'].append(part)
            category_map[cat_id]['total_on_hand'] += (part.quantity_on_hand or 0)
            category_map[cat_id]['total_items'] += 1

        groups = list(category_map.values())
        groups.sort(key=lambda g: (len(g['prefix']), g['prefix'], g['category_name']))
        ctx['groups'] = groups
        ctx['total_parts'] = qs.count()
        ctx['total_categories'] = len(groups)
        ctx['total_on_hand'] = sum(g['total_on_hand'] for g in groups)
        ctx['categories'] = Category.objects.all().annotate(prefix_len=Length('prefix')).order_by('prefix_len', 'prefix', 'name')
        ctx['locations'] = Location.objects.all().order_by('name')
        ctx['current_category'] = filters['category']
        ctx['current_location'] = filters['location']
        ctx['current_stock'] = filters['stock']
        ctx['current_q'] = filters['q']
        ctx['generated_at'] = timezone.now()
        return ctx

    def post(self, request, *args, **kwargs):
        adjusted_parts = 0
        net_delta = 0

        # Support both array inputs (part_id[] / actual_count[]) and named inputs (actual_count_<pk>)
        part_ids = request.POST.getlist('part_id[]') or request.POST.getlist('part_id')
        actual_counts = request.POST.getlist('actual_count[]') or request.POST.getlist('actual_count')

        updates_map = {}
        if part_ids and actual_counts:
            for i, pid in enumerate(part_ids):
                if str(pid).isdigit() and i < len(actual_counts):
                    raw_val = str(actual_counts[i]).strip()
                    if raw_val != '':
                        try:
                            updates_map[int(pid)] = int(raw_val)
                        except (ValueError, TypeError):
                            pass

        for key, val in request.POST.items():
            if key.startswith('actual_count_'):
                pid_str = key.replace('actual_count_', '').strip()
                raw_val = str(val).strip()
                if pid_str.isdigit() and raw_val != '':
                    try:
                        updates_map[int(pid_str)] = int(raw_val)
                    except (ValueError, TypeError):
                        pass

        parts_to_adjust = []
        missing_reasons = []

        if updates_map:
            parts = Part.objects.filter(pk__in=updates_map.keys())
            for part in parts:
                new_on_hand = max(0, updates_map[part.pk])
                old_on_hand = part.quantity_on_hand or 0
                if new_on_hand != old_on_hand:
                    delta = new_on_hand - old_on_hand
                    reason = (
                        request.POST.get(f'reason_{part.pk}')
                        or request.POST.get(f'adjustment_reason_{part.pk}')
                        or request.POST.get('adjustment_reason')
                        or ''
                    ).strip()
                    if not reason:
                        missing_reasons.append(f"{part.part_number} ({old_on_hand} → {new_on_hand})")
                    else:
                        parts_to_adjust.append((part, old_on_hand, new_on_hand, delta, reason))

        if missing_reasons:
            messages.error(
                request,
                f"A reason must be included for every inventory adjustment! Missing reason for: {', '.join(missing_reasons)}"
            )
            return redirect('take_inventory')

        if parts_to_adjust:
            with transaction.atomic():
                for part, old_on_hand, new_on_hand, delta, reason in parts_to_adjust:
                    part.quantity_on_hand = new_on_hand
                    part.quantity_availible = max(0, new_on_hand - (part.quantity_committed or 0))
                    part.save(update_fields=['quantity_on_hand', 'quantity_availible', 'updated_at'])
                    if hasattr(part, 'assembly_bom') and part.assembly_bom:
                        part.assembly_bom.quantity_on_hand = new_on_hand
                        part.assembly_bom.save(update_fields=['quantity_on_hand', 'updated_at'])

                    InventoryAdjustment.objects.create(
                        part=part,
                        old_quantity=old_on_hand,
                        new_quantity=new_on_hand,
                        delta=delta,
                        reason=reason,
                        user=request.user if request.user.is_authenticated else None,
                    )
                    adjusted_parts += 1
                    net_delta += delta

        if adjusted_parts > 0:
            sign = f"+{net_delta}" if net_delta > 0 else str(net_delta)
            messages.success(
                request,
                f"Inventory adjustment applied! Updated on-hand quantities for {adjusted_parts} part(s) (Net change: {sign} units)."
            )
        else:
            messages.info(request, "No inventory discrepancies or changes were detected to adjust.")

        return redirect('take_inventory')


# ==============================================================================
# 1000-SERIES ASSEMBLY STOCK ADJUSTMENT & SALES / INVOICES VIEWS
# ==============================================================================

def bom_adjust_assembly_stock(request, pk):
    """
    POST action to directly adjust a 1000-series Assembly's `quantity_on_hand`,
    `assembly_number`, or `sale_price` (supports mode='add', 'subtract', 'set').
    """
    if request.method != 'POST':
        return redirect('bom_detail', pk=pk)

    bom = get_object_or_404(BOM, pk=pk)
    next_url = request.POST.get('next') or reverse('bom_detail', kwargs={'pk': bom.pk})
    mode = (request.POST.get('mode') or 'set').strip().lower()
    old_on_hand = bom.quantity_on_hand or 0

    try:
        qty = int(request.POST.get('quantity', 1))
    except (ValueError, TypeError):
        qty = 1

    try:
        target_on_hand = int(request.POST.get('target_on_hand', old_on_hand))
        if target_on_hand < 0:
            target_on_hand = 0
    except (ValueError, TypeError):
        target_on_hand = old_on_hand

    update_fields = ['updated_at']

    raw_asm_num = request.POST.get('assembly_number')
    if raw_asm_num is not None and str(raw_asm_num).strip():
        desired_asm_num = str(raw_asm_num).strip()
        if desired_asm_num != bom.assembly_number:
            if BOM.objects.filter(assembly_number=desired_asm_num).exclude(pk=bom.pk).exists():
                messages.error(request, f"Assembly number '{desired_asm_num}' is already assigned to another assembly.")
                return redirect(next_url)
            bom.assembly_number = desired_asm_num
            update_fields.append('assembly_number')
    elif not bom.assembly_number:
        bom.assembly_number = BOM.generate_next_assembly_number(exclude_pk=bom.pk)
        update_fields.append('assembly_number')

    raw_sale_price = request.POST.get('sale_price')
    if raw_sale_price is not None:
        raw_sp_str = str(raw_sale_price).strip()
        if raw_sp_str == '':
            bom.sale_price = None
            update_fields.append('sale_price')
        else:
            try:
                bom.sale_price = Decimal(raw_sp_str)
                update_fields.append('sale_price')
            except (InvalidOperation, ValueError):
                pass

    if mode == 'add':
        qty = max(1, qty)
        bom.quantity_on_hand = old_on_hand + qty
        update_fields.append('quantity_on_hand')
        bom.save(update_fields=update_fields)
        messages.success(
            request,
            f"Added {qty} built assembly unit(s) to {bom.assembly_number} — '{bom.name}' (On-Hand: {old_on_hand} → {bom.quantity_on_hand})."
        )
    elif mode == 'subtract':
        qty = max(1, qty)
        bom.quantity_on_hand = max(0, old_on_hand - qty)
        update_fields.append('quantity_on_hand')
        bom.save(update_fields=update_fields)
        messages.success(
            request,
            f"Removed {min(old_on_hand, qty)} built assembly unit(s) from {bom.assembly_number} — '{bom.name}' (On-Hand: {old_on_hand} → {bom.quantity_on_hand})."
        )
    else:
        if 'target_on_hand' in request.POST:
            bom.quantity_on_hand = target_on_hand
            update_fields.append('quantity_on_hand')
        bom.save(update_fields=update_fields)
        messages.success(
            request,
            f"Updated Assembly {bom.assembly_number} — '{bom.name}' (Built On-Hand: {bom.quantity_on_hand})."
        )

    try:
        part = bom.sync_part()
        if part and bom.quantity_on_hand != old_on_hand:
            delta = bom.quantity_on_hand - old_on_hand
            reason = (request.POST.get('reason') or f"Built assembly {mode} adjustment for {bom.assembly_number}").strip()
            InventoryAdjustment.objects.create(
                part=part,
                old_quantity=old_on_hand,
                new_quantity=bom.quantity_on_hand,
                delta=delta,
                reason=reason,
                user=request.user if request.user.is_authenticated else None,
            )
    except Exception:
        pass

    return redirect(next_url)


SALE_FILTER_KEYS = ['q', 'status', 'payment_method']


def generate_and_save_invoice_pdf(sale, request=None):
    """
    Renders and saves the WeasyPrint PDF for an AssemblySale invoice into MEDIA_ROOT/invoices/.
    Returns (rel_path, pdf_bytes).
    """
    import weasyprint

    context = {
        'sale': sale,
        'items': list(sale.items.all()),
        'company_name': AssemblySale.DEFAULT_COMPANY_NAME,
        'company_address': AssemblySale.DEFAULT_COMPANY_ADDRESS,
        'company_phone': AssemblySale.DEFAULT_COMPANY_PHONE,
        'company_email': AssemblySale.DEFAULT_COMPANY_EMAIL,
        'generated_at': timezone.now(),
        'request': request,
    }

    base_url = request.build_absolute_uri('/') if request else f"file://{settings.BASE_DIR}/"
    html_content = render_to_string('core/invoice_pdf.html', context)
    pdf_bytes = weasyprint.HTML(
        string=html_content,
        base_url=base_url
    ).write_pdf()

    invoices_dir = Path(settings.MEDIA_ROOT) / 'invoices'
    invoices_dir.mkdir(parents=True, exist_ok=True)
    filename = f"Invoice_{sale.invoice_number}.pdf"
    file_path = invoices_dir / filename
    with open(file_path, 'wb') as f:
        f.write(pdf_bytes)

    rel_path = f"invoices/{filename}"
    if sale.pdf_file.name != rel_path:
        sale.pdf_file.name = rel_path
        sale.save(update_fields=['pdf_file', 'updated_at'])

    return rel_path, pdf_bytes


class AssemblySaleListView(ListView):
    """
    Lists all 1000-series built Assemblies available for sale AND the history of all
    Sales / Invoices with sequential invoice numbers and status filters (Unpaid vs Paid).
    """
    model = AssemblySale
    template_name = 'core/sale_list.html'
    context_object_name = 'sales'
    paginate_by = 25

    def get(self, request, *args, **kwargs):
        if request.GET.get('clear') or request.GET.get('reset'):
            request.session.pop('sale_list_filters', None)
            return redirect('sale_list')
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        filters = resolve_persistent_filters(self.request, 'sale_list_filters', SALE_FILTER_KEYS)
        qs = AssemblySale.objects.prefetch_related('items', 'items__bom').all()
        q = filters['q']
        if q:
            qs = qs.filter(
                Q(invoice_number__icontains=q) |
                Q(customer_name__icontains=q) |
                Q(customer_email__icontains=q) |
                Q(customer_phone__icontains=q) |
                Q(items__item_number__icontains=q) |
                Q(items__description__icontains=q)
            ).distinct()
        status_filter = filters['status']
        if status_filter:
            qs = qs.filter(status=status_filter)
        payment_method = filters['payment_method']
        if payment_method:
            qs = qs.filter(payment_method=payment_method)
        return qs.order_by('-invoice_date', '-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = resolve_persistent_filters(self.request, 'sale_list_filters', SALE_FILTER_KEYS)
        boms = list(BOM.objects.prefetch_related('items__part').order_by('assembly_number', 'name'))
        for bom in boms:
            _compute_bom_kit_metrics(bom)
        ctx['assemblies'] = boms
        ctx['built_assemblies_count'] = sum(1 for b in boms if (b.quantity_on_hand or 0) > 0)
        ctx['total_built_units'] = sum((b.quantity_on_hand or 0) for b in boms)

        all_sales = list(AssemblySale.objects.prefetch_related('items').all())
        ctx['total_invoices_count'] = len(all_sales)
        ctx['unpaid_invoices_count'] = sum(1 for s in all_sales if s.status == 'UNPAID')
        ctx['paid_invoices_count'] = sum(1 for s in all_sales if s.status == 'PAID')
        ctx['total_revenue'] = sum((s.total_amount for s in all_sales if s.status == 'PAID'), Decimal('0.00'))
        ctx['total_invoiced_amount'] = sum((s.total_amount for s in all_sales), Decimal('0.00'))
        ctx['total_units_sold'] = sum(s.total_quantity for s in all_sales if s.status == 'PAID')

        ctx['current_q'] = filters['q']
        ctx['current_status'] = filters['status']
        ctx['current_payment_method'] = filters['payment_method']
        ctx['status_choices'] = AssemblySale.STATUS_CHOICES
        ctx['payment_method_choices'] = AssemblySale.PAYMENT_METHOD_CHOICES
        ctx['next_invoice_number'] = AssemblySale.generate_next_invoice_number()
        return ctx


class AssemblySaleCreateView(CreateView):
    """
    Page to create an invoice for 1000-series assemblies (built or not built yet).
    If status='UNPAID', the invoice is created without deducting assembly inventory yet.
    When the assembly is built and payment received, closing the invoice marks it PAID,
    stamps it with a big PAID stamp, and deducts the assembly from stock.
    Saves the print-ready PDF to media/invoices/.
    """
    model = AssemblySale
    form_class = AssemblySaleForm
    template_name = 'core/sale_form.html'

    def get_initial(self):
        initial = super().get_initial()
        initial['invoice_number'] = AssemblySale.generate_next_invoice_number()
        initial['invoice_date'] = timezone.now().date()
        initial['status'] = 'UNPAID'
        initial['payment_date'] = None
        initial['customer_name'] = AssemblySale.DEFAULT_COMPANY_NAME
        initial['customer_address'] = AssemblySale.DEFAULT_COMPANY_ADDRESS
        initial['customer_phone'] = AssemblySale.DEFAULT_COMPANY_PHONE
        initial['customer_email'] = AssemblySale.DEFAULT_COMPANY_EMAIL
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        boms = list(BOM.objects.prefetch_related('items__part').order_by('assembly_number', 'name'))
        ctx['assemblies'] = boms
        ctx['next_invoice_number'] = AssemblySale.generate_next_invoice_number()
        preselected_bom_id = self.request.GET.get('bom')
        if preselected_bom_id and preselected_bom_id.isdigit():
            ctx['preselected_bom'] = next((b for b in boms if b.pk == int(preselected_bom_id)), None)
        else:
            ctx['preselected_bom'] = None
        return ctx

    def form_valid(self, form):
        bom_ids = self.request.POST.getlist('item_bom[]') or self.request.POST.getlist('item_bom')
        item_numbers = self.request.POST.getlist('item_number[]') or self.request.POST.getlist('item_number')
        descriptions = self.request.POST.getlist('item_description[]') or self.request.POST.getlist('item_description')
        quantities = self.request.POST.getlist('item_quantity[]') or self.request.POST.getlist('item_quantity')
        unit_prices = self.request.POST.getlist('item_unit_price[]') or self.request.POST.getlist('item_unit_price')

        row_count = max(len(bom_ids), len(item_numbers), len(descriptions))
        parsed_rows = []
        for i in range(row_count):
            b_id_str = str(bom_ids[i]).strip() if i < len(bom_ids) and bom_ids[i] else ''
            i_num = str(item_numbers[i]).strip() if i < len(item_numbers) and item_numbers[i] else ''
            i_desc = str(descriptions[i]).strip() if i < len(descriptions) and descriptions[i] else ''

            bom_obj = None
            if b_id_str.isdigit():
                bom_obj = BOM.objects.filter(pk=int(b_id_str)).first()

            if not bom_obj and not i_num and not i_desc:
                continue

            try:
                qty = int(quantities[i]) if i < len(quantities) and str(quantities[i]).strip() else 1
                if qty <= 0:
                    continue
            except (ValueError, TypeError):
                qty = 1

            u_price = None
            if i < len(unit_prices) and str(unit_prices[i]).strip():
                try:
                    u_price = Decimal(str(unit_prices[i]).strip())
                except (InvalidOperation, ValueError):
                    u_price = None

            if bom_obj:
                if not i_num:
                    i_num = bom_obj.assembly_number or BOM.generate_next_assembly_number(exclude_pk=bom_obj.pk)
                if not i_desc:
                    i_desc = f"{bom_obj.name}" + (f" — {bom_obj.description}" if bom_obj.description else "")
                if u_price is None:
                    u_price = bom_obj.effective_sale_price

            if u_price is None:
                u_price = Decimal('0.00')

            parsed_rows.append({
                'bom': bom_obj,
                'item_number': i_num or '1000-001',
                'description': i_desc or 'Built Assembly',
                'quantity': qty,
                'unit_price': u_price,
            })

        if not parsed_rows:
            messages.error(self.request, "Please select at least one Assembly or enter an item to invoice.")
            return self.form_invalid(form)

        status_val = form.cleaned_data.get('status') or self.request.POST.get('status') or 'UNPAID'
        is_paid = (status_val == 'PAID')

        with transaction.atomic():
            sale = form.save(commit=False)
            sale.status = status_val
            sale.stock_deducted = is_paid
            if is_paid and not sale.payment_date:
                sale.payment_date = timezone.now().date()
            elif not is_paid and not form.cleaned_data.get('payment_date'):
                sale.payment_date = None
            sale.save()
            self.object = sale

            shortages = []
            total_units = 0
            for row in parsed_rows:
                bom_obj = row['bom']
                qty = row['quantity']
                AssemblySaleItem.objects.create(
                    sale=sale,
                    bom=bom_obj,
                    item_number=row['item_number'],
                    description=row['description'],
                    quantity=qty,
                    unit_price=row['unit_price'],
                )
                total_units += qty

                if bom_obj:
                    bom_update_fields = ['updated_at']
                    if not bom_obj.assembly_number and row['item_number']:
                        bom_obj.assembly_number = row['item_number']
                        bom_update_fields.append('assembly_number')
                    if bom_obj.sale_price is None and row['unit_price'] > 0:
                        bom_obj.sale_price = row['unit_price']
                        bom_update_fields.append('sale_price')

                    # If marked as PAID right away, deduct from built assembly inventory
                    if is_paid:
                        old_on_hand = bom_obj.quantity_on_hand or 0
                        if old_on_hand < qty:
                            shortages.append(f"{bom_obj.assembly_number} ({bom_obj.name}: invoiced {qty}, had {old_on_hand} built)")
                        bom_obj.quantity_on_hand = max(0, old_on_hand - qty)
                        bom_update_fields.append('quantity_on_hand')

                    bom_obj.save(update_fields=bom_update_fields)
                    try:
                        bom_obj.sync_part()
                    except Exception:
                        pass

            # Generate and save the PDF file to disk in media/invoices/
            generate_and_save_invoice_pdf(sale, request=self.request)

            if is_paid:
                msg = (
                    f"Invoice {sale.invoice_number} created and marked PAID! "
                    f"Deducted {total_units} assembly unit(s) from built stock. PDF invoice saved to media/invoices/."
                )
                if shortages:
                    messages.warning(self.request, f"{msg} Note: Low built stock for {', '.join(shortages)}.")
                else:
                    messages.success(self.request, msg)
            else:
                messages.success(
                    self.request,
                    f"Invoice {sale.invoice_number} created (Status: Unpaid / Assembly not built yet)! "
                    f"Assemblies have not been deducted from built stock yet. PDF invoice saved to media/invoices/."
                )

        return redirect('sale_detail', pk=sale.pk)


class AssemblySaleDetailView(DetailView):
    """
    Displays the printable / PDF-ready Invoice for an `AssemblySale` with PAID STAMP overlay
    when paid, action button to Mark Paid & Close, and action to email the invoice PDF.
    """
    model = AssemblySale
    template_name = 'core/sale_detail.html'
    context_object_name = 'sale'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        items = list(self.object.items.select_related('bom').all())
        ctx['items'] = items
        ctx['company_name'] = AssemblySale.DEFAULT_COMPANY_NAME
        ctx['company_address'] = AssemblySale.DEFAULT_COMPANY_ADDRESS
        ctx['company_phone'] = AssemblySale.DEFAULT_COMPANY_PHONE
        ctx['company_email'] = AssemblySale.DEFAULT_COMPANY_EMAIL
        ctx['can_fulfill'] = all(
            (item.bom.quantity_on_hand or 0) >= item.quantity
            for item in items if item.bom
        )
        return ctx


class AssemblySaleUpdateView(UpdateView):
    """
    Allows editing invoice header details (customer info, payment method, payment date, notes, status)
    and line items on an existing `AssemblySale`, synchronizing built stock deduction and PDF.
    """
    model = AssemblySale
    form_class = AssemblySaleForm
    template_name = 'core/sale_form.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['assemblies'] = list(BOM.objects.prefetch_related('items__part').order_by('assembly_number', 'name'))
        ctx['existing_items'] = list(self.object.items.select_related('bom').all())
        return ctx

    def form_valid(self, form):
        with transaction.atomic():
            old_sale = AssemblySale.objects.get(pk=self.object.pk)
            old_stock_deducted = old_sale.stock_deducted
            sale = form.save()
            self.object = sale
            new_status = sale.status
            should_deduct = (new_status == 'PAID')

            # If line items were submitted in the update form, sync them
            if 'item_number[]' in self.request.POST or 'item_bom[]' in self.request.POST:
                bom_ids = self.request.POST.getlist('item_bom[]') or self.request.POST.getlist('item_bom')
                item_numbers = self.request.POST.getlist('item_number[]') or self.request.POST.getlist('item_number')
                descriptions = self.request.POST.getlist('item_description[]') or self.request.POST.getlist('item_description')
                quantities = self.request.POST.getlist('item_quantity[]') or self.request.POST.getlist('item_quantity')
                unit_prices = self.request.POST.getlist('item_unit_price[]') or self.request.POST.getlist('item_unit_price')

                row_count = max(len(bom_ids), len(item_numbers), len(descriptions))
                new_rows = []
                for i in range(row_count):
                    b_id_str = str(bom_ids[i]).strip() if i < len(bom_ids) and bom_ids[i] else ''
                    i_num = str(item_numbers[i]).strip() if i < len(item_numbers) and item_numbers[i] else ''
                    i_desc = str(descriptions[i]).strip() if i < len(descriptions) and descriptions[i] else ''
                    bom_obj = BOM.objects.filter(pk=int(b_id_str)).first() if b_id_str.isdigit() else None
                    if not bom_obj and not i_num and not i_desc:
                        continue
                    try:
                        qty = max(1, int(quantities[i])) if i < len(quantities) and str(quantities[i]).strip() else 1
                    except (ValueError, TypeError):
                        qty = 1
                    try:
                        u_price = Decimal(str(unit_prices[i]).strip()) if i < len(unit_prices) and str(unit_prices[i]).strip() else Decimal('0.00')
                    except (InvalidOperation, ValueError):
                        u_price = Decimal('0.00')
                    new_rows.append({
                        'bom': bom_obj,
                        'item_number': i_num or (bom_obj.assembly_number if bom_obj else '1000-001'),
                        'description': i_desc or (bom_obj.name if bom_obj else 'Assembly'),
                        'quantity': qty,
                        'unit_price': u_price,
                    })

                if new_rows:
                    # If stock was previously deducted, restore old quantities first
                    if old_stock_deducted:
                        for old_item in sale.items.select_related('bom').all():
                            if old_item.bom:
                                old_item.bom.quantity_on_hand = (old_item.bom.quantity_on_hand or 0) + old_item.quantity
                                old_item.bom.save(update_fields=['quantity_on_hand', 'updated_at'])

                    sale.items.all().delete()
                    for row in new_rows:
                        AssemblySaleItem.objects.create(
                            sale=sale,
                            bom=row['bom'],
                            item_number=row['item_number'],
                            description=row['description'],
                            quantity=row['quantity'],
                            unit_price=row['unit_price'],
                        )
                        if row['bom'] and should_deduct:
                            row['bom'].quantity_on_hand = max(0, (row['bom'].quantity_on_hand or 0) - row['quantity'])
                            row['bom'].save(update_fields=['quantity_on_hand', 'updated_at'])

                    sale.stock_deducted = should_deduct
            else:
                # Line items unchanged, check status transition
                if should_deduct and not old_stock_deducted:
                    for item in sale.items.select_related('bom').all():
                        if item.bom:
                            item.bom.quantity_on_hand = max(0, (item.bom.quantity_on_hand or 0) - item.quantity)
                            item.bom.save(update_fields=['quantity_on_hand', 'updated_at'])
                    sale.stock_deducted = True
                elif not should_deduct and old_stock_deducted:
                    for item in sale.items.select_related('bom').all():
                        if item.bom:
                            item.bom.quantity_on_hand = (item.bom.quantity_on_hand or 0) + item.quantity
                            item.bom.save(update_fields=['quantity_on_hand', 'updated_at'])
                    sale.stock_deducted = False

            if should_deduct and not sale.payment_date:
                sale.payment_date = timezone.now().date()
            sale.save(update_fields=['status', 'stock_deducted', 'payment_date', 'updated_at'])

            # Synchronize 1000-series inventory parts
            for item in sale.items.select_related('bom').all():
                if item.bom:
                    try:
                        item.bom.sync_part()
                    except Exception:
                        pass

            # Regenerate saved PDF
            generate_and_save_invoice_pdf(sale, request=self.request)

            messages.success(self.request, f"Invoice {sale.invoice_number} updated successfully and PDF refreshed!")
            return redirect('sale_detail', pk=sale.pk)


def sale_mark_paid(request, pk):
    """
    POST action to close an invoice and mark it as PAID:
    - Deducts the assemblies from built inventory (bom.quantity_on_hand)
    - Sets `stock_deducted = True` and `status = 'PAID'`
    - Sets `payment_date = today` if not set
    - Regenerates and saves the updated PDF with the big "PAID" stamp
    """
    if request.method != 'POST':
        return redirect('sale_detail', pk=pk)

    sale = get_object_or_404(AssemblySale.objects.prefetch_related('items', 'items__bom'), pk=pk)
    shortages = []

    with transaction.atomic():
        if not sale.stock_deducted:
            for item in sale.items.select_related('bom').all():
                if item.bom:
                    old_on_hand = item.bom.quantity_on_hand or 0
                    if old_on_hand < item.quantity:
                        shortages.append(f"{item.bom.assembly_number} (needed {item.quantity}, had {old_on_hand} built)")
                    item.bom.quantity_on_hand = max(0, old_on_hand - item.quantity)
                    item.bom.save(update_fields=['quantity_on_hand', 'updated_at'])
                    try:
                        item.bom.sync_part()
                    except Exception:
                        pass
            sale.stock_deducted = True

        sale.status = 'PAID'
        if not sale.payment_date:
            sale.payment_date = timezone.now().date()
        sale.save(update_fields=['status', 'stock_deducted', 'payment_date', 'updated_at'])

        # Regenerate saved PDF with the big PAID stamp
        generate_and_save_invoice_pdf(sale, request=request)

    msg = f"Invoice {sale.invoice_number} is now marked as PAID & Closed! Assemblies were deducted from built stock, and the stamped PDF was saved to disk."
    if shortages:
        messages.warning(request, f"{msg} Note: Low built stock for {', '.join(shortages)}.")
    else:
        messages.success(request, msg)

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('sale_detail', pk=sale.pk)


def sale_send_email(request, pk):
    """
    POST action to send the invoice PDF via email to the customer.
    Uses default from email michael@granarywatch.com.
    """
    if request.method != 'POST':
        return redirect('sale_detail', pk=pk)

    sale = get_object_or_404(AssemblySale.objects.prefetch_related('items', 'items__bom'), pk=pk)
    recipient = (request.POST.get('recipient') or sale.customer_email or AssemblySale.DEFAULT_COMPANY_EMAIL).strip()
    subject = (request.POST.get('subject') or f"Invoice {sale.invoice_number} from {AssemblySale.DEFAULT_COMPANY_NAME}").strip()
    custom_message = (request.POST.get('message') or '').strip()

    if not custom_message:
        status_text = "PAID in full" if sale.is_paid else f"due ({sale.get_payment_method_display})"
        custom_message = (
            f"Dear {sale.customer_name},\n\n"
            f"Please find attached your invoice {sale.invoice_number} for ${sale.total_amount:.2f} ({status_text}).\n\n"
            f"If you have any questions, please reach out to us at {AssemblySale.DEFAULT_COMPANY_EMAIL} or {AssemblySale.DEFAULT_COMPANY_PHONE}.\n\n"
            f"Thank you for your business!\n\n"
            f"{AssemblySale.DEFAULT_COMPANY_NAME}\n"
            f"{AssemblySale.DEFAULT_COMPANY_ADDRESS}\n"
        )

    # Ensure saved PDF is fresh
    rel_path, pdf_bytes = generate_and_save_invoice_pdf(sale, request=request)

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'michael@granarywatch.com')
    try:
        email = EmailMessage(
            subject=subject,
            body=custom_message,
            from_email=from_email,
            to=[recipient],
        )

        pdf_filename = f"Invoice_{sale.invoice_number}.pdf"
        if pdf_bytes:
            email.attach(pdf_filename, pdf_bytes, 'application/pdf')
        elif sale.pdf_file and os.path.exists(sale.pdf_file.path):
            email.attach_file(sale.pdf_file.path)

        email.send(fail_silently=False)
        messages.success(
            request,
            f"Invoice {sale.invoice_number} was successfully emailed to {recipient} with the attached PDF!"
        )
    except Exception as exc:
        messages.warning(
            request,
            f"Email attempt to {recipient} failed with: {exc}. "
            f"(Once the email server for {from_email} is online, emails will be delivered automatically)."
        )

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('sale_detail', pk=sale.pk)


class AssemblySaleDeleteView(DeleteView):
    """
    Deletes an `AssemblySale` invoice and restores the sold assembly quantities back to `BOM.quantity_on_hand`
    if they were deducted.
    """
    model = AssemblySale
    template_name = 'core/confirm_delete.html'
    success_url = reverse_lazy('sale_list')

    def form_valid(self, form):
        sale = self.get_object()
        with transaction.atomic():
            if sale.stock_deducted:
                for item in sale.items.select_related('bom').all():
                    if item.bom:
                        item.bom.quantity_on_hand = (item.bom.quantity_on_hand or 0) + item.quantity
                        item.bom.save(update_fields=['quantity_on_hand', 'updated_at'])
                        try:
                            item.bom.sync_part()
                        except Exception:
                            pass

            # Remove saved PDF file if it exists
            if sale.pdf_file:
                try:
                    if os.path.exists(sale.pdf_file.path):
                        os.remove(sale.pdf_file.path)
                except Exception:
                    pass

            messages.success(
                self.request,
                f"Invoice {sale.invoice_number} was deleted and finished assembly inventory was updated."
            )
            return super().form_valid(form)


def assembly_sale_pdf(request, pk):
    """
    Renders and streams a print-ready PDF invoice for `AssemblySale` using WeasyPrint.
    Also ensures the saved PDF exists on disk in media/invoices/.
    Supports `?download=1` for attachment download vs inline viewing.
    """
    sale = get_object_or_404(AssemblySale.objects.prefetch_related('items', 'items__bom'), pk=pk)
    rel_path, pdf_bytes = generate_and_save_invoice_pdf(sale, request=request)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'attachment' if request.GET.get('download') == '1' else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="Invoice_{sale.invoice_number}.pdf"'
    return response



