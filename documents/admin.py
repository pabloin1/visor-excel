from django.contrib import admin

from .models import Document, Version


class VersionInline(admin.TabularInline):
    model = Version
    extra = 0
    fields = ("version_number", "original_filename", "uploaded_at", "sheet_count", "row_count")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at", "version_count")
    search_fields = ("name",)
    inlines = (VersionInline,)
    readonly_fields = ("name", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Versiones")
    def version_count(self, obj):
        return obj.versions.count()


@admin.register(Version)
class VersionAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "document", "version_number", "uploaded_at", "row_count")
    search_fields = ("original_filename", "document__name", "sha256")
    list_filter = ("uploaded_at",)
    readonly_fields = (
        "document", "version_number", "original_filename", "stored_path", "sha256",
        "uploaded_at", "sheet_count", "row_count", "import_options", "schema_info",
        "comparison_keys", "change_summary",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
