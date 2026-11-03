import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import Company, Category, Part, Order, OrderItem


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
