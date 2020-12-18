from typing import Type, TYPE_CHECKING

from django.shortcuts import redirect
from django.urls import reverse


if TYPE_CHECKING:
    from django.contrib.admin import ModelAdmin  # noqa
    from django.db import models  # noqa


__all__ = [
    "redirect_to_list_view",
    "get_admin_url",
    "get_object_url",
    "get_object_url_from_obj",
]


def redirect_to_list_view(admin: "ModelAdmin"):
    """Return redirect to list view of any ModelAdmin."""
    urlpattern = [url for url in admin.urls if url.name and "changelist" in url.name][0]
    return redirect(f"admin:{urlpattern.name}")


def get_admin_url(model: Type["models.Model"], method_name="change", args=None, kwargs=None):
    opts = model._meta
    return reverse(f"admin:{opts.app_label}_{opts.model_name}_{method_name}", args=args, kwargs=kwargs)


def get_object_url(model: Type["models.Model"], pk: int):
    return get_admin_url(model, method_name="change", args=(pk,))


def get_object_url_from_obj(obj: "models.Model"):
    return get_admin_url(obj.__class__, method_name="change", args=(obj.pk,))
