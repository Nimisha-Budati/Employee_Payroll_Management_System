"""Tests for interactive attendance location selection, radius configuration, and employee GPS validation."""

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .models import AttendanceRecord, AttendanceSettings, Company, UserProfile
from .test_utils import test_company


class AttendanceLocationAndRadiusTests(TestCase):
    def setUp(self):
        self.company = test_company()
        self.admin = User.objects.create_user(
            username='admin_loc', email='admin_loc@example.com', password='password123',
        )
        UserProfile.objects.create(user=self.admin, role='ADMIN', company=self.company)

        self.employee = User.objects.create_user(
            username='emp_loc', email='emp_loc@example.com', password='password123',
        )
        UserProfile.objects.create(user=self.employee, role='EMPLOYEE', company=self.company)

        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

        self.employee_client = APIClient()
        self.employee_client.force_authenticate(user=self.employee)

    def test_admin_can_get_and_update_attendance_location_and_radius(self):
        # 1. Admin reads initial settings
        get_res = self.admin_client.get('/api/attendance/settings/')
        self.assertEqual(get_res.status_code, 200)

        # 2. Admin sets custom location (e.g. HITEC City, Hyderabad) with 250m radius and place label
        put_res = self.admin_client.put('/api/attendance/settings/', {
            'latitude': '17.443500',
            'longitude': '78.377200',
            'radius_meters': 250,
            'location_name': 'Tech Park Campus, Hyderabad',
            'is_enabled': True,
        })
        self.assertEqual(put_res.status_code, 200)
        self.assertEqual(put_res.data['latitude'], '17.443500')
        self.assertEqual(put_res.data['longitude'], '78.377200')
        self.assertEqual(put_res.data['radius_meters'], 250)
        self.assertEqual(put_res.data['location_name'], 'Tech Park Campus, Hyderabad')
        self.assertTrue(put_res.data['is_enabled'])

        # 3. Verify settings persist in database
        saved = AttendanceSettings.objects.get(company=self.company)
        self.assertEqual(str(saved.latitude), '17.443500')
        self.assertEqual(str(saved.longitude), '78.377200')
        self.assertEqual(saved.radius_meters, 250)
        self.assertEqual(saved.location_name, 'Tech Park Campus, Hyderabad')
        self.assertTrue(saved.is_enabled)

    def test_attendance_status_endpoint_returns_location_details(self):
        # Configure location
        self.admin_client.put('/api/attendance/settings/', {
            'latitude': '12.971600',
            'longitude': '77.594600',
            'radius_meters': 150,
            'location_name': 'Bangalore HQ',
            'is_enabled': True,
        })

        # Employee reads attendance status
        status_res = self.employee_client.get('/api/attendance/status/')
        self.assertEqual(status_res.status_code, 200)
        data = status_res.data
        self.assertTrue(data['attendance_enabled'])
        self.assertEqual(data['radius_meters'], 150)
        self.assertAlmostEqual(data['latitude'], 12.9716, places=4)
        self.assertAlmostEqual(data['longitude'], 77.5946, places=4)
        self.assertEqual(data['location_name'], 'Bangalore HQ')

    def test_employee_within_radius_can_check_in_and_check_out(self):
        # Admin sets office at 17.443500, 78.377200 with 100m radius
        self.admin_client.put('/api/attendance/settings/', {
            'latitude': '17.443500',
            'longitude': '78.377200',
            'radius_meters': 100,
            'location_name': 'Main Office',
            'is_enabled': True,
        })

        # Employee checks in ~30 metres away (17.443700, 78.377200)
        checkin_res = self.employee_client.post('/api/attendance/check-in/', {
            'latitude': '17.443700',
            'longitude': '78.377200',
        })
        self.assertEqual(checkin_res.status_code, 201)
        self.assertIsNotNone(checkin_res.data['check_in_at'])
        self.assertLessEqual(checkin_res.data['check_in_distance_meters'], 100)

        # Employee checks out within permitted radius
        checkout_res = self.employee_client.post('/api/attendance/check-out/', {
            'latitude': '17.443600',
            'longitude': '78.377200',
        })
        self.assertEqual(checkout_res.status_code, 201)
        self.assertIsNotNone(checkout_res.data['check_out_at'])

    def test_employee_outside_radius_is_rejected_with_clear_message(self):
        # Office at 17.443500, 78.377200 with 50m radius
        self.admin_client.put('/api/attendance/settings/', {
            'latitude': '17.443500',
            'longitude': '78.377200',
            'radius_meters': 50,
            'location_name': 'Downtown Branch',
            'is_enabled': True,
        })

        # Employee is ~10 km away in central Hyderabad (17.385000, 78.486700)
        checkin_res = self.employee_client.post('/api/attendance/check-in/', {
            'latitude': '17.385000',
            'longitude': '78.486700',
        })
        self.assertEqual(checkin_res.status_code, 403)
        self.assertIn('You must be within 50 m', checkin_res.data['detail'])
        self.assertIn('Downtown Branch', checkin_res.data['detail'])

        # No record should be checked in
        self.assertFalse(AttendanceRecord.objects.filter(employee=self.employee).exists())

    def test_invalid_coordinates_are_rejected(self):
        # Latitude out of bounds
        res1 = self.admin_client.put('/api/attendance/settings/', {
            'latitude': '95.000000',
            'longitude': '78.000000',
            'radius_meters': 100,
            'is_enabled': True,
        })
        self.assertEqual(res1.status_code, 400)

        # Longitude out of bounds
        res2 = self.admin_client.put('/api/attendance/settings/', {
            'latitude': '17.000000',
            'longitude': '195.000000',
            'radius_meters': 100,
            'is_enabled': True,
        })
        self.assertEqual(res2.status_code, 400)

    def test_different_companies_have_independent_locations_and_radii(self):
        # Create second company
        company2 = Company.objects.create(name='Second Company', email='company2@example.com')
        admin2 = User.objects.create_user(username='admin2_loc', password='password123')
        UserProfile.objects.create(user=admin2, role='ADMIN', company=company2)

        client2 = APIClient()
        client2.force_authenticate(user=admin2)

        # Company 1 sets location in Mumbai
        self.admin_client.put('/api/attendance/settings/', {
            'latitude': '19.076000',
            'longitude': '72.877700',
            'radius_meters': 100,
            'location_name': 'Mumbai Office',
            'is_enabled': True,
        })

        # Company 2 sets location in Delhi
        client2.put('/api/attendance/settings/', {
            'latitude': '28.613900',
            'longitude': '77.209000',
            'radius_meters': 300,
            'location_name': 'Delhi Office',
            'is_enabled': True,
        })

        # Verify Company 1 settings are unchanged
        c1_settings = AttendanceSettings.objects.get(company=self.company)
        self.assertEqual(str(c1_settings.latitude), '19.076000')
        self.assertEqual(c1_settings.radius_meters, 100)
        self.assertEqual(c1_settings.location_name, 'Mumbai Office')

        # Verify Company 2 settings
        c2_settings = AttendanceSettings.objects.get(company=company2)
        self.assertEqual(str(c2_settings.latitude), '28.613900')
        self.assertEqual(c2_settings.radius_meters, 300)
        self.assertEqual(c2_settings.location_name, 'Delhi Office')
