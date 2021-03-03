import inspect
from functools import wraps
from typing import Iterable, TYPE_CHECKING, Any, Optional

from django import forms
from django.conf import settings
from django.contrib.admin import ModelAdmin
from django.http import HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import render

from django.template.loader import render_to_string
from django.urls import path, reverse
from typing_extensions import Protocol

from .utils import get_object_url, get_object_url_from_obj, redirect_to_list_view


if TYPE_CHECKING:
    from django.db import models  # noqa


__all__ = ["action", "ActionsModelAdmin", "hide_in_prod"]


def isaction(obj):
    return inspect.ismethod(obj) and hasattr(obj, "__is_action")


class VisibleCallback(Protocol):
    def __call__(
        self, *, view: "ActionsModelAdmin", request, obj: "models.Model", **kwargs
    ) -> bool:
        ...


def always_visible(**kwargs):
    return True


def hide_in_prod(**kwargs):
    return not settings.APPLICATION_ENVIRONMENT.is_production


def action(
    *,
    row=False,
    list=False,
    detail=False,
    name: str = None,
    show_message=True,
    visible: VisibleCallback = always_visible,
):
    """
    Args:
        row: If True, each row in list view will have its own action (right most column)
        list: If True, list view will have action
        detail: if True, detail/change view will have action

        name (str): Action name, that will become button label.
            Defaults to None, (will use function name).
            e.g.: "Decline"

        show_message: If True, auto-generated django message will be shown.
            e.g.: "Action <ActionName> successfully executed"

        visible: Condition to control action visibility (e.g. based on instance state(*)).
            e.g. don't show "Hide" action for already hidden instance, check examples for more.
            Defaults to always_visible.

            (*) self.object and obj will be set only for detail and row actions,
            for list action it will be None.

    Notes:
        Wrapped action can return response (not required).
        e.g.: `HttpResponseRedirect(url)` or `render(request, "template_name")`

        If return None next redirects will be applied:
        * list action: list view
        * row action: instance detail view
        * detail action: instance detail view

    Examples:

        class SimpleActionsView(ActionsModelAdmin):

            # 1. Action "Cancel" will be available in object detail page
            # and in the list view as the right most column
            # (each row will have its own button)

            @action(row=True, detail=True)
            def cancel(self, request, pk):
                some_task.delay()
                return instance

            # 2. List action with custom name

            @action(list=True, name="Fill some values to database")
            def function_name_does_not_matter(self, request):
                some_task.delay()

            # 3. Redirect to another page with filters

            @action(detail=True, show_message=False)
            def show_objects(self, request, pk):
                url = reverse("...")
                url += f"?source_id={pk}"
                return HttpResponseRedirect(url)

            # 4. Visibility condition: don't show "Hide" action for already hidden instance

            @action(
                detail=True,
                visible=lambda obj, **kw: not obj.is_hidden,
            )
            def hide(self, request, pk):
                obj = Model.objects.get(pk=pk)
                obj.hide()

            # 5. Visibility condition: don't show on prod

            @action(list=True, visible=hide_in_prod)
            def only_stage(self, request, pk):
                pass
    """

    def decorator(f):
        readable_name = f.__name__.capitalize().replace("_", " ")

        @wraps(f)
        def inner(self: "ActionsModelAdmin", request, pk=None, *args, **kwargs):
            result = f(self, request, pk, *args, **kwargs)

            if show_message:
                self.generate_action_message(request, inner)

            if isinstance(result, HttpResponseBase):
                return result

            if pk:
                return HttpResponseRedirect(get_object_url(self.model, pk))
            else:
                return redirect_to_list_view(self)

        inner.__is_action = True
        inner.short_description = name or readable_name
        inner.__is_row = row
        inner.__is_list = list
        inner.__is_detail = detail
        inner.__visible = visible

        return inner

    return decorator


class ActionsModelAdmin(ModelAdmin):
    """
    Base class for admin views that allows:

    1. Make ridiculously easy to add new actions
    2. Make a straightforward way to add actions with intermediate
      pages to approve or request additional info from admin

    """

    request: Any
    object: Optional["models.Model"]  # None for list action

    _actions_row = ()
    _actions_list = ()
    _actions_detail = ()

    def __init__(self, *args, **kwargs):
        for name, func in inspect.getmembers(self, predicate=isaction):
            if getattr(func, "__is_row"):
                self._actions_row += (func,)
            if getattr(func, "__is_list"):
                self._actions_list += (func,)
            if getattr(func, "__is_detail"):
                self._actions_detail += (func,)

        super().__init__(*args, **kwargs)

    @property
    def actions_row(self):
        visible_actions = self._get_visible_actions(
            self._actions_row, check_instance=True
        )

        return [f.__name__ for f in visible_actions]

    @property
    def actions_list(self):
        visible_actions = self._get_visible_actions(
            self._actions_list, check_instance=False
        )

        return [f.__name__ for f in visible_actions]

    @property
    def actions_detail(self):
        visible_actions = self._get_visible_actions(
            self._actions_detail, check_instance=True
        )

        return [f.__name__ for f in visible_actions]

    def _get_visible_actions(self, actions, check_instance):
        obj = getattr(self, "object", None)
        if not hasattr(self, "request") or check_instance and obj is None:
            # return all possible actions, e.g. we are inside urls generate
            # or `get_list_display` check if there's a need for column with actions (most right)
            return actions

        return [
            func
            for func in actions
            if getattr(func, "__visible")(view=self, request=self.request, obj=obj)
        ]

    def actions_holder(self, instance):
        """
        Overridden to make conditionally visible actions
        We need to set `self.object`
        """
        self.object = instance

        return render_to_string(
            "admin/change_list_item_object_tools.html",
            context={
                "instance": instance,
                "actions_row": self._get_action_buttons(self.actions_row, instance.pk),
            },
        )

    actions_holder.short_description = ""

    def get_list_display(self, request):
        self.request = request
        if len(self.actions_row) > 0:
            return super().get_list_display(request) + ("actions_holder",)
        return super().get_list_display(request)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        """
        Overridden to make conditionally visible actions
        We need to set `self.object`
        """
        self.request = request
        self.object = self.get_object(request, object_id)

        extra_context = self.add_actions_context(
            extra_context, self.actions_detail, object_id=object_id
        )
        return super().change_view(request, object_id, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        """
        Overridden to make conditionally visible actions
        We need to set `self.object`
        """
        self.request = request
        self.object = None

        extra_context = self.add_actions_context(
            extra_context, self.actions_list, object_id=None
        )
        return super().changelist_view(request, extra_context)

    def add_actions_context(self, extra_context, method_names, object_id):
        return {
            **(extra_context or {}),
            "actions_list": self._get_action_buttons(method_names, object_id),
        }

    def _get_action_buttons(self, method_names, object_id):
        url_args = (object_id,) if object_id else ()

        actions = []
        for method_name in method_names:
            method = getattr(self, method_name)

            actions.append(
                {
                    "title": getattr(method, "short_description", method_name),
                    "path": self._get_url(method_name, url_args),
                }
            )
        return actions

    def _confirmation_view(
        self,
        *,
        request,
        pk,
        entrypoint_action,
        form_valid_callback,
        form_cls=forms.Form,
        html_template_path="admin/intermediate_action.html"
    ):
        form = None
        opts = self.model._meta
        obj = self.get_object(request, pk)
        obj_url = get_object_url_from_obj(obj)

        # All requests here will actually be of type POST
        # so we will need to check for our special key 'apply'
        # rather than the actual request type
        if "apply" in request.POST:
            form = form_cls(request.POST)

            if form.is_valid():
                return form_valid_callback(request, form, obj)

        if not form:
            form = form_cls()

        return render(
            request,
            html_template_path,
            context={
                "action_name": entrypoint_action.__name__,
                "action_short_description": entrypoint_action.short_description,
                "form": form,
                "app_label": opts.app_label,
                "opts": opts,
                "instance": obj,
                "obj_url": obj_url,
            },
        )

    def generate_action_message(self, request, action):
        self.message_user(
            request, f'Action "{action.short_description}" successfully executed'
        )

    def get_urls(self):
        urls = super().get_urls()
        detail_method_names = set(self.actions_row) | set(self.actions_detail)

        return (
            self._generate_urls_for(detail_method_names, detail=True)
            + self._generate_urls_for(self.actions_list, detail=False)
            + urls
        )

    def _generate_urls_for(self, method_names: Iterable[str], detail: bool):
        action_urls = []
        for method_name in method_names:
            method = getattr(self, method_name)
            url_path = method_name

            if detail:
                url_path += "/<int:pk>/"

            action_urls.append(
                path(
                    url_path,
                    self.admin_site.admin_view(method),
                    name=self._get_url_name(method_name),
                )
            )

        return action_urls

    def _get_url_name(self, method_name):
        opts = self.model._meta
        return "%s_%s_%s" % (opts.app_label, opts.model_name, method_name)

    def _get_url(self, method_name, url_args):
        return reverse(
            "%s:%s"
            % (
                self.admin_site.name,
                self._get_url_name(method_name),
            ),
            args=url_args,
        )

    class Media:
        css = {"all": ("css/admin-actions.css",)}
