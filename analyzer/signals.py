"""
Signals for the analyzer app.

- Resume post_delete: clean up the physical file from storage (R2 / local)
  when a Resume row is hard-deleted, but only if no other Resume row
  references the same file path.
- ResumeAnalysis post_delete: clean up report_pdf from storage when
  an analysis is hard-deleted (e.g., user cascade delete).
"""
import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Resume, ResumeAnalysis

logger = logging.getLogger('analyzer')


@receiver(post_delete, sender=Resume)
def delete_resume_file_from_storage(sender, instance, **kwargs):
    """
    After a Resume is hard-deleted, remove the file from storage.
    Skips deletion if the file field is empty or another Resume row
    references the same physical file (shared via dedup).
    """
    if instance.file:
        # Don't delete if another Resume row points to the same file
        if Resume.objects.filter(file=instance.file.name).exclude(pk=instance.pk).exists():
            logger.info(
                'Skipping file deletion (shared by another resume): %s',
                instance.file.name,
            )
            return
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


@receiver(post_delete, sender=ResumeAnalysis)
def delete_analysis_report_from_storage(sender, instance, **kwargs):
    """
    After a ResumeAnalysis is hard-deleted (e.g., user cascade delete),
    remove the report_pdf from storage. The resume_file is handled by
    the Resume model's own post_delete signal.
    """
    if instance.report_pdf:
        try:
            instance.report_pdf.delete(save=False)
            logger.info(
                'Deleted analysis report from storage: %s (analysis=%s)',
                instance.report_pdf.name, instance.pk,
            )
        except Exception:
            logger.exception(
                'Failed to delete analysis report from storage: %s',
                instance.report_pdf.name,
            )
