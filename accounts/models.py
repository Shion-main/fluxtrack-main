"""Identity and organization (SRS §5)."""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Department(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return f"{self.code} — {self.name}"


class Role(models.TextChoices):
    FACULTY = "faculty", "Faculty"
    CHECKER = "checker", "Checker"
    IFO_ADMIN = "ifo_admin", "IFO Admin"
    HR_ADMIN = "hr_admin", "HR Admin"
    GUARD = "guard", "Guard"
    DEAN = "dean", "Dean"
    SYSTEM_ADMIN = "system_admin", "System Admin"


class User(AbstractUser):
    """
    Each User holds exactly one role and may belong to a Department (§5).
    Identity maps to a Microsoft Entra object id (azure_oid); password login
    stays available for the dev-login stub until Entra is wired (Phase 2).
    """
    azure_oid = models.CharField(max_length=64, unique=True, null=True, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.FACULTY)
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="members"
    )
    profile_photo = models.ImageField(upload_to="profile_photos/", null=True, blank=True)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"
