"""Flask blueprints module - simplified for SWE-bench task."""
import typing as t


class Scaffold:
    """Base class with common functionality."""

    def __init__(
        self,
        import_name: str,
        static_folder: t.Optional[str] = None,
        static_url_path: t.Optional[str] = None,
        template_folder: t.Optional[str] = None,
        root_path: t.Optional[str] = None,
    ):
        self.import_name = import_name
        self.static_folder = static_folder
        self.template_folder = template_folder


class Blueprint(Scaffold):
    """Represents a blueprint, a collection of routes and other
    app-related functions that can be registered on a real application
    later.

    A blueprint is an object that allows defining application functions
    without requiring an application object ahead of time. It uses the
    same decorators as :class:`~flask.Flask`, but defers the need for an
    application by recording them for later registration.

    .. versionadded:: 0.7
    """

    def __init__(
        self,
        name: str,
        import_name: str,
        static_folder: t.Optional[str] = None,
        static_url_path: t.Optional[str] = None,
        template_folder: t.Optional[str] = None,
        url_prefix: t.Optional[str] = None,
        subdomain: t.Optional[str] = None,
        url_defaults: t.Optional[dict] = None,
        root_path: t.Optional[str] = None,
    ):
        super().__init__(
            import_name=import_name,
            static_folder=static_folder,
            template_folder=template_folder,
            root_path=root_path,
        )
        if "." in name:
            raise ValueError("'name' may not contain a dot '.' character.")
        self.name = name
        self.url_prefix = url_prefix
        self.subdomain = subdomain
        self.url_defaults = url_defaults or {}
        self._blueprints: t.List[t.Tuple["Blueprint", dict]] = []
        self._rules: t.List[dict] = []

    def add_url_rule(
        self,
        rule: str,
        endpoint: t.Optional[str] = None,
        view_func: t.Optional[t.Callable] = None,
        **options: t.Any,
    ) -> None:
        """Like :meth:`Flask.add_url_rule` but for a blueprint.  The endpoint for
        the :func:`url_for` function is prefixed with the name of the blueprint.
        """
        if endpoint and "." in endpoint:
            raise ValueError("Blueprint endpoints should not contain dots.")
        if view_func and hasattr(view_func, "__name__") and "." in view_func.__name__:
            raise ValueError("Blueprint view function name should not contain dots.")
        self._rules.append({"rule": rule, "endpoint": endpoint, "view_func": view_func})

    def route(self, rule: str, **options: t.Any) -> t.Callable:
        """Decorate a view function to register it with the given URL
        rule and options.
        """
        def decorator(f: t.Callable) -> t.Callable:
            endpoint = options.pop("endpoint", None)
            self.add_url_rule(rule, endpoint, f, **options)
            return f
        return decorator

    def register_blueprint(self, blueprint: "Blueprint", **options: t.Any) -> None:
        """Register a nested blueprint."""
        self._blueprints.append((blueprint, options))
