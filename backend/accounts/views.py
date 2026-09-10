from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from datetime import timedelta
from math import asin, cos, radians, sin, sqrt
import secrets
import json

from .models import AttendanceRecord, AttendanceSettings, UserProfile, PasswordResetOTP, LeaveRequest, Employee, EmployeeDocument, Holiday, WorkFromHomeRequest
from .serializers import AttendanceRecordSerializer, AttendanceSettingsSerializer, EmployeeSerializer, EmployeeDocumentSerializer, HolidaySerializer, LeaveRequestSerializer, ProfileSerializer, WorkFromHomeSerializer
from .permissions import IsAdminUserRole
from rest_framework_simplejwt.tokens import RefreshToken


def _json_body(request):
    try:
        return json.loads(request.body)
    except json.JSONDecodeError:
        return None


def _user_for_identifier(identifier):
    return User.objects.filter(email__iexact=identifier).first() or User.objects.filter(username__iexact=identifier).first()


def _password_error(password, user=None):
    try:
        validate_password(password, user)
    except ValidationError as error:
        return ' '.join(error.messages)
    return None


@csrf_exempt
def register(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST requests are allowed'}, status=405)

    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)

    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')
    role = data.get('role', 'EMPLOYEE').upper()

    if not username or not email or not password or not confirm_password:
        return JsonResponse({'error': 'Please fill in all fields'}, status=400)

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({'error': 'Please enter a valid email address'}, status=400)

    if password != confirm_password:
        return JsonResponse({'error': 'Passwords do not match'}, status=400)

    if role not in ('ADMIN', 'EMPLOYEE'):
        return JsonResponse({'error': 'Invalid account role'}, status=400)

    password_error = _password_error(password)
    if password_error:
        return JsonResponse({'error': password_error}, status=400)

    if User.objects.filter(username=username).exists():
        return JsonResponse({'error': 'Username already exists'}, status=400)

    if User.objects.filter(email=email).exists():
        return JsonResponse({'error': 'Email already exists'}, status=400)

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password
    )

    UserProfile.objects.create(
        user=user,
        role=role
    )

    return JsonResponse({'message': 'Account created successfully'}, status=201)


@csrf_exempt
def login_user(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST requests are allowed'}, status=405)

    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)

    identifier = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', '')
    remember_me = bool(data.get('remember_me'))

    user_record = _user_for_identifier(identifier)
    if user_record is not None and not user_record.is_active:
        return JsonResponse({'error': 'This account is inactive'}, status=403)

    user = authenticate(
        request,
        username=user_record.username if user_record else identifier,
        password=password
    )

    if user is None:
        return JsonResponse({'error': 'Invalid username or password'}, status=401)

    try:
        profile = UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        return JsonResponse({'error': 'User profile not found'}, status=400)

    if profile.role != role:
        return JsonResponse({'error': 'Incorrect login type'}, status=403)

    login(request, user)
    request.session.set_expiry(settings.SESSION_COOKIE_AGE if remember_me else 0)
    refresh = RefreshToken.for_user(user)

    return JsonResponse({
        'message': 'Login successful',
        'username': user.username,
        'email': user.email,
        'role': profile.role,
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'remember_me': remember_me,
    })


@csrf_exempt
def logout_user(request):
    logout(request)
    return JsonResponse({'message': 'Logout successful'})


@csrf_exempt
def request_password_reset(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST requests are allowed'}, status=405)
    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    identifier = data.get('email', '').strip()
    user = _user_for_identifier(identifier)
    if user is None or not user.is_active:
        return JsonResponse({'error': 'No active account was found for that email or username'}, status=404)

    code = f'{secrets.randbelow(1000000):06d}'
    PasswordResetOTP.objects.filter(user=user, verified=False).delete()
    PasswordResetOTP.objects.create(
        user=user,
        reset_token=secrets.token_urlsafe(32),
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    return JsonResponse({'message': 'OTP generated. Enter it to continue.', 'otp': code})


@csrf_exempt
def verify_password_reset(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST requests are allowed'}, status=405)
    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    user = _user_for_identifier(data.get('email', '').strip())
    reset = PasswordResetOTP.objects.filter(user=user, verified=False).order_by('-created_at').first() if user else None
    if reset is None or reset.is_expired():
        return JsonResponse({'error': 'OTP is invalid or expired'}, status=400)
    if reset.attempts >= 5:
        return JsonResponse({'error': 'Too many OTP attempts. Request a new OTP.'}, status=429)
    reset.attempts += 1
    reset.save(update_fields=['attempts'])
    if not check_password(str(data.get('otp', '')), reset.code_hash):
        return JsonResponse({'error': 'OTP is invalid or expired'}, status=400)
    reset.verified = True
    reset.save(update_fields=['verified'])
    return JsonResponse({'message': 'OTP verified', 'reset_token': reset.reset_token})


@csrf_exempt
def reset_password(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST requests are allowed'}, status=405)
    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    reset = PasswordResetOTP.objects.filter(reset_token=data.get('reset_token'), verified=True).select_related('user').first()
    if reset is None or reset.is_expired():
        return JsonResponse({'error': 'Password reset session is invalid or expired'}, status=400)
    password = data.get('password', '')
    if password != data.get('confirm_password', ''):
        return JsonResponse({'error': 'Passwords do not match'}, status=400)
    password_error = _password_error(password, reset.user)
    if password_error:
        return JsonResponse({'error': password_error}, status=400)
    reset.user.set_password(password)
    reset.user.save(update_fields=['password'])
    reset.delete()
    return JsonResponse({'message': 'Password reset successfully'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    current_password = request.data.get('current_password', '')
    new_password = request.data.get('new_password', '')
    if not request.user.check_password(current_password):
        return Response({'error': 'Current password is incorrect'}, status=status.HTTP_400_BAD_REQUEST)
    if new_password != request.data.get('confirm_password', ''):
        return Response({'error': 'Passwords do not match'}, status=status.HTTP_400_BAD_REQUEST)
    password_error = _password_error(new_password, request.user)
    if password_error:
        return Response({'error': password_error}, status=status.HTTP_400_BAD_REQUEST)
    request.user.set_password(new_password)
    request.user.save(update_fields=['password'])
    update_session_auth_hash(request, request.user)
    return Response({'message': 'Password changed successfully'})


# --- LEAVE MANAGEMENT APIs ---

@csrf_exempt
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def leave_list_create(request):
    user = request.user

    # Determine role
    is_admin = user.is_staff or user.is_superuser
    if not is_admin:
        try:
            profile = UserProfile.objects.get(user=user)
            is_admin = (profile.role == 'ADMIN')
        except UserProfile.DoesNotExist:
            is_admin = False

    if request.method == 'GET':
        if is_admin:
            leaves = LeaveRequest.objects.all().order_by('-applied_at')
        else:
            leaves = LeaveRequest.objects.filter(employee=user).order_by('-applied_at')
        serializer = LeaveRequestSerializer(leaves, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        # Employees or Admins can submit leave
        serializer = LeaveRequestSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(employee=user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(['PUT'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def leave_update_status(request, pk):
    try:
        leave_req = LeaveRequest.objects.get(pk=pk)
    except LeaveRequest.DoesNotExist:
        return Response({'detail': 'Leave request not found.'}, status=status.HTTP_404_NOT_FOUND)

    if leave_req.status != 'PENDING':
        return Response({'detail': 'This leave request has already been processed.'}, status=status.HTTP_400_BAD_REQUEST)

    new_status = request.data.get('status')
    if new_status not in ['APPROVED', 'REJECTED']:
        return Response({'detail': 'Status must be APPROVED or REJECTED.'}, status=status.HTTP_400_BAD_REQUEST)

    leave_req.status = new_status
    if new_status == 'REJECTED':
        leave_req.rejection_reason = request.data.get('rejection_reason', '')
    leave_req.save()

    serializer = LeaveRequestSerializer(leave_req)
    return Response(serializer.data, status=status.HTTP_200_OK)


# --- DOCUMENT MANAGEMENT APIs ---

def _is_admin(user):
    return user.is_staff or user.is_superuser or UserProfile.objects.filter(user=user, role='ADMIN').exists()


@csrf_exempt
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def employee_list_create(request):
    if request.method == 'GET':
        employees = Employee.objects.select_related('user').order_by('employee_id')
        return Response(EmployeeSerializer(employees, many=True).data)

    required = ['username', 'email', 'password', 'employee_id', 'phone', 'department', 'designation', 'joining_date']
    missing = [field for field in required if not str(request.data.get(field, '')).strip()]
    if missing:
        return Response({'detail': f'Missing required fields: {", ".join(missing)}'}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(username__iexact=request.data['username']).exists():
        return Response({'detail': 'Username already exists.'}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(email__iexact=request.data['email']).exists():
        return Response({'detail': 'Email already exists.'}, status=status.HTTP_400_BAD_REQUEST)
    if Employee.objects.filter(employee_id=request.data['employee_id']).exists():
        return Response({'detail': 'Employee ID already exists.'}, status=status.HTTP_400_BAD_REQUEST)
    password_error = _password_error(request.data['password'])
    if password_error:
        return Response({'detail': password_error}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(username=request.data['username'], email=request.data['email'], password=request.data['password'])
    UserProfile.objects.create(user=user, role='EMPLOYEE', phone=request.data['phone'])
    employee = Employee.objects.create(
        user=user,
        employee_id=request.data['employee_id'],
        phone=request.data['phone'],
        department=request.data['department'],
        designation=request.data['designation'],
        joining_date=request.data['joining_date'],
    )
    return Response(EmployeeSerializer(employee).data, status=status.HTTP_201_CREATED)


@csrf_exempt
@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def employee_detail(request, pk):
    try:
        employee = Employee.objects.select_related('user').get(pk=pk)
    except Employee.DoesNotExist:
        return Response({'detail': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'DELETE':
        employee.user.is_active = False
        employee.user.save(update_fields=['is_active'])
        employee.status = 'INACTIVE'
        employee.save(update_fields=['status'])
        return Response({'detail': 'Employee deactivated.'})

    serializer = EmployeeSerializer(employee, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    employee = serializer.save()
    if 'status' in request.data:
        employee.user.is_active = request.data['status'] == 'ACTIVE'
        employee.user.save(update_fields=['is_active'])
    return Response(EmployeeSerializer(employee).data)


@csrf_exempt
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def document_list_create(request):
    if request.method == 'GET':
        documents = EmployeeDocument.objects.all() if _is_admin(request.user) else EmployeeDocument.objects.filter(employee=request.user)
        serializer = EmployeeDocumentSerializer(documents.order_by('-uploaded_at'), many=True, context={'request': request})
        return Response(serializer.data)

    if _is_admin(request.user):
        return Response({'detail': 'Administrators review employee documents; they cannot upload them here.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = EmployeeDocumentSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        serializer.save(employee=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def document_delete(request, pk):
    try:
        document = EmployeeDocument.objects.get(pk=pk, employee=request.user)
    except EmployeeDocument.DoesNotExist:
        return Response({'detail': 'Document not found.'}, status=status.HTTP_404_NOT_FOUND)

    if document.status != 'PENDING':
        return Response({'detail': 'Only documents awaiting review can be deleted.'}, status=status.HTTP_400_BAD_REQUEST)
    document.file.delete(save=False)
    document.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_exempt
@api_view(['PUT'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def document_review(request, pk):
    try:
        document = EmployeeDocument.objects.get(pk=pk)
    except EmployeeDocument.DoesNotExist:
        return Response({'detail': 'Document not found.'}, status=status.HTTP_404_NOT_FOUND)

    new_status = request.data.get('status')
    if new_status not in ['VERIFIED', 'REJECTED']:
        return Response({'detail': 'Status must be VERIFIED or REJECTED.'}, status=status.HTTP_400_BAD_REQUEST)
    if new_status == 'REJECTED' and not str(request.data.get('review_note', '')).strip():
        return Response({'detail': 'A rejection reason is required.'}, status=status.HTTP_400_BAD_REQUEST)

    document.status = new_status
    document.review_note = str(request.data.get('review_note', '')).strip()
    document.save()
    return Response(EmployeeDocumentSerializer(document, context={'request': request}).data)


@csrf_exempt
@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def my_profile(request):
    profile, _ = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'role': 'ADMIN' if request.user.is_staff or request.user.is_superuser else 'EMPLOYEE'},
    )
    if request.method == 'GET':
        return Response(ProfileSerializer(profile, context={'request': request}).data)

    serializer = ProfileSerializer(profile, data=request.data, partial=True, context={'request': request})
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- HOLIDAY CALENDAR APIs ---

@csrf_exempt
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def holiday_list_create(request):
    if request.method == 'GET':
        return Response(HolidaySerializer(Holiday.objects.all(), many=True).data)

    if not _is_admin(request.user):
        return Response({'detail': 'Only administrators can manage holidays.'}, status=status.HTTP_403_FORBIDDEN)
    serializer = HolidaySerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def holiday_detail(request, pk):
    try:
        holiday = Holiday.objects.get(pk=pk)
    except Holiday.DoesNotExist:
        return Response({'detail': 'Holiday not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'DELETE':
        holiday.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = HolidaySerializer(holiday, data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- LOCATION-BASED ATTENDANCE APIs ---

def _attendance_settings():
    settings, _ = AttendanceSettings.objects.get_or_create(pk=1)
    return settings


def _distance_in_meters(latitude_one, longitude_one, latitude_two, longitude_two):
    earth_radius = 6371000
    latitude_delta = radians(float(latitude_two) - float(latitude_one))
    longitude_delta = radians(float(longitude_two) - float(longitude_one))
    a = sin(latitude_delta / 2) ** 2 + cos(radians(float(latitude_one))) * cos(radians(float(latitude_two))) * sin(longitude_delta / 2) ** 2
    return round(2 * earth_radius * asin(sqrt(a)))


def _provided_location(data):
    try:
        latitude = float(data.get('latitude'))
        longitude = float(data.get('longitude'))
    except (TypeError, ValueError):
        return None, None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None, None
    return latitude, longitude


@csrf_exempt
@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def attendance_settings(request):
    settings = _attendance_settings()
    if request.method == 'GET':
        return Response(AttendanceSettingsSerializer(settings).data)
    serializer = AttendanceSettingsSerializer(settings, data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def attendance_status(request):
    settings = _attendance_settings()
    today = timezone.localdate()
    record = AttendanceRecord.objects.filter(employee=request.user, date=today).first()
    return Response({
        'date': today,
        'attendance_enabled': settings.is_enabled and settings.latitude is not None and settings.longitude is not None,
        'radius_meters': settings.radius_meters,
        'record': AttendanceRecordSerializer(record).data if record else None,
    })


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def attendance_mark(request, action):
    if _is_admin(request.user):
        return Response({'detail': 'Administrators cannot mark employee attendance.'}, status=status.HTTP_403_FORBIDDEN)
    if action not in ('check-in', 'check-out'):
        return Response({'detail': 'Unsupported attendance action.'}, status=status.HTTP_400_BAD_REQUEST)
    settings = _attendance_settings()
    if not settings.is_enabled or settings.latitude is None or settings.longitude is None:
        return Response({'detail': 'Attendance has not been configured by an administrator.'}, status=status.HTTP_409_CONFLICT)

    latitude, longitude = _provided_location(request.data)
    if latitude is None:
        return Response({'detail': 'A valid GPS location is required.'}, status=status.HTTP_400_BAD_REQUEST)
    distance = _distance_in_meters(settings.latitude, settings.longitude, latitude, longitude)
    if distance > settings.radius_meters:
        return Response({'detail': f'You are {distance} m from the office. You must be within {settings.radius_meters} m to mark attendance.'}, status=status.HTTP_403_FORBIDDEN)

    today = timezone.localdate()
    record, created = AttendanceRecord.objects.get_or_create(employee=request.user, date=today)
    now = timezone.now()
    if action == 'check-in':
        if record.check_in_at:
            return Response({'detail': 'You have already checked in today.'}, status=status.HTTP_409_CONFLICT)
        record.check_in_at = now
        record.check_in_latitude = latitude
        record.check_in_longitude = longitude
        record.check_in_distance_meters = distance
    else:
        if not record.check_in_at:
            if created:
                record.delete()
            return Response({'detail': 'Check in before checking out.'}, status=status.HTTP_409_CONFLICT)
        if record.check_out_at:
            return Response({'detail': 'You have already checked out today.'}, status=status.HTTP_409_CONFLICT)
        record.check_out_at = now
        record.check_out_latitude = latitude
        record.check_out_longitude = longitude
        record.check_out_distance_meters = distance
    record.save()
    return Response(AttendanceRecordSerializer(record).data, status=status.HTTP_201_CREATED)


@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def attendance_list(request):
    selected_date = request.query_params.get('date')
    records = AttendanceRecord.objects.select_related('employee').all()
    if selected_date:
        records = records.filter(date=selected_date)
    return Response(AttendanceRecordSerializer(records, many=True).data)


@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def attendance_history(request):
    try:
        limit = min(max(int(request.query_params.get('limit', 14)), 1), 90)
    except ValueError:
        limit = 14
    records = AttendanceRecord.objects.filter(employee=request.user).select_related('employee')[:limit]
    return Response(AttendanceRecordSerializer(records, many=True).data)


# --- WORK FROM HOME APIs ---

@csrf_exempt
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def wfh_list_create(request):
    if request.method == 'GET':
        requests = WorkFromHomeRequest.objects.all() if _is_admin(request.user) else WorkFromHomeRequest.objects.filter(employee=request.user)
        selected_status = request.query_params.get('status')
        if selected_status:
            requests = requests.filter(status=selected_status)
        return Response(WorkFromHomeSerializer(requests, many=True).data)
    if _is_admin(request.user):
        return Response({'detail': 'Administrators can review WFH requests but cannot create them.'}, status=status.HTTP_403_FORBIDDEN)
    serializer = WorkFromHomeSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        serializer.save(employee=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def wfh_detail(request, pk):
    try:
        item = WorkFromHomeRequest.objects.get(pk=pk)
    except WorkFromHomeRequest.DoesNotExist:
        return Response({'detail': 'WFH request not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'DELETE':
        if item.employee != request.user or item.status != 'PENDING':
            return Response({'detail': 'Only your pending WFH requests can be cancelled.'}, status=status.HTTP_403_FORBIDDEN)
        item.status = 'CANCELLED'; item.save(update_fields=['status', 'updated_at'])
        return Response(WorkFromHomeSerializer(item).data)
    if not _is_admin(request.user):
        return Response({'detail': 'Only administrators can review WFH requests.'}, status=status.HTTP_403_FORBIDDEN)
    if item.status != 'PENDING':
        return Response({'detail': 'This WFH request has already been processed.'}, status=status.HTTP_400_BAD_REQUEST)
    new_status = request.data.get('status')
    if new_status not in ['APPROVED', 'REJECTED']:
        return Response({'detail': 'Status must be APPROVED or REJECTED.'}, status=status.HTTP_400_BAD_REQUEST)
    note = str(request.data.get('admin_note', '')).strip()
    if new_status == 'REJECTED' and not note:
        return Response({'detail': 'A note is required when rejecting a WFH request.'}, status=status.HTTP_400_BAD_REQUEST)
    item.status, item.admin_note = new_status, note
    item.save()
    return Response(WorkFromHomeSerializer(item).data)
