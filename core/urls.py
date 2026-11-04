from django.urls import path
from . import views

urlpatterns = [
    # Dashboard
    path('', views.home, name='home'),

    # Parts CRUD
    path('parts/', views.PartListView.as_view(), name='part_list'),
    path('parts/export/csv/', views.part_export_csv, name='part_export_csv'),
    path('parts/add/', views.PartCreateView.as_view(), name='part_create'),
    path('parts/<int:pk>/', views.PartDetailView.as_view(), name='part_detail'),
    path('parts/<int:pk>/duplicate/', views.PartDuplicateView.as_view(), name='part_duplicate'),
    path('parts/<int:pk>/edit/', views.PartUpdateView.as_view(), name='part_update'),
    path('parts/<int:pk>/delete/', views.PartDeleteView.as_view(), name='part_delete'),

    # Companies / Suppliers CRUD
    path('companies/', views.CompanyListView.as_view(), name='company_list'),
    path('companies/add/', views.CompanyCreateView.as_view(), name='company_create'),
    path('companies/<int:pk>/', views.CompanyDetailView.as_view(), name='company_detail'),
    path('companies/<int:pk>/edit/', views.CompanyUpdateView.as_view(), name='company_update'),
    path('companies/<int:pk>/delete/', views.CompanyDeleteView.as_view(), name='company_delete'),

    # Manufacturers CRUD
    path('manufacturers/', views.ManufacturerListView.as_view(), name='manufacturer_list'),
    path('manufacturers/add/', views.ManufacturerCreateView.as_view(), name='manufacturer_create'),
    path('manufacturers/<int:pk>/', views.ManufacturerDetailView.as_view(), name='manufacturer_detail'),
    path('manufacturers/<int:pk>/edit/', views.ManufacturerUpdateView.as_view(), name='manufacturer_update'),
    path('manufacturers/<int:pk>/delete/', views.ManufacturerDeleteView.as_view(), name='manufacturer_delete'),

    # Categories CRUD
    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/add/', views.CategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/', views.CategoryDetailView.as_view(), name='category_detail'),
    path('categories/<int:pk>/edit/', views.CategoryUpdateView.as_view(), name='category_update'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category_delete'),

    # Locations CRUD
    path('locations/', views.LocationListView.as_view(), name='location_list'),
    path('locations/add/', views.LocationCreateView.as_view(), name='location_create'),
    path('locations/<int:pk>/', views.LocationDetailView.as_view(), name='location_detail'),
    path('locations/<int:pk>/edit/', views.LocationUpdateView.as_view(), name='location_update'),
    path('locations/<int:pk>/delete/', views.LocationDeleteView.as_view(), name='location_delete'),

    # Part Documents, Scans, Datasheets & Articles
    path('parts/<int:part_pk>/documents/add/', views.PartDocumentCreateView.as_view(), name='part_document_create'),
    path('documents/<int:pk>/', views.PartDocumentDetailView.as_view(), name='part_document_detail'),
    path('documents/<int:pk>/edit/', views.PartDocumentUpdateView.as_view(), name='part_document_update'),
    path('documents/<int:pk>/delete/', views.PartDocumentDeleteView.as_view(), name='part_document_delete'),

    # Bills of Materials (BOM) / Product Assemblies
    path('boms/', views.BOMListView.as_view(), name='bom_list'),
    path('boms/add/', views.BOMCreateView.as_view(), name='bom_create'),
    path('boms/<int:pk>/', views.BOMDetailView.as_view(), name='bom_detail'),
    path('boms/<int:pk>/edit/', views.BOMUpdateView.as_view(), name='bom_update'),
    path('boms/<int:pk>/delete/', views.BOMDeleteView.as_view(), name='bom_delete'),
    path('boms/<int:bom_pk>/items/add/', views.BOMItemCreateView.as_view(), name='bom_item_create'),
    path('bom-items/<int:pk>/delete/', views.BOMItemDeleteView.as_view(), name='bom_item_delete'),

    # Inventory Count Sheet & Audit
    path('inventory/count-sheet/', views.InventoryCountSheetView.as_view(), name='inventory_count_sheet'),
    path('inventory/count-sheet/export/csv/', views.inventory_count_sheet_export_csv, name='inventory_count_sheet_csv'),
    path('inventory/count-sheet/pdf/', views.inventory_count_sheet_pdf, name='inventory_count_sheet_pdf'),

    # Purchase Orders & Order Action
    path('orders/', views.OrderListView.as_view(), name='order_list'),
    path('orders/create/', views.OrderCreateView.as_view(), name='order_create'),
    path('orders/quick-create-part/', views.order_quick_create_part, name='order_quick_create_part'),
    path('orders/<int:pk>/', views.OrderDetailView.as_view(), name='order_detail'),
    path('orders/<int:pk>/edit/', views.OrderUpdateView.as_view(), name='order_update'),
    path('orders/<int:pk>/delete/', views.OrderDeleteView.as_view(), name='order_delete'),
    path('orders/<int:order_pk>/items/add/', views.OrderItemCreateView.as_view(), name='order_item_create'),
    path('order-items/<int:pk>/delete/', views.OrderItemDeleteView.as_view(), name='order_item_delete'),
    path('orders/<int:order_pk>/items/<int:item_pk>/receive/', views.order_receive_item, name='order_receive_item'),
]
