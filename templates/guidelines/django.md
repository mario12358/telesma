---
tag: django
keywords: django, drf, django rest framework, orm, queryset, migrations, models.py, views, templates, forms, admin, pytest-django, factory_boy, manage.py
---

# Guidelines: Django

## Style

- Thin views: parse the request, call a model method or a function in `services.py`, return a response; business rules never live in a view, serializer or template
- Function-based views by default; a class-based view only when a generic one (`ListView`, `DetailView`, DRF viewsets) fits as-is — never a `View` subclass that reimplements `if request.method == "POST"`
- Models: `__str__` always; `class Meta: ordering = [...]`, `constraints = [UniqueConstraint(...), CheckConstraint(...)]`, `indexes = [...]`; `TextChoices` / `IntegerChoices` for enumerated fields
- Custom querysets as managers: `objects = OrderQuerySet.as_manager()` so callers write `Order.objects.active().for_user(user)` instead of repeating filters
- Namespaced URLs: `app_name = "orders"`, `path("<int:pk>/", views.detail, name="detail")`, `reverse("orders:detail", args=[pk])` / `{% url 'orders:detail' order.pk %}`; never a hardcoded path
- `get_user_model()` in code, `settings.AUTH_USER_MODEL` in model fields; never `from django.contrib.auth.models import User`
- `django.utils.timezone.now()` with `USE_TZ = True`; never `datetime.now()`
- `ruff format` + `ruff check` (with `DJ` rules) + `mypy` with `django-stubs`; run them, do not argue with them

## Project structure

- `config/` holds `settings/`, root `urls.py`, `asgi.py`, `wsgi.py`; apps named after a domain (`orders`, `accounts`), never after a layer (`models`, `utils`)
- Per app: `models.py`, `views.py`, `urls.py`, `services.py` (writes), `selectors.py` (complex reads), `serializers.py` (DRF), `forms.py`, `admin.py`, `migrations/`, `tests/`
- Settings split: `config/settings/base.py`, `local.py`, `production.py`, `test.py`, chosen by `DJANGO_SETTINGS_MODULE`; environment values read once in `base.py` through `django-environ` (`env = environ.Env()`, `SECRET_KEY = env("SECRET_KEY")`)
- `manage.py` is the only command entry point; recurring jobs as `management/commands/<name>.py` or Celery tasks in `tasks.py`
- Static files through `STATICFILES_DIRS` + `collectstatic` (WhiteNoise when self-serving); user uploads under `MEDIA_ROOT`, never served by Django in production

## Tests

- `pytest` + `pytest-django` with `DJANGO_SETTINGS_MODULE = "config.settings.test"` in `pyproject.toml`; never `unittest.TestCase` or `manage.py test`
- `@pytest.mark.django_db` on tests that hit the database; `transaction=True` only for code using `transaction.on_commit`
- `factory_boy`: `class OrderFactory(DjangoModelFactory)` in `apps/<name>/tests/factories.py`, `Faker` providers for values, `SubFactory` for relations; never JSON fixture dumps
- Views through `client` (`client.force_login(user)`) or DRF `APIClient` (`api_client.force_authenticate(user)`); assert the status code and the content, not internal calls
- Run one: `pytest apps/orders/tests/test_views.py::test_create_order_requires_login`
- `django_assert_num_queries(3)` on every list view that touches relations — the N+1 regression test
- Mock only external HTTP (`responses`/`respx`), time (`time_machine`) and Celery (`CELERY_TASK_ALWAYS_EAGER = True` in test settings); `django.core.mail.outbox` is already a fake; never mock the ORM
- Cover: anonymous → 302 to login or 401, another user's object → 404 (not 403 — do not leak existence), invalid form re-rendered with field errors, `makemigrations --check --dry-run` passes in CI

## ORM and migrations

- Every model change ships with its migration: `makemigrations orders -n add_status_index`; never edit or delete an applied migration
- Data migrations as separate files with `RunPython(forward, backward)` using `apps.get_model("orders", "Order")`, never importing the model class
- `select_related` for FK / OneToOne, `prefetch_related` for reverse FK / M2M on every query that is iterated with relation access
- `.only()` / `.values()` for wide tables in lists; `.exists()` instead of `.count() > 0`; `bulk_create` / `bulk_update` / `.update()` for mass writes; `F("stock") - 1` for in-place arithmetic
- `transaction.atomic()` around multi-row writes; `select_for_update()` on rows you read then write
- Ownership in the lookup: `get_object_or_404(Order, pk=pk, user=request.user)`, not an `if order.user != request.user` afterwards
- `blank=True, default=""` on string fields, never `null=True`; `null=True` only on non-string fields that are genuinely optional
- `.raw()` / `cursor.execute()` only with `%s` parameters; never f-strings in SQL

## DRF, forms, security

- `ModelSerializer` with explicit `fields = [...]` (never `"__all__"`) and `read_only_fields`; separate input and output serializers when they diverge; validation in `validate_<field>` / `validate`
- `ModelViewSet` + `DefaultRouter` for CRUD, `APIView` for one-off actions; `permission_classes` explicit on every view, `IsAuthenticated` as `DEFAULT_PERMISSION_CLASSES`
- `DEFAULT_PAGINATION_CLASS` + `PAGE_SIZE` in `REST_FRAMEWORK`; filtering with `django-filter`; `DEFAULT_THROTTLE_CLASSES` on auth endpoints
- HTML forms: `ModelForm`, validation in `clean_<field>` / `clean`, `{% csrf_token %}` in every POST form, `form.save(commit=False)` to attach `request.user`
- Production settings: `DEBUG = False`, explicit `ALLOWED_HOSTS`, `SECRET_KEY` from the environment, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS`; `manage.py check --deploy` in CI
- `@login_required` / `LoginRequiredMixin` on every non-public view; object permissions through `queryset.for_user(user)` or `django-guardian`
- Templates auto-escape; `|safe` and `mark_safe()` only on HTML you generated; user HTML through `nh3`/`bleach` first
- Admin behind `@admin.register` with `list_display`, `search_fields`, `raw_id_fields` for large FKs; admin URL not at `/admin/` in production

## What to avoid

- Business logic in views, serializers, templates or signals — `services.py` or model methods; signals only for cross-app decoupling you can name
- `for order in orders: order.customer.name` without `select_related` (N+1); `len(qs)` instead of `.count()`; `for o in qs: o.save()` instead of `bulk_update`
- `null=True` on `CharField` / `TextField`; `auto_now_add=True` when tests must set the value (use `default=timezone.now`)
- Editing applied migrations; `migrate --fake` outside a documented recovery
- `fields = "__all__"`, `AllowAny` as the default, `CORS_ALLOW_ALL_ORIGINS = True`
- `objects.get()` without catching `DoesNotExist` in a view — `get_object_or_404`
- Storing files or secrets under version control; `DEBUG = True` in any committed settings module but `local.py`
