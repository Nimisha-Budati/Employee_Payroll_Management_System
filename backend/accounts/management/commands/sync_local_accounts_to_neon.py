"""Copy the four approved local PayrollPro accounts into a matching Neon tenant."""

import os
from copy import deepcopy

import dj_database_url
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.db.models import Q
from django.db.utils import ConnectionHandler

from accounts.models import Company, Employee, UserProfile


TARGETS = (
    ('Charan', 'charansrisai@gmail.com', 'ADMIN'),
    ('Nimmi', 'nimmi@gmail.com', 'EMPLOYEE'),
    ('Anitha', 'anitha@gmail.com', 'EMPLOYEE'),
    ('Hasini', 'hasini@gmail.com', 'EMPLOYEE'),
)


class Command(BaseCommand):
    """Management command with deliberately explicit, fail-closed preflight checks."""

    help = 'Safely synchronize four specified local accounts to a Neon database.'

    def add_arguments(self, parser):
        modes = parser.add_mutually_exclusive_group(required=True)
        modes.add_argument('--dry-run', action='store_true', help='Inspect and report; do not write.')
        modes.add_argument('--apply', action='store_true', help='Create the validated records in Neon.')

    def _production_connection(self):
        url = os.environ.get('DATABASE_URL_PRODUCTION', '').strip()
        if not url:
            raise CommandError('DATABASE_URL_PRODUCTION is required; no database was changed.')
        try:
            config = dj_database_url.parse(url, conn_max_age=0, conn_health_checks=True,
                                          ssl_require='neon.tech' in url)
        except Exception:
            raise CommandError('DATABASE_URL_PRODUCTION is invalid; its value was not displayed.')
        if config.get('ENGINE') != 'django.db.backends.postgresql':
            raise CommandError('Production connection must use PostgreSQL.')
        # Normalize URL-derived settings with Django's full per-alias defaults
        # (including TIME_ZONE and TEST settings) before exposing the alias.
        database_settings = ConnectionHandler({
            'default': deepcopy(connections.databases['default']),
            'production': config,
        }).databases['production']
        connections.databases['production'] = database_settings
        return connections['production']

    @staticmethod
    def _single_company(alias, *, lock=False):
        companies = Company.objects.using(alias).filter(name__iexact='Charan', email__iexact='charan@gmail.com')
        if lock:
            companies = companies.select_for_update()
        matches = list(companies)
        if len(matches) != 1:
            raise CommandError(
                f'Expected exactly one Charan company with email charan@gmail.com in {alias}; '
                f'found {len(matches)}. No accounts were synchronized.'
            )
        return matches[0]

    def _read_source(self):
        company = self._single_company('default')
        source_users = {}
        for username, email, role in TARGETS:
            matches = list(User.objects.using('default').filter(username=username, email__iexact=email))
            if len(matches) != 1:
                raise CommandError(f'Expected one local source account for {username}; found {len(matches)}.')
            user = matches[0]
            profile = UserProfile.objects.using('default').filter(user_id=user.pk).first()
            if profile is None or profile.role != role or profile.company_id != company.pk:
                raise CommandError(f'Local profile/company/role validation failed for {username}.')
            employee = Employee.objects.using('default').filter(user_id=user.pk).first()
            if role == 'EMPLOYEE' and (employee is None or employee.company_id != company.pk):
                raise CommandError(f'Local employee record/company validation failed for {username}.')
            if role == 'ADMIN' and employee is not None:
                raise CommandError(f'Unexpected local employee record for administrator {username}.')
            source_users[username] = (user, profile, employee)
        return company, source_users

    def _preflight_destination(self, alias, records, *, lock=False):
        company = self._single_company(alias, lock=lock)
        conflicts = []
        existing = {}
        for username, email, _role in TARGETS:
            users = list(User.objects.using(alias).filter(
                Q(username__iexact=username) | Q(email__iexact=email)
            ).distinct())
            if users:
                conflicts.append(f'account username/email: {username}')
                existing[username] = users
        if conflicts:
            if len(existing) == len(TARGETS) and all(len(existing[name]) == 1 for name, _email, _role in TARGETS):
                target_users = {name: existing[name][0] for name, _email, _role in TARGETS}
                exact = True
                for username, email, role in TARGETS:
                    dest_user = target_users[username]
                    source_user, source_profile, source_employee = records[username]
                    exact = exact and dest_user.username == username and dest_user.email.lower() == email.lower()
                    for field in User._meta.concrete_fields:
                        if field.name != 'id':
                            exact = exact and getattr(dest_user, field.attname) == getattr(source_user, field.attname)
                    dest_profile = UserProfile.objects.using(alias).filter(user_id=dest_user.pk).first()
                    exact = exact and bool(dest_profile and dest_profile.role == role
                                            and dest_profile.company_id == company.pk
                                            and dest_profile.phone == source_profile.phone
                                            and dest_profile.address == source_profile.address
                                            and dest_profile.profile_photo.name == source_profile.profile_photo.name)
                    dest_employee = Employee.objects.using(alias).filter(user_id=dest_user.pk).first()
                    if source_employee is None:
                        exact = exact and dest_employee is None
                    else:
                        exact = exact and bool(dest_employee and dest_employee.company_id == company.pk and all(
                            getattr(dest_employee, field) == getattr(source_employee, field) for field in (
                                'employee_id', 'phone', 'department', 'designation', 'joining_date', 'status',
                                'deactivated_at', 'onboarding_status', 'onboarding_ready_at',
                                'onboarding_completed_at', 'onboarding_note',
                            )
                        ))
                if exact:
                    return company, True
            raise CommandError('Production conflicts found (' + ', '.join(conflicts) + '). No data was changed.')
        source_employee_ids = [records[name][2].employee_id for name, _email, role in TARGETS
                               if role == 'EMPLOYEE']
        if Employee.objects.using(alias).filter(company=company, employee_id__in=source_employee_ids).exists():
            raise CommandError('Production employee ID conflict found. No data was changed.')
        return company, False

    def handle(self, *args, **options):
        self._production_connection()
        _source_company, source_records = self._read_source()
        try:
            if options['apply']:
                with transaction.atomic(using='production'):
                    company, already_synced = self._preflight_destination('production', source_records, lock=True)
                    if already_synced:
                        self.stdout.write(f'Already synchronized: all four accounts match company {company.pk}; no changes made.')
                        return
                    new_users = {}
                    for username, _email, _role in TARGETS:
                        source_user, _profile, _employee = source_records[username]
                        fields = {field.attname: getattr(source_user, field.attname)
                                  for field in User._meta.concrete_fields if field.name != 'id'}
                        user = User(**fields)
                        user.save(using='production', force_insert=True)
                        new_users[username] = user
                    mapped_users = {
                        source_records[name][0].pk: new_users[name]
                        for name, _email, _role in TARGETS
                    }
                    for username, _email, role in TARGETS:
                        _user, profile, employee = source_records[username]
                        UserProfile.objects.using('production').create(
                            user=new_users[username], role=role, phone=profile.phone, address=profile.address,
                            profile_photo=profile.profile_photo.name, company=company,
                        )
                        if employee is not None:
                            Employee.objects.using('production').create(
                                employee_id=employee.employee_id, phone=employee.phone,
                                department=employee.department, designation=employee.designation,
                                joining_date=employee.joining_date, status=employee.status,
                                user=new_users[username], company=company,
                                deactivated_at=employee.deactivated_at,
                                onboarding_status=employee.onboarding_status,
                                onboarding_ready_at=employee.onboarding_ready_at,
                                onboarding_completed_at=employee.onboarding_completed_at,
                                # Preserve this optional relation only when its user is among the copied accounts.
                                onboarding_completed_by=mapped_users.get(employee.onboarding_completed_by_id),
                                onboarding_note=employee.onboarding_note,
                            )
                    self.stdout.write(f'Created 4 users, 4 profiles, and 3 employee records in company {company.pk}.')
                    for username, email, role in TARGETS:
                        self.stdout.write(f'  {username} | {email} | {role}' + (' | Employee' if role == 'EMPLOYEE' else ''))
        except CommandError:
            raise
        except Exception:
            # Keep database exceptions and parameters (which may contain credentials) out of command output.
            raise CommandError('Synchronization failed; the production transaction was rolled back.') from None
        if options['dry_run']:
            company, already_synced = self._preflight_destination('production', source_records)
            if already_synced:
                self.stdout.write(f'Dry run: all four accounts already match company {company.pk}; no changes planned.')
                return
            self.stdout.write(f'Dry run: would create 4 users, 4 profiles, and 3 employee records in company {company.pk}.')
            for username, email, role in TARGETS:
                self.stdout.write(f'  {username} | {email} | {role}' + (' | Employee' if role == 'EMPLOYEE' else ''))
