from django.urls import path
from . import views

urlpatterns = [
    # Member endpoints
    path(
        "api/shelf-rental/my-shelves/",
        views.MemberShelfRequestView.as_view(),
        name="MemberShelfRequest",
    ),
    # Admin endpoints
    path(
        "api/shelf-rental/admin/shelves/",
        views.AdminShelfManagementView.as_view(),
        name="AdminShelfManagement",
    ),
    path(
        "api/shelf-rental/admin/queue/",
        views.AdminShelfQueueView.as_view(),
        name="AdminShelfQueue",
    ),
    path(
        "api/shelf-rental/admin/members/search/",
        views.MemberSearchView.as_view(),
        name="MemberSearch",
    ),
]
