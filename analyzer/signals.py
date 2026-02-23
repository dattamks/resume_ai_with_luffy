"""
Signals for the analyzer app.

- Resume post_delete: clean up the physical file from storage (R2 / local)
  when a Resume row is hard-deleted, but only if no other Resume row
  references the same file path.
"""
import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Resume

logger = logging.getLogger('analyzer')


@receiver(post_delete, sender=Resume)
def delete_resume_file_from_storage(sender, instance, **kwargs):
    """
    After a Resume is hard-deleted, remove the file from storage.
    Skips deletion if the file field is empty.
    """
    if instance.file:
        try:
            instance.file.delete(save=False)
            logger.info(
                'Deleted resume file from storage: %s (user=%s)',
                instance.file.name, instance.user_id,
            )
        except Exception:
            logger.exception(
                'Failed to delete resume file from storage: %s',
                instance.file.name,
            )
