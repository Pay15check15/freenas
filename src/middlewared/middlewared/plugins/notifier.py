from middlewared.service import CallError, Service

import errno
import os
import subprocess
import sys
import logging

if '/usr/local/www' not in sys.path:
    sys.path.append('/usr/local/www')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'freenasUI.settings')

import django
from django.apps import apps
if not apps.ready:
    django.setup()

from django.conf import settings
from freenasUI import choices
from freenasUI import common as fcommon
from freenasUI.common.freenasldap import (
    FreeNAS_LDAP,
    FLAGS_DBINIT,
)
from freenasUI.common.freenasusers import FreeNAS_User, FreeNAS_Group
from freenasUI.middleware import zfs
from middlewared.utils import Popen


logger = logging.getLogger('plugins.notifier')


class NotifierService(Service):
    """
    This service is supposed to be temporary.
    It will serve as a transition from pre-middlewared world when
    everything was just methods randomly placed somewhere (mainly notifier.py).
    In a better world we will have specific services to split things logically.
    e.g. account, zfs, network, sharing, services, etc.
    """

    class Config:
        private = True

    def __getattr__(self, attr):
        _n = notifier()
        try:
            return object.__getattribute__(self, attr)
        except AttributeError:
            return getattr(_n, attr)

    def common(self, name, method, params=None):
        """Simple wrapper to access methods under freenasUI.common.*"""
        if params is None:
            params = []
        subsystem = getattr(fcommon, name)
        rv = getattr(subsystem, method)(*params)
        return rv

    def zpool_list(self, name=None):
        """Wrapper for zfs.zpool_list"""
        return zfs.zpool_list(name)

    def zfs_list(self, *args):
        """Wrapper to serialize zfs.zfs_list"""
        rv = zfs.zfs_list(*args)

        def serialize(i):
            data = {}
            if isinstance(i, zfs.ZFSList):
                for k, v in list(i.items()):
                    data[k] = serialize(v)
            elif isinstance(i, (zfs.ZFSVol, zfs.ZFSDataset)):
                data = i.__dict__
                data.update(data.pop('_ZFSVol__props', {}))
                data.update(data.pop('_ZFSDataset__props', {}))
                data['children'] = [serialize(j) for j in data.get('children') or []]
            return data

        return serialize(rv)

    def directoryservice(self, name):
        """Temporary wrapper to serialize DS connectors"""
        if name == 'AD':
            smb = self.middleware.call_sync('smb.config')
            ad = self.middleware.call_sync('activedirectory.config')
            data = {
                'netbiosname': smb['netbiosname'],
                'domainname': ad['domainname'],
                'use_default_domain': ad['use_default_domain'],
                'ad_idmap_backend': ad['idmap_backend'],
                'ds_type': 1,
                'krb_realm': ad['kerberos_realm']['krb_realm'],
                'workgroups': smb['workgroup'],
            }
            return data
        elif name == 'LDAP':
            ds = FreeNAS_LDAP(flags=FLAGS_DBINIT)
        else:
            raise ValueError('Unknown ds name {0}'.format(name))
        data = {}
        for i in (
            'netbiosname', 'keytab_file', 'keytab_principal', 'domainname',
            'use_default_domain', 'dchost', 'basedn', 'binddn', 'bindpw',
            'userdn', 'groupdn', 'ssl', 'certfile', 'id',
            'ad_idmap_backend', 'ds_type',
            'krb_realm', 'krbname', 'kpwdname',
            'krb_kdc', 'krb_admin_server', 'krb_kpasswd_server',
            'workgroups'
        ):
            if hasattr(ds, i):
                data[i] = getattr(ds, i)
        return data

    def get_user_object(self, username):
        user = False
        try:
            user = FreeNAS_User(username)
        except Exception:
            pass
        return user

    def get_group_object(self, groupname):
        group = False
        try:
            group = FreeNAS_Group(groupname)
        except Exception:
            pass
        return group

    def ldap_status(self):
        ret = False
        try:
            f = FreeNAS_LDAP(flags=FLAGS_DBINIT)
            f.open()
            if f.isOpen():
                ret = True
            f.close()
        except Exception as e:
            pass

        return ret

    def ad_status(self):
        return self.middleware.call_sync('activedirectory.started')

    def ds_get_idmap_object(self, ds_type, id, idmap_backend):
        data = self.middleware.call_sync('idmap.get_idmap_legacy', ds_type, idmap_backend)
        return data 

    async def ds_clearcache(self):
        """Temporary call to rebuild DS cache"""
        await Popen(
            '/usr/local/bin/python /usr/local/www/freenasUI/tools/cachetool.py expire && '
            '/usr/local/bin/python /usr/local/www/freenasUI/tools/cachetool.py fill',
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True
        )

    def choices(self, name, args=None):
        """Temporary wrapper to get to UI choices"""
        if args is None:
            args = []
        try:
            attr = getattr(choices, name)
        except AttributeError as e:
            raise CallError(str(e), errno.ENOENT)
        if callable(attr):
            rv = list(attr(*args))
        else:
            rv = attr
        # We need to make sure the label is str and not django
        # translation proxy
        _choices = []
        for k, v in rv:
            if not isinstance(v, str):
                v = str(v)
            _choices.append((k, v))
        return _choices

    def gui_languages(self):
        """Temporary wrapper to return available languages in django"""
        return settings.LANGUAGES

    def dojango_dojo_version(self):
        # Being used by nginx.conf in etc plugin
        return settings.DOJANGO_DOJO_VERSION

    def humanize_size(self, number):
        """Temporary wrapper to return a human readable bytesize"""
        try:
            return fcommon.humanize_size(number)
        except Exception:
            logger.debug(
                'fcommon.humanize_size: Failed to translate sizes',
                exc_info=True
            )
            return number
