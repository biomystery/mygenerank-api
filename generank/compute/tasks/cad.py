""" A module for distributing calculation tasks for CAD Risk Score. """
import os, requests, sys, subprocess, uuid
from django.conf import settings

from celery import shared_task, chord, group
from django.core.exceptions import ObjectDoesNotExist

from generank.api import models
from generank.api.tasks import send_risk_score_notification, send_post_cad_survey_to_users
from generank.twentythreeandme.models  import User, Profile, Genotype
from generank.compute.contextmanagers import record

sys.path.append(os.environ['PIPELINE_DIRECTORY'].strip())
from analysis import steps

PHENOTYPE = 'cad_160808'
SCORE_RESULTS_ORDER = [
    'custom', 'africans', 'native americans', 'east asians', 'europeans', 'south asians'
]


@shared_task
def _get_cad_haplotypes(user_id, chromosome):
    """ Given a chromosome, determine the known haplotypes inside it. """
    with record('tasks.cad._get_cad_haplotypes', user_id):
        user = User.objects.get(api_user_id=user_id)
        return steps.grs_step_2(uuid.uuid4().hex, user.profile.genotype.converted_file,
            user_id, PHENOTYPE, chromosome)


#@shared_task(bind=True)
#def _dispatch_impute_tasks(self, haps, user_id, chromosome):
#    """ Given a chromosome and it's haplotypes, return the imputation tasks over
#    each chunk for that chromosome. """
#    self.replace(group(_impute_and_get_cad_risk_per_chunk.s(haps, user_id, chunk)
#        for chunk in steps.get_chunks() if chunk[0] == chromosome))


@shared_task
def _impute_and_get_cad_risk_per_chunk(haps, user_id, chunk):
    """ Given a user, the chunk of a chromosome and the known haplotypes for that
    chromosome, calculate their risk for that given chunk. """
    with record('tasks.cad._impute_and_get_cad_risk_per_chunk', user_id):
        return steps.grs_step_3(uuid.uuid4().hex, *haps, PHENOTYPE, *chunk)


@shared_task
def _get_total_cad_risk(results, user_id):
    """ Given the user's ancestry, and their individual risk per chromosome
    per chunk, calculate their total overall risk. """
    with record('tasks.cad._get_total_cad_risk', user_id):
        # A hack to filter out the ancestry record. Celery doesn't guarantee order.
        ancestry = [result for result in results if 'ancestry' in result[1]][0]
        risk_of_risks = [result for result in results if 'ancestry' not in result[1]]

        filename, ancestry_path, ancestry_contents = ancestry
        return (ancestry_contents, *steps.grs_step_4(uuid.uuid4().hex, filename,
            ancestry_path, ancestry_contents, risk_of_risks, user_id, PHENOTYPE))

#NEED to modify store results and get total risk
@shared_task
def _store_results(results, user_id):
    """ Given the results of a user's CAD risk score, store the data. """
    with record('tasks.cad._store_results', user_id):
        ancestries, path, scores = results
        user = models.User.objects.get(id=user_id)
        cad = models.Condition.objects.filter(name__iexact='coronary artery disease')[0]

        for population_name, score in zip(SCORE_RESULTS_ORDER, scores.split('\n')):
            featured = True if population_name == 'custom' else False
            population = models.Population.objects.filter(name__iexact=population_name)[0]
            risk_score = models.RiskScore(user=user, condition=cad, featured=featured,
                population=population, calculated=True, value=float(score))
            risk_score.save()

        for population_name, per_ancestry in zip(SCORE_RESULTS_ORDER, ancestries.split()):
            population = models.Population.objects.filter(name__iexact=population_name)[0]
            ancestry = models.Ancestry(user=user, population=population, value=float(per_ancestry))
            ancestry.save()



@shared_task
def _send_cad_notification(user_id):
    """ Send a Risk Score Notification for the CAD condition.
    Uses the API method for sending notifications. """
    with record('tasks.cad._send_cad_notification', user_id):
        cad = models.Condition.objects.filter(name__iexact='coronary artery disease')[0]
        send_risk_score_notification(user_id, cad.name)


# Public Tasks

@shared_task
def get_ancestry(user_id):
    """ Given an API user id, perform the ancestry calculations on that
    user's genotype data. """
    with record('tasks.cad.get_ancestry', user_id):
        user = User.objects.get(api_user_id=user_id)
        return steps.grs_step_1(uuid.uuid4().hex, user.profile.genotype.converted_file)


@shared_task
def get_cad_risk_score(user_id):
    """ Given an API user id, perform the grs risk score calculations.
    This is the high level pipeline invocation method used to submit all
    subsequent and dependent steps. """
    with record('tasks.cad.get_cad_risk_score', user_id):
        step_1 = get_ancestry.s(user_id)
        steps_2_and_3 = [
            _get_cad_haplotypes.s(user_id, chunk[0]) | _impute_and_get_cad_risk_per_chunk.s(user_id, chunk)
            for chunk in steps.get_chunks()
        ]
        step_4 = _get_total_cad_risk.s(user_id)
        notify_user = (
            _send_cad_notification.si(user_id) | send_post_cad_survey_to_users.si(user_id)
        )

        workflow = chord(
            header=group([step_1, *steps_2_and_3]),
            body=step_4
        ) | _store_results.s(user_id) | notify_user

        workflow.delay()

@shared_task
def get_numeric_total_cholesterol(user_id):
    """Reviews responses to total cholesterol survey questions to collect either
        numerical value provided by user or estimated qualitative values (low, moderate, high)
        which are then translated to numerical values as provided by NIH Medline plus
        https://medlineplus.gov/magazine/issues/summer12/articles/summer12pg6-7.html.
        07/25/17 Andre Leon"""

    user = models.User.objects.get(id=user_id)

    low_total_cholesterol = 190
    moderate_total_cholesterol = 220
    high_total_cholesterol = 250

    subjective_total_cholesterol_level = models.ActivityAnswer.objects.get(
        question_identifier=settings.TOTAL_CHOLESTEROL_IDENTIFIER, user=user).value

    subjective_total_cholesterol_value = 0

    if subjective_total_cholesterol_level == "low":
        subjective_total_cholesterol_value = low_total_cholesterol

    elif subjective_total_cholesterol_level == "moderate" or subjective_total_cholesterol_level == "unknown":
        subjective_total_cholesterol_value = moderate_total_cholesterol

    elif subjective_total_cholesterol_level == "high":
        subjective_total_cholesterol_value = high_total_cholesterol

    if models.ActivityAnswer.objects.filter(
            question_identifier=settings.PRECISE_TOTAL_CHOLESTEROL_IDENTIFIER, user=user).exists():

        return float(models.ActivityAnswer.objects.get(question_identifier= settings.PRECISE_TOTAL_CHOLESTEROL_IDENTIFIER, user=user).value)

    else:
        return subjective_total_cholesterol_value


@shared_task
def get_numeric_HDL_cholesterol(user_id):
    """Reviews responses to HDL cholesterol survey questions to collect either
    numerical value provided by user or estimated qualitative values (low, moderate, high)
    which are then translated to numerical values as provided by NIH Medline plus
    https://medlineplus.gov/magazine/issues/summer12/articles/summer12pg6-7.html.
    07/25/17 Andre Leon"""

    user = models.User.objects.get(id=user_id)

    low_total_HDL_cholesterol = 35
    moderate_total_HDL_cholesterol = 50
    high_total_HDL_cholesterol = 65

    subjective_HDL_cholesterol_level = models.ActivityAnswer.objects.get(
        question_identifier=settings.TOTAL_HDL_CHOLESTEROL_IDENTIFIER, user=user).value

    subjective_HDL_cholesterol_value = 0

    if subjective_HDL_cholesterol_level == "normal":
        subjective_HDL_cholesterol_value = low_total_HDL_cholesterol

    elif subjective_HDL_cholesterol_level == "moderate" or subjective_HDL_cholesterol_level == "unknown":
        subjective_HDL_cholesterol_value = moderate_total_HDL_cholesterol

    elif subjective_HDL_cholesterol_level == "high":
        subjective_HDL_cholesterol_value = high_total_HDL_cholesterol

    if models.ActivityAnswer.objects.filter(
            question_identifier=settings.PRECISE_HDL_CHOLESTEROL_IDENTIFIER, user=user).exists():

        return float(models.ActivityAnswer.objects.get(question_identifier=settings.PRECISE_HDL_CHOLESTEROL_IDENTIFIER, user=user).value)

    else:
        return subjective_HDL_cholesterol_value

@shared_task
def get_numeric_systolic_blood_pressure(user_id):
    """Reviews responses to blood pressure survey questions to collect either
    numerical value provided by user or estimated qualitative values (normal, moderate, high)
    which are then translated to numerical values as supplied by Evan Muse.
    07/25/17 Andre Leon"""
    user = models.User.objects.get(id=user_id)

    normal_blood_pressure = 110
    moderate_blood_pressure = 145
    high_blood_pressure = 170

    if models.ActivityAnswer.objects.filter(
            question_identifier=settings.SYSTOLIC_BLOOD_PRESSURE_IDENTIFIER, user= user).exists():

        return float(models.ActivityAnswer.objects.get(question_identifier=settings.SYSTOLIC_BLOOD_PRESSURE_IDENTIFIER, user=user).value)

    subjective_blood_pressure_level = models.ActivityAnswer.objects.get(
        question_identifier=settings.BLOOD_PRESSURE_QUESTION_IDENTIFIER, user= user).value

    subjective_blood_pressure_value = 0

    if subjective_blood_pressure_level == "normal":
        subjective_blood_pressure_value = normal_blood_pressure

    elif subjective_blood_pressure_level == "moderate" or subjective_blood_pressure_level == "unknown":
        subjective_blood_pressure_value = moderate_blood_pressure

    elif subjective_blood_pressure_level == "high":
        subjective_blood_pressure_value = high_blood_pressure

    else:
        return subjective_blood_pressure_value

@shared_task
def get_obesity_status(user_id):
    """Reviews responses to height and weight survey questions to calculate BMI
    and obesity status (by extension). Calculations follow guidelines by CDC.
    https://www.cdc.gov/nccdphp/dnpao/growthcharts/training/bmiage/page5_2.html
    Returns Obesity: FALSE if either height or weight are omitted.
    07/25/17 Andre Leon"""
    user = models.User.objects.get(id = user_id)

    if models.ActivityAnswer.objects.filter(question_identifier=settings.HEIGHT_QUESTION_IDENTIFIER, user= user).exists():
        if models.ActivityAnswer.objects.filter(question_identifier=settings.WEIGHT_QUESTION_IDENTIFIER, user= user).exists():
            height = float(models.ActivityAnswer.objects.get(question_identifier=settings.HEIGHT_QUESTION_IDENTIFIER, user= user).value)
            weight = float(models.ActivityAnswer.objects.get(question_identifier=settings.WEIGHT_QUESTION_IDENTIFIER, user= user).value)

            BMI = (weight/(height*height))*703

            if BMI >= 30:
                return True
            else:
                return False
    else:
        raise ObjectDoesNotExist

@shared_task
def validate_numb(parameter, lower_bound_inclusive, upper_bound_inclusive):
    if parameter < lower_bound_inclusive or parameter > upper_bound_inclusive:
        raise ValueError

    else:
        return parameter


@shared_task
def verify_boolean(parameter):
    # verifies boolean is valid (this is for the lifestyle parameters in condition.py)
    if parameter == 1:
        return True
    elif parameter == 0:
        return False
    else:
        raise ValueError

@shared_task
def get_survey_responses(user_id):
    """Given an API user id, return a list that contains survey responses
     relevant for risk score calculation ('predict' function) in condition.py.

     NOTE: This script ensures that the correct systolic blood pressure values are calculated. If
        the user is NOT treated for BP than the systolic_blood_pressure_treated parameter is set to 0 so
        that it does not influence the baseline risk calculation. Vice Versa.
        07/25/17 Andre Leon"""


    user = models.User.objects.get(id = user_id)

    sex_value = models.ActivityAnswer.objects.get(question_identifier=settings.SEX_QUESTION_IDENTIFIER, user= user).value
    if sex_value != "male" or "female":
        raise ValueError

    ancestry_value = models.ActivityAnswer.objects.get(question_identifier=settings.ANCESTRY_QUESTION_IDENTIFIER, user = user).boolean_value

    age_value = int(models.ActivityAnswer.objects.get(question_identifier=settings.AGE_QUESTION_IDENTIFIER, user=user).value)
    validate_numb(age_value, 40, 79)

    diabetic_value = models.ActivityAnswer.objects.get(question_identifier=settings.DIABETES_IDENTIFIER, user = user).boolean_value

    numeric_HDL_cholesterol = get_numeric_HDL_cholesterol(user.id.hex)
    validate_numb(numeric_HDL_cholesterol, 20, 100)

    numeric_total_cholesterol = get_numeric_total_cholesterol(user.id.hex)
    validate_numb(numeric_HDL_cholesterol, 130, 320)

    numeric_systolic_blood_pressure = get_numeric_systolic_blood_pressure(user.id.hex)
    validate_numb(numeric_systolic_blood_pressure, 90, 200)

    smoking_value = models.ActivityAnswer.objects.get(question_identifier=settings.SMOKING_IDENTIFIER, user = user).boolean_value

    obesity_value = get_obesity_status(user.id.hex)

    #Returns false if activity question is omitted.
    if models.ActivityAnswer.objects.filter(question_identifier=settings.ACTIVITY_IDENTIFIER, user= user).exists():
        subjective_activity = models.ActivityAnswer.objects.get(question_identifier=settings.ACTIVITY_IDENTIFIER, user=user).boolean_value
    else:
        subjective_activity = False

    #Returns false if diet question is omitted.
    if models.ActivityAnswer.objects.filter(question_identifier=settings.DIET_IDENTIFIER, user= user).exists():
        subjective_diet = models.ActivityAnswer.objects.get(question_identifier=settings.DIET_IDENTIFIER, user=user).boolean_value
    else:
        subjective_diet = False

    #THIS IS THE SCRIPT THAT DETERMINES WHAT SYSTOLIC BLOOD PRESSURE TO USE.
    if(models.ActivityAnswer.objects.filter(question_identifier=settings.BLOOD_PRESSURE_MEDICATION_IDENTIFIER, user= user).exists()):
        if(models.ActivityAnswer.objects.get(question_identifier=settings.BLOOD_PRESSURE_MEDICATION_IDENTIFIER,
                                                            user= user).boolean_value):
            systolic_blood_pressure_treated = numeric_systolic_blood_pressure
            systolic_blood_pressure_untreated = 1

        else:
            systolic_blood_pressure_untreated = numeric_systolic_blood_pressure
            systolic_blood_pressure_treated = 1

    relevant_values = {
        "sex": sex_value,
        "ancestry": ancestry_value,
        "age": age_value,
        "diabetic": diabetic_value,
        "HDL_cholesterol": numeric_HDL_cholesterol,
        "total_cholesterol": numeric_total_cholesterol,
        "systolicBP_untreated": systolic_blood_pressure_untreated,
        "systolicBP_treated": systolic_blood_pressure_treated,
        "smoking_default": smoking_value,
        "obesity_default": obesity_value,
        "physical_activity_default": subjective_activity,
        "healthy_diet_default": subjective_diet,

        # This is the median odds ratio for genetic CAD risk. It comes from: https://www.ncbi.nlm.nih.gov/pubmed/25748612
        "medium_odds": 1.32
    }

    return relevant_values

