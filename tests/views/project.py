# -*- coding: utf-8 -*-
#
# Copyright (C) Pootle contributors.
#
# This file is a part of the Pootle project. It is distributed under the GPL3
# or later license. See the LICENSE file for a copy of the license and the
# AUTHORS file for copyright and authorship information.

import json
import locale
from urllib import unquote

import pytest

from django.contrib.auth import get_user_model
from django.core.urlresolvers import reverse

from pytest_pootle.suite import view_context_test

from pootle_app.models import Directory
from pootle_app.models.permissions import check_permission
from pootle.core.browser import (
    get_table_headings, make_language_item, make_xlanguage_item,
    make_project_list_item)
from pootle.core.helpers import (
    SIDEBAR_COOKIE_NAME, get_sidebar_announcements_context)
from pootle.core.url_helpers import get_previous_url, get_path_parts
from pootle.core.utils.stats import (get_top_scorers_data,
                                     get_translation_states)
from pootle_misc.checks import get_qualitycheck_list, get_qualitycheck_schema
from pootle_misc.forms import make_search_form
from pootle_project.models import Project, ProjectResource, ProjectSet
from pootle_store.models import Store


def _test_translate_view(project, request, response, kwargs, settings):

    if not request.user.is_superuser:
        assert response.status_code == 403
        return

    ctx = response.context
    kwargs["project_code"] = project.code
    ctx_path = (
        "/projects/%(project_code)s/" % kwargs)
    resource_path = (
        "%(dir_path)s%(filename)s" % kwargs)
    pootle_path = "%s%s" % (ctx_path, resource_path)
    display_priority = False
    view_context_test(
        ctx,
        **dict(
            page="translate",
            has_admin_access=request.user.is_superuser,
            language=None,
            project=project,
            pootle_path=pootle_path,
            ctx_path=ctx_path,
            resource_path=resource_path,
            resource_path_parts=get_path_parts(resource_path),
            editor_extends="projects/base.html",
            check_categories=get_qualitycheck_schema(),
            previous_url=get_previous_url(request),
            display_priority=display_priority,
            cantranslate=check_permission("translate", request),
            cansuggest=check_permission("suggest", request),
            canreview=check_permission("review", request),
            search_form=make_search_form(request=request),
            current_vfolder_pk="",
            POOTLE_MT_BACKENDS=settings.POOTLE_MT_BACKENDS,
            AMAGAMA_URL=settings.AMAGAMA_URL))


def _test_browse_view(project, request, response, kwargs):
    cookie_data = json.loads(
        unquote(response.cookies[SIDEBAR_COOKIE_NAME].value))
    assert cookie_data["foo"] == "bar"
    assert "announcements_projects_%s" % project.code in cookie_data
    ctx = response.context
    kwargs["project_code"] = project.code
    resource_path = (
        "%(dir_path)s%(filename)s" % kwargs)
    project_path = (
        "%s/%s"
        % (kwargs["project_code"], resource_path))
    if not (kwargs["dir_path"] or kwargs["filename"]):
        obj = project
    elif not kwargs["filename"]:
        obj = ProjectResource(
            Directory.objects.live().filter(
                pootle_path__regex="^/.*/%s$" % project_path),
            pootle_path="/projects/%s" % project_path)
    else:
        obj = ProjectResource(
            Store.objects.live().filter(
                pootle_path__regex="^/.*/%s$" % project_path),
            pootle_path="/projects/%s" % project_path)

    item_func = (
        make_xlanguage_item
        if (kwargs["dir_path"]
            or kwargs["filename"])
        else make_language_item)
    items = [
        item_func(item)
        for item
        in obj.get_children_for_user(request.user)
    ]
    items.sort(lambda x, y: locale.strcoll(x['title'], y['title']))

    table_fields = ['name', 'progress', 'total', 'need-translation',
                    'suggestions', 'critical', 'last-updated', 'activity']
    table = {
        'id': 'project',
        'fields': table_fields,
        'headings': get_table_headings(table_fields),
        'items': items}

    if request.user.is_superuser or kwargs.get("language_code"):
        url_action_continue = obj.get_translate_url(state='incomplete')
        url_action_fixcritical = obj.get_critical_url()
        url_action_review = obj.get_translate_url(state='suggestions')
        url_action_view_all = obj.get_translate_url(state='all')
    else:
        (url_action_continue,
         url_action_fixcritical,
         url_action_review,
         url_action_view_all) = [None] * 4

    User = get_user_model()
    top_scorers = User.top_scorers(project=project.code, limit=10)
    assertions = dict(
        page="browse",
        project=project,
        browser_extends="projects/base.html",
        pootle_path="/projects/%s" % project_path,
        resource_path=resource_path,
        resource_path_parts=get_path_parts(resource_path),
        url_action_continue=url_action_continue,
        url_action_fixcritical=url_action_fixcritical,
        url_action_review=url_action_review,
        url_action_view_all=url_action_view_all,
        translation_states=get_translation_states(obj),
        checks=get_qualitycheck_list(obj),
        table=table,
        top_scorers=top_scorers,
        top_scorers_data=get_top_scorers_data(top_scorers, 10),
        stats=obj.data_tool.get_stats(user=request.user),
    )
    sidebar = get_sidebar_announcements_context(
        request, (project, ))
    for k in ["has_sidebar", "is_sidebar_open", "announcements"]:
        assertions[k] = sidebar[0][k]
    view_context_test(ctx, **assertions)


@pytest.mark.django_db
def test_views_project(project_views, settings):
    test_type, project, request, response, kwargs = project_views
    if test_type == "browse":
        _test_browse_view(project, request, response, kwargs)
    elif test_type == "translate":
        _test_translate_view(project, request, response, kwargs, settings)


@pytest.mark.django_db
def test_view_projects_browse(client, request_users):
    user = request_users["user"]
    client.login(
        username=user.username,
        password=request_users["password"])
    response = client.get(reverse("pootle-projects-browse"))
    assert response.cookies["pootle-language"].value == "projects"
    ctx = response.context
    request = response.wsgi_request
    user_projects = Project.accessible_by_user(request.user)
    user_projects = (
        Project.objects.for_user(request.user)
                       .filter(code__in=user_projects))
    obj = ProjectSet(user_projects)
    items = [
        make_project_list_item(project)
        for project in obj.children]
    items.sort(lambda x, y: locale.strcoll(x['title'], y['title']))
    table_fields = [
        'name', 'progress', 'total', 'need-translation',
        'suggestions', 'critical', 'last-updated', 'activity']
    table = {
        'id': 'projects',
        'fields': table_fields,
        'headings': get_table_headings(table_fields),
        'items': items}

    if request.user.is_superuser:
        url_action_continue = obj.get_translate_url(state='incomplete')
        url_action_fixcritical = obj.get_critical_url()
        url_action_review = obj.get_translate_url(state='suggestions')
        url_action_view_all = obj.get_translate_url(state='all')
    else:
        (url_action_continue,
         url_action_fixcritical,
         url_action_review,
         url_action_view_all) = [None] * 4

    User = get_user_model()
    top_scorers = User.top_scorers(limit=10)
    assertions = dict(
        page="browse",
        pootle_path="/projects/",
        resource_path="",
        resource_path_parts=[],
        object=obj,
        table=table,
        browser_extends="projects/all/base.html",
        stats=obj.data_tool.get_stats(user=request.user),
        checks=get_qualitycheck_list(obj),
        top_scorers=top_scorers,
        top_scorers_data=get_top_scorers_data(top_scorers, 10),
        translation_states=get_translation_states(obj),
        url_action_continue=url_action_continue,
        url_action_fixcritical=url_action_fixcritical,
        url_action_review=url_action_review,
        url_action_view_all=url_action_view_all)
    view_context_test(ctx, **assertions)


@pytest.mark.django_db
def test_view_projects_translate(client, settings, request_users):
    user = request_users["user"]
    client.login(
        username=user.username,
        password=request_users["password"])
    response = client.get(reverse("pootle-projects-translate"))

    if not user.is_superuser:
        assert response.status_code == 403
        return

    ctx = response.context
    request = response.wsgi_request
    assertions = dict(
        page="translate",
        has_admin_access=user.is_superuser,
        language=None,
        project=None,
        pootle_path="/projects/",
        ctx_path="/projects/",
        resource_path="",
        resource_path_parts=[],
        editor_extends="projects/all/base.html",
        check_categories=get_qualitycheck_schema(),
        previous_url=get_previous_url(request),
        display_priority=False,
        cantranslate=check_permission("translate", request),
        cansuggest=check_permission("suggest", request),
        canreview=check_permission("review", request),
        search_form=make_search_form(request=request),
        current_vfolder_pk="",
        POOTLE_MT_BACKENDS=settings.POOTLE_MT_BACKENDS,
        AMAGAMA_URL=settings.AMAGAMA_URL)
    view_context_test(ctx, **assertions)
