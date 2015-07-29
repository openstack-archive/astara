# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
# Copyright 2015 Akanda, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""SQLAlchemy storage backend."""

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import session as db_session
from oslo_log import log

from akanda.rug.db import api
from akanda.rug.db.sqlalchemy import models

CONF = cfg.CONF
LOG = log.getLogger(__name__)


_FACADE = None


def _create_facade_lazily():
    global _FACADE
    if _FACADE is None:
        _FACADE = db_session.EngineFacade.from_config(CONF)
    return _FACADE


def get_engine():
    facade = _create_facade_lazily()
    return facade.get_engine()


def get_session(**kwargs):
    facade = _create_facade_lazily()
    return facade.get_session(**kwargs)


def get_backend():
    """The backend is this module itself."""
    return Connection()


def model_query(model, *args, **kwargs):
    """Query helper for simpler session usage.

    :param session: if present, the session to use
    """

    session = kwargs.get('session') or get_session()
    query = session.query(model, *args)
    return query


class Connection(api.Connection):
    """SqlAlchemy connection."""

    def __init__(self):
        pass

    def _enable_debug(self, model, uuid, reason=None):
        model.update({
            'uuid': uuid,
            'reason': reason,
        })
        try:
            model.save()
        except db_exc.DBDuplicateEntry:
            pass

    def _disable_debug(self, model=None, uuid=None):
        query = model_query(model)
        query.filter_by(uuid=uuid).delete()

    def _check_debug(self, model, uuid):
        query = model_query(model)
        res = query.filter_by(uuid=uuid).all()
        if not res:
            return (False, None)
        return (True, res[0].reason)

    def _list_debug(self, model):
        res = model_query(model).all()
        return set((r.uuid, r.reason) for r in res)

    def enable_router_debug(self, router_uuid, reason=None):
        self._enable_debug(
            model=models.RouterDebug(),
            uuid=router_uuid,
            reason=reason,
        )

    def disable_router_debug(self, router_uuid):
        self._disable_debug(
            model=models.RouterDebug,
            uuid=router_uuid,
        )

    def router_in_debug(self, router_uuid):
        return self._check_debug(models.RouterDebug, router_uuid)

    def routers_in_debug(self):
        return self._list_debug(models.RouterDebug)

    def enable_tenant_debug(self, tenant_uuid, reason=None):
        self._enable_debug(
            model=models.TenantDebug(),
            uuid=tenant_uuid,
            reason=reason,
        )

    def disable_tenant_debug(self, tenant_uuid):
        self._disable_debug(
            model=models.TenantDebug,
            uuid=tenant_uuid,
        )

    def tenant_in_debug(self, tenant_uuid):
        return self._check_debug(models.TenantDebug, tenant_uuid)

    def tenants_in_debug(self):
        return self._list_debug(models.TenantDebug)

    def _set_global_debug(self, status, reason=None):
        query = model_query(models.GlobalDebug)
        res = query.first()
        if not res:
            gdb = models.GlobalDebug()
            gdb.update({
                'status': status,
                'reason': reason,
            })
            gdb.save()

    def enable_global_debug(self, reason=None):
        gdb = models.GlobalDebug()
        gdb.update({
            'status': 1,
            'reason': reason,
        })
        try:
            gdb.save()
        except db_exc.DBDuplicateEntry:
            pass

    def disable_global_debug(self):
        query = model_query(models.GlobalDebug)
        query.filter_by(status=1).delete()

    def global_debug(self):
        query = model_query(models.GlobalDebug)
        res = query.filter_by(status=1).all()
        if not res:
            return (False, None)
        return (True, res[0].reason)
