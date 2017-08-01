import sys, os

from django.core.exceptions import ObjectDoesNotExist
from django.utils.datastructures import MultiValueDictKeyError
from rest_framework import viewsets, mixins
from rest_framework import filters as django_filters
from rest_framework.decorators import detail_route
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication
from oauth2_provider.ext.rest_framework.authentication import OAuth2Authentication
from rest_framework.response import Response

from generank.compute.tasks.cad import get_survey_responses, verify_boolean

from .. import filters
from ..models import Condition, RiskScore, Population
from ..tasks import send_registration_email_to_user
from ..permissions import IsRegistered
from ..serializers import RiskScoreSerializer, ConditionSerializer, \
    PopulationSerializer

sys.path.append(os.environ['PIPELINE_DIRECTORY'].strip())
from analysis import cad


class ConditionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """ Conditions are a possible beneficial or detremental set of symptoms or
    afflictions that are caused by (and also possibly mitigated by genetic
    variants.

    This endpoint provides a read-only way to access the global list of
    conditions as well as a list of possible risk reductors for that condition.

    list:
    The list of all conditions and their associated risk reductors.

    retrieve:
    Get a single condition and its risk reductors by the condition {id}.
    """
    authentication_classes = [OAuth2Authentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = Condition.objects.all().order_by('-name')
    serializer_class = ConditionSerializer


class PopulationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """ Risk Scores are calculted relative to the user's determined ancestry.
    This ancestry is determined as a percentage of the user's similarity to the
    given populations. There is also a "custom" population which is user specific
    and reflects the user's combined ancestry.

    list:
    A list of all of the super populations, against which a user's ancestry is
    calculated.

    retrieve:
    A single population given by its {id}.
    """
    authentication_classes = [OAuth2Authentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = Population.objects.all().order_by('-name')
    serializer_class = PopulationSerializer


class RiskScoreViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """ Risk scores are the user's given genetic risk, and other adjusted baseline
    risks for a given condition relative to a population. Each risk score also
    has a series of adjusted risk scores that can be used to visualized the
    effect of different lifestyle changes and how they affect the user's risk.

    list:
    A list of all of the given risk scores. Conditions without risk scores are
    assumed to not be ready for the user.

    retrieve:
    Get a single risk score by its {id}.
    """

    authentication_classes = [OAuth2Authentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = RiskScore.objects.all().order_by('-user')
    serializer_class = RiskScoreSerializer
    filter_backends = (filters.IsOwnerFilterBackend, django_filters.SearchFilter)
    search_fields = ['user__id', 'name', 'condition__id', 'condition__name']

    # Queries pipeline to calculate and return baseline, combined, and lifestyle risk.
    # 07/25/17 Andre Leon

    @detail_route(methods=["GET"])
    def predict(self, request, pk):

        try:

            values = get_survey_responses(request.user.id.hex)

        except ValueError:
            return Response({"error":
                    {
                        "message": "Invalid value(s) provided in survey. Please review your answers and resubmit.",
                    }
            }, status=400)
            # parameter is out of bound
        except ObjectDoesNotExist:
            return Response({"error":
                    {
                        "message": "Survey has not been completed and risk score cannot be calculated.",
                    }
            }, status=400)
            # survey

        try:
            # verify boolean checks if value is 1 or 0 and returns ValueError if it is neither
            # it is stored in compute/tasks/cad.py
            smoking = verify_boolean(request.GET["smoking"])

            physically_active = verify_boolean(request.GET["physically_active"])

            healthy_diet = verify_boolean(request.GET["healthy_diet"])

            obese = verify_boolean(request.GET["obese"])

        # missing or invalid lifestyle parameter
        except MultiValueDictKeyError:
            return Response({"error":
                    {
                        "message": "Unable to retrieve lifestyle risk value.",
                    }
            }, status=400)

        except ValueError:
            return Response({"error":
                {
                    "message": "Invalid value provided for lifestyle risk category.",
                }
            }, status=400)

        try:

            baseline_risk = cad.get_baseline_risk(values["sex"],
                                                  values["ancestry"],
                                                  values["age"],
                                                  values["total_cholesterol"],
                                                  values["HDL_cholesterol"],
                                                  values["systolicBP_untreated"],
                                                  values["systolicBP_treated"],
                                                  values["smoking_default"],
                                                  values["diabetic"])

            individual_risk_score = RiskScore.objects.get(id=pk).value

            combined_risk = cad.get_combined_risk(baseline_risk,
                                                  individual_risk_score,
                                                  values["average_odds"])

            # The non-default values need to be provided from the lifestyle risk user interface.
            lifestyle_risk = cad.get_lifestyle_risk(smoking,
                                                    obese,
                                                    physically_active,
                                                    healthy_diet,
                                                    combined_risk,
                                                    values["smoking_default"],
                                                    values["obesity_default"],
                                                    values["physical_activity_default"],
                                                    values["healthy_diet_default"]
                                                    )

        # missing or invalid parameter from cad.get_survey_responses
        except Exception:
            return Response({"error":
                {
                    "message": "An error occurred during risk score calculation. Please contact supervisor for support.",
                }
            }, status=400)

        return Response({"results": [{
            "name": "Baseline Risk",
            "value": baseline_risk
        },
        {
            "name": "Combined Risk",
            "value": combined_risk
        },
        {
            "name": "Lifestyle Risk",
            "value": lifestyle_risk
        }]})
