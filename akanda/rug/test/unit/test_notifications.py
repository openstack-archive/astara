import unittest2 as unittest

from akanda.rug import notifications


class TestGetTenantID(unittest.TestCase):

    def test_rpc(self):
        msg = {u'oslo.message': u'{"_context_roles": ["anotherrole", "Member", "admin"], "_context_read_deleted": "no", "args": {"router_id": "f37f31e9-adc2-4712-a002-4ccf0be17a99"}, "_unique_id": "c87303336c7c4bb0b097b3e97bebf7ea", "_context_timestamp": "2013-07-25 13:51:50.791338", "_context_is_admin": false, "version": "1.0", "_context_project_id": "c25992581e574b6485dbfdf39a3df46c", "_context_tenant_id": "c25992581e574b6485dbfdf39a3df46c", "_context_user_id": "472511eedebd4322a26c5fb1f52711ee", "method": "router_deleted"}', u'oslo.version': u'2.0'}  # noqa
        tenant_id = notifications._get_tenant_id_for_message(msg)
        self.assertEquals("c25992581e574b6485dbfdf39a3df46c", tenant_id)

    def test_notification_tenant_id(self):
        msg = {u'_context_roles': [u'anotherrole', u'Member'], u'priority': u'INFO', u'_context_read_deleted': u'no', u'event_type': u'port.create.end', u'timestamp': u'2013-07-25 14:02:55.244126', u'_context_tenant_id': u'c25992581e574b6485dbfdf39a3df46c', u'payload': {u'port': {u'status': u'DOWN', u'name': u'', u'admin_state_up': True, u'network_id': u'c3a30111-dd52-405c-84b2-4d62068e2d35', u'tenant_id': u'c25992581e574b6485dbfdf39a3df46c', u'device_owner': u'', u'mac_address': u'fa:16:3e:f4:81:a9', u'fixed_ips': [{u'subnet_id': u'53d8a76a-3e1a-43e0-975e-83a4b464d18c', u'ip_address': u'192.168.123.3'}], u'id': u'bbd92f5a-5a1d-4ec5-9272-8e4dd5f0c084', u'security_groups': [u'5124be1c-b2d5-47e6-ac62-411a0ea028c8'], u'device_id': u''}}, u'_unique_id': u'8825f8a6ccec4285a7ecfdad7bd53815', u'_context_is_admin': False, u'_context_timestamp': u'2013-07-25 14:02:55.073049', u'_context_user_id': u'472511eedebd4322a26c5fb1f52711ee', u'publisher_id': u'network.akanda', u'message_id': u'bb9bcf1d-1547-4867-b41e-f5298fa10869'}  # noqa
        tenant_id = notifications._get_tenant_id_for_message(msg)
        self.assertEquals('c25992581e574b6485dbfdf39a3df46c', tenant_id)

    def test_notification_project_id(self):
        msg = {u'_context_roles': [u'anotherrole', u'Member'], u'priority': u'INFO', u'_context_read_deleted': u'no', u'event_type': u'port.create.end', u'timestamp': u'2013-07-25 14:02:55.244126', u'payload': {u'port': {u'status': u'DOWN', u'name': u'', u'admin_state_up': True, u'network_id': u'c3a30111-dd52-405c-84b2-4d62068e2d35', u'tenant_id': u'c25992581e574b6485dbfdf39a3df46c', u'device_owner': u'', u'mac_address': u'fa:16:3e:f4:81:a9', u'fixed_ips': [{u'subnet_id': u'53d8a76a-3e1a-43e0-975e-83a4b464d18c', u'ip_address': u'192.168.123.3'}], u'id': u'bbd92f5a-5a1d-4ec5-9272-8e4dd5f0c084', u'security_groups': [u'5124be1c-b2d5-47e6-ac62-411a0ea028c8'], u'device_id': u''}}, u'_unique_id': u'8825f8a6ccec4285a7ecfdad7bd53815', u'_context_is_admin': False, u'_context_project_id': u'c25992581e574b6485dbfdf39a3df46c', u'_context_timestamp': u'2013-07-25 14:02:55.073049', u'_context_user_id': u'472511eedebd4322a26c5fb1f52711ee', u'publisher_id': u'network.akanda', u'message_id': u'bb9bcf1d-1547-4867-b41e-f5298fa10869'}  # noqa
        tenant_id = notifications._get_tenant_id_for_message(msg)
        self.assertEquals('c25992581e574b6485dbfdf39a3df46c', tenant_id)
