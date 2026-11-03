from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.db.models import Q, Count, Sum
from .models import Part, Company, Manufacturer, Category, Location, PartDocument
from .forms import PartForm, CompanyForm, ManufacturerForm, CategoryForm, LocationForm, PartDocumentForm


def home(request):
    """
    Landing / Dashboard view for Project Manager.
    """
    total_parts = Part.objects.count()
    total_companies = Company.objects.count()
    total_categories = Category.objects.count()
    total_locations = Location.objects.count()

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
        },
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
# PART CRUD VIEWS
# ==============================================================================

class PartListView(ListView):
    model = Part
    template_name = 'core/part_list.html'
    context_object_name = 'parts'
    paginate_by = 25

    def get_queryset(self):
        qs = Part.objects.select_related('company', 'manufacturer', 'category', 'location').all()
        q = self.request.GET.get('q', '').strip()
        company_id = self.request.GET.get('company')
        category_id = self.request.GET.get('category')
        location_id = self.request.GET.get('location')
        confirmed = self.request.GET.get('confirmed')

        if q:
            qs = qs.filter(
                Q(part_number__icontains=q) |
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

        return qs.order_by('-created_at')

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

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Part '{self.object}' was created successfully!")
        return response


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
        qs = Category.objects.select_related('parent').annotate(parts_count=Count('parts')).all()
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(prefix__icontains=q) | Q(description__icontains=q))
        return qs.order_by('name')

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
