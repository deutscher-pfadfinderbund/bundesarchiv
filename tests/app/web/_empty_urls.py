"""A URLconf with NO routes — stand-in for a production process that mounts no HTTP surface.

Used by the prod-safety tests to assert the dev switcher neither resolves nor reverses when its
URLconf is not the one in effect.
"""

urlpatterns: list[object] = []
