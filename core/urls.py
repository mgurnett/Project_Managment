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
    path('parts/<int:pk>/move-category/', views.part_move_category_action, name='part_move_category'),

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
    path('categories/<int:pk>/next-part-number/', views.category_next_part_number_json, name='category_next_part_number'),
    path('categories/<int:pk>/next-prefix/', views.category_next_prefix_json, name='category_next_prefix'),

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

    # BoM / Assembly / Kit Documents, Schematics & Video Links
    path('boms/<int:bom_pk>/documents/add/', views.BOMDocumentCreateView.as_view(), name='bom_document_create'),
    path('boms/documents/<int:pk>/', views.BOMDocumentDetailView.as_view(), name='bom_document_detail'),
    path('boms/documents/<int:pk>/edit/', views.BOMDocumentUpdateView.as_view(), name='bom_document_update'),
    path('boms/documents/<int:pk>/delete/', views.BOMDocumentDeleteView.as_view(), name='bom_document_delete'),

    # Bills of Materials (BOM) / Product Assemblies
    path('boms/', views.BOMListView.as_view(), name='bom_list'),
    path('boms/add/', views.BOMCreateView.as_view(), name='bom_create'),
    path('boms/<int:pk>/', views.BOMDetailView.as_view(), name='bom_detail'),
    path('boms/<int:pk>/edit/', views.BOMUpdateView.as_view(), name='bom_update'),
    path('boms/<int:pk>/delete/', views.BOMDeleteView.as_view(), name='bom_delete'),
    path('boms/<int:bom_pk>/items/add/', views.BOMItemCreateView.as_view(), name='bom_item_create'),
    path('boms/<int:pk>/add-bom/', views.bom_add_from_bom_action, name='bom_add_from_bom'),
    path('bom-items/<int:pk>/explode/', views.bom_item_explode_action, name='bom_item_explode'),
    path('boms/<int:pk>/items-json/', views.bom_get_items_json, name='bom_items_json'),
    path('bom-items/<int:pk>/update/', views.bom_item_update_action, name='bom_item_update'),
    path('bom-items/<int:pk>/delete/', views.BOMItemDeleteView.as_view(), name='bom_item_delete'),
    path('boms/<int:pk>/kit/', views.bom_kit_action, name='bom_kit_action'),
    path('boms/<int:pk>/adjust-kit/', views.bom_adjust_kit_action, name='bom_adjust_kit_action'),
    path('boms/<int:pk>/close-kit/', views.bom_close_kit_action, name='bom_close_kit_action'),
    path('boms/<int:pk>/build/', views.bom_build_action, name='bom_build_action'),
    path('boms/<int:pk>/adjust-stock/', views.bom_adjust_assembly_stock, name='bom_adjust_assembly_stock'),
    path('parts/<int:pk>/adjust-committed/', views.part_adjust_committed_action, name='part_adjust_committed_action'),

    # Kit & Build Actions
    path('actions/kit/', views.KitActionView.as_view(), name='kit_action'),
    path('actions/build/', views.BuildActionView.as_view(), name='build_action'),
    path('assemblies/', views.BuildActionView.as_view(), name='assemblies'),

    # Sales Quotes & Estimates (Built from BOMs)
    path('quotes/', views.QuoteListView.as_view(), name='quote_list'),
    path('quotes/create/', views.QuoteCreateView.as_view(), name='quote_create'),
    path('quotes/<int:pk>/', views.QuoteDetailView.as_view(), name='quote_detail'),
    path('quotes/<int:pk>/edit/', views.QuoteUpdateView.as_view(), name='quote_update'),
    path('quotes/<int:pk>/delete/', views.QuoteDeleteView.as_view(), name='quote_delete'),
    path('quotes/<int:pk>/accept/', views.quote_accept, name='quote_accept'),
    path('quotes/<int:pk>/send-email/', views.quote_send_email, name='quote_send_email'),
    path('quotes/<int:pk>/pdf/', views.quote_pdf, name='quote_pdf'),

    # Sales & Invoices (1000-Series Built Assemblies)
    path('sales/', views.AssemblySaleListView.as_view(), name='sale_list'),
    path('sales/create/', views.AssemblySaleCreateView.as_view(), name='sale_create'),
    path('sales/<int:pk>/', views.AssemblySaleDetailView.as_view(), name='sale_detail'),
    path('sales/<int:pk>/mark-paid/', views.sale_mark_paid, name='sale_mark_paid'),
    path('sales/<int:pk>/send-email/', views.sale_send_email, name='sale_send_email'),
    path('sales/<int:pk>/edit/', views.AssemblySaleUpdateView.as_view(), name='sale_update'),
    path('sales/<int:pk>/delete/', views.AssemblySaleDeleteView.as_view(), name='sale_delete'),
    path('sales/<int:pk>/pdf/', views.assembly_sale_pdf, name='sale_pdf'),

    # Inventory Count Sheet & Take Inventory Adjustments
    path('inventory/count-sheet/', views.InventoryCountSheetView.as_view(), name='inventory_count_sheet'),
    path('inventory/count-sheet/export/csv/', views.inventory_count_sheet_export_csv, name='inventory_count_sheet_csv'),
    path('inventory/count-sheet/pdf/', views.inventory_count_sheet_pdf, name='inventory_count_sheet_pdf'),
    path('inventory/take-inventory/', views.TakeInventoryView.as_view(), name='take_inventory'),

    # Purchase Orders & Order / Receive Actions
    path('orders/', views.OrderListView.as_view(), name='order_list'),
    path('orders/create/', views.OrderCreateView.as_view(), name='order_create'),
    path('orders/receive/', views.OrderReceiveActionView.as_view(), name='order_receive_action'),
    path('orders/receive-all/', views.orders_receive_everything, name='orders_receive_everything'),
    path('orders/quick-create-part/', views.order_quick_create_part, name='order_quick_create_part'),
    path('orders/<int:pk>/', views.OrderDetailView.as_view(), name='order_detail'),
    path('orders/<int:pk>/receive-all/', views.order_receive_all, name='order_receive_all'),
    path('orders/<int:pk>/edit/', views.OrderUpdateView.as_view(), name='order_update'),
    path('orders/<int:pk>/delete/', views.OrderDeleteView.as_view(), name='order_delete'),
    path('orders/<int:order_pk>/items/add/', views.OrderItemCreateView.as_view(), name='order_item_create'),
    path('order-items/<int:pk>/delete/', views.OrderItemDeleteView.as_view(), name='order_item_delete'),
    path('orders/<int:order_pk>/items/<int:item_pk>/receive/', views.order_receive_item, name='order_receive_item'),
]
