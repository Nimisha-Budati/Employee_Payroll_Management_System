"""Safety tests for the one-time local-to-Neon account sync command."""
from io import StringIO
from copy import deepcopy
from unittest import TestCase
from unittest.mock import Mock, patch

from django.core.management.base import CommandError
from django.db import connections

from accounts.management.commands.sync_local_accounts_to_neon import Command, TARGETS


class SyncCommandTests(TestCase):
    def test_requires_database_url_production_without_echoing_it(self):
        command = Command()
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(CommandError, 'DATABASE_URL_PRODUCTION is required'):
                command._production_connection()

    def test_production_alias_has_django_defaults_and_dry_run_reaches_preflight(self):
        command = Command()
        command.stdout = StringIO()
        fake_url = 'postgresql://test_user:test_password@localhost:5432/test_neon'
        default_config = deepcopy(connections.databases['default'])
        with patch.dict('os.environ', {'DATABASE_URL_PRODUCTION': fake_url}):
            production = command._production_connection()
            try:
                config = connections.databases['production']
                for key in (
                    'ENGINE', 'NAME', 'USER', 'PASSWORD', 'HOST', 'PORT', 'OPTIONS',
                    'AUTOCOMMIT', 'ATOMIC_REQUESTS', 'CONN_MAX_AGE', 'CONN_HEALTH_CHECKS',
                    'TIME_ZONE', 'TEST',
                ):
                    self.assertIn(key, config)
                self.assertEqual(connections.databases['default'], default_config)
                self.assertIn('TIME_ZONE', config)

                with patch.object(command, '_read_source', return_value=(Mock(), {})), \
                     patch.object(command, '_preflight_destination', return_value=(Mock(pk=4), False)) as preflight:
                    command.handle(dry_run=True, apply=False)
                preflight.assert_called_once_with('production', {})
                self.assertIn('Dry run: would create', command.stdout.getvalue())
            finally:
                production.close()
                connections.databases.pop('production', None)

    def test_company_lookup_requires_a_unique_exact_email_match(self):
        command = Command()
        company = Mock(pk=4)
        with patch('accounts.management.commands.sync_local_accounts_to_neon.Company') as model:
            model.objects.using.return_value.filter.return_value = [company]
            self.assertIs(command._single_company('production'), company)
            model.objects.using.return_value.filter.assert_called_once_with(
                name__iexact='Charan', email__iexact='charan@gmail.com')
            model.objects.using.return_value.filter.return_value = [company, Mock(pk=2)]
            with self.assertRaisesRegex(CommandError, 'found 2'):
                command._single_company('production')

    def test_dry_run_reports_exact_scope_without_creating_records(self):
        command = Command()
        command.stdout = StringIO()
        company = Mock(pk=4)
        with patch.object(command, '_read_source', return_value=(Mock(), {})), \
             patch.object(command, '_production_connection'), \
             patch.object(command, '_preflight_destination', return_value=(company, False)) as preflight, \
             patch('accounts.management.commands.sync_local_accounts_to_neon.User.objects') as users:
            command.handle(dry_run=True, apply=False)
        output = command.stdout.getvalue()
        self.assertIn('4 users, 4 profiles, and 3 employee records', output)
        for username, email, role in TARGETS:
            self.assertIn(f'{username} | {email} | {role}', output)
        preflight.assert_called_once_with('production', {})
        users.create_user.assert_not_called()

    def test_duplicate_conflict_aborts_before_any_write(self):
        command = Command()
        command.stdout = StringIO()
        with patch.object(command, '_read_source', return_value=(Mock(), {})), \
             patch.object(command, '_production_connection'), \
             patch.object(command, '_preflight_destination', side_effect=CommandError('Production conflicts found')) as preflight:
            with self.assertRaisesRegex(CommandError, 'conflicts'):
                command.handle(dry_run=True, apply=False)
        preflight.assert_called_once()

    def test_repeat_apply_of_an_already_synced_set_is_a_no_op(self):
        command = Command()
        command.stdout = StringIO()
        with patch.object(command, '_read_source', return_value=(Mock(), {})), \
             patch.object(command, '_production_connection'), \
             patch.object(command, '_preflight_destination', return_value=(Mock(pk=4), True)), \
             patch('accounts.management.commands.sync_local_accounts_to_neon.transaction.atomic') as atomic, \
             patch('accounts.management.commands.sync_local_accounts_to_neon.User') as users, \
             patch('accounts.management.commands.sync_local_accounts_to_neon.UserProfile') as profiles, \
             patch('accounts.management.commands.sync_local_accounts_to_neon.Employee') as employees:
            command.handle(dry_run=False, apply=True)
        atomic.assert_called_once_with(using='production')
        users.assert_not_called()
        profiles.objects.using.return_value.create.assert_not_called()
        employees.objects.using.return_value.create.assert_not_called()
        self.assertIn('Already synchronized', command.stdout.getvalue())

    def test_apply_failure_exits_atomic_and_reports_rollback_without_details(self):
        command = Command()
        command.stdout = StringIO()
        transaction_context = Mock()
        transaction_context.__enter__ = Mock(return_value=None)
        transaction_context.__exit__ = Mock(return_value=False)
        source_user = Mock(pk=101)
        source_profile = Mock()
        source_employee = Mock()
        records = {'Charan': (source_user, source_profile, None)}
        # The user save fails inside the atomic block, before profile/employee creation.
        with patch.object(command, '_read_source', return_value=(Mock(), records)), \
             patch.object(command, '_production_connection'), \
             patch.object(command, '_preflight_destination', return_value=(Mock(pk=4), False)), \
             patch('accounts.management.commands.sync_local_accounts_to_neon.transaction.atomic',
                   return_value=transaction_context), \
             patch('accounts.management.commands.sync_local_accounts_to_neon.User._meta') as meta, \
             patch('accounts.management.commands.sync_local_accounts_to_neon.User.save',
                   side_effect=RuntimeError('database detail must not escape')), \
             patch('accounts.management.commands.sync_local_accounts_to_neon.UserProfile.objects') as profiles, \
             patch('accounts.management.commands.sync_local_accounts_to_neon.Employee.objects') as employees:
            meta.concrete_fields = [Mock(name='id', attname='id'), Mock(name='username', attname='username')]
            meta.concrete_fields[0].name = 'id'
            meta.concrete_fields[1].name = 'username'
            with self.assertRaisesRegex(CommandError, 'transaction was rolled back') as raised:
                command.handle(dry_run=False, apply=True)
        transaction_context.__exit__.assert_called_once()
        self.assertNotIn('database detail', str(raised.exception))
        profiles.using.return_value.create.assert_not_called()
        employees.using.return_value.create.assert_not_called()
