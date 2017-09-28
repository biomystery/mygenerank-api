""" Client functions for the 23andMe API. """
import json
import requests

from django.conf import settings

from .models import User, Genotype

def get(url, token):
    """ Given a resource URL and token, return
    the response from the API as a dictionary."""

    headers = {
        'Authorization': 'Bearer {token}'.format(token=token)
        }
    response = requests.get(url, headers=headers, timeout=60)
    data = json.loads(response.text)
    return data


def get_user_info(token):
    """ Given a bearer token this function will fetch the
    user json data from 23 and me."""
    url = User.resource_url
    response = get(url,token)
    return response


def get_genotype_data(token, profile):
    """ Given a bearer token and a profile id this function will
    fetch the genotype json data from 23 and me."""
    profile_id = profile.profile_id
    url = Genotype.resource_url.format(profile_id=profile_id)
    response = get(url,token)
    return response


def get_token(auth_code):
    """ Given an authentication code this function should
    retrieve a bearer token from the 23 and Me API"""

    url = "https://api.23andme.com/token/"
    post_data = {
     'client_id': settings.TTM_CLIENT_ID,
     'client_secret': settings.TTM_CLIENT_SECRET,
     'grant_type': settings.TTM_GRANT_TYPE,
     'code': auth_code,
     'redirect_uri': settings.TTM_REDIRECT_URL,
     'scope': settings.TTM_SCOPE
    }

    response = requests.post(url, data=post_data, timeout=2)
    data = json.loads(response.text)
    token = data['access_token']
    return token
