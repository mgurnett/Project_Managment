import os
import re
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import Company, Category, Part, BOM, BOMItem


class Command(BaseCommand):
    help = "Imports BoMs.ods spreadsheet data into the database (Parts, Companies, BOMs, and Items)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default=os.path.join(settings.BASE_DIR, 'BoMs.ods'),
            help='Path to the BoMs.ods file'
        )

    def handle(self, *args, **options):
        file_path = options['file']
        if not os.path.exists(file_path):
            self.stderr.write(self.style.ERROR(f"File not found: {file_path}"))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(f"Reading ODS file: {file_path}..."))

        sheets = self.extract_ods_sheets(file_path)
        self.stdout.write(self.style.SUCCESS(f"Found {len(sheets)} sheets: {', '.join(sheets.keys())}"))

        # Step 1: Default Categories
        cat_hardware, _ = Category.objects.get_or_create(
            name='Hardware & Mechanical',
            defaults={'prefix': '100', 'description': 'Cables, fasteners, crimps, and structural hardware'}
        )
        cat_compute, _ = Category.objects.get_or_create(
            name='Electronics & Compute',
            defaults={'prefix': '200', 'description': 'Microcontrollers, radios, boards, and compute units'}
        )
        cat_passives, _ = Category.objects.get_or_create(
            name='Passives & Discrete Components',
            defaults={'prefix': '101', 'description': 'Resistors, capacitors, diodes, and passive filters', 'parent': cat_hardware}
        )

        parts_by_number = {}

        # Step 2: Import Master 'Parts list'
        if 'Parts list' in sheets:
            self.stdout.write(self.style.MIGRATE_LABEL("\n--- Importing Master 'Parts list' ---"))
            parts_rows = sheets['Parts list']
            created_parts = 0
            updated_parts = 0

            # Headers: Part number, Description, Company, quantity, Price, Confirmed, Price per, Link, Notes
            for r in parts_rows[1:]:
                if not r or len(r) < 2:
                    continue
                part_num = r[0].strip()
                if not part_num:
                    continue

                desc = r[1].strip() if len(r) > 1 else ''
                company_str = r[2].strip() if len(r) > 2 else ''
                qty_str = r[3].strip() if len(r) > 3 else '1'
                price_str = r[4].strip() if len(r) > 4 else ''
                confirmed_str = r[5].strip() if len(r) > 5 else ''
                price_per_str = r[6].strip() if len(r) > 6 else ''
                link_str = r[7].strip() if len(r) > 7 else ''
                notes_str = r[8].strip() if len(r) > 8 else ''

                # Company lookup
                company = None
                if company_str:
                    company, _ = Company.objects.get_or_create(name=company_str)

                # Quantity & Prices
                qty = self.parse_int(qty_str, default=1)
                price = self.parse_decimal(price_str)
                price_per = self.parse_decimal(price_per_str)
                confirmed = confirmed_str in ['√', '1', 'true', 'True', 'yes', 'Yes', 'x', 'X']

                # Categorization based on Part # prefix
                if part_num.startswith('10'):
                    cat = cat_hardware
                elif part_num.startswith('20'):
                    cat = cat_compute
                else:
                    cat = cat_hardware

                notes_html = f"<p>{notes_str}</p>" if notes_str else None

                existing = Part.objects.filter(description__iexact=desc).first() if desc else None
                if not existing:
                    existing = Part.objects.filter(part_number=part_num).first()

                if existing:
                    part = existing
                    if company and not part.company:
                        part.company = company
                    part.quantity = qty
                    if price is not None:
                        part.price = price
                    if price_per is not None:
                        part.price_per = price_per
                    part.confirmed = confirmed
                    if link_str:
                        part.link = link_str
                    if notes_html and not part.notes:
                        part.notes = notes_html
                    part.save()
                    updated_parts += 1
                else:
                    part = Part.objects.create(
                        part_number=part_num,
                        description=desc or f"Part {part_num}",
                        company=company,
                        category=cat,
                        quantity=qty,
                        price=price,
                        price_per=price_per,
                        confirmed=confirmed,
                        link=link_str,
                        notes=notes_html,
                    )
                    created_parts += 1

                parts_by_number[part_num] = part

            self.stdout.write(self.style.SUCCESS(f"Parts list: {created_parts} created, {updated_parts} updated."))

        # Step 3: Automatically link Superseded Revisions (e.g. 2002.1 -> 2002.2, 2003.1 -> 2003.2)
        self.stdout.write(self.style.MIGRATE_LABEL("\n--- Linking Superseded Part Revisions ---"))
        superseded_count = 0
        all_parts = {p.part_number: p for p in Part.objects.all()}

        for pnum, part in all_parts.items():
            # Check if part is a revision, like '2002.2'
            match = re.match(r"^(\d+)\.(\d+)$", pnum)
            if match:
                base_code = match.group(1)
                rev = int(match.group(2))
                if rev > 1:
                    prev_pnum = f"{base_code}.{rev - 1}"
                    if prev_pnum in all_parts:
                        prev_part = all_parts[prev_pnum]
                        if prev_part.superseded_by != part:
                            prev_part.superseded_by = part
                            prev_part.save(update_fields=['superseded_by'])
                            superseded_count += 1
                            self.stdout.write(f"  ✓ Linked: {prev_part.part_number} is superseded by -> {part.part_number}")

        self.stdout.write(self.style.SUCCESS(f"Superseded links established: {superseded_count}"))

        # Step 4: Import 'tipups' DigiKey Components
        if 'tipups' in sheets:
            self.stdout.write(self.style.MIGRATE_LABEL("\n--- Importing 'Tipups' Components (DigiKey) ---"))
            digikey, _ = Company.objects.get_or_create(
                name='DigiKey',
                defaults={'website': 'https://www.digikey.com', 'contact_name': 'Sales & Support'}
            )
            tipups_rows = sheets['tipups']
            tipups_parts_created = 0

            # Headers: Ref, Component, Specification, Package / Details, DigiKey P#, Notes, Price Per, Quantity, Price
            for r in tipups_rows[1:]:
                if not r or len(r) < 3:
                    continue
                ref = r[0].strip()
                spec = r[2].strip() if len(r) > 2 else ''
                pkg = r[3].strip() if len(r) > 3 else ''
                dk_part_num = r[4].strip() if len(r) > 4 else ''
                notes = r[5].strip() if len(r) > 5 else ''
                price_per = self.parse_decimal(r[6] if len(r) > 6 else '')
                qty = self.parse_int(r[7] if len(r) > 7 else '1', default=1)

                if not spec and not dk_part_num:
                    continue

                full_desc = f"{spec} ({pkg})" if pkg else spec

                # Check if already in Part by supplier_part_number or description
                existing_part = Part.objects.filter(supplier_part_number=dk_part_num).first()
                if not existing_part and dk_part_num:
                    existing_part = Part.objects.filter(description__iexact=full_desc).first()

                if not existing_part:
                    # Categorize tipup component
                    if ref.startswith('U') or ref.startswith('BAR'):
                        cat = cat_compute
                    elif ref.startswith('C') or ref.startswith('R'):
                        cat = cat_passives
                    else:
                        cat = cat_hardware

                    new_part = Part.objects.create(
                        description=full_desc,
                        supplier_part_number=dk_part_num,
                        company=digikey,
                        category=cat,
                        quantity=qty,
                        price_per=price_per,
                        confirmed=True,
                        notes=f"<p>{notes}</p>" if notes else None
                    )
                    tipups_parts_created += 1
                    parts_by_number[f"TIPUP-{ref}"] = new_part
                else:
                    parts_by_number[f"TIPUP-{ref}"] = existing_part

            self.stdout.write(self.style.SUCCESS(f"Tipups DigiKey components imported: {tipups_parts_created} new parts."))

        # Step 5: Import Assembly BOMs
        self.stdout.write(self.style.MIGRATE_LABEL("\n--- Creating BOM Assemblies ---"))

        # Assembly 1: String Assembly
        if 'string' in sheets:
            bom_string, _ = BOM.objects.get_or_create(
                name='String Assembly',
                defaults={
                    'description': 'Hardware string for sensor nodes (based on 5 nodes)',
                    'notes': '<p>Includes aircraft cable, thimbles, crimps, quick links, zip ties, loom covers, and 3-part cables.</p>'
                }
            )
            self.import_bom_items(bom_string, sheets['string'])

        # Assembly 2: Sensor Node Assembly
        if 'Node' in sheets:
            bom_node, _ = BOM.objects.get_or_create(
                name='Sensor Node Assembly',
                defaults={
                    'description': 'Sensor node hardware assembly (based on 5 nodes)',
                    'notes': '<p>Includes case, ESP32-C6-Super mini, sensor board, 20k resistor, armored cable, plug, battery, and antenna.</p>'
                }
            )
            self.import_bom_items(bom_node, sheets['Node'])

        # Assembly 3: Base Station Assembly
        if 'Base_station' in sheets:
            bom_base, _ = BOM.objects.get_or_create(
                name='Base Station Assembly',
                defaults={
                    'description': 'Base station receiver, compute, and gateway unit',
                    'notes': '<p>Includes case, Raspberry Pi 4, ESP32 gateway, antenna, and antenna wiring.</p>'
                }
            )
            self.import_bom_items(bom_base, sheets['Base_station'])

        # Assembly 4: Tipups Wireless Monitor
        if 'tipups' in sheets:
            bom_tipups, _ = BOM.objects.get_or_create(
                name='Tipups Wireless Monitor',
                defaults={
                    'description': 'Ice fishing tip-up continuous radio monitor & display gateway',
                    'notes': '<p>Full electronics BoM with LDO regulator, ESP32-WROOM-32E, MAX7219 driver, LED lightbar, and Li-SOCl2 primary battery.</p>'
                }
            )
            self.import_tipups_bom_items(bom_tipups, sheets['tipups'])

        # Summary Statistics
        self.stdout.write(self.style.SUCCESS(f"\n=========================================="))
        self.stdout.write(self.style.SUCCESS(f"IMPORT COMPLETE!"))
        self.stdout.write(self.style.SUCCESS(f"Total Companies in DB: {Company.objects.count()}"))
        self.stdout.write(self.style.SUCCESS(f"Total Parts in DB:     {Part.objects.count()}"))
        self.stdout.write(self.style.SUCCESS(f"Total BOMs in DB:      {BOM.objects.count()}"))
        self.stdout.write(self.style.SUCCESS(f"Total BOM Items in DB: {BOMItem.objects.count()}"))
        for b in BOM.objects.all():
            self.stdout.write(f"  &bull; {b.name}: {b.items.count()} items | Total Unit Cost: ${b.total_cost:.2f}")
        self.stdout.write(self.style.SUCCESS(f"=========================================="))

    def import_bom_items(self, bom, rows):
        """Imports standard Part # rows into BOMItem."""
        bom.items.all().delete()
        items_count = 0
        for r in rows[1:]:
            if not r or len(r) < 2:
                continue
            part_num = r[0].strip()
            # Stop if total row
            if not part_num or 'total' in part_num.lower() or 'based on' in part_num.lower():
                continue
            qty_str = r[4].strip() if len(r) > 4 else '1'
            qty = self.parse_int(qty_str, default=1)
            desc = r[1].strip() if len(r) > 1 else ''

            part = Part.objects.filter(part_number=part_num).first()
            if not part and desc:
                part = Part.objects.filter(description__icontains=desc).first()

            if part:
                BOMItem.objects.create(
                    bom=bom,
                    part=part,
                    quantity=qty,
                    notes=f"Hardware: {desc}" if desc else ''
                )
                items_count += 1
            else:
                self.stdout.write(self.style.WARNING(f"  [Warning] Part not found for {bom.name}: {part_num} ({desc})"))
        self.stdout.write(self.style.SUCCESS(f"  ✓ {bom.name}: Added {items_count} component line items."))

    def import_tipups_bom_items(self, bom, rows):
        """Imports tipups rows matching by DigiKey P# or Ref."""
        bom.items.all().delete()
        items_count = 0
        for r in rows[1:]:
            if not r or len(r) < 3:
                continue
            ref = r[0].strip()
            spec = r[2].strip() if len(r) > 2 else ''
            pkg = r[3].strip() if len(r) > 3 else ''
            dk_part_num = r[4].strip() if len(r) > 4 else ''
            qty_str = r[7].strip() if len(r) > 7 else '1'
            qty = self.parse_int(qty_str, default=1)
            notes = r[5].strip() if len(r) > 5 else ''

            part = None
            if dk_part_num:
                part = Part.objects.filter(supplier_part_number=dk_part_num).first()
            if not part and spec:
                part = Part.objects.filter(description__icontains=spec).first()

            if part:
                BOMItem.objects.create(
                    bom=bom,
                    part=part,
                    reference=ref,
                    quantity=qty,
                    notes=notes
                )
                items_count += 1
            else:
                self.stdout.write(self.style.WARNING(f"  [Warning] Part not found for {bom.name}: Ref {ref} ({spec})"))
        self.stdout.write(self.style.SUCCESS(f"  ✓ {bom.name}: Added {items_count} component line items."))

    def extract_ods_sheets(self, file_path):
        """Extracts sheets and table rows from an ODS file using zipfile & xml."""
        with zipfile.ZipFile(file_path, 'r') as z:
            content_xml = z.read('content.xml')

        tree = ET.fromstring(content_xml)
        namespaces = {
            'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
            'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
        }

        sheets = {}
        for table in tree.findall('.//table:table', namespaces):
            name = table.attrib.get('{urn:oasis:names:tc:opendocument:xmlns:table:1.0}name', '').strip()
            rows_data = []
            for row in table.findall('table:table-row', namespaces):
                row_vals = []
                for cell in row.findall('table:table-cell', namespaces):
                    repeat = int(cell.attrib.get('{urn:oasis:names:tc:opendocument:xmlns:table:1.0}number-columns-repeated', 1))
                    texts = [p.text for p in cell.findall('text:p', namespaces) if p.text]
                    cell_val = ' '.join(texts).strip() if texts else ''
                    if repeat > 20 and not cell_val:
                        continue
                    for _ in range(min(repeat, 25)):
                        row_vals.append(cell_val)
                while row_vals and not row_vals[-1]:
                    row_vals.pop()
                if row_vals:
                    rows_data.append(row_vals)
            if rows_data:
                sheets[name] = rows_data
        return sheets

    def parse_decimal(self, val_str):
        if not val_str:
            return None
        cleaned = re.sub(r'[^\d.]', '', str(val_str))
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None

    def parse_int(self, val_str, default=0):
        if not val_str:
            return default
        cleaned = re.sub(r'[^\d]', '', str(val_str))
        if not cleaned:
            return default
        try:
            return int(cleaned)
        except ValueError:
            return default
