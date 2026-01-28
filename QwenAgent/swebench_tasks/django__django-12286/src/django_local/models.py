"""Simplified Django Model validation for SWE-bench task.

Bug: Model.full_clean() does not validate that unique fields are non-empty.
An empty string passes unique validation but violates data integrity.
SWECAS-500: Security & Validation
"""


class ValidationError(Exception):
    """Raised when model validation fails."""
    def __init__(self, message, field=None):
        self.message = message
        self.field = field
        super().__init__(message)


class Field:
    def __init__(self, required=True, unique=False, max_length=None, blank=False):
        self.required = required
        self.unique = unique
        self.max_length = max_length
        self.blank = blank


class CharField(Field):
    pass


class Model:
    """Simplified Model with field validation."""

    # Registry of all instances for unique checks
    _instances = []

    def __init__(self, **kwargs):
        for attr, field in self._get_fields().items():
            setattr(self, attr, kwargs.get(attr))
        Model._instances.append(self)

    @classmethod
    def _get_fields(cls):
        fields = {}
        for attr in dir(cls):
            val = getattr(cls, attr, None)
            if isinstance(val, Field):
                fields[attr] = val
        return fields

    def full_clean(self):
        """Validate all fields.

        BUG: Does not check that unique fields have non-empty values.
        Empty string '' passes unique check but violates data integrity.
        Should raise ValidationError for blank unique fields when blank=False.
        """
        errors = []
        for attr, field in self._get_fields().items():
            value = getattr(self, attr, None)

            # Check required
            if field.required and value is None:
                errors.append(f"Field '{attr}' is required")

            # Check max_length
            if field.max_length and value and len(str(value)) > field.max_length:
                errors.append(f"Field '{attr}' exceeds max_length {field.max_length}")

            # BUG: unique check does not validate empty strings
            # Should also check: if field.unique and not field.blank and value == '':
            #     errors.append(f"Unique field '{attr}' cannot be blank")

        if errors:
            raise ValidationError("; ".join(errors))

    @classmethod
    def reset_registry(cls):
        cls._instances = []


class User(Model):
    username = CharField(required=True, unique=True, max_length=150, blank=False)
    email = CharField(required=True, unique=True, max_length=254, blank=False)
