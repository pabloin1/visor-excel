from django.urls import path

from . import pages, views

app_name = "documents"

urlpatterns = [
    path("", pages.library, name="library"),
    path("upload/", pages.upload, name="upload"),
    path("documents/<int:doc_id>/versions/", pages.document_versions, name="document_versions"),
    path("versions/<int:vid>/", pages.version, name="version"),
    path("versions/<int:vid>/delete/", pages.delete_version, name="delete"),
    path("api/files", views.upload_file, name="upload_file"),
    path("api/documents", views.documents, name="documents"),
    path("api/library", views.library, name="library_api"),
    path("api/versions/<int:vid>", views.version, name="version_api"),
    path("api/versions/<int:vid>/rows", views.version_rows, name="version_rows"),
    path("api/versions/<int:vid>/summary", views.version_summary, name="version_summary"),
    path("api/versions/<int:vid>/changes", views.version_changes, name="version_changes"),
]
