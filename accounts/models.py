from django.contrib.auth.models import AbstractUser, BaseUserManager, Permission, Group
from django.db import models


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)

        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)

class Dealership(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    name = models.CharField(help_text='Required. 30 characters or fewer.', max_length=30, verbose_name='dealership name')
    address = models.CharField(help_text='Enter an address of the dealership', max_length=30, verbose_name='dealership address')
    main_phone = models.CharField(help_text='Enter an main phone of the dealership', max_length=20, verbose_name='dealership main phone')
    service_phone = models.CharField(help_text='Enter an service phone of the dealership', max_length=20, verbose_name='dealership service phone')
    bac_code = models.CharField(help_text='Enter an bac code of the dealership', max_length=10, verbose_name='dealership bac code')
    labor_rate = models.DecimalField(max_digits=10, decimal_places=2, help_text='Required. Dollar Amount', null=True, default=0.00)
    labor_options = models.CharField(help_text='Enter an labor option of the dealership', max_length=30, verbose_name='dealership labor option')
    parts_markup = models.CharField(help_text='Enter an parts markup of the dealership', max_length=30, verbose_name='dealership parts markup')
    ev_restriction = models.CharField(help_text='Enter ev restriction of the dealership', max_length=30, verbose_name='dealership ev restriction')
    md_restriction = models.CharField(help_text='Enter md restriction of the dealership', max_length=30, verbose_name='dealership md restriction')
    wrs_billing_rate = models.CharField(help_text='Enter wrs billing rate of the dealership', max_length=30, verbose_name='dealership wrs billing rate')
    wrs_service_plan = models.CharField(help_text='Enter wrs service plan of the dealership', max_length=100, verbose_name='dealership wrs service plan')
    agreement_date = models.DateTimeField(null=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True)
    compliance_enable = models.BooleanField(help_text="Compliance enable filed", default=True)

    # Metadata
    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

class CustomUser(AbstractUser):
    username = None
    email = models.EmailField("email address", unique=True)
    dealership = models.ManyToManyField(
        Dealership,
        blank=True,
        related_name="users",
        verbose_name="dealership",
    )

    receive_daily_report = models.BooleanField(
        default=False,
        help_text="If True, this user will receive the daily report via email."
    )
    daily_report_email = models.EmailField(
        blank=True,
        null=True,
        help_text="Optional override for report delivery email. Defaults to user's primary email."
    )
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.email

    @classmethod
    def create_user(
        cls, email: str, password: str, first_name: str = "", last_name: str = ""
    ):
        user_exist = CustomUser.objects.filter(email=email)
        if user_exist:
            raise ValueError("User already exists")

        user = cls()
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.set_password(password)
        try:
            user.save()
        except IntegrityError:
            raise ValueError("User already exists")

        return user
    
    groups = models.ManyToManyField(
        Group,
        verbose_name="groups",
        blank=True,
        help_text="The groups this user belongs to.",
        related_name="custom_users",
        related_query_name="custom_user",
    )

    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name="user permissions",
        blank=True,
        help_text="Specific permissions for this user.",
        related_name="custom_users",
        related_query_name="custom_user",
    )


