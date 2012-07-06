import cgi, urllib, json

from django.conf import settings
from django.contrib.auth.models import User, AnonymousUser
from django.db import IntegrityError
import string
import random
from horizon import api
from models import FacebookProfile
from keystoneclient import service_catalog
from keystoneclient.v2_0 import client as keystone_client
from keystoneclient.v2_0 import tokens
from django.contrib import messages

def _set_session_data(request, token):
    request.session['serviceCatalog'] = token.serviceCatalog
    request.session['tenant'] = token.tenant['name']
    request.session['tenant_id'] = token.tenant['id']
    request.session['token'] = token.id
    request.session['user_name'] = token.user['name']
    request.session['user_id'] = token.user['id']
    request.session['roles'] = token.user['roles']

class FacebookBackend:
    def _admin_client(self):
        return  keystone_client.Client(username=settings.ADMIN_USER,
                                      password=settings.ADMIN_PASSWORD,
                                      tenant_name=settings.ADMIN_TENANT,
                                      auth_url=settings.OPENSTACK_KEYSTONE_URL)

    def authenticate(self, token=None, request=None):
        """ Reads in a Facebook code and asks Facebook if it's valid and what user it points to. """
        args = {
            'client_id': settings.FACEBOOK_APP_ID,
            'client_secret': settings.FACEBOOK_APP_SECRET,
            'redirect_uri': settings.CALLBACK,
            'code': token,
        }

        # Get a legit access token
        target = urllib.urlopen('https://graph.facebook.com/oauth/access_token?' + urllib.urlencode(args)).read()
        response = cgi.parse_qs(target)
        access_token = response['access_token'][-1]

        # Read the user's profile information
        fb_profile = urllib.urlopen('https://graph.facebook.com/me?access_token=%s' % access_token)
        fb_profile = json.load(fb_profile)
        tenant_id = None
        password = ""
        try:
            # Try and find existing user
            fb_user = FacebookProfile.objects.get(facebook_id=fb_profile['id'])
            user = fb_user.user

            # Update access_token
            fb_user.access_token = access_token
            password = fb_user.password
            tenant_id = fb_user.tenant_id
            fb_user.save()

        except FacebookProfile.DoesNotExist:
            # No existing user

            facebook_id = fb_profile['id']
            username = "facebook%s" % facebook_id
 
            try:
                user = User.objects.create_user(username, fb_profile['email'])
            except IntegrityError:
                # Username already exists, make it unique
                existing_user = User.objects.get(username=username)
                existing_user.delete()
                user = User.objects.create_user(username, fb_profile['email'])
           
            user.save()
            
            password = "".join([random.choice(string.ascii_lowercase + string.digits) for i in range(8)])
            # Create the FacebookProfile
            fb_user = FacebookProfile(user=user, facebook_id=fb_profile['id'], access_token=access_token,password=password)
            tenant_name = "facebook%s" % fb_profile['id']
            keystone_admin = self._admin_client()
            
            tenant = keystone_admin.tenants.create(tenant_name,"Auto created account",True)
            keystone_admin.users.create(tenant_name,password,fb_profile['email'],tenant.id,True)
            fb_user.tenant_id = tenant.id
            tenant_id = fb_user.tenant_id
            fb_user.save()

        facebook_id = fb_profile['id']
        user_name = "facebook%s" % facebook_id
        try:
            group_url = "https://graph.facebook.com/269238013145112/members?access_token=%s" % access_token
            f = urllib.urlopen(group_url)
            graph_data_json = f.read()
            f.close()
            graph_data = json.loads(graph_data_json)
            if len(graph_data['data']) > 0 :
                token = api.token_create(request,
                         tenant_id,
                         user_name,
                         password)
                tenants = api.tenant_list_for_token(request, token.id)
                _set_session_data(request,token)
            else:
                messages.error(request, "Your facebookID is not in TryStack group yet.")
        except Exception as e:
	    messages.error(request,"Failed to login facebookID %s" % e)  
        return user

    def get_user(self, user_id):
        """ Just returns the user of a given ID. """
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

    supports_object_permissions = False
    supports_anonymous_user = True
