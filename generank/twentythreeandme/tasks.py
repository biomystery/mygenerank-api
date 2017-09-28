import os, requests, sys

from celery import shared_task, chord, group
from celery.utils.log import get_task_logger
from django.conf import settings
from django.core.files.base import ContentFile
from django.db.utils import IntegrityError
from requests.exceptions import ReadTimeout

from generank.compute import tasks as compute_tasks
from generank.compute.contextmanagers import record

from .models  import User, Profile, Genotype, APIToken
from .api_client import get_user_info, get_genotype_data


sys.path.append(os.environ['PIPELINE_DIRECTORY'].strip())
from conversion.convert_ttm_to_vcf import convert


@shared_task(autoretry_for=(ReadTimeout,), retry_kwargs={'max_retries': 3})
def _import_user(token, api_user_id):
    """ Given a token and a api_user and a 23andMe profile_id,
    it fetches user data for that profile from 23andMe and saves the user.
    :returns user_info: A dict of the 23andMe User/Profile information.
    """
    with record('23andMe.tasks._import_user'):
        user_info = get_user_info(token['access_token'])

        user = User.from_json(user_info)
        user.api_user_id = api_user_id
        user.save()

        token = APIToken.from_json(token, user)
        token.save()

        return user_info


@shared_task
def _import_profile(user_info, token, api_user_id, profileid):
    """ Given a token and a user info JSON object this will create a 23andMe
    User. It will also create a Profile object and spawn a job to import the
    genotype data.
    """
    with record('23andMe.tasks._import_profile'):
        prof = [prof for prof in user_info['profiles']
            if prof['id'] == profileid][0]

        user = User.objects.get(api_user_id=api_user_id)
        profile = Profile.from_json(prof, user)
        profile.save()

        return str(profile.id)


@shared_task(autoretry_for=(ReadTimeout,), retry_kwargs={'max_retries': 3})
def _import_genotype(token, api_user_id, profile_id):
    """ Given the id of a profile model and a bearer token, this function will download
    the raw genotype data from 23andme and save it in a genotype object and
    spawns a job to convert the raw file into the VCF format.
    """
    with record('23andMe.tasks._import_genotype'):
        profile = Profile.objects.get(profile_id=profile_id, user__api_user_id=api_user_id)
        genotype_data = get_genotype_data(token, profile)
        genotype = Genotype.from_json(genotype_data, profile)
        genotype.save()

        return str(genotype.id)


@shared_task
def _convert_genotype(genotype_id):
    """ Given a genotype, this function converts the genotype data file from the
    23 and Me format to a VCF format.
    """
    with record('23andMe.tasks._convert_genotype'):
        genotype = Genotype.objects.get(id=genotype_id)

        raw_data = genotype.genotype_file.read().decode('ascii')
        vcf_data = convert(raw_data)

        filename = '{}_genotype.vcf'.format(genotype.profile.id)
        genotype.converted_file.save(name=filename, content=ContentFile(vcf_data))

        genotype.save()


# Public Tasks

@shared_task
def import_account(token, api_user_id, profile_id, run_after=True):
    """ Import a given user's account details using the OAuth token
    and save the profile under the given API User ID.

    By default, this workflow initiates the computation for all
    risk scores once complete. """
    workflow = (
        _import_user.s(token, api_user_id) |
        _import_profile.s(token['access_token'], api_user_id, profile_id) |
        _import_genotype.si(token['access_token'], api_user_id, profile_id) |
        _convert_genotype.s()
    )

    if run_after:
        workflow |= compute_tasks.run_all.si(api_user_id)

    workflow.delay()

