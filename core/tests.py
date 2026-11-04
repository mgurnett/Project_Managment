import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import Company, Category, Part, Order, OrderItem, BOM, BOMItem


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
            f'actual_count_{self.part_b.pk}': '22',
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





