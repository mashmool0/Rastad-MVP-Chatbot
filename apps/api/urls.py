from django.urls import path

from apps.api import views

urlpatterns = [
    path("message", views.message_view, name="message"),
    path("users", views.users_view, name="users"),
    path("users/<int:user_id>/messages", views.user_messages_view, name="user-messages"),
]
