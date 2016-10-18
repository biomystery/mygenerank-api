""" A module for distributing calculation tasks for CAD Risk Score. """
import os, requests, sys, subprocess, uuid

from celery import shared_task, chord, group
from celery.utils.log import get_task_logger

from generank.twentythreeandme.models  import User, Profile, Genotype
from generank.utils.task_addons import dynamic_task

sys.path.append(os.environ['PIPELINE_DIRECTORY'].strip())
from analysis import steps


logger = get_task_logger(__name__)
PHENOTYPE = 'cad_160808'


@shared_task
def _get_cad_haplotypes(user_id, chromosome):
    """ Given a chromosome, determine the known haplotypes inside it. """
    logger.debug('tasks.cad._get_cad_haplotypes')
    user = User.objects.get(user_id=user_id)
    return steps.grs_step_2(uuid.uuid4().hex, user.profile.genotype.converted_file,
        user_id, PHENOTYPE, chromosome)


@dynamic_task
def _dispatch_impute_tasks(haps, user_id, chromosome):
    """ Given a chromosome and it's haplotypes, return the imputation tasks over
    each chunk for that chromosome. """
    return group(_impute_and_get_cad_risk_per_chunk.s(haps, user_id, chunk)
        for chunk in steps.get_chunks() if chunk[0] == chromosome)


@shared_task
def _impute_and_get_cad_risk_per_chunk(haps, user_id, chunk):
    """ Given a user, the chunk of a chromosome and the known haplotypes for that
    chromosome, calculate their risk for that given chunk.
    """
    logger.debug('tasks.cad._impute_and_get_cad_risk_per_chunk')
    return steps.grs_step_3(uuid.uuid4().hex, *haps, PHENOTYPE, *chunk)


@shared_task
def _get_total_cad_risk(results, user_id):
    """ Given the user's ancestry, and their individual risk per chromosome
    per chunk, calculate their total overall risk.
    """
    logger.debug('tasks.cad._get_total_cad_risk')
    ancestry, *risk_of_risks_result = results
    risk_of_risks = risk_of_risks_result.join()

    filename, ancestry_path, ancestry_contents = ancestry
    risks = [risk for chr_risks in risk_of_risks for risk in chr_risks]
    return steps.grs_step_4(uuid.uuid4().hex, filename, ancestry_path,
        ancestry_contents, risks, user_id)


# Public Tasks


@shared_task
def get_ancestry(user_id):
    """ Given an API user id, perform the ancestry calculations on that
    user's genotype data. """
    logger.debug('tasks.cad.get_ancestry')
    user = User.objects.get(user_id=user_id)
    return steps.grs_step_1(uuid.uuid4().hex, user.profile.genotype.converted_file)


@shared_task
def get_cad_risk_score(user_id):
    """ Given an API user id, perform the grs risk score calculations.
    This is the high level pipeline invocation method used to submit all
    subsequent and dependent steps.
    """
    logger.debug('tasks.cad.get_cad_risk_score')
    chromosomes = list(set([chunk[0] for chunk in steps.get_chunks()]))

    step_1 = get_ancestry.s(user_id)
    steps_2_and_3 = [
        _get_cad_haplotypes.s(user_id, chromosome) | _dispatch_impute_tasks.s(user_id, chromosome)
        for chromosome in chromosomes
    ]
    step_4 = _get_total_cad_risk.s(user_id)

    workflow = chord(
        header=group([step_1, *steps_2_and_3]),
        body=step_4
    )

    workflow.delay()
