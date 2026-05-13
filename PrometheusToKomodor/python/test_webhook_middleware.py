import importlib.util
import pathlib
import sys
import types


def install_test_stubs() -> None:
    # Stub dependencies imported by webhook-middleware.py so unit tests can run
    # without requiring full runtime packages in the local environment.
    if "fastapi" not in sys.modules:
        fastapi_stub = types.ModuleType("fastapi")

        class FastAPI:  # noqa: N801
            def __init__(self, *args, **kwargs):
                _ = (args, kwargs)

            def get(self, *args, **kwargs):
                _ = (args, kwargs)
                return lambda fn: fn

            def post(self, *args, **kwargs):
                _ = (args, kwargs)
                return lambda fn: fn

        class HTTPException(Exception):  # noqa: N801
            def __init__(self, status_code: int, detail):
                self.status_code = status_code
                self.detail = detail
                super().__init__(str(detail))

        class Request:  # noqa: N801
            pass

        fastapi_stub.FastAPI = FastAPI
        fastapi_stub.HTTPException = HTTPException
        fastapi_stub.Request = Request
        sys.modules["fastapi"] = fastapi_stub

    if "pydantic" not in sys.modules:
        pydantic_stub = types.ModuleType("pydantic")

        class BaseModel:  # noqa: N801
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

            def model_dump(self, exclude_none: bool = False):
                data = dict(self.__dict__)
                if exclude_none:
                    return {k: v for k, v in data.items() if v is not None}
                return data

        def Field(default, **kwargs):  # noqa: N802
            _ = kwargs
            return default

        pydantic_stub.BaseModel = BaseModel
        pydantic_stub.Field = Field
        sys.modules["pydantic"] = pydantic_stub

    if "httpx" not in sys.modules:
        httpx_stub = types.ModuleType("httpx")

        class _FakeResponse:
            status_code = 201
            text = ""

        class AsyncClient:  # noqa: N801
            def __init__(self, *args, **kwargs):
                _ = (args, kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                _ = (exc_type, exc, tb)
                return False

            async def post(self, *args, **kwargs):
                _ = (args, kwargs)
                return _FakeResponse()

        httpx_stub.AsyncClient = AsyncClient
        sys.modules["httpx"] = httpx_stub


def load_module():
    install_test_stubs()
    module_path = pathlib.Path(__file__).resolve().parent / "webhook-middleware.py"
    spec = importlib.util.spec_from_file_location("webhook_middleware_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


wm = load_module()


def test_build_event_returns_none_without_cluster():
    alert = {
        "status": "firing",
        "labels": {"alertname": "HighErrorRate"},
        "annotations": {},
    }

    event = wm.build_event(alert)
    assert event is None


def test_build_event_maps_expected_fields():
    alert = {
        "status": "firing",
        "labels": {
            "alertname": "VeryLongAlertNameThatShouldBeTruncatedAtThirtyCharacters",
            "cluster": "prod-eks-01",
            "kubernetes_namespace": "payments",
            "app_kubernetes_io_name": "checkout-api",
            "severity": "warning",
        },
        "annotations": {
            "description": "checkout api is reporting elevated errors",
        },
        "startsAt": "2026-05-08T12:00:00Z",
        "endsAt": "2026-05-08T12:10:00Z",
        "generatorURL": "http://prometheus.example/graph",
        "fingerprint": "abc123",
    }

    event = wm.build_event(alert)

    assert event is not None
    assert event.eventType == "VeryLongAlertNameThatShouldBeT"
    assert event.summary == "checkout api is reporting elevated errors"
    assert event.severity == "warning"
    assert event.scope.clusters == ["prod-eks-01"]
    assert event.scope.namespaces == ["payments"]
    assert event.scope.servicesNames == ["checkout-api"]
    assert event.details["label_cluster"] == "prod-eks-01"
    assert event.details["annotation_description"] == "checkout api is reporting elevated errors"


def test_map_severity_resolved_is_information():
    assert wm.map_severity({"severity": "critical"}, "resolved") == "information"


def test_map_severity_warning():
    assert wm.map_severity({"severity": "warn"}, "firing") == "warning"


def test_map_severity_default():
    assert wm.map_severity({"severity": "unknown"}, "firing") == "information"
