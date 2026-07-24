from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
def health(request):
    """Return the smallest possible DRF endpoint for local verification."""
    return Response({"status": "ok"})
