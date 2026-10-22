from django.db import models


class Document(models.Model):
    name = models.TextField()
    created_at = models.DateTimeField()

    class Meta:
        db_table = "documents"
        ordering = ["-id"]

    def __str__(self):
        return self.name


class Version(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()
    original_filename = models.TextField()
    stored_path = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64, unique=True)
    uploaded_at = models.DateTimeField()
    sheet_count = models.PositiveIntegerField()
    row_count = models.PositiveIntegerField()
    import_options = models.JSONField(null=True, blank=True)
    schema_info = models.JSONField(null=True, blank=True)
    comparison_keys = models.JSONField(null=True, blank=True)
    change_summary = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "versions"
        ordering = ["-version_number", "-id"]
        constraints = [models.UniqueConstraint(fields=["document", "version_number"], name="unique_document_version")]

    def __str__(self):
        return f"{self.document.name} v{self.version_number}"


class VersionContent(models.Model):
    """Durable copy of an original workbook for hosts with ephemeral disks."""

    version = models.OneToOneField(Version, on_delete=models.CASCADE, primary_key=True, related_name="content_record")
    content = models.BinaryField()

    class Meta:
        db_table = "version_contents"


class PendingContent(models.Model):
    """A staged upload that must survive a web service restart."""

    token = models.CharField(max_length=32, primary_key=True)
    content = models.BinaryField()
    created_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "pending_contents"
