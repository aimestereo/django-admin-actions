from typing import Type

from django.shortcuts import redirect
from django.urls import reverse


__all__ = [
    "redirect_to_list_view",
    "get_object_url",
    "get_object_url_from_obj",
]


def redirect_to_list_view(admin: "ModelAdmin"):
    """Return redirect to list view of any ModelAdmin."""
    urlpattern = [url for url in admin.urls if url.name and "changelist" in url.name][0]
    return redirect(f"admin:{urlpattern.name}")


def get_object_url(model: Type["models.Model"], pk: int):
    opts = model._meta
    return reverse(
        f"admin:{opts.app_label}_{opts.model_name}_change", args=(pk,)
    )


def get_object_url_from_obj(obj: "models.Model"):
    return get_object_url(obj.__class__, obj.pk)
