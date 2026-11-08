import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import Company, Category, Location, Part, Order, OrderItem, BOM, BOMItem, InventoryAdjustment


class OrderActionTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.supplier = Company.objects.create(
            name="DigiKey",
            contact_name="Sales Dept",
            email="sales@digikey.com",
            phone="1-800-344-4539",
            account_number="DK-88992"
        )
        self.category = Category.objects.create(name="Microcontrollers", prefix="100")
        self.part1 = Part.objects.create(
            part_number="100-001",
            name="ATmega328P",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=10,
            quantity_on_order=0,
            price_per=Decimal("2.50")
        )
        self.part2 = Part.objects.create(
            part_number="100-002",
            name="ESP32-WROOM-32E",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=5,
            quantity_on_order=2,
            price_per=Decimal("3.80")
        )

    def test_order_creation_increases_quantity_on_order(self):
        """
        Tests that creating an order with line items increases each part's quantity_on_order
        by the exact ordered amount.
        """
        delivery_date = (timezone.now() + datetime.timedelta(days=7)).date()
        
        post_data = {
            'supplier': self.supplier.pk,
            'order_number': 'PO-TEST-001',
            'order_date': timezone.now().date().isoformat(),
            'expected_delivery_date': delivery_date.isoformat(),
            'tracking_number': '1Z9999999999999999',
            'carrier': 'UPS',
            'status': 'ORDERED',
            'notes': 'Urgent production replenishment',
            'item_part': [self.part1.pk, self.part2.pk],
            'item_quantity': [25, 10],
            'item_unit_price': ['2.50', '3.80'],
            'item_notes': ['Reel', 'Tray'],
        }

        response = self.client.post(reverse('order_create'), post_data)
        self.assertEqual(response.status_code, 302)

        order = Order.objects.get(order_number='PO-TEST-001')
        self.assertEqual(order.supplier, self.supplier)
        self.assertEqual(order.expected_delivery_date, delivery_date)
        self.assertEqual(order.tracking_number, '1Z9999999999999999')
        self.assertEqual(order.carrier, 'UPS')
        self.assertEqual(order.status, 'ORDERED')
        self.assertEqual(order.items.count(), 2)

        # Refresh parts from database
        self.part1.refresh_from_db()
        self.part2.refresh_from_db()

        # part1 had 0 on order + 25 = 25
        self.assertEqual(self.part1.quantity_on_order, 25)
        # part2 had 2 on order + 10 = 12
        self.assertEqual(self.part2.quantity_on_order, 12)

    def test_order_item_create_view_increases_quantity_on_order(self):
        """
        Tests adding a line item to an existing order increases quantity_on_order.
        """
        order = Order.objects.create(
            supplier=self.supplier,
            order_number='PO-EXISTING-001',
            status='ORDERED'
        )

        response = self.client.post(reverse('order_item_create', kwargs={'order_pk': order.pk}), {
            'part': self.part1.pk,
            'quantity': 15,
            'unit_price': '2.50',
            'notes': 'Additional buffer'
        })
        self.assertEqual(response.status_code, 302)

        self.part1.refresh_from_db()
        self.assertEqual(self.part1.quantity_on_order, 15)

    def test_order_item_delete_decrements_quantity_on_order(self):
        """
        Tests removing a line item decrements the on-order count.
        """
        order = Order.objects.create(
            supplier=self.supplier,
            order_number='PO-DEL-001',
            status='ORDERED'
        )
        item = OrderItem.objects.create(
            order=order,
            part=self.part1,
            quantity=20,
            unit_price=Decimal("2.50")
        )
        self.part1.quantity_on_order = 20
        self.part1.save()

        response = self.client.post(reverse('order_item_delete', kwargs={'pk': item.pk}))
        self.assertEqual(response.status_code, 302)

        self.part1.refresh_from_db()
        self.assertEqual(self.part1.quantity_on_order, 0)

    def test_order_receive_item_transfers_on_order_to_on_hand(self):
        """
        Tests receiving items moves quantity from on_order to on_hand and updates order status.
        """
        order = Order.objects.create(
            supplier=self.supplier,
            order_number='PO-REC-001',
            status='ORDERED'
        )
        item = OrderItem.objects.create(
            order=order,
            part=self.part1,
            quantity=10,
            unit_price=Decimal("2.50")
        )
        self.part1.quantity_on_order = 10
        self.part1.quantity_on_hand = 5
        self.part1.save()

        # Receive 4 units
        response = self.client.post(
            reverse('order_receive_item', kwargs={'order_pk': order.pk, 'item_pk': item.pk}),
            {'quantity_received': 4}
        )
        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()
        self.part1.refresh_from_db()
        order.refresh_from_db()

        self.assertEqual(item.quantity_received, 4)
        self.assertEqual(self.part1.quantity_on_order, 6)
        self.assertEqual(self.part1.quantity_on_hand, 9)
        self.assertEqual(order.status, 'PARTIALLY_RECEIVED')

        # Receive remaining 6 units
        self.client.post(
            reverse('order_receive_item', kwargs={'order_pk': order.pk, 'item_pk': item.pk}),
            {'quantity_received': 6}
        )
        item.refresh_from_db()
        self.part1.refresh_from_db()
        order.refresh_from_db()

        self.assertEqual(item.quantity_received, 10)
        self.assertEqual(self.part1.quantity_on_order, 0)
        self.assertEqual(self.part1.quantity_on_hand, 15)
        self.assertEqual(order.status, 'RECEIVED')

    def test_order_list_and_detail_views(self):
        order = Order.objects.create(
            supplier=self.supplier,
            order_number='PO-VIEW-001',
            tracking_number='TRK-12345',
            status='ORDERED'
        )
        OrderItem.objects.create(order=order, part=self.part1, quantity=5)

        # List view
        res = self.client.get(reverse('order_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'PO-VIEW-001')
        self.assertContains(res, 'TRK-12345')

        # Detail view
        res = self.client.get(reverse('order_detail', kwargs={'pk': order.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'PO-VIEW-001')
        self.assertContains(res, '100-001')

    def test_order_receive_updates_part_price_model(self):
        """
        Tests that when a part is ordered at a new price and received,
        that price becomes the new price (price_per and price) in the Part model.
        """
        self.part1.quantity = 10
        self.part1.price_per = Decimal("2.50")
        self.part1.price = Decimal("25.00")
        self.part1.save()

        # Place order for part1 at a new price of $3.25/unit
        post_data = {
            'supplier': self.supplier.pk,
            'order_number': 'PO-PRICE-001',
            'order_date': timezone.now().date().isoformat(),
            'status': 'ORDERED',
            'item_part': [self.part1.pk],
            'item_package_quantity': [10],
            'item_quantity': [20],
            'item_unit_price': ['3.25'],
            'item_notes': ['Updated vendor pricing'],
        }
        res = self.client.post(reverse('order_create'), post_data)
        self.assertEqual(res.status_code, 302)

        order = Order.objects.get(order_number='PO-PRICE-001')
        item = order.items.first()
        self.assertEqual(item.unit_price, Decimal("3.25"))

        # Receive the item
        rec_res = self.client.post(
            reverse('order_receive_item', kwargs={'order_pk': order.pk, 'item_pk': item.pk}),
            {'quantity_received': 20}
        )
        self.assertEqual(rec_res.status_code, 302)

        self.part1.refresh_from_db()
        self.assertEqual(self.part1.price_per, Decimal("3.25"))
        self.assertEqual(self.part1.price, Decimal("32.50"))  # 10 pkg qty * 3.25

    def test_order_change_package_quantity_and_box_price(self):
        """
        Tests changing the package quantity that a part comes in (e.g. box of 50)
        and package price when ordering, then verifying the part's price model updates upon receipt.
        """
        post_data = {
            'supplier': self.supplier.pk,
            'order_number': 'PO-BOX50-001',
            'order_date': timezone.now().date().isoformat(),
            'status': 'ORDERED',
            'item_part': [self.part1.pk],
            'item_package_quantity': [50],
            'item_quantity': [50],
            'item_package_price': ['20.00'],
            'item_unit_price': [''],
            'item_notes': ['Box of 50'],
        }
        res = self.client.post(reverse('order_create'), post_data)
        self.assertEqual(res.status_code, 302)

        self.part1.refresh_from_db()
        # Package quantity updated to 50 when ordered
        self.assertEqual(self.part1.quantity, 50)

        order = Order.objects.get(order_number='PO-BOX50-001')
        item = order.items.first()
        # $20.00 / 50 = $0.40 unit price
        self.assertEqual(item.unit_price, Decimal("0.40"))

        # Receive the box of 50
        self.client.post(
            reverse('order_receive_item', kwargs={'order_pk': order.pk, 'item_pk': item.pk}),
            {'quantity_received': 50}
        )
        self.part1.refresh_from_db()
        self.assertEqual(self.part1.quantity, 50)
        self.assertEqual(self.part1.price_per, Decimal("0.40"))
        self.assertEqual(self.part1.price, Decimal("20.00"))

        # Also test ordering Qty=1 of a [Pkg of 50] part priced at $20.20 ($0.40/unit) ->
        # should order 1 package (50 units) with an Estimated Total / Subtotal of $20.20 (not $0.40)
        qd_part = Part.objects.create(
            part_number="600-003",
            name="Quick Disconnect plug",
            company=self.supplier,
            category=self.category,
            quantity=50,
            price=Decimal("20.20"),
            price_per=Decimal("0.40"),
            quantity_on_hand=50,
            quantity_on_order=0,
        )
        res_qd = self.client.post(reverse('order_create'), {
            'supplier': self.supplier.pk,
            'order_number': 'PO-QD-600-003',
            'order_date': timezone.now().date().isoformat(),
            'status': 'ORDERED',
            'item_part': [qd_part.pk],
            'item_package_quantity': [50],
            'item_quantity': [1],
            'item_package_price': ['20.20'],
            'item_unit_price': ['0.40'],
            'item_notes': ['1 package of 50'],
        })
        self.assertEqual(res_qd.status_code, 302)
        qd_order = Order.objects.get(order_number='PO-QD-600-003')
        qd_item = qd_order.items.first()
        self.assertEqual(qd_item.quantity, 50)
        self.assertEqual(qd_item.subtotal, Decimal("20.20"))
        self.assertEqual(qd_order.total_cost, Decimal("20.20"))
        qd_part.refresh_from_db()
        self.assertEqual(qd_part.quantity_on_order, 50)

    def test_order_create_with_inline_new_part_and_quick_create_endpoint(self):
        """
        Tests creating a brand new part directly during order creation (both via inline '__new__'
        and via the quick-create AJAX endpoint) with box quantity of 50 and price.
        """
        # 1. Test quick-create endpoint
        qc_res = self.client.post(reverse('order_quick_create_part'), {
            'name': 'Nylon Crimp Terminal',
            'category': self.category.pk,
            'supplier': self.supplier.pk,
            'supplier_part_number': 'DK-CRIMP-50',
            'package_quantity': '50',
            'package_price': '15.00',
        })
        self.assertEqual(qc_res.status_code, 200)
        qc_data = qc_res.json()
        self.assertEqual(qc_data['status'], 'ok')
        created_part = Part.objects.get(pk=qc_data['part']['id'])
        self.assertEqual(created_part.quantity, 50)
        self.assertEqual(created_part.price, Decimal("15.00"))
        self.assertEqual(created_part.price_per, Decimal("0.30"))

        # 2. Test inline '__new__' part creation inside OrderCreateView
        post_data = {
            'supplier': self.supplier.pk,
            'order_number': 'PO-NEWPART-001',
            'order_date': timezone.now().date().isoformat(),
            'status': 'ORDERED',
            'item_part': ['__new__'],
            'item_new_name': [' Brass Standoff M3 '],
            'item_new_category': [str(self.category.pk)],
            'item_new_part_number': [''],
            'item_new_supplier_pn': ['DK-M3-50'],
            'item_new_description': ['M3x10mm Hex Brass Standoff'],
            'item_package_quantity': ['50'],
            'item_quantity': ['100'],
            'item_package_price': ['25.00'],
            'item_unit_price': [''],
            'item_notes': ['2 boxes of 50'],
        }
        res = self.client.post(reverse('order_create'), post_data)
        self.assertEqual(res.status_code, 302)

        standoff = Part.objects.get(name='Brass Standoff M3')
        self.assertEqual(standoff.quantity, 50)
        self.assertEqual(standoff.price, Decimal("25.00"))
        self.assertEqual(standoff.price_per, Decimal("0.50"))
        self.assertEqual(standoff.quantity_on_order, 100)

    def test_part_detail_displays_purchase_order_history(self):
        """
        Tests that a part's detail page displays a history of all purchase orders it has been added to.
        """
        order1 = Order.objects.create(
            supplier=self.supplier,
            order_number='PO-HIST-101',
            tracking_number='TRK-HIST-1',
            status='RECEIVED'
        )
        OrderItem.objects.create(
            order=order1,
            part=self.part1,
            quantity=25,
            quantity_received=25,
            unit_price=Decimal("2.40")
        )

        order2 = Order.objects.create(
            supplier=self.supplier,
            order_number='PO-HIST-102',
            tracking_number='TRK-HIST-2',
            status='ORDERED'
        )
        OrderItem.objects.create(
            order=order2,
            part=self.part1,
            quantity=50,
            quantity_received=0,
            unit_price=Decimal("2.65")
        )

        res = self.client.get(reverse('part_detail', kwargs={'pk': self.part1.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Purchase Order History (2)')
        self.assertContains(res, 'PO-HIST-101')
        self.assertContains(res, 'PO-HIST-102')
        self.assertContains(res, 'TRK-HIST-1')
        self.assertContains(res, 'TRK-HIST-2')


class PartDuplicateTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.supplier = Company.objects.create(name="Molex", contact_name="Support")
        self.category = Category.objects.create(name="Connectors", prefix="300")
        self.female_part = Part.objects.create(
            part_number="PART-001",
            name="Quick Disconnect plug",
            description='Nylon Full 22-18ga Female .250"',
            company=self.supplier,
            category=self.category,
            supplier_part_number="TEC-761354",
            quantity=50,
            price_per=Decimal("0.40"),
            price=Decimal("20.20"),
            confirmed=False,
        )

    def test_duplicate_view_renders_prefilled_form(self):
        url = reverse('part_duplicate', kwargs={'pk': self.female_part.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Duplicate Component')
        self.assertContains(response, 'Quick Disconnect plug')
        self.assertContains(response, 'Nylon Full 22-18ga Female .250&quot;')
        self.assertContains(response, 'TEC-761354')

    def test_duplicate_submission_creates_new_male_part(self):
        url = reverse('part_duplicate', kwargs={'pk': self.female_part.pk})
        post_data = {
            'part_number': 'PART-002',
            'name': 'Quick Disconnect plug Male',
            'description': 'Nylon Full 22-18ga Male .250"',
            'supplier_part_number': 'TEC-761355',
            'company': self.supplier.pk,
            'category': self.category.pk,
            'quantity': 50,
            'price_per': '0.40',
            'price': '20.20',
            'quantity_on_hand': 0,
            'quantity_on_order': 0,
            'quantity_committed': 0,
            'quantity_availible': 0,
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        male_part = Part.objects.get(part_number='PART-002')
        self.assertEqual(male_part.name, 'Quick Disconnect plug Male')
        self.assertEqual(male_part.description, 'Nylon Full 22-18ga Male .250"')
        self.assertEqual(male_part.company, self.supplier)
        self.assertEqual(male_part.category, self.category)
        self.assertEqual(male_part.price_per, Decimal('0.40'))

    def test_duplicate_button_present_in_part_list_and_detail(self):
        # Part list
        res_list = self.client.get(reverse('part_list'))
        self.assertEqual(res_list.status_code, 200)
        duplicate_url = reverse('part_duplicate', kwargs={'pk': self.female_part.pk})
        self.assertContains(res_list, duplicate_url)

        # Part detail
        res_detail = self.client.get(reverse('part_detail', kwargs={'pk': self.female_part.pk}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, duplicate_url)


class PriorityLowActionsTestCase(TestCase):
    """
    Tests all 5 Priority Low items:
    1. Make a receive action - can receive everything that was on order
    2. Make a BOM - you can make up what it takes to build something (inline components)
    3. Make a kit action - move everything from a BoM to a kit (committed inventory)
    4. Make a build action - takes all the parts out of inventory
    5. Make a take inventory sheet that shows what should be there and allows for adjustments
    """
    def setUp(self):
        self.client = Client()
        self.supplier = Company.objects.create(name="Mouser Electronics")
        self.category = Category.objects.create(name="Passives", prefix="100")
        self.part_a = Part.objects.create(
            part_number="100-010",
            name="10k Resistor",
            description="Resistor 10k Ohm 1%",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=20,
            quantity_on_order=0,
            quantity_committed=0,
            quantity_availible=20,
            quantity=100,
            price_per=Decimal("0.10"),
            price=Decimal("10.00"),
        )
        self.part_b = Part.objects.create(
            part_number="100-011",
            name="100nF Capacitor",
            description="Capacitor Ceramic 100nF",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=15,
            quantity_on_order=0,
            quantity_committed=0,
            quantity_availible=15,
            quantity=50,
            price_per=Decimal("0.20"),
            price=Decimal("10.00"),
        )

    def test_receive_all_on_order_and_receive_everything(self):
        # Create two orders
        order1 = Order.objects.create(supplier=self.supplier, order_number="PO-RCV-001", status="ORDERED")
        OrderItem.objects.create(order=order1, part=self.part_a, quantity=30, unit_price=Decimal("0.12"))
        self.part_a.quantity_on_order = 30
        self.part_a.save()

        order2 = Order.objects.create(supplier=self.supplier, order_number="PO-RCV-002", status="ORDERED")
        OrderItem.objects.create(order=order2, part=self.part_b, quantity=25, unit_price=Decimal("0.25"))
        self.part_b.quantity_on_order = 25
        self.part_b.save()

        # Check Receive Action page renders
        res_page = self.client.get(reverse('order_receive_action'))
        self.assertEqual(res_page.status_code, 200)
        self.assertContains(res_page, "PO-RCV-001")
        self.assertContains(res_page, "PO-RCV-002")

        # 1. Receive single order (order1) via order_receive_all
        res_o1 = self.client.post(reverse('order_receive_all', kwargs={'pk': order1.pk}))
        self.assertEqual(res_o1.status_code, 302)
        self.part_a.refresh_from_db()
        order1.refresh_from_db()
        self.assertEqual(order1.status, "RECEIVED")
        self.assertEqual(self.part_a.quantity_on_hand, 50)  # 20 + 30
        self.assertEqual(self.part_a.quantity_on_order, 0)
        self.assertEqual(self.part_a.price_per, Decimal("0.12"))

        # 2. Receive everything remaining on order across all POs via orders_receive_everything
        res_all = self.client.post(reverse('orders_receive_everything'))
        self.assertEqual(res_all.status_code, 302)
        self.part_b.refresh_from_db()
        order2.refresh_from_db()
        self.assertEqual(order2.status, "RECEIVED")
        self.assertEqual(self.part_b.quantity_on_hand, 40)  # 15 + 25
        self.assertEqual(self.part_b.quantity_on_order, 0)
        self.assertEqual(self.part_b.price_per, Decimal("0.25"))

    def test_bom_create_with_components_and_kit_and_build_actions(self):
        # 1. Create a BOM with inline components in one step
        res_create = self.client.post(reverse('bom_create'), {
            'name': 'Telemetry Sensor Node',
            'description': 'Main sensor node assembly',
            'notes': 'Solder R1 and C1 first.',
            'item_part[]': [str(self.part_a.pk), str(self.part_b.pk)],
            'item_reference[]': ['R1-R4', 'C1-C2'],
            'item_quantity[]': ['4', '2'],
            'item_notes[]': ['10k pullups', 'Decoupling'],
        })
        self.assertEqual(res_create.status_code, 302)
        bom = BOM.objects.get(name='Telemetry Sensor Node')
        self.assertEqual(bom.items.count(), 2)
        self.assertEqual(bom.total_parts_quantity, 6)

        # 2. Kit Action: Move 2 kits of this BOM into Committed Kit inventory
        res_kit = self.client.post(reverse('bom_kit_action', kwargs={'pk': bom.pk}), {'quantity': 2})
        self.assertEqual(res_kit.status_code, 302)
        self.part_a.refresh_from_db()
        self.part_b.refresh_from_db()
        # 2 kits * 4 = 8 committed for part_a; 20 - 8 = 12 available
        self.assertEqual(self.part_a.quantity_committed, 8)
        self.assertEqual(self.part_a.quantity_availible, 12)
        # 2 kits * 2 = 4 committed for part_b; 15 - 4 = 11 available
        self.assertEqual(self.part_b.quantity_committed, 4)
        self.assertEqual(self.part_b.quantity_availible, 11)

        # 3. Build Action: Build 2 units of this BOM (takes parts out of on-hand and committed kit stock)
        res_build = self.client.post(reverse('bom_build_action', kwargs={'pk': bom.pk}), {
            'quantity': 2,
            'consume_committed': '1',
        })
        self.assertEqual(res_build.status_code, 302)
        self.part_a.refresh_from_db()
        self.part_b.refresh_from_db()
        # On-hand reduced by 8 (20 -> 12) and committed reduced by 8 (8 -> 0)
        self.assertEqual(self.part_a.quantity_on_hand, 12)
        self.assertEqual(self.part_a.quantity_committed, 0)
        self.assertEqual(self.part_a.quantity_availible, 12)
        # On-hand reduced by 4 (15 -> 11) and committed reduced by 4 (4 -> 0)
        self.assertEqual(self.part_b.quantity_on_hand, 11)
        self.assertEqual(self.part_b.quantity_committed, 0)
        self.assertEqual(self.part_b.quantity_availible, 11)

    def test_take_inventory_sheet_shows_expected_and_applies_adjustments(self):
        # GET take inventory sheet
        res_get = self.client.get(reverse('take_inventory'))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, "100-010")
        self.assertContains(res_get, "100-011")

        # POST adjustments: part_a from 20 -> 18, part_b from 15 -> 22
        res_post = self.client.post(reverse('take_inventory'), {
            f'actual_count_{self.part_a.pk}': '18',
            f'reason_{self.part_a.pk}': 'Damaged items scrapped',
            f'actual_count_{self.part_b.pk}': '22',
            f'reason_{self.part_b.pk}': 'Found unopened pack on shelf',
        })
        self.assertEqual(res_post.status_code, 302)
        self.part_a.refresh_from_db()
        self.part_b.refresh_from_db()
        self.assertEqual(self.part_a.quantity_on_hand, 18)
        self.assertEqual(self.part_a.quantity_availible, 18)
        self.assertEqual(self.part_b.quantity_on_hand, 22)
        self.assertEqual(self.part_b.quantity_availible, 22)


class EndToEndAllActionsWorkflowTestCase(TestCase):
    """
    Comprehensive end-to-end test covering the full lifecycle of all actions (TODO line 5):
    1. Start with initial part inventory and verify baseline numbers.
    2. Add a Purchase Order for the part -> verify `quantity_on_order` increases and `quantity_on_hand` is unchanged.
    3. Receive the Purchase Order -> verify `Order.status == 'RECEIVED'`, `OrderItem.quantity_received` matches,
       `quantity_on_order` goes back to 0, `quantity_on_hand` and `quantity_availible` increase by the ordered amount,
       and `price_per` / `price` update to the ordered price.
    4. Create a BoM using the part number that was on the order and Make a Kit from that BoM ->
       verify `quantity_committed` increases by the kit requirement, `quantity_availible` decreases accordingly,
       and `quantity_on_hand` remains intact while in the kit.
    5. Close the Kit (build/complete the kit) -> verify the kitted parts are taken out of inventory
       (`quantity_on_hand` decreases by the kit quantity, `quantity_committed` returns to 0, and
       `quantity_availible` equals the remaining `quantity_on_hand`).
    6. Perform a Take Inventory adjustment at the end -> verify numbers stay consistent throughout.
    """
    def setUp(self):
        self.client = Client()
        self.supplier = Company.objects.create(
            name="DigiKey Electronics",
            contact_name="Orders Desk",
            email="orders@digikey.com"
        )
        self.category = Category.objects.create(name="Transceivers", prefix="400")
        self.part = Part.objects.create(
            part_number="400-001",
            name="LoRa RF Transceiver Module",
            description="SX1276 915MHz Transceiver",
            company=self.supplier,
            category=self.category,
            supplier_part_number="SX1276RF1JAS",
            quantity_on_hand=5,
            quantity_on_order=0,
            quantity_committed=0,
            quantity_availible=5,
            quantity=10,
            price_per=Decimal("8.00"),
            price=Decimal("80.00"),
        )

    def test_full_purchase_order_receive_kit_and_close_kit_workflow(self):
        from django.conf import settings
        settings.TEST = True
        # --- STEP 0: Verify initial inventory state ---
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_on_hand, 5)
        self.assertEqual(self.part.quantity_on_order, 0)
        self.assertEqual(self.part.quantity_committed, 0)
        self.assertEqual(self.part.quantity_availible, 5)
        self.assertEqual(self.part.price_per, Decimal("8.00"))

        # --- STEP 1: Add a Purchase Order for 20 units of 400-001 at $9.50/unit (2 boxes of 10 @ $95/box) ---
        po_date = timezone.now().date()
        expected_date = po_date + datetime.timedelta(days=5)
        res_order = self.client.post(reverse('order_create'), {
            'supplier': self.supplier.pk,
            'order_number': 'PO-E2E-2026-001',
            'order_date': po_date.isoformat(),
            'expected_delivery_date': expected_date.isoformat(),
            'tracking_number': '1Z999AA10123456784',
            'carrier': 'UPS',
            'status': 'ORDERED',
            'notes': 'Urgent production order',
            'item_part': [str(self.part.pk)],
            'item_package_quantity': ['10'],
            'item_quantity': ['20'],
            'item_package_price': ['95.00'],
            'item_unit_price': ['9.50'],
            'item_notes': ['For Base Station Kits'],
        })
        self.assertEqual(res_order.status_code, 302)

        order = Order.objects.get(order_number='PO-E2E-2026-001')
        self.assertEqual(order.status, 'ORDERED')
        self.assertEqual(order.total_units_ordered, 20)
        self.assertEqual(order.total_units_received, 0)

        self.part.refresh_from_db()
        # Verify numbers after placing PO: on_order increased by 20, on_hand still 5
        self.assertEqual(self.part.quantity_on_hand, 5)
        self.assertEqual(self.part.quantity_on_order, 20)
        self.assertEqual(self.part.quantity_committed, 0)
        self.assertEqual(self.part.quantity_availible, 5)

        # --- STEP 2: Receive the Purchase Order ---
        res_receive = self.client.post(reverse('order_receive_all', kwargs={'pk': order.pk}))
        self.assertEqual(res_receive.status_code, 302)

        order.refresh_from_db()
        self.assertEqual(order.status, 'RECEIVED')
        self.assertTrue(order.is_fully_received)
        self.assertEqual(order.total_units_received, 20)

        self.part.refresh_from_db()
        # Verify numbers after receiving PO:
        # on_hand = 5 + 20 = 25, on_order = 0, committed = 0, available = 25, price_per = $9.50
        self.assertEqual(self.part.quantity_on_hand, 25)
        self.assertEqual(self.part.quantity_on_order, 0)
        self.assertEqual(self.part.quantity_committed, 0)
        self.assertEqual(self.part.quantity_availible, 25)
        self.assertEqual(self.part.price_per, Decimal("9.50"))
        self.assertEqual(self.part.price, Decimal("95.00"))

        # --- STEP 3: Create a BoM using the part number from the order (3 pcs per assembly) ---
        res_bom = self.client.post(reverse('bom_create'), {
            'name': 'LoRa Base Station Assembly',
            'description': 'Multi-channel LoRa gateway assembly',
            'notes': 'Mount transceiver modules onto main carrier board.',
            'item_part[]': [str(self.part.pk)],
            'item_reference[]': ['U1, U2, U3'],
            'item_quantity[]': ['3'],
            'item_notes[]': ['915MHz transceivers'],
        })
        self.assertEqual(res_bom.status_code, 302)
        bom = BOM.objects.get(name='LoRa Base Station Assembly')
        self.assertEqual(bom.items.count(), 1)
        self.assertEqual(bom.total_parts_quantity, 3)
        self.assertEqual(bom.total_cost, Decimal("28.50"))  # 3 * $9.50

        # --- STEP 4: Make a Kit from the BoM (prepare 4 kits = 12 pcs committed) ---
        res_kit = self.client.post(reverse('kit_action'), {
            'bom': str(bom.pk),
            'quantity': '4',
        })
        self.assertEqual(res_kit.status_code, 302)

        self.part.refresh_from_db()
        # Verify numbers while kitted:
        # on_hand is still 25, committed is 4 * 3 = 12, available is 25 - 12 = 13, on_order is 0
        self.assertEqual(self.part.quantity_on_hand, 25)
        self.assertEqual(self.part.quantity_on_order, 0)
        self.assertEqual(self.part.quantity_committed, 12)
        self.assertEqual(self.part.quantity_availible, 13)

        # --- STEP 5: Close the Kit (complete/build the 4 kits -> consumes the 12 kitted parts out of inventory) ---
        res_close_kit = self.client.post(reverse('bom_close_kit_action', kwargs={'pk': bom.pk}), {
            'quantity': '4',
            'action_type': 'build',
        })
        self.assertEqual(res_close_kit.status_code, 302)

        self.part.refresh_from_db()
        # Verify numbers after closing the kit:
        # on_hand = 25 - 12 = 13, committed = 12 - 12 = 0, available = 13, on_order = 0
        self.assertEqual(self.part.quantity_on_hand, 13)
        self.assertEqual(self.part.quantity_on_order, 0)
        self.assertEqual(self.part.quantity_committed, 0)
        self.assertEqual(self.part.quantity_availible, 13)

        # --- STEP 6: Verify Take Inventory Sheet reflects 13 on hand and unit price $9.50, then adjust to 12 ---
        res_inv_get = self.client.get(reverse('take_inventory'))
        self.assertEqual(res_inv_get.status_code, 200)
        self.assertContains(res_inv_get, '400-001')
        self.assertContains(res_inv_get, '$9.50')

        res_inv_post = self.client.post(reverse('take_inventory'), {
            f'actual_count_{self.part.pk}': '12',
            f'reason_{self.part.pk}': '1 unit scrapped during lab testing',
        })
        self.assertEqual(res_inv_post.status_code, 302)

        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_on_hand, 12)
        self.assertEqual(self.part.quantity_on_order, 0)
        self.assertEqual(self.part.quantity_committed, 0)
        self.assertEqual(self.part.quantity_availible, 12)

        # --- STEP 7: Verify Part Detail page displays the Transaction & Movement Journal ---
        res_part_detail = self.client.get(reverse('part_detail', kwargs={'pk': self.part.pk}))
        self.assertEqual(res_part_detail.status_code, 200)
        self.assertContains(res_part_detail, 'Transaction &amp; Movement Journal')
        self.assertContains(res_part_detail, 'Purchase Order')
        self.assertContains(res_part_detail, 'Order Received')
        self.assertContains(res_part_detail, 'Kit Picked')
        self.assertContains(res_part_detail, 'Kit Closed / Built')
        self.assertContains(res_part_detail, 'Inventory Adjustment')

    def test_duplicate_part_generates_new_part_number_and_persistent_filters(self):
        """
        Tests that duplicating a part pre-fills the form with the next sequential part number
        (not the old part number), and that list filters persist across requests until cleared.
        """
        # 1. Duplicate part 400-001 -> form initial part_number should be 400-002
        dup_res = self.client.get(reverse('part_duplicate', kwargs={'pk': self.part.pk}))
        self.assertEqual(dup_res.status_code, 200)
        self.assertEqual(dup_res.context['form'].initial['part_number'], '400-002')
        self.assertNotEqual(dup_res.context['form'].initial['part_number'], self.part.part_number)

        # Create a second category and part to test filter persistence
        other_cat = Category.objects.create(name='Connectors', prefix='600')
        other_part = Part.objects.create(
            part_number='600-001',
            name='SMA Bulkhead Jack',
            category=other_cat,
        )

        # 2. Set category filter on part_list -> only 400-001 should appear
        res_filtered = self.client.get(reverse('part_list'), {'category': str(self.category.pk)})
        self.assertEqual(res_filtered.status_code, 200)
        self.assertContains(res_filtered, '400-001')
        self.assertNotContains(res_filtered, '600-001')

        # 3. Revisit part_list with no query params -> filter stays active from session
        res_persisted = self.client.get(reverse('part_list'))
        self.assertEqual(res_persisted.status_code, 200)
        self.assertContains(res_persisted, '400-001')
        self.assertNotContains(res_persisted, '600-001')
        self.assertEqual(res_persisted.context['current_category'], str(self.category.pk))

        # 4. Hit Clear Filter (?clear=1) -> redirects to part_list with all parts shown
        res_clear = self.client.get(reverse('part_list'), {'clear': '1'}, follow=True)
        self.assertEqual(res_clear.status_code, 200)
        self.assertContains(res_clear, '400-001')
        self.assertContains(res_clear, '600-001')
        self.assertEqual(res_clear.context['current_category'], '')

    def test_kits_list_and_adjustments_add_subtract_set_delete(self):
        """
        Tests listing kits and adjusting kit quantities (add, subtract, set exact target, delete/clear)
        as well as adjusting individual committed part quantities and BoM item quantities.
        """
        self.part.quantity_on_hand = 30
        self.part.quantity_committed = 0
        self.part.quantity_availible = 30
        self.part.save()

        bom = BOM.objects.create(name='Node Sensor Kit')
        bom_item = BOMItem.objects.create(bom=bom, part=self.part, quantity=2)

        # 1. Add 3 kits -> commits 6 parts
        self.client.post(reverse('bom_adjust_kit_action', kwargs={'pk': bom.pk}), {
            'mode': 'add',
            'quantity': '3',
        })
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_committed, 6)
        self.assertEqual(self.part.quantity_availible, 24)

        # 2. Subtract 1 kit -> returns 2 parts to available (4 committed)
        self.client.post(reverse('bom_adjust_kit_action', kwargs={'pk': bom.pk}), {
            'mode': 'subtract',
            'quantity': '1',
        })
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_committed, 4)
        self.assertEqual(self.part.quantity_availible, 26)

        # 3. Set exact kit count to 5 -> commits +3 kits = 10 committed
        self.client.post(reverse('bom_adjust_kit_action', kwargs={'pk': bom.pk}), {
            'mode': 'set',
            'target_kits': '5',
        })
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_committed, 10)
        self.assertEqual(self.part.quantity_availible, 20)

        # 4. Adjust individual part committed count directly (set to 8)
        self.client.post(reverse('part_adjust_committed_action', kwargs={'pk': self.part.pk}), {
            'mode': 'set',
            'target_committed': '8',
        })
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_committed, 8)
        self.assertEqual(self.part.quantity_availible, 22)

        # 5. Delete / clear kit -> returns all 8 committed parts to available stock
        self.client.post(reverse('bom_adjust_kit_action', kwargs={'pk': bom.pk}), {
            'mode': 'delete',
        })
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_committed, 0)
        self.assertEqual(self.part.quantity_availible, 30)

        # 6. Adjust BOMItem quantity (+1 -> 3)
        self.client.post(reverse('bom_item_update', kwargs={'pk': bom_item.pk}), {
            'mode': 'add',
        })
        bom_item.refresh_from_db()
        self.assertEqual(bom_item.quantity, 3)

        # 7. When a BoM has an active kit (e.g. 2 kits of Node Sensor Kit = 6 of self.part),
        # adding a new component part to that BoM automatically commits (qty * active_kits)
        self.client.post(reverse('bom_adjust_kit_action', kwargs={'pk': bom.pk}), {
            'mode': 'set',
            'target_kits': '2',
        })
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_committed, 6)

        box_part = Part.objects.create(
            part_number='500-004',
            name='Blue project box',
            category=self.category,
            quantity_on_hand=5,
            quantity_committed=0,
            quantity_availible=5,
        )
        self.client.post(reverse('bom_item_create', kwargs={'bom_pk': bom.pk}), {
            'part': box_part.pk,
            'quantity': 1,
            'reference': 'ENC1',
            'notes': 'Enclosure',
        })
        box_part.refresh_from_db()
        self.assertEqual(box_part.quantity_committed, 2)
        self.assertEqual(box_part.quantity_availible, 3)

    def test_kit_to_1000_series_assembly_and_sale_invoice_generation(self):
        """
        Tests the full lifecycle requested by the user:
        1. Once a kit is built/closed, it is assigned a 1000-series assembly number (e.g. 1000-001),
           component parts are removed from inventory, and the built assembly is added to assembly stock.
        2. The built 1000-series assembly can then be sold in the Sales & Invoices section.
        3. Selling the assembly decrements the built assembly inventory and produces a sequential
           Invoice (INV-0001, INV-0002) with:
           - Invoice number (sequential)
           - Invoice date (date of sale)
           - Customer information (Granary Watch, 11940 52 St NW, Edmonton, AB T5J 3J6, 780.901.9315, michael@granarywatch.com)
           - Item information (1000-series item number, item description, quantity, price)
           - Total amount
           - Payment information (payment method, payment date)
        """
        from .models import AssemblySale

        self.part.quantity_on_hand = 20
        self.part.quantity_committed = 0
        self.part.quantity_availible = 20
        self.part.price_per = Decimal("15.00")
        self.part.save()

        # Create a BoM Assembly -> should auto-assign 1000-series number (e.g. 1000-001)
        bom = BOM.objects.create(
            name="LiPo Battery Checker Assembly",
            description="Complete LiPo Battery Checker with Blue Project Box",
            sale_price=Decimal("75.00"),
        )
        self.assertTrue(bom.assembly_number.startswith("1000-"))
        self.assertEqual(bom.quantity_on_hand, 0)

        BOMItem.objects.create(bom=bom, part=self.part, quantity=2)

        # Pick 3 kits -> commits 6 parts
        self.client.post(reverse('bom_kit_action', kwargs={'pk': bom.pk}), {'quantity': 3})
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_committed, 6)
        self.assertEqual(self.part.quantity_on_hand, 20)

        # Close/Build 2 kits -> removes 4 parts from inventory (on_hand: 20 -> 16, committed: 6 -> 2)
        # AND adds 2 built assemblies to bom.quantity_on_hand (0 -> 2) with 1000-series assembly_number
        self.client.post(reverse('bom_close_kit_action', kwargs={'pk': bom.pk}), {
            'quantity': 2,
            'action_type': 'build',
            'assembly_number': '1000-001',
        })
        self.part.refresh_from_db()
        bom.refresh_from_db()
        self.assertEqual(self.part.quantity_on_hand, 16)
        self.assertEqual(self.part.quantity_committed, 2)
        self.assertEqual(bom.assembly_number, '1000-001')
        self.assertEqual(bom.quantity_on_hand, 2)

        # Sell 1 built assembly to Granary Watch and generate sequential invoice INV-0001
        sale_date = timezone.now().date().isoformat()
        res_sale = self.client.post(reverse('sale_create'), {
            'invoice_number': '',  # Let it auto-assign INV-0001 sequentially
            'invoice_date': sale_date,
            'status': 'PAID',
            'customer_name': 'Granary Watch',
            'customer_address': '11940 52 St NW, Edmonton, AB T5J 3J6',
            'customer_phone': '780.901.9315',
            'customer_email': 'michael@granarywatch.com',
            'payment_method': 'E-Transfer',
            'payment_date': sale_date,
            'notes': 'Net paid upon delivery.',
            'item_bom[]': [str(bom.pk)],
            'item_number[]': [bom.assembly_number],
            'item_description[]': [bom.name],
            'item_quantity[]': ['1'],
            'item_unit_price[]': ['75.00'],
        })
        self.assertEqual(res_sale.status_code, 302)

        # Built assembly stock is decremented from 2 -> 1
        bom.refresh_from_db()
        self.assertEqual(bom.quantity_on_hand, 1)

        # Verify sequential invoice INV-0001 and all required fields
        sale1 = AssemblySale.objects.first()
        self.assertIsNotNone(sale1)
        self.assertEqual(sale1.invoice_number, 'INV-0001')
        self.assertEqual(sale1.status, 'PAID')
        self.assertEqual(sale1.customer_name, 'Granary Watch')
        self.assertEqual(sale1.customer_address, '11940 52 St NW, Edmonton, AB T5J 3J6')
        self.assertEqual(sale1.customer_phone, '780.901.9315')
        self.assertEqual(sale1.customer_email, 'michael@granarywatch.com')
        self.assertEqual(sale1.total_amount, Decimal("75.00"))
        self.assertEqual(sale1.payment_method, 'E-Transfer')

        # Verify next sequential invoice number is INV-0002
        self.assertEqual(AssemblySale.generate_next_invoice_number(), 'INV-0002')

        # Verify Invoice Detail page renders all required fields
        res_detail = self.client.get(reverse('sale_detail', kwargs={'pk': sale1.pk}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, 'INV-0001')
        self.assertContains(res_detail, 'Granary Watch')
        self.assertContains(res_detail, '11940 52 St NW, Edmonton, AB T5J 3J6')
        self.assertContains(res_detail, '780.901.9315')
        self.assertContains(res_detail, 'michael@granarywatch.com')
        self.assertContains(res_detail, '1000-001')
        self.assertContains(res_detail, 'LiPo Battery Checker Assembly')
        self.assertContains(res_detail, '$75.00')
        self.assertContains(res_detail, 'Interac e-Transfer')

    def test_invoice_for_unbuilt_assembly_then_mark_paid_with_stamp_and_email(self):
        """
        Tests the workflow requested by the user:
        1. Create an invoice for an assembly that is NOT built yet (bom.quantity_on_hand == 0).
           - Status is UNPAID (Open).
           - Stock is NOT deducted (quantity_on_hand remains 0).
           - PDF is generated and physically saved to media/invoices/.
           - Detail view displays UNPAID status and no watermark.
        2. Assembly is subsequently built (bom.quantity_on_hand becomes 1).
        3. Close invoice by marking as PAID:
           - Status transitions to PAID.
           - Built assembly is deducted (bom.quantity_on_hand decrements from 1 to 0).
           - Payment date is automatically recorded.
           - Big diagonal 'PAID' stamp watermark is applied in view and PDF.
           - Stamped PDF is refreshed on disk.
        4. Send invoice via email with the PDF attached.
        """
        import os
        from django.core import mail
        from .models import AssemblySale

        # 1000-series assembly that is not built yet
        bom = BOM.objects.create(
            name="Field Gateway Telemetry Unit",
            description="Cellular telemetry node with solar charger",
            sale_price=Decimal("450.00"),
            assembly_number="1000-042",
            quantity_on_hand=0,
        )
        self.assertEqual(bom.quantity_on_hand, 0)

        sale_date = timezone.now().date().isoformat()
        res_create = self.client.post(reverse('sale_create'), {
            'invoice_number': 'INV-9001',
            'invoice_date': sale_date,
            'status': 'UNPAID',
            'customer_name': 'Granary Watch',
            'customer_address': '11940 52 St NW, Edmonton, AB T5J 3J6',
            'customer_phone': '780.901.9315',
            'customer_email': 'michael@granarywatch.com',
            'payment_method': 'E-Transfer',
            'payment_date': '',
            'notes': 'Fabricating custom enclosures.',
            'item_bom[]': [str(bom.pk)],
            'item_number[]': [bom.assembly_number],
            'item_description[]': [bom.name],
            'item_quantity[]': ['1'],
            'item_unit_price[]': ['450.00'],
        })
        self.assertEqual(res_create.status_code, 302)

        sale = AssemblySale.objects.get(invoice_number='INV-9001')
        self.assertEqual(sale.status, 'UNPAID')
        self.assertFalse(sale.stock_deducted)
        self.assertFalse(sale.is_paid)

        # Inventory must NOT be deducted while unpaid
        bom.refresh_from_db()
        self.assertEqual(bom.quantity_on_hand, 0)

        # PDF must be generated and saved to media/invoices/
        self.assertTrue(sale.pdf_file)
        self.assertTrue(os.path.exists(sale.pdf_file.path))

        # Detail view shows UNPAID status
        res_detail = self.client.get(reverse('sale_detail', kwargs={'pk': sale.pk}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, 'UNPAID / OPEN')
        self.assertContains(res_detail, 'Mark as Paid &amp; Close Invoice')

        # 2. Assembly is now built in production
        bom.quantity_on_hand = 1
        bom.save(update_fields=['quantity_on_hand'])

        # 3. Mark invoice as PAID & close it
        res_mark = self.client.post(reverse('sale_mark_paid', kwargs={'pk': sale.pk}))
        self.assertEqual(res_mark.status_code, 302)

        sale.refresh_from_db()
        self.assertEqual(sale.status, 'PAID')
        self.assertTrue(sale.stock_deducted)
        self.assertTrue(sale.is_paid)
        self.assertEqual(sale.payment_date, timezone.now().date())

        # Built assembly is now deducted from 1 to 0
        bom.refresh_from_db()
        self.assertEqual(bom.quantity_on_hand, 0)

        # Detail view shows Paid & Closed status and watermark
        res_detail_paid = self.client.get(reverse('sale_detail', kwargs={'pk': sale.pk}))
        self.assertEqual(res_detail_paid.status_code, 200)
        self.assertContains(res_detail_paid, 'is Paid &amp; Closed')
        self.assertContains(res_detail_paid, 'paid-stamp-watermark')
        self.assertContains(res_detail_paid, 'PAID')

        # PDF serves correctly
        res_pdf = self.client.get(reverse('sale_pdf', kwargs={'pk': sale.pk}))
        self.assertEqual(res_pdf.status_code, 200)
        self.assertEqual(res_pdf['Content-Type'], 'application/pdf')

        # 4. Email invoice with PDF attachment
        res_email = self.client.post(reverse('sale_send_email', kwargs={'pk': sale.pk}), {
            'recipient': 'michael@granarywatch.com',
            'subject': 'Your Paid Invoice INV-9001',
            'message': 'Thank you for your business!',
        })
        self.assertEqual(res_email.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.subject, 'Your Paid Invoice INV-9001')
        self.assertIn('michael@granarywatch.com', sent_email.to)
        self.assertEqual(len(sent_email.attachments), 1)
        self.assertEqual(sent_email.attachments[0][0], 'Invoice_INV-9001.pdf')

    def test_assemblies_visible_as_1000_prefix_parts_in_catalog_and_inventory(self):
        """
        Tests that:
        1. Built/Product Assemblies are represented as Part objects with prefix '1000'
           under Category 'Assemblies'.
        2. They are visible in the Parts Catalog (/parts/) and can be filtered by Category or searched by '1000'.
        3. They appear in the Take Inventory Sheet (/inventory/take-inventory/) under Category '[1000] Assemblies'.
        4. Building or adjusting stock increases both bom.quantity_on_hand and part.quantity_on_hand.
        5. Adjusting on-hand in Take Inventory syncs both Part and BOM.
        """
        from .models import BOM, Part, Category

        # Create BOM with assembly number 1000-010
        bom = BOM.objects.create(
            name="Smart Soil Moisture Probe",
            description="RS485 Modbus Soil Probe Assembly",
            sale_price=Decimal("120.00"),
            assembly_number="1000-010",
            quantity_on_hand=0,
        )

        # BOM.sync_part() should automatically create the Part in Category [1000] Assemblies
        self.assertIsNotNone(bom.part)
        part = bom.part
        self.assertEqual(part.part_number, "1000-010")
        self.assertEqual(part.name, "Smart Soil Moisture Probe")
        self.assertEqual(part.category.prefix, "1000")
        self.assertEqual(part.category.name, "Assemblies")
        self.assertEqual(part.quantity_on_hand, 0)

        # Verify visible in Parts Catalog (/parts/)
        res_catalog = self.client.get(reverse('part_list'))
        self.assertEqual(res_catalog.status_code, 200)
        self.assertContains(res_catalog, '1000-010')
        self.assertContains(res_catalog, 'Smart Soil Moisture Probe')
        self.assertContains(res_catalog, 'Assemblies')

        # Verify search by '1000'
        res_search = self.client.get(reverse('part_list') + '?q=1000')
        self.assertEqual(res_search.status_code, 200)
        self.assertContains(res_search, '1000-010')

        # Verify in Take Inventory sheet (/inventory/take-inventory/)
        res_take_inv = self.client.get(reverse('take_inventory'))
        self.assertEqual(res_take_inv.status_code, 200)
        self.assertContains(res_take_inv, '1000-010')
        self.assertContains(res_take_inv, 'Assemblies')

        # Verify in Count Sheet (/inventory/count-sheet/)
        res_sheet = self.client.get(reverse('inventory_count_sheet'))
        self.assertEqual(res_sheet.status_code, 200)
        self.assertContains(res_sheet, '1000-010')

        # Build assembly (+3 units) via bom_adjust_assembly_stock
        res_adjust = self.client.post(reverse('bom_adjust_assembly_stock', kwargs={'pk': bom.pk}), {
            'mode': 'add',
            'quantity': 3,
        })
        self.assertEqual(res_adjust.status_code, 302)

        bom.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual(bom.quantity_on_hand, 3)
        self.assertEqual(part.quantity_on_hand, 3)
        self.assertEqual(part.quantity_availible, 3)

        # Audit and adjust physical count in Take Inventory to 5
        res_inv_post = self.client.post(reverse('take_inventory'), {
            f'actual_count_{part.pk}': '5',
            f'reason_{part.pk}': 'Found 2 extra finished assemblies in bin',
        })
        self.assertEqual(res_inv_post.status_code, 302)

        part.refresh_from_db()
        bom.refresh_from_db()
        self.assertEqual(part.quantity_on_hand, 5)
        self.assertEqual(bom.quantity_on_hand, 5)


class IdeasFeaturesTestCase(TestCase):
    """
    Tests for recent enhancement requests:
    1. Orders can be edited until closed (RECEIVED or CANCELLED), then locked/fixed.
    2. Orders record how they were paid (payment_method, payment_reference, payment_date).
    3. Duplicating parts defaults inventory quantities to 0.
    4. Adjusting inventory quantities requires a reason and saves an adjustment record.
    """
    def setUp(self):
        self.client = Client()
        self.supplier = Company.objects.create(
            name="Mouser Electronics",
            contact_name="Support",
            email="support@mouser.com"
        )
        self.category = Category.objects.create(name="Passives", prefix="200")
        self.part = Part.objects.create(
            part_number="200-001",
            name="10k Resistor 0805",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=50,
            quantity_on_order=100,
            quantity_committed=10,
            quantity_availible=40,
            price_per=Decimal("0.05")
        )

    def test_open_order_can_be_edited(self):
        """Open order (e.g. ORDERED) can be edited via OrderUpdateView."""
        order = Order.objects.create(
            order_number="PO-TEST-OPEN",
            supplier=self.supplier,
            status='ORDERED',
            payment_method='CREDIT_CARD',
        )
        url = reverse('order_update', kwargs={'pk': order.pk})
        res_get = self.client.get(url)
        self.assertEqual(res_get.status_code, 200)

        res_post = self.client.post(url, {
            'supplier': self.supplier.pk,
            'order_number': 'PO-TEST-OPEN',
            'order_date': timezone.now().date().isoformat(),
            'status': 'PARTIALLY_RECEIVED',
            'payment_method': 'COMPANY_CARD',
            'payment_reference': 'Card *4821',
        })
        self.assertEqual(res_post.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, 'PARTIALLY_RECEIVED')
        self.assertEqual(order.payment_method, 'COMPANY_CARD')
        self.assertEqual(order.payment_reference, 'Card *4821')

    def test_closed_order_is_locked_from_edit_and_delete(self):
        """Closed orders (RECEIVED or CANCELLED) cannot be edited or deleted."""
        closed_order = Order.objects.create(
            order_number="PO-TEST-CLOSED",
            supplier=self.supplier,
            status='RECEIVED',
            payment_method='WIRE',
        )
        self.assertTrue(closed_order.is_closed)

        # GET order_update should redirect with error
        update_url = reverse('order_update', kwargs={'pk': closed_order.pk})
        res_get = self.client.get(update_url)
        self.assertEqual(res_get.status_code, 302)
        self.assertRedirects(res_get, reverse('order_detail', kwargs={'pk': closed_order.pk}))

        # POST order_update should be blocked
        res_post = self.client.post(update_url, {
            'supplier': self.supplier.pk,
            'order_number': 'PO-TEST-CLOSED',
            'order_date': timezone.now().date().isoformat(),
            'status': 'ORDERED',
        })
        self.assertEqual(res_post.status_code, 302)
        closed_order.refresh_from_db()
        self.assertEqual(closed_order.status, 'RECEIVED')

        # DELETE order_delete should be blocked
        delete_url = reverse('order_delete', kwargs={'pk': closed_order.pk})
        res_del = self.client.post(delete_url)
        self.assertEqual(res_del.status_code, 302)
        self.assertTrue(Order.objects.filter(pk=closed_order.pk).exists())

    def test_closed_order_items_cannot_be_added_or_removed(self):
        """Cannot add or remove items on a closed order."""
        closed_order = Order.objects.create(
            order_number="PO-TEST-CLOSED-ITEMS",
            supplier=self.supplier,
            status='RECEIVED',
        )
        item = OrderItem.objects.create(
            order=closed_order,
            part=self.part,
            quantity=10,
            quantity_received=10,
        )

        # Attempt to add new item
        add_url = reverse('order_item_create', kwargs={'order_pk': closed_order.pk})
        res_add = self.client.post(add_url, {
            'part': str(self.part.pk),
            'quantity': 5,
        })
        self.assertEqual(res_add.status_code, 302)
        self.assertEqual(closed_order.items.count(), 1)

        # Attempt to delete existing item
        del_item_url = reverse('order_item_delete', kwargs={'pk': item.pk})
        res_del = self.client.post(del_item_url)
        self.assertEqual(res_del.status_code, 302)
        self.assertTrue(OrderItem.objects.filter(pk=item.pk).exists())

    def test_order_records_payment_details(self):
        """Purchase order correctly records payment method, reference, and date."""
        today = timezone.now().date()
        res = self.client.post(reverse('order_create'), {
            'supplier': self.supplier.pk,
            'order_number': 'PO-TEST-PAYMENT',
            'order_date': today.isoformat(),
            'status': 'ORDERED',
            'payment_method': 'NET_30',
            'payment_reference': 'INV-98234-NET30',
            'payment_date': today.isoformat(),
            'payment_notes': 'Net 30 days payable on receipt',
            'item_part': [self.part.pk],
            'item_quantity': [20],
            'item_unit_price': ['0.05'],
            'item_notes': ['Reel'],
        })
        self.assertEqual(res.status_code, 302)
        order = Order.objects.get(order_number='PO-TEST-PAYMENT')
        self.assertEqual(order.payment_method, 'NET_30')
        self.assertEqual(order.payment_reference, 'INV-98234-NET30')
        self.assertEqual(order.payment_date, today)
        self.assertEqual(order.payment_notes, 'Net 30 days payable on receipt')

        # Verify on order_detail view
        res_detail = self.client.get(reverse('order_detail', kwargs={'pk': order.pk}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, 'Account / Net 30')
        self.assertContains(res_detail, 'INV-98234-NET30')

    def test_duplicate_part_defaults_stock_quantities_to_zero(self):
        """Duplicating a part pre-fills on-hand, on-order, committed, available as 0."""
        # Test via PartDuplicateView
        dup_url = reverse('part_duplicate', kwargs={'pk': self.part.pk})
        res_dup = self.client.get(dup_url)
        self.assertEqual(res_dup.status_code, 200)
        form = res_dup.context['form']
        self.assertEqual(form.initial.get('quantity_on_hand'), 0)
        self.assertEqual(form.initial.get('quantity_on_order'), 0)
        self.assertEqual(form.initial.get('quantity_committed'), 0)
        self.assertEqual(form.initial.get('quantity_availible'), 0)

        # Test via PartCreateView with ?duplicate=
        create_url = reverse('part_create') + f"?duplicate={self.part.pk}"
        res_create = self.client.get(create_url)
        self.assertEqual(res_create.status_code, 200)
        form2 = res_create.context['form']
        self.assertEqual(form2.initial.get('quantity_on_hand'), 0)
        self.assertEqual(form2.initial.get('quantity_on_order'), 0)
        self.assertEqual(form2.initial.get('quantity_committed'), 0)
        self.assertEqual(form2.initial.get('quantity_availible'), 0)

    def test_inventory_adjustment_requires_reason(self):
        """TakeInventoryView rejects stock count adjustments that omit a reason."""
        self.assertEqual(self.part.quantity_on_hand, 50)

        # Adjust count without reason -> should be rejected and NOT change stock
        res_no_reason = self.client.post(reverse('take_inventory'), {
            f'actual_count_{self.part.pk}': '55',
            f'reason_{self.part.pk}': '',
        })
        self.assertEqual(res_no_reason.status_code, 302)
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_on_hand, 50)
        self.assertEqual(InventoryAdjustment.objects.filter(part=self.part).count(), 0)

        # Adjust count with reason -> succeeds and creates InventoryAdjustment record
        res_with_reason = self.client.post(reverse('take_inventory'), {
            f'actual_count_{self.part.pk}': '55',
            f'reason_{self.part.pk}': 'Cycle count correction, found unopened pack',
        })
        self.assertEqual(res_with_reason.status_code, 302)
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_on_hand, 55)

        adj = InventoryAdjustment.objects.filter(part=self.part).first()
        self.assertIsNotNone(adj)
        self.assertEqual(adj.old_quantity, 50)
        self.assertEqual(adj.new_quantity, 55)
        self.assertEqual(adj.delta, 5)
        self.assertEqual(adj.reason, 'Cycle count correction, found unopened pack')

        # Check that the reason appears on the part detail page in the Journal
        res_detail = self.client.get(reverse('part_detail', kwargs={'pk': self.part.pk}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, 'Cycle count correction, found unopened pack')
        self.assertContains(res_detail, 'Inventory Adjustment')

    def test_superseded_part_propagates_to_boms_and_kits(self):
        """
        When a part is superseded by another part:
        1. All BOM items referencing the old part switch to the replacement part.
        2. Active kit commitments (quantity_committed) transfer to the replacement part.
        """
        part_a = self.part  # 200-001, quantity_committed=10, quantity_on_hand=50, quantity_availible=40
        part_b = Part.objects.create(
            part_number="200-010",
            name="10k Resistor 0805 Upgraded 1%",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=30,
            quantity_on_order=0,
            quantity_committed=0,
            quantity_availible=30,
            price_per=Decimal("0.06")
        )

        bom = BOM.objects.create(name="Control Board", description="Test BOM for supersession")
        bom_item = BOMItem.objects.create(
            bom=bom,
            part=part_a,
            quantity=2,
            reference="R1, R2"
        )

        # Supersede part_a with part_b
        part_a.superseded_by = part_b
        part_a.save()

        # 1. BOM item updated to part_b
        bom_item.refresh_from_db()
        self.assertEqual(bom_item.part, part_b)
        self.assertEqual(bom.items.filter(part=part_a).count(), 0)
        self.assertEqual(bom.items.filter(part=part_b).count(), 1)

        # 2. Kit commitments transferred
        part_a.refresh_from_db()
        part_b.refresh_from_db()
        self.assertEqual(part_a.quantity_committed, 0)
        self.assertEqual(part_a.quantity_availible, 50)
        self.assertEqual(part_b.quantity_committed, 10)
        self.assertEqual(part_b.quantity_availible, 20)

        # 3. Chained supersession: part_b is then superseded by part_c
        part_c = Part.objects.create(
            part_number="200-015",
            name="10k Resistor 0805 Upgraded 0.1%",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=50,
            quantity_on_order=0,
            quantity_committed=0,
            quantity_availible=50,
            price_per=Decimal("0.12")
        )
        part_b.superseded_by = part_c
        part_b.save()

        bom_item.refresh_from_db()
        self.assertEqual(bom_item.part, part_c)
        part_b.refresh_from_db()
        part_c.refresh_from_db()
        self.assertEqual(part_b.quantity_committed, 0)
        self.assertEqual(part_b.quantity_availible, 30)
        self.assertEqual(part_c.quantity_committed, 10)
        self.assertEqual(part_c.quantity_availible, 40)
        self.assertEqual(part_a.get_effective_replacement(), part_c)

    def test_superseded_part_merges_when_replacement_already_in_bom(self):
        """
        When replacement part is already in the BOM, propagate_supersession merges
        quantities and designators instead of violating unique_bom_component.
        """
        part_a = self.part
        part_b = Part.objects.create(
            part_number="200-020",
            name="10k Resistor 0805 Precision",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=20,
            quantity_on_order=0,
            quantity_committed=0,
            quantity_availible=20,
            price_per=Decimal("0.08")
        )

        bom = BOM.objects.create(name="Power Supply", description="BOM with both parts")
        BOMItem.objects.create(
            bom=bom,
            part=part_a,
            quantity=2,
            reference="R1, R2",
            notes="Original tolerance"
        )
        BOMItem.objects.create(
            bom=bom,
            part=part_b,
            quantity=3,
            reference="R3, R4, R5",
            notes="Precision rail"
        )

        part_a.superseded_by = part_b
        part_a.save()

        # Should now have only 1 BOMItem for part_b with merged quantity 5
        self.assertEqual(bom.items.count(), 1)
        merged_item = bom.items.first()
        self.assertEqual(merged_item.part, part_b)
        self.assertEqual(merged_item.quantity, 5)
        self.assertIn("R1, R2", merged_item.reference)
        self.assertIn("R3, R4, R5", merged_item.reference)

    def test_bom_forms_and_views_resolve_superseded_parts(self):
        """
        Adding or creating BOM items with a superseded part automatically resolves
        to the replacement part.
        """
        part_a = self.part
        part_b = Part.objects.create(
            part_number="200-030",
            name="10k Resistor Thin Film",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=15,
            price_per=Decimal("0.10")
        )
        part_a.superseded_by = part_b
        part_a.save()

        bom = BOM.objects.create(name="Sensor Node", description="Test auto-resolution")

        # Test BOMItemCreateView
        add_item_url = reverse('bom_item_create', kwargs={'bom_pk': bom.pk})
        res_item = self.client.post(add_item_url, {
            'bom': bom.pk,
            'part': part_a.pk,
            'quantity': 4,
            'reference': 'R10-R13'
        })
        self.assertEqual(res_item.status_code, 302)
        created_item = bom.items.get(reference='R10-R13')
        self.assertEqual(created_item.part, part_b)

        # Test BOMCreateView with superseded component
        create_bom_url = reverse('bom_create')
        res_bom = self.client.post(create_bom_url, {
            'name': 'Telemetry Board',
            'description': 'Auto-resolved superseded component BOM',
            'item_part': [part_a.pk],
            'item_quantity': [2],
            'item_ref': ['R1, R2'],
            'item_notes': ['Should be part_b'],
        })
        self.assertEqual(res_bom.status_code, 302)
        new_bom = BOM.objects.get(name='Telemetry Board')
        self.assertEqual(new_bom.items.count(), 1)
        self.assertEqual(new_bom.items.first().part, part_b)

    def test_bom_explode_and_separate_out_components(self):
        """
        Adding another BoM to a BoM separates out into its constituent parts:
        e.g. A rechargeable battery BoM (18650, holder, 300-002, 270-006) explodes
        into those 4 distinct component rows.
        """
        # Create the 4 parts mentioned in user request
        p_18650 = Part.objects.create(
            part_number="270-001",
            name="18650 Li-Ion Cell 2600mAh",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=50,
            price_per=Decimal("4.50")
        )
        p_holder = Part.objects.create(
            part_number="270-002",
            name="18650 Battery Holder PCB Mount",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=40,
            price_per=Decimal("0.85")
        )
        p_300_002 = Part.objects.create(
            part_number="300-002",
            name="USB C Connector 16-pin",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=100,
            price_per=Decimal("0.35")
        )
        p_270_006 = Part.objects.create(
            part_number="270-006",
            name="5V Boost Step Up Module USB C",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=30,
            price_per=Decimal("1.25")
        )

        # 1. Create the sub-assembly BOM: "Rechargeable Battery BOM"
        battery_bom = BOM.objects.create(
            name="Rechargeable Battery Pack",
            description="18650 + holder + USB-C + 5V boost module"
        )
        BOMItem.objects.create(bom=battery_bom, part=p_18650, quantity=1, reference="BT1")
        BOMItem.objects.create(bom=battery_bom, part=p_holder, quantity=1, reference="H1")
        BOMItem.objects.create(bom=battery_bom, part=p_300_002, quantity=1, reference="J1")
        BOMItem.objects.create(bom=battery_bom, part=p_270_006, quantity=1, reference="U1")

        # 2. Create the destination BOM: "Field Sensor Assembly"
        dest_bom = BOM.objects.create(
            name="Field Sensor Assembly",
            description="Main node assembly that needs power"
        )
        # Pre-seed with an existing component (e.g. 300-002) to verify quantity merging
        BOMItem.objects.create(bom=dest_bom, part=p_300_002, quantity=1, reference="J2", notes="Aux port")

        # Explode battery_bom into dest_bom with multiplier=2
        result = dest_bom.import_and_explode_bom(battery_bom, multiplier=2)
        self.assertEqual(result['total_components'], 4)
        self.assertEqual(result['added_count'], 3)
        self.assertEqual(result['merged_count'], 1)

        # Verify dest_bom now has all 4 parts
        self.assertEqual(dest_bom.items.count(), 4)
        item_18650 = dest_bom.items.get(part=p_18650)
        self.assertEqual(item_18650.quantity, 2)
        self.assertEqual(item_18650.reference, "BT1")

        item_holder = dest_bom.items.get(part=p_holder)
        self.assertEqual(item_holder.quantity, 2)

        item_270_006 = dest_bom.items.get(part=p_270_006)
        self.assertEqual(item_270_006.quantity, 2)

        # Verify merged item: 1 (existing) + 2 (from explosion) = 3
        item_300_002 = dest_bom.items.get(part=p_300_002)
        self.assertEqual(item_300_002.quantity, 3)
        self.assertIn("J2", item_300_002.reference)
        self.assertIn("J1", item_300_002.reference)

    def test_bom_add_from_bom_action_view_and_json_endpoint(self):
        """Tests the POST view to explode a BoM and the JSON items endpoint."""
        p1 = Part.objects.create(
            part_number="500-001",
            name="Microcontroller IC",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=20,
            price_per=Decimal("3.00")
        )
        p2 = Part.objects.create(
            part_number="500-002",
            name="Crystal 16MHz",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=40,
            price_per=Decimal("0.50")
        )

        sub_bom = BOM.objects.create(name="MCU Sub-Assembly")
        BOMItem.objects.create(bom=sub_bom, part=p1, quantity=1, reference="U1")
        BOMItem.objects.create(bom=sub_bom, part=p2, quantity=2, reference="Y1")

        dest_bom = BOM.objects.create(name="Carrier Board Assembly")

        # Test JSON endpoint
        json_url = reverse('bom_items_json', kwargs={'pk': sub_bom.pk}) + "?multiplier=3"
        res_json = self.client.get(json_url)
        self.assertEqual(res_json.status_code, 200)
        data = res_json.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(len(data['components']), 2)
        self.assertEqual(data['components'][0]['quantity'], 3)
        self.assertEqual(data['components'][1]['quantity'], 6)

        # Test POST action view
        add_url = reverse('bom_add_from_bom', kwargs={'pk': dest_bom.pk})
        res_post = self.client.post(add_url, {
            'source_bom': sub_bom.pk,
            'multiplier': 2
        })
        self.assertEqual(res_post.status_code, 302)
        self.assertRedirects(res_post, reverse('bom_detail', kwargs={'pk': dest_bom.pk}))

        dest_bom.refresh_from_db()
        self.assertEqual(dest_bom.items.count(), 2)
        self.assertEqual(dest_bom.items.get(part=p1).quantity, 2)
        self.assertEqual(dest_bom.items.get(part=p2).quantity, 4)

    def test_bom_item_explode_action_and_modal_switch(self):
        """Tests exploding an existing assembly line item and BOMItemCreateView with explode=1."""
        comp1 = Part.objects.create(
            part_number="600-011",
            name="LED Red 0805",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=100,
            price_per=Decimal("0.05")
        )
        comp2 = Part.objects.create(
            part_number="600-012",
            name="Resistor 330R 0805",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=100,
            price_per=Decimal("0.02")
        )

        led_indicator_bom = BOM.objects.create(name="LED Indicator Module")
        BOMItem.objects.create(bom=led_indicator_bom, part=comp1, quantity=1, reference="D1")
        BOMItem.objects.create(bom=led_indicator_bom, part=comp2, quantity=1, reference="R1")
        assembly_part = led_indicator_bom.sync_part()

        main_bom = BOM.objects.create(name="Control Console")

        # 1. Test BOMItemCreateView with explode=1
        add_item_url = reverse('bom_item_create', kwargs={'bom_pk': main_bom.pk})
        res_add = self.client.post(add_item_url, {
            'bom': main_bom.pk,
            'part': assembly_part.pk,
            'quantity': 2,
            'explode': '1'
        })
        self.assertEqual(res_add.status_code, 302)
        # Since explode was requested, main_bom should have comp1 and comp2, NOT assembly_part!
        self.assertEqual(main_bom.items.count(), 2)
        self.assertFalse(main_bom.items.filter(part=assembly_part).exists())
        self.assertEqual(main_bom.items.get(part=comp1).quantity, 2)
        self.assertEqual(main_bom.items.get(part=comp2).quantity, 2)

        # 2. Test exploding an existing assembly line item via bom_item_explode_action
        second_bom = BOM.objects.create(name="Remote Unit")
        raw_assembly_item = BOMItem.objects.create(bom=second_bom, part=assembly_part, quantity=3)
        self.assertEqual(second_bom.items.count(), 1)

        explode_item_url = reverse('bom_item_explode', kwargs={'pk': raw_assembly_item.pk})
        res_exp = self.client.post(explode_item_url)
        self.assertEqual(res_exp.status_code, 302)

        second_bom.refresh_from_db()
        self.assertEqual(second_bom.items.count(), 2)
        self.assertFalse(second_bom.items.filter(part=assembly_part).exists())
        self.assertEqual(second_bom.items.get(part=comp1).quantity, 3)
        self.assertEqual(second_bom.items.get(part=comp2).quantity, 3)

    def test_bom_create_view_with_multiple_exploded_component_rows(self):
        """Creating a new BoM with multiple component rows (e.g. from exploding a sub-assembly)."""
        p1 = Part.objects.create(
            part_number="270-001-A",
            name="18650 Battery",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=20,
            price_per=Decimal("4.00")
        )
        p2 = Part.objects.create(
            part_number="270-002-A",
            name="Battery Holder",
            company=self.supplier,
            category=self.category,
            quantity_on_hand=30,
            price_per=Decimal("0.80")
        )

        res = self.client.post(reverse('bom_create'), {
            'name': 'Power Pack Device',
            'description': 'Device using exploded battery sub-assembly',
            'item_part[]': [p1.pk, p2.pk],
            'item_quantity[]': ['1', '1'],
            'item_reference[]': ['BT1', 'H1'],
            'item_notes[]': ['Li-Ion', 'PCB Mount'],
        })
        self.assertEqual(res.status_code, 302)
        created_bom = BOM.objects.get(name='Power Pack Device')
        self.assertEqual(created_bom.items.count(), 2)
        self.assertEqual(created_bom.items.get(part=p1).reference, 'BT1')
        self.assertEqual(created_bom.items.get(part=p2).reference, 'H1')

    def test_category_prefix_generation_for_subcategories(self):
        """Subcategories auto-generate the next sequential prefix under their parent."""
        mcu_cat = Category.objects.create(name="Microcontrollers", prefix="230")
        # Next subcategory under 230 should be 231
        prefix_1 = Category.generate_next_prefix(mcu_cat)
        self.assertEqual(prefix_1, "231")

        # Create subcategory RPis leaving prefix empty -> auto-generates 231
        rpi_cat = Category.objects.create(name="RPis", parent=mcu_cat)
        self.assertEqual(rpi_cat.prefix, "231")
        self.assertEqual(rpi_cat.get_prefix(), "231")

        # Next subcategory under 230 should now be 232
        prefix_2 = Category.generate_next_prefix(mcu_cat)
        self.assertEqual(prefix_2, "232")

    def test_move_part_to_new_category_assigns_new_part_number(self):
        """
        When a part is moved to another category (e.g. from Microcontrollers 230
        to subcategory RPis 231), a new sequential part number is automatically found.
        """
        mcu_cat = Category.objects.create(name="MCUs", prefix="230")
        rpi_cat = Category.objects.create(name="Raspberry Pis", prefix="231", parent=mcu_cat)

        part = Part.objects.create(
            part_number="230-003",
            name="Raspberry Pi 4 Model B",
            category=mcu_cat,
            quantity_on_hand=5,
            price_per=Decimal("35.00")
        )

        # 1. Test move via part_move_category_action POST view
        res = self.client.post(reverse('part_move_category', kwargs={'pk': part.pk}), {
            'target_category': rpi_cat.pk,
        })
        self.assertEqual(res.status_code, 302)
        part.refresh_from_db()
        self.assertEqual(part.category, rpi_cat)
        self.assertEqual(part.part_number, "231-001")

        # 2. Add second part in MCUs and move via direct save()
        part2 = Part.objects.create(
            part_number="230-006",
            name="Raspberry Pi ZERO",
            category=mcu_cat,
            quantity_on_hand=10,
        )
        part2.category = rpi_cat
        part2.save()
        part2.refresh_from_db()
        self.assertEqual(part2.part_number, "231-002")

    def test_part_update_view_category_change_renumbers_part(self):
        """Updating part's category in PartUpdateView automatically assigns new part number."""
        cat_a = Category.objects.create(name="Sensors", prefix="250")
        cat_b = Category.objects.create(name="Actuators", prefix="260")

        sensor_part = Part.objects.create(
            part_number="250-001",
            name="Temp Sensor",
            category=cat_a,
            quantity_on_hand=10,
            price_per=Decimal("1.50")
        )

        # POST PartUpdateView changing category to cat_b
        res = self.client.post(reverse('part_update', kwargs={'pk': sensor_part.pk}), {
            'category': cat_b.pk,
            'name': 'Temp Sensor Motorized',
            'quantity_on_hand': 10,
            'part_number': '250-001',  # Left as old PN by form
            'adjustment_reason': 'Category transfer',
        })
        self.assertEqual(res.status_code, 302)
        sensor_part.refresh_from_db()
        self.assertEqual(sensor_part.category, cat_b)
        self.assertEqual(sensor_part.part_number, "260-001")

    def test_category_json_endpoints(self):
        """Tests the category next-part-number and next-prefix JSON endpoints."""
        parent_cat = Category.objects.create(name="Computers", prefix="700")
        Part.objects.create(part_number="700-001", name="PC 1", category=parent_cat)
        Part.objects.create(part_number="700-002", name="PC 2", category=parent_cat)

        # Next part number endpoint
        res_pn = self.client.get(reverse('category_next_part_number', kwargs={'pk': parent_cat.pk}))
        self.assertEqual(res_pn.status_code, 200)
        data_pn = res_pn.json()
        self.assertEqual(data_pn['status'], 'ok')
        self.assertEqual(data_pn['next_part_number'], '700-003')

        # Next subcategory prefix endpoint
        res_pfx = self.client.get(reverse('category_next_prefix', kwargs={'pk': parent_cat.pk}))
        self.assertEqual(res_pfx.status_code, 200)
        data_pfx = res_pfx.json()
        self.assertEqual(data_pfx['status'], 'ok')
        self.assertEqual(data_pfx['suggested_prefix'], '710')


class CategoryHierarchyAndCountSheetFilterTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.supplier = Company.objects.create(name="Mouser Electronics")
        self.loc_main = Location.objects.create(name="Bin A1", code="A1")
        self.loc_other = Location.objects.create(name="Bin B2", code="B2")

        # Category tree:
        # Electronic components (prefix 200)
        #   -> Microcontrollers (prefix 230, parent=Electronic components)
        #        -> RPis (prefix 231, parent=Microcontrollers)
        # Hardware (prefix 500)
        self.cat_electronics = Category.objects.create(name="Electronic components", prefix="200")
        self.cat_micro = Category.objects.create(name="Microcontrollers", prefix="230", parent=self.cat_electronics)
        self.cat_rpis = Category.objects.create(name="RPis", prefix="231", parent=self.cat_micro)
        self.cat_hardware = Category.objects.create(name="Hardware", prefix="500")

        # Parts in each category
        self.part_elec = Part.objects.create(
            part_number="200-001",
            name="Generic Resistor Pack",
            category=self.cat_electronics,
            company=self.supplier,
            location=self.loc_main,
            quantity_on_hand=100
        )
        self.part_micro = Part.objects.create(
            part_number="230-001",
            name="ATmega328",
            category=self.cat_micro,
            company=self.supplier,
            location=self.loc_main,
            quantity_on_hand=25
        )
        self.part_rpi = Part.objects.create(
            part_number="231-001",
            name="Raspberry Pi 4B",
            category=self.cat_rpis,
            company=self.supplier,
            location=self.loc_main,
            quantity_on_hand=10
        )
        self.part_hw = Part.objects.create(
            part_number="500-001",
            name="M3 Screw 10mm",
            category=self.cat_hardware,
            company=self.supplier,
            location=self.loc_other,
            quantity_on_hand=500
        )

    def test_category_family_and_descendants_ids(self):
        """Verifies get_descendant_ids and get_family_ids collect all nested subcategories recursively."""
        # Top-level Electronics should include itself, Microcontrollers, and RPis
        family_elec = Category.get_family_ids(self.cat_electronics.pk)
        self.assertEqual(family_elec, {self.cat_electronics.pk, self.cat_micro.pk, self.cat_rpis.pk})

        # Mid-level Microcontrollers should include itself and RPis
        family_micro = Category.get_family_ids(self.cat_micro.pk)
        self.assertEqual(family_micro, {self.cat_micro.pk, self.cat_rpis.pk})

        # Leaf RPis should only include itself
        family_rpi = Category.get_family_ids(self.cat_rpis.pk)
        self.assertEqual(family_rpi, {self.cat_rpis.pk})

        # Category model instance method get_descendant_ids
        self.assertEqual(self.cat_micro.get_descendant_ids(), {self.cat_micro.pk, self.cat_rpis.pk})
        self.assertEqual(self.cat_micro.get_descendant_ids(include_self=False), {self.cat_rpis.pk})

    def test_hierarchical_categories_ordering_and_labels(self):
        """Verifies Category.get_hierarchical_categories() structures children under parents with dropdown labels."""
        ordered = Category.get_hierarchical_categories()
        ordered_ids = [c.pk for c in ordered]

        # Microcontrollers and RPis must follow Electronic components
        idx_elec = ordered_ids.index(self.cat_electronics.pk)
        idx_micro = ordered_ids.index(self.cat_micro.pk)
        idx_rpi = ordered_ids.index(self.cat_rpis.pk)

        self.assertTrue(idx_elec < idx_micro < idx_rpi)

        # Check dropdown label formatting
        label_elec = self.cat_electronics.dropdown_label
        label_micro = self.cat_micro.dropdown_label
        label_rpi = self.cat_rpis.dropdown_label

        self.assertIn("[200] Electronic components", label_elec)
        self.assertIn("(+ subcategories)", label_elec)
        self.assertIn("↳ [230] Microcontrollers", label_micro)
        self.assertIn("(+ subcategories)", label_micro)
        self.assertIn("↳ [231] RPis", label_rpi)

    def test_part_list_parent_category_filter_includes_subcategories(self):
        """Selecting Microcontrollers on /parts/ must return Microcontrollers AND RPis parts."""
        response = self.client.get(reverse('part_list') + f'?category={self.cat_micro.pk}')
        self.assertEqual(response.status_code, 200)

        parts = list(response.context['parts'])
        part_pks = [p.pk for p in parts]

        self.assertIn(self.part_micro.pk, part_pks)
        self.assertIn(self.part_rpi.pk, part_pks)
        self.assertNotIn(self.part_elec.pk, part_pks)
        self.assertNotIn(self.part_hw.pk, part_pks)
        self.assertEqual(response.context['total_count'], 2)

    def test_part_list_grandparent_category_filter_includes_all_descendants(self):
        """Selecting root Electronic components returns its direct parts, Microcontrollers parts, and RPis parts."""
        response = self.client.get(reverse('part_list') + f'?category={self.cat_electronics.pk}')
        self.assertEqual(response.status_code, 200)

        parts = list(response.context['parts'])
        part_pks = [p.pk for p in parts]

        self.assertIn(self.part_elec.pk, part_pks)
        self.assertIn(self.part_micro.pk, part_pks)
        self.assertIn(self.part_rpi.pk, part_pks)
        self.assertNotIn(self.part_hw.pk, part_pks)
        self.assertEqual(response.context['total_count'], 3)

    def test_count_sheet_parent_category_filter_includes_subcategories(self):
        """Inventory Count Sheet filtered by Microcontrollers includes both Microcontrollers and RPis groups."""
        response = self.client.get(reverse('inventory_count_sheet') + f'?category={self.cat_micro.pk}')
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context['total_parts'], 2)
        group_names = [g['category_name'] for g in response.context['groups']]
        self.assertIn('Microcontrollers', group_names)
        self.assertIn('RPis', group_names)

    def test_part_list_to_count_sheet_filter_forwarding(self):
        """Count Sheet link on /parts/ carries active filters and applies them when opened."""
        # User filters on /parts/ by Microcontrollers and Location A1
        res_parts = self.client.get(reverse('part_list') + f'?category={self.cat_micro.pk}&location={self.loc_main.pk}')
        self.assertEqual(res_parts.status_code, 200)

        count_sheet_url = res_parts.context['count_sheet_url']
        self.assertIn(f"category={self.cat_micro.pk}", count_sheet_url)
        self.assertIn(f"location={self.loc_main.pk}", count_sheet_url)
        self.assertIn("from_parts=1", count_sheet_url)

        # User clicks the Count Sheet link
        res_cs = self.client.get(count_sheet_url)
        self.assertEqual(res_cs.status_code, 200)
        self.assertEqual(res_cs.context['current_category'], str(self.cat_micro.pk))
        self.assertEqual(res_cs.context['current_location'], str(self.loc_main.pk))
        self.assertEqual(res_cs.context['total_parts'], 2)

    def test_count_sheet_csv_export_respects_category_hierarchy_filter(self):
        """CSV export of count sheet includes parent and all subcategory parts."""
        res_csv = self.client.get(reverse('inventory_count_sheet_csv') + f'?category={self.cat_micro.pk}')
        self.assertEqual(res_csv.status_code, 200)
        content = res_csv.content.decode('utf-8')

        self.assertIn("230-001", content)
        self.assertIn("231-001", content)
        self.assertNotIn("200-001", content)
        self.assertNotIn("500-001", content)













