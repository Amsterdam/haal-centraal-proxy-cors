import logging

from rest_framework.permissions import BasePermission

audit_log = logging.getLogger("haal_centraal_proxy.audit")


class IsUserScope(BasePermission):
    """Permission check, wrapped in a DRF permissions adapter"""

    def __init__(self, needed_scopes):
        self.needed_scopes = frozenset(needed_scopes)

    def has_permission(self, request, view):
        """Check whether the user has all required scopes"""
        # This calls into 'authorization_django middleware':
        return request.is_authorized_for(*self.needed_scopes)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
