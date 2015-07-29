# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
# Copyright 2015 Akanda, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
SQLAlchemy models for baremetal data.
"""

from akanda.rug.common.i18n import _

from oslo_config import cfg
from oslo_db import options as db_options
from oslo_db.sqlalchemy import models
import six.moves.urllib.parse as urlparse
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import schema, String
from sqlalchemy.ext.declarative import declarative_base


sql_opts = [
    cfg.StrOpt('mysql_engine',
               default='InnoDB',
               help=_('MySQL engine to use.'))
]

_DEFAULT_SQL_CONNECTION = 'sqlite:///akanda-ruxg.db'


cfg.CONF.register_opts(sql_opts, 'database')
db_options.set_defaults(cfg.CONF, _DEFAULT_SQL_CONNECTION, 'ironic.sqlite')


def table_args():
    engine_name = urlparse.urlparse(cfg.CONF.database.connection).scheme
    if engine_name == 'mysql':
        return {'mysql_engine': cfg.CONF.database.mysql_engine,
                'mysql_charset': "utf8"}
    return None


class AkandaBase(models.TimestampMixin,
                 models.ModelBase):

    metadata = None

    def as_dict(self):
        d = {}
        for c in self.__table__.columns:
            d[c.name] = self[c.name]
        return d

    def save(self, session=None):
        import akanda.rug.db.sqlalchemy.api as db_api

        if session is None:
            session = db_api.get_session()

        super(AkandaBase, self).save(session)

Base = declarative_base(cls=AkandaBase)


class RouterDebug(Base):
    """Represents a router in debug mode."""

    __tablename__ = 'router_debug'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_debug_router0uuid'),
        table_args()
    )
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    reason = Column(String(255), nullable=True)


class TenantDebug(Base):
    """Represents a tenant in debug mode."""

    __tablename__ = 'tenant_debug'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_debug_tenant0uuid'),
        table_args()
    )
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    reason = Column(String(255), nullable=True)


class GlobalDebug(Base):
    """Stores a single row that serves as a status flag for global debug"""

    __tablename__ = 'global_debug'
    __table_args__ = (
        schema.UniqueConstraint('status', name='uniq_global_debug0status'),
        table_args()
    )
    id = Column(Integer, primary_key=True)
    status = Column(Integer)
    reason = Column(String(255), nullable=True)
