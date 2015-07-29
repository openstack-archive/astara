# Copyright (c) 2012 NTT DOCOMO, INC.
# All Rights Reserved.
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

"""Akanda Rug DB test base class."""

import os
import shutil

import fixtures
from oslo_config import cfg
from oslo_db.sqlalchemy import enginefacade

from akanda.rug.db import api as dbapi
from akanda.rug.db.sqlalchemy import migration
from akanda.rug.db.sqlalchemy import models
from akanda.rug.test.unit import base


CONF = cfg.CONF

_DB_CACHE = None

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), 'rug_test.db')
CLEAN_TEST_DB_PATH = os.path.join(os.path.dirname(__file__), 'rug_test.db_clean')

def get_engine(connection):
    engine = enginefacade.get_legacy_facade().get_engine()
    return engine


class Database(fixtures.Fixture):
    def __init__(self, db_migrate, sql_connection):
        if sql_connection.startswith('sqlite:///'):
            if os.path.exists(TEST_DB_PATH):
                os.unlink(TEST_DB_PATH)
            if os.path.exists(CLEAN_TEST_DB_PATH):
                os.unlink(CLEAN_TEST_DB_PATH)

            self.setup_sqlite(sql_connection, db_migrate)
            db_migrate.upgrade('head')
        elif sql_connection == "sqlite://":
            conn = self.engine.connect()
            self._DB = "".join(line for line in conn.connection.iterdump())
            self.engine.dispose()
        db_migrate.upgrade('head')
        shutil.copyfile(TEST_DB_PATH, CLEAN_TEST_DB_PATH)

    def setup_sqlite(self, sql_connection, db_migrate):
        self.sql_connection = sql_connection
        self.engine = enginefacade.get_legacy_facade().get_engine()
        self.engine.dispose()
        conn = self.engine.connect()

    def setUp(self):
        super(Database, self).setUp()

        if self.sql_connection == "sqlite://":
            conn = self.engine.connect()
            conn.connection.executescript(self._DB)
            self.addCleanup(self.engine.dispose)
        else:
            shutil.copyfile(CLEAN_TEST_DB_PATH,
                            TEST_DB_PATH)
            self.addCleanup(os.unlink, TEST_DB_PATH)


class DbTestCase(base.RugTestBase):

    def setUp(self):
        super(DbTestCase, self).setUp()
        sql_connection = 'sqlite:///' + TEST_DB_PATH
        self.config(group='database', connection=sql_connection)
        self.dbapi = dbapi.get_instance()

        global _DB_CACHE
        if not _DB_CACHE:
            _DB_CACHE = Database(migration,
                                 sql_connection=sql_connection)
        self.useFixture(_DB_CACHE)
