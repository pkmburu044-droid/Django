from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required

from .forms import (
    CustomUserCreationForm,         
    NonTeachingStaffProfileForm, 
    TeachingStaffProfileForm
)
from .models import NonTeachingStaffProfile, TeachingStaffProfile


def signup_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # Log them in immediately
            return redirect('complete_profile')  # redirect based on role later
    else:
        form = CustomUserCreationForm()

    return render(request, 'users/signup.html', {'form': form})


@login_required
def role_based_redirect(request):
    role = request.user.role
    if role == 'teaching':
        return redirect('teaching_dashboard')
    elif role == 'non_teaching':
        return redirect('non_teaching_dashboard')
    elif role == 'supervisor':
        return redirect('supervisor_dashboard')
    else:
        return redirect('login')

@login_required
def complete_profile(request):
    user = request.user

    if user.role == "teaching":
        profile = TeachingStaffProfile.objects.filter(user=user).first()
        form_class = TeachingStaffProfileForm
    elif user.role == "non_teaching":
        profile = NonTeachingStaffProfile.objects.filter(user=user).first()
        form_class = NonTeachingStaffProfileForm
    else:
        return redirect("role_based_redirect")

    if request.method == "POST":
        form = form_class(request.POST, request.FILES, instance=profile)  # <-- important
        if form.is_valid():
            profile = form.save(commit=False)
            profile.user = user  # assign user just in case
            profile.save()
            return redirect("role_based_redirect")
    else:
        form = form_class(instance=profile)  # <-- important

    return render(request, "users/complete_profile.html", {"form": form})
