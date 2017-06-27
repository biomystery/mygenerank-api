""" GeneRank URL Configuration """
from django.contrib import admin
from django.conf.urls import url, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView
from django.contrib.auth import views as auth_views

from rest_framework.authtoken import views
from rest_framework import routers

from push_notifications.api.rest_framework import APNSDeviceAuthorizedViewSet, \
    GCMDeviceAuthorizedViewSet

from .website import views as web_views
from .api import views as gpc_views
from .twentythreeandme import views as ttm_views
from .api import signals


api_router = routers.DefaultRouter()
api_router.register(r'users', gpc_views.UserViewSet)
api_router.register(r'activities', gpc_views.ActivityViewSet)
api_router.register(r'conditions', gpc_views.ConditionViewSet)
api_router.register(r'populations', gpc_views.PopulationViewSet)
api_router.register(r'activity-answers', gpc_views.ActivityAnswerViewSet)
api_router.register(r'activity-statuses', gpc_views.ActivityStatusViewSet)
api_router.register(r'risk-scores', gpc_views.RiskScoreViewSet)
api_router.register(r'signatures', gpc_views.SignatureViewSet)
api_router.register(r'consent-forms', gpc_views.ConsentPDFViewSet)
api_router.register(r'health-samples', gpc_views.HealthSampleViewSet)
api_router.register(r'lifestyle', gpc_views.LifestyleMetricStatusViewSet)
api_router.register(r'newsfeed', gpc_views.ItemViewSet)

api_router.register(r'device/apns', APNSDeviceAuthorizedViewSet)
api_router.register(r'device/gcm', GCMDeviceAuthorizedViewSet)

ttm_router = routers.DefaultRouter()
ttm_router.register(r'users', ttm_views.UserViewSet)
ttm_router.register(r'profiles', ttm_views.ProfileViewSet)
ttm_router.register(r'genotypes', ttm_views.GenotypeViewSet)
ttm_router.register(r'settings', ttm_views.SettingsViewSet)



urlpatterns = ([
    url(r'^$', web_views.home_view),
    url(r'^team/$', web_views.team_view),
    url(r'^contact/$', web_views.contact_view),
    url(r'^news/$', web_views.newsfeed.NewsFeedView.as_view()),

#     Accounts/Registration
#     url(r'^accounts/',
#         include('rest_framework.urls', namespace='rest_framework')),

    # Public API
    url(r'^api/', include(
            api_router.urls,
            namespace="api",
            app_name='generank'
        )
    ),
    url(r'^api/o/', include('oauth2_provider.urls', namespace='oauth2_provider')),
    url(r'^api/register/', gpc_views.CreateUserView.as_view()),

    url('^', include('django.contrib.auth.urls')),

    # Twenty Three and Me Integrations
    url(r'^twentythreeandme/import/', ttm_views.import_data),
    url(r'^twentythreeandme/', include(ttm_router.urls,
        namespace="twentythreeandme", app_name='twentythreeandme')),

    # Admin
    url(r'^admin/', admin.site.urls),

] + static(settings.CONSENT_FILE_URL, document_root=settings.CONSENT_FILE_LOCATION)
    + static(settings.TTM_RAW_URL, document_root=settings.TTM_RAW_STORAGE)
    + static(settings.TTM_CONVERTED_URL, document_root=settings.TTM_CONVERTED_STORAGE)
    + static(settings.DATA_URL, document_root=settings.DATA_STORAGE)
)
