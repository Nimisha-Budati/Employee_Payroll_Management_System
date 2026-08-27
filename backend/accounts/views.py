from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import UserProfile
import json


@csrf_exempt
def register(request):
    if request.method != 'POST':
        return JsonResponse({
            'error': 'Only POST requests are allowed'
        }, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({
            'error': 'Invalid JSON data'
        }, status=400)

    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    if not username or not email or not password or not confirm_password:
        return JsonResponse({
            'error': 'Please fill in all fields'
        }, status=400)

    if password != confirm_password:
        return JsonResponse({
            'error': 'Passwords do not match'
        }, status=400)

    if User.objects.filter(username=username).exists():
        return JsonResponse({
            'error': 'Username already exists'
        }, status=400)

    if User.objects.filter(email=email).exists():
        return JsonResponse({
            'error': 'Email already exists'
        }, status=400)

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password
    )

    UserProfile.objects.create(
        user=user,
        role='EMPLOYEE'
    )

    return JsonResponse({
        'message': 'Account created successfully'
    }, status=201)


@csrf_exempt
def login_user(request):
    if request.method != 'POST':
        return JsonResponse({
            'error': 'Only POST requests are allowed'
        }, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({
            'error': 'Invalid JSON data'
        }, status=400)

    username = data.get('username', '')
    password = data.get('password', '')
    role = data.get('role', '')

    user = authenticate(
        request,
        username=username,
        password=password
    )

    if user is None:
        return JsonResponse({
            'error': 'Invalid username or password'
        }, status=401)

    try:
        profile = UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        return JsonResponse({
            'error': 'User profile not found'
        }, status=400)

    if profile.role != role:
        return JsonResponse({
            'error': 'Incorrect login type'
        }, status=403)

    login(request, user)

    return JsonResponse({
        'message': 'Login successful',
        'username': user.username,
        'role': profile.role
    })


@csrf_exempt
def logout_user(request):
    logout(request)

    return JsonResponse({
        'message': 'Logout successful'
    })

