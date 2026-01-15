from rest_framework.routers import DefaultRouter

from django.urls import include, path

from . import views

router = DefaultRouter()
router.register(r"drf/viewset", views.DRFViewSet, basename="drf-viewset")

urlpatterns = [
    # A. Algorithms
    path("algo/fixed/", views.algo_fixed, name="algo_fixed"),
    path("algo/sliding/", views.algo_sliding, name="algo_sliding"),
    path("algo/token/", views.algo_token, name="algo_token"),
    path("algo/seconds/", views.algo_seconds, name="algo_seconds"),
    path("algo/hours/", views.algo_hours, name="algo_hours"),
    path("algo/async/", views.algo_async, name="algo_async"),
    path("algo/batch/", views.batch_demo, name="batch_demo"),
    path("middleware/async/", views.middleware_async, name="middleware_async"),
    # B. Keys
    path("key/ip/", views.key_ip, name="key_ip"),
    path("key/user/", views.key_user, name="key_user"),
    path("key/user_or_ip/", views.key_user_or_ip, name="key_user_or_ip"),
    path("key/header/", views.key_header, name="key_header"),
    path("key/param/", views.key_param, name="key_param"),
    path("key/custom/", views.key_custom, name="key_custom"),
    # C. Options
    path("opt/block_false/", views.opt_block_false, name="opt_block_false"),
    path("opt/group/a/", views.opt_group_a, name="opt_group_a"),
    path("opt/group/b/", views.opt_group_b, name="opt_group_b"),
    path("opt/methods/", views.opt_methods, name="opt_methods"),
    path("opt/skip/", views.opt_skip, name="opt_skip"),
    # D. Frameworks
    path("drf/apiview/", views.DRFAPIView.as_view(), name="drf_apiview"),
    path("", include(router.urls)),
    path("middleware/global/", views.middleware_global, name="middleware_global"),
    # E. Infrastructure
    path("infra/redis/", views.infra_redis, name="infra_redis"),
    path("infra/mongodb/", views.infra_mongodb, name="infra_mongodb"),
    path("infra/multi/", views.infra_multi, name="infra_multi"),
    path("infra/fail-open/", views.infra_fail_open, name="infra_fail_open"),
    path("infra/fail-closed/", views.infra_fail_closed, name="infra_fail_closed"),
    path("infra/cb-status/", views.infra_cb_status, name="infra_cb_status"),
    # F. Real World
    path("real_world/login/", views.real_world_login, name="real_world_login"),
    path("real_world/tiering/", views.real_world_tiering, name="real_world_tiering"),
    path("real_world/search/", views.real_world_search, name="real_world_search"),
    path(
        "real_world/dashboard/", views.real_world_dashboard, name="real_world_dashboard"
    ),
    # G. Window Alignment
    path(
        "window/alignment/", views.window_alignment_test, name="window_alignment_test"
    ),
]
