from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Domain, Term


@receiver([post_save, post_delete], sender=Term)
@receiver([post_save, post_delete], sender=Domain)
def clear_term_index(**kwargs):
    from .matcher import invalidate_index

    invalidate_index()
