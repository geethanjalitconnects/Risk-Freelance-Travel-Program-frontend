class FromFieldMixin:
    """Expose a field declared as ``origin`` under the JSON key ``from``.

    ``from`` is a Python keyword, so it can't be a class attribute, but the frontend's ride
    objects use ``from`` / ``to``. Declare ``origin = ...`` and this renames it.
    """

    def get_fields(self):
        fields = super().get_fields()
        if "origin" in fields:
            fields["from"] = fields.pop("origin")
        return fields
