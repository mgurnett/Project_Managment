from django.db import migrations


def propagate_all_superseded_parts(apps, schema_editor):
    """
    Scans all parts that have superseded_by set, updates any BOM items currently
    pointing to the superseded part to point to the new replacement part, and
    transfers any active kit commitments from the old part to the replacement part.
    """
    Part = apps.get_model('core', 'Part')
    BOMItem = apps.get_model('core', 'BOMItem')

    superseded_parts = Part.objects.filter(superseded_by__isnull=False)

    for old_part in superseded_parts:
        # Resolve effective replacement
        visited = {old_part.pk}
        curr = old_part.superseded_by
        while curr and curr.superseded_by_id:
            if curr.pk in visited:
                break
            visited.add(curr.pk)
            curr = curr.superseded_by

        if not curr or curr.pk == old_part.pk:
            continue

        replacement = curr
        bom_items = list(BOMItem.objects.filter(part=old_part).select_related('bom'))
        if not bom_items:
            continue

        for item in bom_items:
            bom = item.bom
            # Check how many active kits this BOM has that committed old_part
            other_items = bom.items.exclude(pk=item.pk)
            active_kits = 0
            if other_items.exists():
                active_kits = min(
                    (oi.part.quantity_committed or 0) // max(1, oi.quantity)
                    for oi in other_items
                )
            else:
                active_kits = (old_part.quantity_committed or 0) // max(1, item.quantity)

            # Transfer commitment to replacement part
            if active_kits > 0:
                transfer_units = item.quantity * active_kits
                transfer_units = min(transfer_units, old_part.quantity_committed or 0)
                if transfer_units > 0:
                    old_part.quantity_committed = max(0, (old_part.quantity_committed or 0) - transfer_units)
                    old_part.quantity_availible = max(0, (old_part.quantity_on_hand or 0) - old_part.quantity_committed)
                    old_part.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])

                    replacement.quantity_committed = (replacement.quantity_committed or 0) + transfer_units
                    replacement.quantity_availible = max(0, (replacement.quantity_on_hand or 0) - replacement.quantity_committed)
                    replacement.save(update_fields=['quantity_committed', 'quantity_availible', 'updated_at'])

            # Check if replacement is already in BOM
            existing_new_item = bom.items.filter(part=replacement).first()
            if existing_new_item:
                existing_new_item.quantity += item.quantity
                if item.reference and item.reference not in (existing_new_item.reference or ''):
                    merged_ref = f"{existing_new_item.reference or ''}, {item.reference}".strip(', ')
                    existing_new_item.reference = merged_ref[:50]
                if item.notes and not existing_new_item.notes:
                    existing_new_item.notes = item.notes
                existing_new_item.save(update_fields=['quantity', 'reference', 'notes'])
                item.delete()
            else:
                item.part = replacement
                item.save(update_fields=['part'])


def reverse_propagate(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_order_payment_date_order_payment_method_and_more'),
    ]

    operations = [
        migrations.RunPython(propagate_all_superseded_parts, reverse_propagate),
    ]

