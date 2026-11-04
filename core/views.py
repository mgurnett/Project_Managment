import csv
import re
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.utils import timezone
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView
from django.db import transaction
from django.db.models import Q, Count, Sum, Case, When, Value, IntegerField, F
from .models import (
    Part, Company, Manufacturer, Category, Location, PartDocument,
    BOM, BOMItem, Order, OrderItem
)
from .forms import (
    PartForm, CompanyForm, ManufacturerForm, CategoryForm, LocationForm,
    PartDocumentForm, BOMForm, BOMItemForm, OrderForm, OrderItemForm
)


def home(request):
    """
    Landing / Dashboard view for Project Manager.
    """
    total_parts = Part.objects.count()
    total_companies = Company.objects.count()
    total_categories = Category.objects.count()
    total_locations = Location.objects.count()
    total_boms = BOM.objects.count()
    total_orders = Order.objects.count()

    context = {
        'page_title': 'Dashboard Overview',
        'metrics': {
            'active_projects': 8,
            'pending_tasks': 24,
            'completed_tasks': 67,
            'team_members': 5,
            'total_parts': total_parts,
            'total_companies': total_companies,
            'total_categories': total_categories,
            'total_locations': total_locations,
            'total_boms': total_boms,
            'total_orders': total_orders,
        },
        'recent_orders': Order.objects.select_related('supplier').order_by('-order_date', '-created_at')[:4],
        'recent_boms': BOM.objects.annotate(item_count=Count('items')).order_by('-created_at')[:4],
        'recent_parts': Part.objects.select_related('company', 'category', 'location').order_by('-created_at')[:8],
        'recent_companies': Company.objects.annotate(part_count=Count('parts')).order_by('-created_at')[:5],
        'recent_projects': [
            {'name': 'Warehouse Inventory Audit', 'category': 'Supply Chain Ops', 'progress': 75, 'status': 'In Progress', 'status_class': 'success', 'due_date': 'Nov 15, 2026'},
            {'name': 'Hardware Asset Tracking', 'category': 'IT Infrastructure', 'progress': 45, 'status': 'In Progress', 'status_class': 'warning', 'due_date': 'Nov 28, 2026'},
            {'name': 'Supplier Integration API', 'category': 'External Logistics', 'progress': 90, 'status': 'Review', 'status_class': 'info', 'due_date': 'Nov 10, 2026'},
            {'name': 'Quarterly Maintenance Schedule', 'category': 'Facilities', 'progress': 20, 'status': 'Planning', 'status_class': 'secondary', 'due_date': 'Dec 05, 2026'},
        ],
        'upcoming_tasks': [
            {'title': 'Review sensory node telemetry report', 'project': 'Warehouse Audit', 'due': 'Tomorrow', 'priority': 'High', 'priority_class': 'danger'},
            {'title': 'Verify database replication status', 'project': 'IT Infrastructure', 'due': 'In 3 days', 'priority': 'Medium', 'priority_class': 'warning'},
            {'title': 'Update stock replenishment thresholds', 'project': 'Logistics', 'due': 'Nov 08', 'priority': 'Low', 'priority_class': 'info'},
            {'title': 'Sync user permissions with LDAP / DB groups', 'project': 'Security', 'due': 'Nov 12', 'priority': 'Medium', 'priority_class': 'warning'},
        ],
        'recent_activities': [
            {'user': 'Michael G.', 'action': 'updated milestone for Warehouse Audit', 'time': '15m ago', 'icon': 'bi-check2-circle', 'color': 'text-success'},
            {'user': 'System', 'action': 'completed daily database sync', 'time': '1h ago', 'icon': 'bi-database-check', 'color': 'text-primary'},
            {'user': 'Team Ops', 'action': 'assigned 3 new tasks to Inventory', 'time': '3h ago', 'icon': 'bi-list-task', 'color': 'text-warning'},
            {'user': 'Michael G.', 'action': 'logged in via local console', 'time': 'Today', 'icon': 'bi-shield-check', 'color': 'text-info'},
        ],
    }
    return render(request, 'home.html', context)


# ==============================================================================
# PART CRUD VIEWS & CSV EXPORT
# ==============================================================================

def get_parts_filtered_queryset(request):
    """
    Applies search query, supplier, category, location, and confirmed status filters to the Part queryset.
    """
    qs = Part.objects.select_related('company', 'manufacturer', 'category', 'location', 'superseded_by').all()
    q = request.GET.get('q', '').strip()
    company_id = request.GET.get('company')
    category_id = request.GET.get('category')
    location_id = request.GET.get('location')
    confirmed = request.GET.get('confirmed')

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

    return qs.order_by('part_number', '-created_at')


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
        if request.GET.get('export') == 'csv':
            return generate_parts_csv(self.get_queryset())
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_q'] = self.request.GET.get('q', '')
        ctx['current_company'] = self.request.GET.get('company', '')
        ctx['current_category'] = self.request.GET.get('category', '')
        ctx['current_location'] = self.request.GET.get('location', '')
        ctx['current_confirmed'] = self.request.GET.get('confirmed', '')
        ctx['companies'] = Company.objects.all()
        ctx['categories'] = Category.objects.all()
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
                initial.update({
                    'part_number': source.part_number,
                    'name': source.name,
                    'description': source.description,
                    'company': source.company_id,
                    'manufacturer': source.manufacturer_id,
                    'category': source.category_id,
                    'location': source.location_id,
                    'supplier_part_number': source.supplier_part_number,
                    'superseded_by': source.superseded_by_id,
                    'quantity_on_hand': source.quantity_on_hand,
                    'quantity_on_order': source.quantity_on_order,
                    'quantity_committed': source.quantity_committed,
                    'quantity_availible': source.quantity_availible,
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
    from an existing part, ready to be customized (e.g. name, part number, description).
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
        initial.update({
            'part_number': source.part_number,
            'name': source.name,
            'description': source.description,
            'company': source.company_id,
            'manufacturer': source.manufacturer_id,
            'category': source.category_id,
            'location': source.location_id,
            'supplier_part_number': source.supplier_part_number,
            'superseded_by': source.superseded_by_id,
            'quantity_on_hand': source.quantity_on_hand,
            'quantity_on_order': source.quantity_on_order,
            'quantity_committed': source.quantity_committed,
            'quantity_availible': source.quantity_availible,
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
        response = super().form_valid(form)
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

    def get_queryset(self):
        qs = Company.objects.annotate(parts_count=Count('parts')).all()
        q = self.request.GET.get('q', '').strip()
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
        ctx['current_q'] = self.request.GET.get('q', '')
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

    def get_queryset(self):
        qs = Manufacturer.objects.annotate(parts_count=Count('parts')).all()
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        return qs.order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_q'] = self.request.GET.get('q', '')
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

    def get_queryset(self):
        qs = Category.objects.select_related('parent').annotate(
            parts_count=Count('parts'),
            empty_prefix=Case(
                When(prefix='', then=Value(1)),
                When(prefix__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            )
        ).all()
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(prefix__icontains=q) | Q(description__icontains=q))
        return qs.order_by('empty_prefix', 'prefix', 'name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_q'] = self.request.GET.get('q', '')
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

    def get_queryset(self):
        qs = Location.objects.annotate(parts_count=Count('parts')).all()
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))
        return qs.order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_q'] = self.request.GET.get('q', '')
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

    def get_queryset(self):
        qs = BOM.objects.annotate(items_count=Count('items')).all()
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        return qs.order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_q'] = self.request.GET.get('q', '')
        ctx['total_count'] = self.get_queryset().count()
        return ctx


class BOMDetailView(DetailView):
    model = BOM
    template_name = 'core/bom_detail.html'
    context_object_name = 'bom'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['items'] = self.object.items.select_related('part', 'part__company').all()
        ctx['item_form'] = BOMItemForm(bom=self.object)
        return ctx


class BOMCreateView(CreateView):
    model = BOM
    form_class = BOMForm
    template_name = 'core/bom_form.html'
    success_url = reverse_lazy('bom_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"BOM Assembly '{self.object.name}' was created successfully!")
        return response


class BOMUpdateView(UpdateView):
    model = BOM
    form_class = BOMForm
    template_name = 'core/bom_form.html'
    success_url = reverse_lazy('bom_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"BOM Assembly '{self.object.name}' was updated successfully!")
        return response


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
        form.instance.bom = self.get_bom()
        response = super().form_valid(form)
        messages.success(self.request, f"Added {self.object.part.part_number} to {self.object.bom.name}!")
        return response

    def form_invalid(self, form):
        for field, errs in form.errors.items():
            for err in errs:
                messages.error(self.request, f"{err}")
        return redirect('bom_detail', pk=self.kwargs['bom_pk'])

    def get_success_url(self):
        return reverse('bom_detail', kwargs={'pk': self.kwargs['bom_pk']})


class BOMItemDeleteView(DeleteView):
    model = BOMItem
    template_name = 'core/confirm_delete.html'

    def form_valid(self, form):
        bom_pk = self.object.bom.pk
        messages.success(self.request, f"Removed {self.object.part.part_number} from {self.object.bom.name}.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('bom_detail', kwargs={'pk': self.object.bom.pk})


# ==============================================================================
# INVENTORY COUNT SHEET & AUDIT VIEWS
# ==============================================================================

def get_count_sheet_queryset(request):
    """
    Returns filtered Part queryset for the Inventory Count Sheet:
    Grouped by Category (by category prefix/name) and sorted by part_number.
    """
    qs = Part.objects.select_related('category', 'location', 'company', 'manufacturer').order_by(
        'category__prefix', 'category__name', 'part_number'
    )

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(part_number__icontains=q) |
            Q(name__icontains=q) |
            Q(description__icontains=q) |
            Q(supplier_part_number__icontains=q)
        )

    category_id = request.GET.get('category', '').strip()
    if category_id:
        if category_id == 'none':
            qs = qs.filter(category__isnull=True)
        else:
            qs = qs.filter(category_id=category_id)

    location_id = request.GET.get('location', '').strip()
    if location_id:
        if location_id == 'none':
            qs = qs.filter(location__isnull=True)
        else:
            qs = qs.filter(location_id=location_id)

    stock = request.GET.get('stock', '').strip()
    if stock == 'in_stock':
        qs = qs.filter(quantity_on_hand__gt=0)
    elif stock == 'zero_stock':
        qs = qs.filter(quantity_on_hand=0)
    elif stock == 'negative':
        qs = qs.filter(quantity_on_hand__lt=0)

    return qs


class InventoryCountSheetView(TemplateView):
    template_name = 'core/inventory_count_sheet.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = get_count_sheet_queryset(self.request)

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

        ctx['groups'] = groups
        ctx['total_parts'] = qs.count()
        ctx['total_categories'] = len(groups)
        ctx['total_on_hand'] = sum(g['total_on_hand'] for g in groups)
        ctx['categories'] = Category.objects.all().order_by('prefix', 'name')
        ctx['locations'] = Location.objects.all().order_by('name')
        ctx['current_category'] = self.request.GET.get('category', '')
        ctx['current_location'] = self.request.GET.get('location', '')
        ctx['current_stock'] = self.request.GET.get('stock', '')
        ctx['current_q'] = self.request.GET.get('q', '')
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

    def get_queryset(self):
        qs = Order.objects.select_related('supplier').annotate(
            items_count=Count('items'),
            total_ordered=Sum('items__quantity'),
            total_received=Sum('items__quantity_received')
        )
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(order_number__icontains=q) |
                Q(tracking_number__icontains=q) |
                Q(carrier__icontains=q) |
                Q(supplier__name__icontains=q) |
                Q(items__part__part_number__icontains=q) |
                Q(items__part__name__icontains=q)
            ).distinct()

        status_filter = self.request.GET.get('status', '').strip()
        if status_filter:
            qs = qs.filter(status=status_filter)

        supplier_filter = self.request.GET.get('supplier', '').strip()
        if supplier_filter.isdigit():
            qs = qs.filter(supplier_id=int(supplier_filter))

        return qs.order_by('-order_date', '-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        all_orders = Order.objects.all()
        ctx['total_orders_count'] = all_orders.count()
        ctx['active_orders_count'] = all_orders.filter(status__in=['PENDING', 'ORDERED', 'PARTIALLY_RECEIVED']).count()
        ctx['received_orders_count'] = all_orders.filter(status='RECEIVED').count()
        ctx['total_on_order_units'] = OrderItem.objects.filter(
            order__status__in=['PENDING', 'ORDERED', 'PARTIALLY_RECEIVED']
        ).aggregate(total=Sum('quantity'))['total'] or 0

        ctx['current_q'] = self.request.GET.get('q', '')
        ctx['current_status'] = self.request.GET.get('status', '')
        ctx['current_supplier'] = self.request.GET.get('supplier', '')
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
                        if part.price_per is not None:
                            part.price = (Decimal(str(part.price_per)) * Decimal(str(pkg_qty))).quantize(Decimal('0.01'))
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

                OrderItem.objects.create(
                    order=order,
                    part=part,
                    quantity=qty,
                    unit_price=u_price,
                    notes=item_notes
                )

                # Increase the part's on order number
                Part.objects.filter(pk=part.pk).update(quantity_on_order=F('quantity_on_order') + qty)
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

    def form_valid(self, form):
        with transaction.atomic():
            order = self.get_object()
            # Restore on-order quantities for remaining unreceived quantities before deleting
            for item in order.items.select_related('part').all():
                remaining = max(0, item.quantity - item.quantity_received)
                if remaining > 0 and order.status not in ['CANCELLED', 'RECEIVED']:
                    Part.objects.filter(pk=item.part.pk).update(
                        quantity_on_order=Case(
                            When(quantity_on_order__gt=remaining, then=F('quantity_on_order') - remaining),
                            default=Value(0),
                            output_field=IntegerField()
                        )
                    )
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

            item = OrderItem.objects.create(
                order=order,
                part=part,
                quantity=qty,
                unit_price=u_price,
                notes=notes,
            )
            Part.objects.filter(pk=part.pk).update(quantity_on_order=F('quantity_on_order') + item.quantity)
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

    def form_valid(self, form):
        item = self.get_object()
        order_pk = item.order.pk
        with transaction.atomic():
            remaining = max(0, item.quantity - item.quantity_received)
            if remaining > 0 and item.order.status not in ['CANCELLED', 'RECEIVED']:
                Part.objects.filter(pk=item.part.pk).update(
                    quantity_on_order=Case(
                        When(quantity_on_order__gt=remaining, then=F('quantity_on_order') - remaining),
                        default=Value(0),
                        output_field=IntegerField()
                    )
                )
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

        # Update the price in the Part model when ordered at a price and received
        part_update_fields = ['quantity_on_order', 'quantity_on_hand', 'quantity', 'updated_at']
        if received_unit_price is not None:
            part.price_per = received_unit_price
            if received_pkg_price is not None:
                part.price = received_pkg_price
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

    return redirect('order_detail', pk=order_pk)

