from django.urls import path
from . import views

urlpatterns = [
    path(
        "api/shelf-rental/my-shelves/",
        views.MemberShelvesView.as_view(),
        name="MemberShelvesView",
    ),
    path(
        "api/shelf-rental/admin/shelves/",
        views.AdminShelvesView.as_view(),
        name="AdminShelvesView",
    ),
    path(
        "api/shelf-rental/admin/members/search/",
        views.AdminMemberSearch.as_view(),
        name="AdminMemberSearch",
    ),
]
