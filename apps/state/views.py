# file path: apps/state/views.py
"""Persistent state API.

    GET    /api/state/bootstrap/     everything needed to restore a page
    GET    /api/state/analysis/      the shared AI analysis session (full payload)
    GET    /api/state/ui/            every stored UI key for the user
    POST   /api/state/ui/            bulk write {"items": {...}}
    GET    /api/state/ui/<key>/      one key
    PUT    /api/state/ui/<key>/      write one key
    DELETE /api/state/ui/<key>/      drop one key
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import UIStateBulkWriteSerializer, UIStateWriteSerializer
from .services import (
    AnalysisSessionService,
    QuizSessionService,
    StateKeyError,
    UIStateService,
    bootstrap_state,
)


class BootstrapStateAPIView(APIView):
    """One request per page load that restores navigation, filters and progress."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(bootstrap_state(request.user))


class AnalysisStateAPIView(APIView):
    """The shared AI analysis session, replayed without re-running the pipeline."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(AnalysisSessionService.restore(request.user))


class QuizStateAPIView(APIView):
    """Progress header for the quiz (the questions live on /api/quiz/)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        session = QuizSessionService.get(request.user)
        if session is None:
            return Response({"has_session": False})
        return Response({
            "has_session": True,
            "status": session.status,
            "answered": len(session.answers or {}),
            "total": session.total,
            "score": session.score,
            "percentage": session.percentage,
            "updated_at": session.updated_at.isoformat(),
        })


class UIStateListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"items": UIStateService.all(request.user)})

    def post(self, request):
        serializer = UIStateBulkWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            saved = UIStateService.set_many(request.user, serializer.validated_data["items"])
        except StateKeyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"items": saved})


class UIStateDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, key):
        row = UIStateService.get(request.user, key)
        if row is None:
            return Response({"key": key, "value": None, "found": False})
        return Response({"key": key, "found": True, **row})

    def put(self, request, key):
        serializer = UIStateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            saved = UIStateService.set(request.user, key, serializer.validated_data["value"])
        except StateKeyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(saved)

    def delete(self, request, key):
        UIStateService.delete(request.user, key)
        return Response(status=status.HTTP_204_NO_CONTENT)
